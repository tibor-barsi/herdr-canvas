"""Delivery rules over the watch socket and ``pending`` (M6).

Covers FB-01, FB-02, FB-03, FB-07, CLI-08, CLI-09 and SES-09 against a real hub.
The raw WebSocket client plays the CLI's part of the acknowledgement protocol,
so that "a watch dies between receive and acknowledge" can be tested exactly.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

pytestmark = pytest.mark.integration


class RawWatch:
    """A watch client speaking the hub's protocol by hand."""

    def __init__(self, hub, session_id: str, key: str | None = None) -> None:  # noqa: ANN001
        self.socket = connect(
            f"ws://127.0.0.1:{hub.port}/api/sessions/{session_id}/watch",
            additional_headers={"X-Agent-Canvas-Key": key or hub.key},
            max_queue=None,  # a dying watch may leave many events unread
        )

    def receive(self, timeout: float = 2.0) -> dict | None:
        """Next event object, or None when nothing arrives in ``timeout`` s."""
        try:
            return json.loads(self.socket.recv(timeout=timeout))
        except TimeoutError:
            return None

    def ack(self, event_id: str) -> None:
        self.socket.send(json.dumps({"type": "ack", "id": event_id}))

    def close(self) -> None:
        self.socket.close()


@pytest.fixture
def watches(hub):  # noqa: ANN001, ANN201
    opened: list[RawWatch] = []

    def open_watch(session_id: str, **kwargs) -> RawWatch:  # noqa: ANN003
        watch = RawWatch(hub, session_id, **kwargs)
        opened.append(watch)
        hub.wait_for(lambda: hub.listening(session_id))
        return watch

    yield open_watch
    for watch in opened:
        watch.close()


def pending(hub, session_id: str, peek: bool = False) -> list[dict]:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{session_id}/pending",
        headers=hub.key_headers,
        json={"peek": peek},
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["session"] == session_id
    return body["events"]


def records(hub, session_id: str) -> list[dict]:  # noqa: ANN001
    path = hub.sessions[session_id].folder / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def delivered_records(hub, session_id: str) -> list[dict]:  # noqa: ANN001
    return [r for r in records(hub, session_id) if r["record"] == "delivered"]


def make_session(hub, name: str) -> None:  # noqa: ANN001
    """Create a registered session (``sessions.json`` entry, survives restarts)."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{name}/path",
        headers=hub.key_headers,
        json={"project": str(hub.project_dir), "agent": "t"},
    )
    assert answer.status_code == 200, answer.text
    hub.sessions[name] = hub.state.session_of(name)


def wait_listener_gone(hub, session_id: str) -> None:  # noqa: ANN001
    hub.wait_for(lambda: not hub.listening(session_id))


# ---- FB-02 --------------------------------------------------------------------


def test_fb_02_with_no_listener_a_now_event_stays_queued(hub) -> None:
    make_session(hub, "a")
    event = hub.create_event("a", "send", message="hello")
    assert hub.event_state("a", event["id"]) == "queued"
    [seen] = pending(hub, "a", peek=True)
    assert seen["id"] == event["id"] and seen["state"] == "queued"


def test_fb_02_one_watch_gets_the_event_and_its_ack_marks_it_delivered(
    hub, watches
) -> None:
    make_session(hub, "a")
    watch = watches("a")
    event = hub.create_event("a", "send", message="hello")
    assert watch.receive()["id"] == event["id"]
    assert hub.event_state("a", event["id"]) == "queued"  # not yet acknowledged
    watch.ack(event["id"])
    hub.wait_for(lambda: hub.event_state("a", event["id"]) == "delivered")
    assert pending(hub, "a") == []
    [record] = delivered_records(hub, "a")
    assert record["id"] == event["id"] and record["via"] == "watch"


def test_fb_02_two_watches_both_receive_and_it_is_delivered_once(hub, watches) -> None:
    make_session(hub, "a")
    first, second = watches("a"), watches("a")
    event = hub.create_event("a", "custom", value={"name": "x", "value": 1})
    assert first.receive()["id"] == event["id"]
    assert second.receive()["id"] == event["id"]
    first.ack(event["id"])
    second.ack(event["id"])  # later acknowledgements are ignored (CLI-08)
    hub.wait_for(lambda: hub.event_state("a", event["id"]) == "delivered")
    first.close()
    second.close()
    wait_listener_gone(hub, "a")
    assert len(delivered_records(hub, "a")) == 1


def test_fb_02_queued_now_events_are_flushed_to_a_new_watch_in_seq_order(
    hub, watches
) -> None:
    make_session(hub, "a")
    ids = [hub.create_event("a", "custom")["id"] for _ in range(3)]
    watch = watches("a")
    assert [watch.receive()["id"] for _ in range(3)] == ids
    assert watch.receive(0.3) is None


def test_fb_02_an_event_is_never_offered_twice_to_one_watch(hub, watches) -> None:
    make_session(hub, "a")
    hub.create_event("a", "custom")
    watch = watches("a")
    first = watch.receive()
    hub.create_event("a", "custom")
    second = watch.receive()
    assert first["seq"] == 1 and second["seq"] == 2
    assert watch.receive(0.3) is None


# ---- FB-03 --------------------------------------------------------------------


def test_fb_03_next_message_is_not_sent_to_a_watch_but_pending_returns_it(
    hub, watches
) -> None:
    make_session(hub, "a")
    queued_before = hub.create_event("a", "send", delivery="next-message")
    watch = watches("a")
    live = hub.create_event("a", "send", delivery="next-message")
    assert watch.receive(0.5) is None  # neither flushed nor live
    assert [e["id"] for e in pending(hub, "a")] == [queued_before["id"], live["id"]]


# ---- CLI-08 -------------------------------------------------------------------


def test_cli_08_a_watch_dying_before_the_ack_leaves_the_event_queued(
    hub, watches
) -> None:
    make_session(hub, "a")
    dying = watches("a")
    event = hub.create_event("a", "send", message="m")
    assert dying.receive()["id"] == event["id"]
    dying.close()  # killed between receive and acknowledge
    wait_listener_gone(hub, "a")
    assert hub.event_state("a", event["id"]) == "queued"
    survivor = watches("a")
    assert survivor.receive()["id"] == event["id"]  # appears at the next watch
    survivor.ack(event["id"])
    hub.wait_for(lambda: hub.event_state("a", event["id"]) == "delivered")


def test_cli_08_two_watches_one_dies_unacknowledged_delivered_once_via_the_other(
    hub, watches
) -> None:
    make_session(hub, "a")
    dying, staying = watches("a"), watches("a")
    event = hub.create_event("a", "send", message="m")
    assert dying.receive()["id"] == event["id"]
    assert staying.receive()["id"] == event["id"]
    dying.close()
    hub.wait_for(lambda: hub.on_loop(lambda: len(hub.state.events.listeners("a")) == 1))
    assert hub.event_state("a", event["id"]) == "queued"
    staying.ack(event["id"])
    hub.wait_for(lambda: hub.event_state("a", event["id"]) == "delivered")
    assert pending(hub, "a") == []
    [record] = delivered_records(hub, "a")
    assert record["via"] == "watch"


def test_cli_08_ack_in_one_session_cannot_deliver_an_event_of_another(
    hub, watches
) -> None:
    make_session(hub, "a")
    make_session(hub, "b")
    event = hub.create_event("a", "custom")
    watch_b = watches("b")
    watch_b.ack(event["id"])
    watch_b.ack("evt_does_not_exist")
    watch_b.close()
    wait_listener_gone(hub, "b")
    assert hub.event_state("a", event["id"]) == "queued"
    assert delivered_records(hub, "a") == []


def test_cli_08_watch_dying_midway_loses_nothing_and_duplicates_nothing(
    hub, watches
) -> None:
    """Race: acknowledged events stay delivered, the rest all go to ``pending``."""
    make_session(hub, "a")
    first = watches("a")
    ids = [hub.create_event("a", "custom")["id"] for _ in range(20)]
    received = [first.receive()["id"] for _ in range(20)]
    assert received == ids
    for event_id in ids[:8]:
        first.ack(event_id)
    first.close()  # dies with 12 events received but not acknowledged
    wait_listener_gone(hub, "a")
    late = hub.create_event("a", "custom")["id"]  # created while nobody listens
    taken = [e["id"] for e in pending(hub, "a")]
    assert taken == ids[8:] + [late]
    assert pending(hub, "a") == []
    delivered = [r["id"] for r in delivered_records(hub, "a")]
    assert sorted(delivered) == sorted(ids + [late])  # each exactly once
    assert len(delivered) == len(set(delivered))


def test_cli_08_pending_wins_over_a_late_watch_ack(hub, watches) -> None:
    """Race: the event is in flight to a watch when ``pending`` takes it."""
    make_session(hub, "a")
    watch = watches("a")
    event = hub.create_event("a", "custom")
    assert watch.receive()["id"] == event["id"]
    assert [e["id"] for e in pending(hub, "a")] == [event["id"]]
    watch.ack(event["id"])
    watch.close()
    wait_listener_gone(hub, "a")
    [record] = delivered_records(hub, "a")
    assert record["via"] == "pending"


def test_cli_08_events_created_while_watches_come_and_go_reach_one_path(
    hub, watches
) -> None:
    """Race: a creator thread runs while watches connect, ack some and die."""
    import threading

    make_session(hub, "a")
    created: list[str] = []

    def create_many() -> None:
        for _ in range(60):
            created.append(hub.create_event("a", "custom")["id"])
            time.sleep(0.002)

    thread = threading.Thread(target=create_many)
    thread.start()
    acknowledged: set[str] = set()
    for _ in range(6):
        watch = watches("a")
        for _ in range(5):
            event = watch.receive(0.2)
            if event is not None and len(acknowledged) % 2 == 0:
                watch.ack(event["id"])
                acknowledged.add(event["id"])
        watch.close()
        wait_listener_gone(hub, "a")
    thread.join()
    rest = {e["id"] for e in pending(hub, "a")}
    delivered = [r["id"] for r in delivered_records(hub, "a")]
    assert len(delivered) == len(set(delivered))  # never delivered twice
    assert set(delivered) == set(created)  # never lost
    assert acknowledged <= set(delivered) and not (acknowledged & rest)


# ---- CLI-09 -------------------------------------------------------------------


def test_cli_09_pending_returns_all_queued_in_seq_order_once(hub) -> None:
    make_session(hub, "a")
    ids = [
        hub.create_event("a", "send", delivery="now")["id"],
        hub.create_event("a", "send", delivery="next-message")["id"],
        hub.create_event("a", "custom", delivery="now")["id"],
    ]
    first = pending(hub, "a")
    assert [e["id"] for e in first] == ids
    assert [e["seq"] for e in first] == [1, 2, 3]
    assert pending(hub, "a") == []
    assert [r["via"] for r in delivered_records(hub, "a")] == ["pending"] * 3


def test_cli_09_peek_leaves_events_queued(hub) -> None:
    make_session(hub, "a")
    event = hub.create_event("a", "send", delivery="next-message")
    assert [e["id"] for e in pending(hub, "a", peek=True)] == [event["id"]]
    assert [e["id"] for e in pending(hub, "a", peek=True)] == [event["id"]]
    assert delivered_records(hub, "a") == []
    assert [e["id"] for e in pending(hub, "a")] == [event["id"]]


def test_cli_09_unknown_session_is_404_no_session(hub) -> None:
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/ghost/pending",
        headers=hub.key_headers,
        json={},
    )
    assert answer.status_code == 404 and answer.json()["error"] == "no-session"


# ---- SES-09 -------------------------------------------------------------------


def test_ses_09_events_and_listeners_of_two_sessions_are_separate(hub, watches) -> None:
    make_session(hub, "a")
    make_session(hub, "b")
    watch_b = watches("b")
    assert hub.listening("b") and not hub.listening("a")
    event_a = hub.create_event("a", "send", message="for A")
    assert watch_b.receive(0.5) is None
    assert pending(hub, "b") == []
    event_b = hub.create_event("b", "send", message="for B")
    assert watch_b.receive()["id"] == event_b["id"]
    assert [e["id"] for e in pending(hub, "a")] == [event_a["id"]]
    assert event_a["seq"] == event_b["seq"] == 1  # seq is per session
    assert not (hub.sessions["a"].folder / "events.jsonl").read_text().count("for B")


def test_ses_09_page_writes_in_one_session_do_not_reach_the_other_watch(
    hub, watches
) -> None:
    make_session(hub, "a")
    make_session(hub, "b")
    (hub.sessions["a"].folder / "page.html").write_text("<p>a</p>")
    (hub.sessions["b"].folder / "page.html").write_text("<p>b</p>")
    watch_b = watches("b")
    (hub.sessions["a"].folder / "page.html").write_text("<p>a2</p>")
    assert watch_b.receive(0.5) is None  # page changes are no events


# ---- listening and watch socket errors ---------------------------------------------


def test_fb_06_session_list_reports_listening(hub, watches) -> None:
    make_session(hub, "a")
    make_session(hub, "b")

    def listing() -> dict[str, bool]:
        answer = httpx.get(f"{hub.base_url}/api/sessions", headers=hub.key_headers)
        listed = [s for s in answer.json() if not s["id"].startswith("project-")]
        return {s["id"]: s["listening"] for s in listed}  # without the pool, A-1022

    assert listing()["a"] is False
    watch = watches("a")
    assert listing() == {"a": True, "b": False}
    watch.close()
    wait_listener_gone(hub, "a")
    assert listing()["a"] is False


def test_cli_07_watch_socket_rejects_unknown_sessions_and_wrong_keys(hub) -> None:
    make_session(hub, "a")
    with pytest.raises(ConnectionClosed) as unknown:
        RawWatch(hub, "ghost").socket.recv(timeout=5)
    assert unknown.value.rcvd.code == 4404
    with pytest.raises(ConnectionClosed) as wrong:
        RawWatch(hub, "a", key="wrong").socket.recv(timeout=5)
    assert wrong.value.rcvd.code == 4401


# ---- FB-07 --------------------------------------------------------------------


def test_fb_07_queued_events_survive_a_hub_restart_and_delivered_ones_do_not_return(
    hub,
) -> None:
    make_session(hub, "a")
    taken = hub.create_event("a", "send", message="taken")
    kept_now = hub.create_event("a", "send", message="kept now")
    kept_later = hub.create_event("a", "send", delivery="next-message")
    hub.on_loop(lambda: hub.state.events.ack("a", taken["id"], "watch"))
    hub.restart()
    hub.sessions["a"] = hub.state.session_of("a")  # reloaded from sessions.json
    again = pending(hub, "a")
    assert [e["id"] for e in again] == [kept_now["id"], kept_later["id"]]
    assert [e["seq"] for e in again] == [2, 3]
    assert hub.create_event("a", "custom")["seq"] == 4
