"""The newest send and its read time, from the event log alone (FB-10)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_canvas.hub.events import EventLog, EventService
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit


def send(log: EventLog, send_id: str, delivery: str = "now") -> dict:
    return log.create("send", delivery=delivery, fields={"send_id": send_id})


def test_fb_10_no_send_gives_none(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    log.create("button")
    assert log.latest_send() is None


def test_fb_10_an_unread_send_has_no_read_time(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    event = send(log, "snd_1", "next-message")
    assert log.latest_send() == {
        "time": event["time"], "delivery": "next-message", "read": None,
    }  # fmt: skip


def test_fb_10_a_delivered_send_has_its_read_time_also_after_a_reload(
    tmp_path,
) -> None:
    log = EventLog("s1", tmp_path)
    event = send(log, "snd_1")
    log.mark_delivered(event["id"], "pending")
    read = log.latest_send()["read"]
    assert read is not None and read >= event["time"]
    assert EventLog("s1", tmp_path).latest_send()["read"] == read


def test_fb_10_a_later_send_does_not_inherit_the_read_of_the_first(tmp_path) -> None:
    log = EventLog("s1", tmp_path)
    first = send(log, "snd_1")
    log.mark_delivered(first["id"], "watch")
    second = send(log, "snd_2")
    assert log.latest_send() == {
        "time": second["time"],
        "delivery": "now",
        "read": None,
    }
    assert EventLog("s1", tmp_path).latest_send()["read"] is None


def test_fb_10_a_send_of_several_pages_is_read_only_when_every_part_is(
    tmp_path,
) -> None:
    log = EventLog("s1", tmp_path)
    one, two = send(log, "snd_1"), send(log, "snd_1")
    log.mark_delivered(one["id"], "watch")
    assert log.latest_send()["read"] is None
    log.mark_delivered(two["id"], "watch")
    assert log.latest_send()["read"] is not None
    log.create("answer")  # other kinds leave the newest send as it was
    assert EventLog("s1", tmp_path).latest_send()["read"] is not None


def run(coroutine):  # noqa: ANN001, ANN201
    """Run a coroutine in a fresh thread (browser tests leave a loop running)."""
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def test_fb_10_only_a_watch_takes_sends_and_its_coming_and_going_is_told(
    tmp_path,
) -> None:
    state = HubState(1, "k", lambda: 0.0)
    state.register_session("s1", tmp_path)
    changes: list[bool] = []
    service = EventService(state, on_listening=lambda s, on: changes.append(on))

    async def scenario() -> list[bool]:
        ask = service.add_listener("s1", "ask")
        seen = [service.watching("s1")]
        watch = service.add_listener("s1", "watch")
        seen.append(service.watching("s1"))
        service.remove_listener(watch)
        seen.append(service.watching("s1"))
        service.remove_listener(ask)
        return seen

    assert run(scenario()) == [False, True, False]
    assert changes == [True, True, True, False]  # first, watch in, watch out, last
