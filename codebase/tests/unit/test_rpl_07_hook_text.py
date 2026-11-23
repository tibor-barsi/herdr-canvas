"""The hook text describes a send's comments one per line (RPL-07, PLG-05)."""

from __future__ import annotations

import pytest

from agent_canvas.hooks import format_events

pytestmark = pytest.mark.unit

TIME = "2026-11-09T09:14:40.002Z"
EARLIER = "2026-11-08T10:00:00.000Z"
LONG = "x" * 130


def comment(n: int, kind: str, text: str, **fields) -> dict:  # noqa: ANN003
    base = {
        "n": n, "kind": kind, "text": text, "anchor": {}, "target": None,
        "text_inside": None, "data": None, "source_line": None, "lost": False,
        "picture": None, "picture_error": None, "replies": [],
    }  # fmt: skip
    return {**base, **fields}


def send(*comments: dict, **fields) -> dict:  # noqa: ANN003
    return {
        "kind": "send", "time": TIME, "message": "check these", "page": "report.pdf",
        "page_version": 2, "screenshot": None, "screenshot_error": "page not shown",
        "actions": [], "comments": list(comments), **fields,
    }  # fmt: skip


FIXED_EVENT = send(
    comment(
        1, "text", "Units missing here.",
        anchor={"space": "pdf-pt", "quote": "damping ratios between 0.8 and 1.9",
                "rects": [{"p": 3, "x": 72.0, "y": 410.2, "w": 301.5, "h": 11.0}]},
        target={"canvas_id": None, "selector": ".page[data-page='3']", "text": "Four"},
        picture="/abs/s/history/sends/0002.c1.png",
        replies=[
            {"from": "claude-code", "text": "Added %.", "at": "t", "sent": None},
            {"from": None, "text": "Old question", "at": "t", "sent": EARLIER},
            {"from": None, "text": "Thanks; also in Table 2.", "at": "t", "sent": TIME},
        ],
    ),
    comment(
        2, "lasso", "Why this peak?",
        target={"canvas_id": "spectrum", "selector": "#plot", "text": None},
        data={"canvas_id": "spectrum", "x": [3.1, 4.4], "y": [0.2, 0.9]},
        text_inside="peak A", picture="/abs/s/history/sends/0002.c2.png",
    ),
    comment(
        3, "point", "Label?", lost=True, picture_error="timed out",
        target={"canvas_id": None, "selector": "#fig", "text": None},
    ),
)  # fmt: skip

EXPECTED = """\
Feedback from the owner in the agent-canvas window:
1. send (page report.pdf, version 2): "check these"
   no screenshot available (page not shown)
comment #1 text on .page[data-page='3'] «damping ratios between 0.8 and 1.9» p. 3: "Units missing here."
   picture: /abs/s/history/sends/0002.c1.png
   reply on #1: "Thanks; also in Table 2."
comment #2 lasso on spectrum data x 3.1 to 4.4, y 0.2 to 0.9 text inside «peak A»: "Why this peak?"
   picture: /abs/s/history/sends/0002.c2.png
comment #3 point on #fig (lost: no longer found on the page): "Label?"
   no picture (timed out)
Answer each: agent-canvas comment reply report.pdf N "text" [--done]"""  # noqa: E501


def test_rpl_07_the_fixed_event_gives_exactly_the_expected_text() -> None:
    assert format_events([FIXED_EVENT]) == EXPECTED


def test_rpl_07_a_markdown_comment_names_its_line_and_a_long_quote_is_cut() -> None:
    event = send(
        comment(4, "text", "t", anchor={"space": "page-px", "quote": LONG},
                source_line=12, data={"canvas_id": "p", "x": 2.5, "y": [1, 2]}),
    )  # fmt: skip
    lines = format_events([event]).splitlines()
    assert (
        f'comment #4 text on the page «{"x" * 120}» line 12 data x 2.5, y 1 to 2: "t"'
        in lines
    )


def test_rpl_07_an_event_without_comments_has_no_answer_line() -> None:
    assert "Answer each" not in format_events([send()])


def test_ans_06_an_answer_line_stays_one_line_and_an_ask_note_is_cut() -> None:
    event = {
        "id": "e1", "kind": "answer", "page": "page.html",
        "target": {"canvas_id": "q1"},
        "value": {"answer": ["a"], "other": "x\ny", "note": "one\ntwo " + LONG * 2},
    }  # fmt: skip
    [line] = format_events([event]).splitlines()[1:]
    assert line.startswith("answer q1 (page.html): a · other: x y · note: one two x")
    assert len(line.split("note: ")[1]) == 200
