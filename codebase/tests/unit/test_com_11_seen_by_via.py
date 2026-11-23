"""A delivered event stamps its comments seen, by every path (COM-11)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from agent_canvas.hub import comments
from agent_canvas.hub.events import DELIVERY_VIAS, EventLog

pytestmark = pytest.mark.unit

FIELDS = {
    "page_version": 1, "kind": "point", "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
    "target": {"canvas_id": None, "selector": "#fig", "text": None},
    "picture": base64.b64encode(b"\x89PNG\r\n\x1a\nx").decode(),
}  # fmt: skip


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Move the store's clock a second per reading: ``seen`` is later than ``sent``."""
    ticks = iter(range(1, 60))
    monkeypatch.setattr(
        comments, "now_iso", lambda: f"2026-11-09T09:00:{next(ticks):02d}.000Z"
    )


def delivered_log(folder: Path, page: str = "page.html") -> tuple[EventLog, dict]:
    comments.create(folder, page, FIELDS)
    taken = comments.take_unsent(folder, page, "now", "evt_x")
    log = EventLog("s1", folder)
    event = log.create("send", event_id="evt_x", page=page, fields={"comments": taken})
    return log, event


def statuses(folder: Path, page: str = "page.html") -> list[str]:
    return [comments.status(c) for c in comments.load(folder, page)["comments"]]


@pytest.mark.parametrize("via", DELIVERY_VIAS)
def test_com_11_delivery_by_every_path_stamps_the_comments_seen(
    tmp_path: Path, via: str
) -> None:
    log, event = delivered_log(tmp_path)
    assert statuses(tmp_path) == ["sent"]
    assert log.mark_delivered(event["id"], via)
    assert statuses(tmp_path) == ["seen"]


def test_com_11_a_second_delivery_does_not_stamp_again(tmp_path: Path) -> None:
    log, event = delivered_log(tmp_path)
    log.mark_delivered(event["id"], "watch")
    log.mark_delivered(event["id"], "pending")
    [record] = comments.load(tmp_path, "page.html")["comments"]
    assert len(record["seen"]) == 1


def test_com_11_the_window_is_told_which_page_changed(tmp_path: Path) -> None:
    told: list[str] = []
    log, event = delivered_log(tmp_path, "a.html")
    log.on_seen = told.append
    log.mark_delivered(event["id"], "hook")
    assert told == ["a.html"]


def test_com_11_an_event_without_comments_touches_no_file(tmp_path: Path) -> None:
    log = EventLog("s1", tmp_path)
    event = log.create("send", page="page.html", fields={"message": "hi"})
    log.mark_delivered(event["id"], "watch")
    assert not (tmp_path / ".comments").exists()
