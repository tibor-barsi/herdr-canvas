"""Waiting Do boxes are counted beside the questions, named apart (AGI-08, D-65)."""
# ruff: noqa: F811

from __future__ import annotations

import pytest
from test_agi_show_and_hook import ASK_PAGE, hook_text  # noqa: F401
from test_agi_stop_reminder import ENV, reminder, show_page, stop_hook
from test_hooks import known  # noqa: F401

from agent_canvas.hooks import STOP_REMINDER, closing_lines

pytestmark = pytest.mark.integration

DO_PAGE = (
    "<title>Heater</title>"
    '<canvas-do data-canvas-id="w1"><script type="application/json">'
    '{"title": "Plug in the heater", "steps": []}'
    "</script></canvas-do>"
)


@pytest.mark.parametrize(
    ("questions", "todos", "line"),
    [
        (1, 0, "agent-canvas: 1 question waits on the canvas."),
        (3, 0, "agent-canvas: 3 questions wait on the canvas."),
        (0, 1, "agent-canvas: 1 to-do waits on the canvas."),
        (0, 2, "agent-canvas: 2 to-dos wait on the canvas."),
        (1, 1, "agent-canvas: 1 question and 1 to-do wait on the canvas."),
        (2, 1, "agent-canvas: 2 questions and 1 to-do wait on the canvas."),
    ],
)
def test_agi_08_the_line_names_questions_and_to_dos_apart(
    questions: int, todos: int, line: str
) -> None:
    assert closing_lines([], questions, todos) == [line]


def test_agi_08_nothing_waits_no_line() -> None:
    assert closing_lines([], 0, 0) == []


def test_agi_08_pending_returns_waiting_todos_beside_waiting(cli, hub, known) -> None:  # noqa: ANN001
    show_page(cli, DO_PAGE)
    answer = cli("pending", "--peek", extra_env=ENV).json
    assert answer["waiting_todos"] == 1 and "waiting" not in answer
    assert answer["listening"] is False
    show_page(cli, ASK_PAGE.replace("</canvas-ask>", "</canvas-ask>" + DO_PAGE))
    answer = cli("pending", "--peek", extra_env=ENV).json
    assert (answer["waiting"], answer["waiting_todos"]) == (1, 1)


def test_agi_08_the_prompt_hook_counts_a_waiting_do(cli, hub, known) -> None:  # noqa: ANN001
    show_page(cli, DO_PAGE)
    assert hook_text(cli) == "agent-canvas: 1 to-do waits on the canvas."
    show_page(cli, ASK_PAGE.replace("</canvas-ask>", "</canvas-ask>" + DO_PAGE))
    assert hook_text(cli) == "agent-canvas: 1 question and 1 to-do wait on the canvas."


def test_agi_08_the_end_of_turn_reminder_counts_a_waiting_do(cli, hub, known) -> None:  # noqa: ANN001
    show_page(cli, DO_PAGE)
    assert reminder(stop_hook(cli, "p1")) == (
        "agent-canvas: 1 to-do waits on the canvas and nothing is listening. Start "
        "`agent-canvas watch --timeout 540` under Monitor, or tell the owner to "
        "reply in the terminal when they have answered."
    )


def test_agi_08_with_no_waiting_do_the_reminder_is_today_s_text(
    cli, hub, known
) -> None:  # noqa: ANN001
    show_page(cli, ASK_PAGE)
    assert reminder(stop_hook(cli, "p1")) == STOP_REMINDER
    assert STOP_REMINDER == (
        "agent-canvas: a question you put on the canvas is still open and nothing is "
        "listening for the answer. Start `agent-canvas watch --timeout 540` under "
        "Monitor, or tell the owner to reply in the terminal when they have answered."
    )
