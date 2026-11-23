"""Event log: schema, append-before-delivery, fold and restart (FB-01, FB-07)."""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_canvas.hub.events import EventLog, EventService
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit

ISO_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
COMMON_FIELDS = {
    "type", "id", "session", "seq", "time", "kind", "page", "page_version",
    "target", "value", "delivery", "state",
}  # fmt: skip
SEND_FIELDS = {
    "message", "actions", "marks", "comments", "screenshot", "screenshot_error",
    "send_file",
}  # fmt: skip


def run(coroutine):  # noqa: ANN001, ANN201
    """Run a coroutine in a fresh thread (browser tests leave a loop running)."""
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def lines_of(folder: Path) -> list[dict]:
    text = (folder / "events.jsonl").read_text()
    return [json.loads(line) for line in text.splitlines()]


def test_fb_01_send_event_has_every_field_of_the_event_object(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    event = log.create("send", page="page.html", page_version=7, fields={
        "message": "why this peak?", "actions": [], "marks": [],
        "screenshot": None, "screenshot_error": "capture failed", "send_file": None,
    })  # fmt: skip
    assert set(event) == COMMON_FIELDS | SEND_FIELDS
    assert event["type"] == "event" and event["kind"] == "send"
    assert event["id"].startswith("evt_") and event["session"] == "s1"
    assert event["seq"] == 1 and ISO_TIME.match(event["time"])
    assert (event["delivery"], event["state"]) == ("now", "queued")
    assert (event["page"], event["page_version"]) == ("page.html", 7)


def test_com_11_a_new_send_event_has_no_marks_and_an_old_stored_one_still_loads(
    tmp_path,
) -> None:
    log = EventLog("s1", tmp_path)
    assert "marks" not in log.create("send")
    old = {"record": "event", "id": "evt_old", "session": "s1", "seq": 5,
           "kind": "send", "delivery": "now", "state": "queued",
           "marks": [{"id": 1, "type": "box"}]}  # fmt: skip
    with (tmp_path / "events.jsonl").open("a") as handle:
        handle.write(json.dumps(old) + "\n")
    assert EventLog("s1", tmp_path).get("evt_old")["marks"] == [
        {"id": 1, "type": "box"}
    ]


def test_fb_01_other_kinds_have_only_the_common_fields(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    event = log.create("custom", value={"name": "pick", "value": 3})
    assert set(event) == COMMON_FIELDS
    assert event["value"] == {"name": "pick", "value": 3}


def test_fb_01_seq_increases_by_one_per_event(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    assert [log.create("custom")["seq"] for _ in range(3)] == [1, 2, 3]


def test_fb_01_unknown_kind_or_delivery_is_refused(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    with pytest.raises(ValueError, match="kind"):
        log.create("poke")
    with pytest.raises(ValueError, match="delivery"):
        log.create("custom", delivery="whenever")
    assert not (tmp_path / "events.jsonl").exists()


def test_fb_01_event_is_on_disk_when_the_append_hook_runs(tmp_path) -> None:
    seen: list[int] = []

    def hook(event: dict) -> None:
        seen.append(len(lines_of(tmp_path)))

    EventLog("s1", tmp_path, after_append=hook).create("custom")
    assert seen == [1]
    assert lines_of(tmp_path)[0]["record"] == "event"


def test_fb_01_crash_after_append_leaves_the_event_queued_after_restart(
    tmp_path,
) -> None:
    def crash(event: dict) -> None:
        raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError):
        EventLog("s1", tmp_path, after_append=crash).create("custom", value={"k": 1})
    restarted = EventLog("s1", tmp_path)
    [event] = restarted.queued()
    assert event["state"] == "queued" and event["value"] == {"k": 1}


def test_fb_01_service_dispatches_only_after_the_append(tmp_path) -> None:
    state = HubState(1, "k", lambda: 0.0)
    state.register_session("s1", tmp_path)
    service = EventService(state)

    def crash(event: dict) -> None:
        raise RuntimeError("simulated crash")

    async def scenario() -> None:
        listener = service.add_listener("s1", "watch")
        service.log("s1").after_append = crash
        with pytest.raises(RuntimeError):
            service.create("s1", "custom")
        assert listener.queue.empty()  # nothing was offered before the append

    run(scenario())
    assert len(lines_of(tmp_path)) == 1


def test_fb_07_delivered_record_is_appended_and_folded(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    first, second = log.create("custom"), log.create("custom")
    assert log.mark_delivered(first["id"], "watch") is True
    record = lines_of(tmp_path)[-1]
    assert record["record"] == "delivered" and record["id"] == first["id"]
    assert record["via"] == "watch" and ISO_TIME.match(record["time"])
    restarted = EventLog("s1", tmp_path)
    assert restarted.get(first["id"])["state"] == "delivered"
    assert [e["id"] for e in restarted.queued()] == [second["id"]]


def test_fb_07_a_second_delivery_is_ignored_and_writes_nothing(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    event = log.create("custom")
    assert log.mark_delivered(event["id"], "watch") is True
    assert log.mark_delivered(event["id"], "pending") is False
    assert log.mark_delivered("evt_unknown", "watch") is False
    records = [r for r in lines_of(tmp_path) if r["record"] == "delivered"]
    assert len(records) == 1 and records[0]["via"] == "watch"
    with pytest.raises(ValueError, match="via"):
        log.mark_delivered(log.create("custom")["id"], "carrier-pigeon")


def test_fb_07_seq_continues_after_a_restart(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    log.create("custom"), log.create("custom")
    assert EventLog("s1", tmp_path).create("custom")["seq"] == 3


def test_fb_07_a_torn_last_line_is_ignored_on_load(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    kept = log.create("custom")
    with (tmp_path / "events.jsonl").open("a") as handle:
        handle.write('{"record": "event", "id": "evt_torn", "se')
    restarted = EventLog("s1", tmp_path)
    assert [e["id"] for e in restarted.queued()] == [kept["id"]]
    assert restarted.create("custom")["seq"] == 2


def test_fb_03_queued_filters_by_delivery_and_keeps_seq_order(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    log.create("custom", delivery="now")
    log.create("send", delivery="next-message")
    log.create("custom", delivery="now")
    assert [e["seq"] for e in log.queued()] == [1, 2, 3]
    assert [e["seq"] for e in log.queued(("now",))] == [1, 3]


def test_cli_08_listener_skips_events_delivered_while_they_waited(tmp_path) -> None:
    """Race: ``pending`` takes an event that a watch's queue still holds."""
    state = HubState(1, "k", lambda: 0.0)
    state.register_session("s1", tmp_path)
    service = EventService(state)

    async def scenario() -> list[str]:
        listener = service.add_listener("s1", "watch")
        first = service.create("s1", "custom")
        second = service.create("s1", "custom")
        taken = service.pending("s1", peek=False)
        assert [e["id"] for e in taken] == [first["id"], second["id"]]
        third = service.create("s1", "custom")
        offered = await asyncio.wait_for(listener.next_event(), 1)
        return [offered["id"], third["id"]]

    offered, third = run(scenario())
    assert offered == third  # the two delivered events are skipped


def test_fb_06_listening_follows_listener_count_and_notifies(tmp_path) -> None:
    state = HubState(1, "k", lambda: 0.0)
    state.register_session("s1", tmp_path)
    changes: list[tuple[str, bool]] = []
    service = EventService(state, on_listening=lambda s, on: changes.append((s, on)))

    async def scenario() -> None:
        assert service.listening("s1") is False
        first = service.add_listener("s1", "watch")
        second = service.add_listener("s1", "watch")
        assert service.listening("s1") is True
        service.remove_listener(first)
        assert service.listening("s1") is True
        service.remove_listener(second)
        service.remove_listener(second)  # idempotent
        assert service.listening("s1") is False

    run(scenario())
    assert changes == [("s1", True), ("s1", False)]
