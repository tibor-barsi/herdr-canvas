"""Routing of project events to one session (PROJ-07 to PROJ-10, #88, D-72)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_canvas.hub.events import EventService
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit

PROJECT = "project-0123456789abcdef"


def run(coroutine):  # noqa: ANN001, ANN201
    """Run a coroutine in a fresh thread (browser tests leave a loop running)."""
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def service(tmp_path: Path, receiver: dict) -> EventService:
    """Sessions A and B of one project; ``receiver["id"]`` decides the receiver."""
    state = HubState(1, "k", lambda: 0.0)
    for session_id in ("A", "B", PROJECT):
        folder = tmp_path / session_id
        folder.mkdir()
        state.register_session(session_id, folder)
    return EventService(
        state,
        project_of=lambda sid: None if sid == PROJECT else PROJECT,
        receiver_of=lambda project, event: receiver["id"],
    )


def ids(events: list[dict]) -> list[str]:
    return [e["id"] for e in events]


def test_proj_07_pending_gives_the_updaters_event_to_it_and_not_to_another(
    tmp_path,
) -> None:
    events = service(tmp_path, {"id": "A"})
    made = events.create(PROJECT, "custom")
    assert events.pending("B", peek=False) == []
    taken = events.pending("A", peek=False)
    assert ids(taken) == [made["id"]] and taken[0]["project_page"] is True
    assert events.get(PROJECT, made["id"])["state"] == "delivered"


def test_proj_07_an_inbox_event_goes_to_the_first_session_that_picks_up(
    tmp_path,
) -> None:
    events = service(tmp_path, {"id": None})
    own = events.create("B", "custom")
    made = events.create(PROJECT, "custom", delivery="next-message")
    assert ids(events.pending("B", peek=True)) == [own["id"], made["id"]]
    assert events.get(PROJECT, made["id"])["state"] == "queued"  # peek takes nothing
    assert ids(events.pending("B", peek=False)) == [own["id"], made["id"]]
    assert events.pending("A", peek=False) == []


def test_proj_07_the_receiver_is_decided_at_pickup_not_at_creation(tmp_path) -> None:
    receiver = {"id": "A"}
    events = service(tmp_path, receiver)
    made = events.create(PROJECT, "custom")
    assert events.pending("B", peek=False) == []
    receiver["id"] = None  # A ended
    assert ids(events.pending("B", peek=False)) == [made["id"]]


def test_proj_08_a_project_event_is_handed_out_once(tmp_path) -> None:
    events = service(tmp_path, {"id": None})
    made = events.create(PROJECT, "custom")
    first, second = events.pending("A", False), events.pending("B", False)
    assert ids(first + second) == [made["id"]]


def test_proj_09_a_session_without_a_log_takes_inbox_items_without_a_folder(
    tmp_path,
) -> None:
    events = service(tmp_path, {"id": None})
    made = events.create(PROJECT, "custom")
    assert ids(events.project_pending("R", peek=False)) == [made["id"]]
    assert not (tmp_path / "R").exists()
    assert events.get(PROJECT, made["id"])["state"] == "delivered"


def test_proj_10_a_now_event_reaches_the_updaters_watch_and_its_ack_marks_it(
    tmp_path,
) -> None:
    events = service(tmp_path, {"id": "A"})

    async def scenario() -> tuple[dict, bool]:
        mine = events.add_listener("A", "watch")
        other = events.add_listener("B", "watch")
        made = events.create(PROJECT, "custom")
        offered = await asyncio.wait_for(mine.next_event(), 1)
        assert other.queue.empty()
        assert events.ack("B", made["id"]) is False  # not B's to acknowledge
        return offered, events.ack("A", made["id"])

    offered, acknowledged = run(scenario())
    assert offered["project_page"] is True and acknowledged is True
    assert events.get(PROJECT, offered["id"])["state"] == "delivered"


def test_proj_10_a_watch_that_starts_later_gets_the_waiting_event_of_its_updater(
    tmp_path,
) -> None:
    events = service(tmp_path, {"id": "A"})

    async def scenario() -> tuple[str, dict]:
        made = events.create(PROJECT, "custom")
        assert events.add_listener("B", "watch").queue.empty()
        listener = events.add_listener("A", "watch")
        return made["id"], await asyncio.wait_for(listener.next_event(), 1)

    made, offered = run(scenario())
    assert offered["id"] == made


def test_proj_10_an_inbox_event_is_never_pushed_to_a_watch(tmp_path) -> None:
    events = service(tmp_path, {"id": None})

    async def scenario() -> bool:
        listener = events.add_listener("B", "watch")
        events.create(PROJECT, "custom")
        await asyncio.sleep(0)
        return listener.queue.empty()

    assert run(scenario()) is True
    assert len(events.pending("B", peek=False)) == 1  # it waited for pending
