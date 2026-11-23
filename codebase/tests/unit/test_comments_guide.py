"""Guideline: comment loop, cards, interaction kinds (RPL-08, PLAN-04, KIND-09)."""

from __future__ import annotations

import re

import pytest

from agent_canvas.cli import main
from agent_canvas.guide_text import guide_text, skill_text
from helpers import PACKAGE_DIR, PLUGIN_DIR, REPO_DIR

pytestmark = pytest.mark.unit

GUIDELINE = PACKAGE_DIR / "guide" / "guideline.md"
BLOCKS = PACKAGE_DIR / "guide" / "blocks.md"
CARDS = ("report", "alert", "ask", "decision", "live", "do")
CONTENT = (
    "plot", "image", "model", "scene", "document", "animation", "file", "source",
    "metrics", "compare", "table", "progress", "markdown",
)  # fmt: skip
COMMANDS = "watch|ask|result|pending|answers|comment|look|show|new|session|guide|page"


def flat(text: str) -> str:
    """Collapse line breaks so that key phrases survive re-wrapping."""
    return " ".join(text.split())


def item(number: int) -> str:
    """The lines of one numbered guideline item, up to the next item or heading."""
    lines = GUIDELINE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{number}. "))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"(\d+\. |#)", lines[i]):
            end = i
            break
    return "\n".join(lines[start:end]).rstrip()


RPL_08 = [
    "Comments arrive with a send", "`watch`", "`wait_for_feedback`", "`pending`",
    "picture", "agent-canvas comment reply", "--done", "then wait again",
    "agent-canvas comment list", "lost",
]  # fmt: skip
PLAN_04 = [
    "approval card", "--approval", "--details-file", "numbered lines", "approved",
    "sent-back", "ask again", "result card",
]  # fmt: skip
KIND_09 = [
    "five kinds", "`canvas-ask`", "`canvas-do`", "`canvas-report`",
    "`canvas-decision`", "`canvas-alert`", "`canvas-live`", "inside a card",
    "only an Ask or Do may go inside a Report, Alert or Live card",
    "One Ask is one question", "`default`", "agent-canvas answers --wait",
    "agent-canvas answers [--open]",
    "watch for it", "tell the owner to reply when done", "answer buttons",
    "shared answer field", "`where`",
    "secrets", "decision log",
]  # fmt: skip
LIFE_13 = [
    "Page kinds", "`single-use`", "`transitional`", "`long-term`", "questions",
    "options", "interviews", "plans", "work in progress", "dashboards",
    "agent-canvas show NAME --kind KIND", "page kind",
    "agent-canvas page list", "agent-canvas page archive NAME",
    "`page restore NAME`", "agent-canvas page extend NAME",
    "past their lifetime", "archive", "extend", "`pending`",
]  # fmt: skip


def test_rpl_08_the_comment_loop_is_told() -> None:
    text = flat(item(10))
    for phrase in RPL_08:
        assert phrase in text, phrase


def test_plan_04_approval_and_result_cards_are_told() -> None:
    text = flat(item(10))
    for phrase in PLAN_04:
        assert phrase in text, phrase


def test_kind_09_the_kinds_are_taught() -> None:
    text = flat(item(1))
    for phrase in KIND_09:
        assert phrase in text, phrase


def test_kind_09_is_at_most_25_lines() -> None:
    assert len(item(1).splitlines()) <= 25


def test_rpl_08_item_8_is_short() -> None:
    assert len(item(10).splitlines()) <= 14 + 8


def page_kind_lines() -> list[str]:
    """The lines of item 10 from the paragraph that starts with the page kinds."""
    lines = item(10).splitlines()
    start = next(i for i, line in enumerate(lines) if "Page kinds" in line)
    return lines[start:]


def test_life_13_page_kinds_are_told() -> None:
    text = flat(" ".join(page_kind_lines()))
    for phrase in LIFE_13:
        assert phrase in text, phrase


def test_life_13_page_kind_lines_are_at_most_8() -> None:
    assert len(page_kind_lines()) <= 8


def test_plan_04_pages_for_a_question_get_kind_single_use() -> None:
    text = flat(item(10))
    assert "question, a choice or a plan" in text
    assert "--kind single-use" in text


def test_kind_09_every_card_and_content_element_has_a_reference_section() -> None:
    text = BLOCKS.read_text()
    for name in CARDS + CONTENT:
        assert f"## `canvas-{name}`" in text, name


def test_kind_09_every_element_the_guideline_names_has_a_reference_section() -> None:
    named = set(re.findall(r"`(canvas-[a-z]+)`", item(1)))
    assert len(named) >= len(CARDS)
    sections = set(re.findall(r"^## `(canvas-[a-z]+)`", BLOCKS.read_text(), re.M))
    assert named <= sections


def test_plg_03_rules_are_in_order_and_cards_come_first_agi_02_agi_13() -> None:
    text = GUIDELINE.read_text()
    positions = [text.index(f"\n{n}. ") for n in range(1, 11)]
    assert positions == sorted(positions)
    assert "five kinds" in item(1)


def test_plg_03_skill_equals_the_generated_text() -> None:
    skill = (PLUGIN_DIR / "skills" / "agent-canvas" / "SKILL.md").read_text()
    assert skill == skill_text()
    assert flat(item(1)) in flat(skill)


def test_plg_03_no_draw_mode_is_left() -> None:
    text = flat(guide_text() + skill_text()).lower()
    for phrase in (
        "draw mode", "drawings", "drawn shapes", "`marks`", "data_bbox",
        "the owner draws",
    ):  # fmt: skip
        assert phrase not in text, phrase


def command_spans(text: str) -> list[str]:
    """Backtick spans of the text that start with a command of the CLI."""
    spans = re.findall(r"`([^`\n]+)`", flat(text))
    return [s for s in spans if re.match(rf"(agent-canvas )?({COMMANDS})(\s|$)", s)]


def command_help(words: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as stop:
        main([*words, "--help"])
    assert stop.value.code == 0
    return flat(capsys.readouterr().out)


def test_plg_03_every_command_and_flag_the_guideline_names_answers_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    named = command_spans(item(10) + "\n" + item(1))
    assert any("comment reply" in s for s in named)
    assert any("answers --wait" in s for s in named)
    for span in command_spans(GUIDELINE.read_text()):
        words = span.removeprefix("agent-canvas ").split()
        command = words[:2] if words[0] in ("comment", "session", "page") else words[:1]
        help_text = command_help(command, capsys)
        for flag in re.findall(r"--[a-z-]+", span):
            assert flag in help_text, (span, flag)


def test_plg_07_opencode_note_names_pending_at_task_start_and_answers_after_todo() -> (
    None
):
    text = flat((REPO_DIR / "docs" / "opencode.md").read_text())
    assert "start of every task" in text
    assert "`answers`" in text and "`todo` event" in text
