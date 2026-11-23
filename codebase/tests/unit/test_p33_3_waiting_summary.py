"""The summary of what waits, read with plain data (P33.3: AGI-08, HOME-26, AGT-20)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from agent_canvas.hub.answers import AnswerStore
from agent_canvas.hub.waiting import (
    Waiting,
    agent_pages,
    for_agent,
)
from agent_canvas.hub.watcher import PageHistory

pytestmark = pytest.mark.unit

SINCE = "2026-11-16T10:00:00.000Z"
NOW = datetime.fromisoformat(SINCE).timestamp() + 60


def box(item_id: str, kind: str = "ask", waits: bool = True, **extra) -> dict:  # noqa: ANN003
    """Return an open box as the home reading gives it."""
    need = {"do": "todo"}.get(kind, "question")
    default = None if waits or kind == "do" else "keep"
    fields = {
        "page": "p.html",
        "id": item_id,
        "kind": kind,
        "text": f"{item_id}?",
        "waits": waits,
        "default": default,
        "need": need,
        "since": SINCE,
    }
    return fields | extra


def asked(ask_id: str, approval: bool = False) -> dict:
    """Return an open question put with ``ask`` as the registry view gives it."""
    return {
        "id": ask_id,
        "approval": approval,
        "question": f"{ask_id}?",
        "created": SINCE,
    }


CASES = {
    "nothing": (Waiting(), None, [], None),
    "ask without default": (
        Waiting(boxes=[box("q1")]), 1, ["q1"], {"kind": "question", "text": "q1?"}
    ),
    "ask with default": (Waiting(boxes=[box("q2", waits=False)]), None, ["q2"], None),
    "approval ask": (
        Waiting(boxes=[box("q3", need="approval")]), 1, ["q3"],
        {"kind": "approval", "text": "q3?"},
    ),
    "do": (Waiting(boxes=[box("w1", "do")]), None, ["w1"],
           {"kind": "todo", "text": "w1?"}),
    "ask command question": (
        Waiting(asks=[asked("a1", approval=True)]), None, ["a1"],
        {"kind": "approval", "text": "a1?"},
    ),
    "ask command first, then boxes": (
        Waiting(asks=[asked("a1")], boxes=[box("q1"), box("w1", "do")]), 1,
        ["a1", "q1", "w1"], {"kind": "question", "text": "a1?"},
    ),
    "first waiting box in page order": (
        Waiting(boxes=[box("q2", waits=False), box("w1", "do"), box("q1")]), 1,
        ["q2", "w1", "q1"], {"kind": "todo", "text": "w1?"},
    ),
    "several asks and dos": (
        Waiting(boxes=[box("q1"), box("q2"), box("w1", "do"), box("q3", waits=False)]),
        2, ["q1", "q2", "w1", "q3"], {"kind": "question", "text": "q1?"},
    ),
}  # fmt: skip


@pytest.mark.parametrize("case", CASES)
def test_agi_08_pending_counts_the_waiting_asks_only(case: str) -> None:
    """``waiting`` counts Ask boxes that wait, never ``ask`` questions or Dos."""
    summary, waiting, _, _ = CASES[case]
    told = for_agent(summary)
    assert told.get("waiting") == waiting  # left out at zero


TODOS = {
    "do": 1,
    "ask command first, then boxes": 1,
    "first waiting box in page order": 1,
    "several asks and dos": 1,
}


@pytest.mark.parametrize("case", CASES)
def test_agi_08_pending_counts_the_waiting_dos_apart(case: str) -> None:
    """``waiting_todos`` counts the Do boxes that wait, left out at zero (D-65)."""
    assert for_agent(CASES[case][0]).get("waiting_todos") == TODOS.get(case)


def test_agi_08_pending_hands_over_feedback_and_reminders_as_they_are() -> None:
    event, reminder = {"id": "evt_1"}, {"page": "p.html", "kind": "plan"}
    summary = Waiting(boxes=[box("q1")], feedback=[event], reminders=[reminder])
    assert for_agent(summary) == {
        "events": [event], "reminders": [reminder], "waiting": 1,
    }  # fmt: skip


def test_agi_08_the_agent_reads_archived_pages_but_no_draft_or_other_file() -> None:
    """The page set of ``pending`` (A-741): archived kept, drafts and non-pages out."""
    meta = {
        "pages": ["a.html", "b.draft.html", "c.html", ".d.html", "notes.md"],
        "page_meta": {"c.html": {"archived": SINCE}},
    }
    assert agent_pages(meta["pages"]) == ["a.html", "c.html"]
    assert agent_pages(()) == []


def card(tag: str, item_id: str, config: dict) -> str:
    """Return one card element with its JSON config."""
    return (
        f'<{tag} data-canvas-id="{item_id}">'
        f'<script type="application/json">{json.dumps(config)}</script></{tag}>'
    )


PAGE = (
    card("canvas-ask", "q1", {"question": "Keep A?", "options": ["keep", "change"]})
    + card("canvas-ask", "q2", {"question": "Wider?", "default": "keep"})
    + card("canvas-ask", "q3", {"question": "Which?", "options": ["a", "b"]})
    + card("canvas-do", "w1", {"title": "Plug in the heater", "steps": []})
    + card("canvas-decision", "d1", {"text": "Use PETG"})
)


def test_agi_08_answered_boxes_and_decisions_are_not_open_boxes(tmp_path: Path) -> None:
    """Both readings of the answer store agree on the open boxes of a page."""
    store = AnswerStore(lambda sid: tmp_path, lambda sid: ["p.html"], lambda *a: None)
    PageHistory(tmp_path).save("p.html", PAGE.encode())
    (tmp_path / "p.html").write_text(PAGE)
    item = store.item_of("s", "p.html", "q3")
    store.record("s", "p.html", item, state="answered", value={"answer": ["a"]},
                 event="evt_1", time=SINCE)  # fmt: skip
    boxes = store.open_boxes("s")
    assert [(b["id"], b["waits"]) for b in boxes] == [
        ("q1", True),
        ("q2", False),
        ("w1", True),
    ]
    assert for_agent(Waiting(boxes=boxes))["waiting"] == 1
