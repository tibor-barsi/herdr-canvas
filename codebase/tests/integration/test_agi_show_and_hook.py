"""`show` takes a bare name and a next step; the hook says what to do (AGI-05..08)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_hooks import SESSION, known, prompt_hook  # noqa: F401

from agent_canvas.hooks import closing_lines

pytestmark = pytest.mark.integration

ASK_PAGE = (
    "<title>Pick the infill</title>"
    '<canvas-ask data-canvas-id="q1"><script type="application/json">'
    '{"question": "Which infill?", "options": ["gyroid", "lines"]}'
    "</script></canvas-ask>"
)


def folder_of(cli, session: str = "a") -> Path:  # noqa: ANN001
    return Path(cli("session", "path", "--session", session).json["folder"])


def test_agi_05_show_accepts_a_name_without_the_extension(cli) -> None:  # noqa: ANN001
    (folder_of(cli) / "plot.html").write_text("<p>x</p>")
    result = cli("show", "plot", "--session", "a")
    assert result.code == 0, result.err
    assert result.json["page"] == "plot.html"


def test_agi_05_a_bare_name_still_refuses_a_draft_and_a_missing_page(cli) -> None:  # noqa: ANN001
    (folder_of(cli) / "plot.draft.html").write_text("<p>x</p>")
    assert cli("show", "plot", "--session", "a").code == 1
    assert cli("show", "plot.draft", "--session", "a").code == 1


def test_agi_05_an_unknown_name_suggests_the_closest_page(cli) -> None:  # noqa: ANN001
    (folder_of(cli) / "bracket-options.html").write_text("<p>x</p>")
    result = cli("show", "bracket-option", "--session", "a")
    assert result.code == 1
    assert "Did you mean bracket-options.html?" in result.err + result.out


def test_agi_05_an_unknown_name_with_nothing_close_suggests_nothing(cli) -> None:  # noqa: ANN001
    (folder_of(cli) / "bracket-options.html").write_text("<p>x</p>")
    result = cli("show", "zzzz", "--session", "a")
    assert result.code == 1
    assert "Did you mean" not in result.err + result.out


def test_agi_06_show_ends_with_a_next_step_naming_the_page_title(cli) -> None:  # noqa: ANN001
    (folder_of(cli) / "ask.html").write_text(ASK_PAGE)
    data = cli("show", "ask", "--session", "a").json
    assert set(data) == {
        "session", "page", "path", "url", "version", "window", "rendered",
        "errors", "audit", "next",
    }  # fmt: skip
    assert '"Pick the infill"' in data["next"]
    assert "next message" in data["next"]
    assert "agent-canvas watch --timeout 540" in data["next"]
    assert "Monitor" in data["next"]


def test_agi_06_without_a_title_tag_the_next_step_names_the_page(cli) -> None:  # noqa: ANN001
    (folder_of(cli) / "plain.html").write_text("<p>x</p>")
    assert '"plain.html"' in cli("show", "plain", "--session", "a").json["next"]


EVENT = {"kind": "answer", "page": "p.html", "target": {"canvas_id": "q1"},
         "value": {"answer": "keep"}}  # fmt: skip
SEND = {"kind": "send", "message": "hi", "screenshot": "/x.png", "actions": []}


def test_agi_07_answers_todos_and_changes_end_with_what_to_do() -> None:
    for kind in ("answer", "todo", "change"):
        lines = closing_lines([{**EVENT, "kind": kind}], waiting=0)
        assert lines == [
            "Act on the answers, todos and changes above, say so in your reply, "
            "and record decisions in the project's decision log."
        ]


def test_agi_07_a_plain_send_adds_no_closing_line() -> None:
    assert closing_lines([SEND], waiting=0) == []


def test_agi_08_open_asks_make_one_short_line() -> None:
    assert closing_lines([], waiting=1) == [
        "agent-canvas: 1 question waits on the canvas."
    ]
    assert closing_lines([], waiting=3) == [
        "agent-canvas: 3 questions wait on the canvas."
    ]


def hook_text(cli) -> str:  # noqa: ANN001
    result = prompt_hook(cli)
    assert (result.code, result.err) == (0, "")
    if not result.out:
        return ""
    return json.loads(result.out)["hookSpecificOutput"]["additionalContext"]


def test_agi_08_the_hook_counts_asks_waiting_on_shown_pages(cli, hub, known) -> None:  # noqa: ANN001, F811
    env = {"AGENT_CANVAS_SESSION": SESSION, "AGENT_CANVAS_AGENT": "claude-code"}
    folder = Path(cli("session", "path", extra_env=env).json["folder"])
    assert hook_text(cli) == ""
    (folder / "ask.html").write_text(ASK_PAGE)
    assert cli("show", "ask", "--no-audit", extra_env=env).code == 0
    assert hook_text(cli) == "agent-canvas: 1 question waits on the canvas."
    assert hook_text(cli) == "agent-canvas: 1 question waits on the canvas."
