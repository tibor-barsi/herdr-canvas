"""Agent instructions: description, guide order, question rule, facts (AGI-01..04)."""

from __future__ import annotations

import asyncio
import re

import pytest
from mcp import Client

from agent_canvas.guide_text import SKILL_DESCRIPTION, _read, guide_text
from agent_canvas.mcp_server import create_server
from agent_canvas.templates import TEMPLATES
from helpers import PACKAGE_DIR, PLUGIN_DIR, REPO_DIR

pytestmark = pytest.mark.unit


def flat(text: str) -> str:
    return " ".join(text.split())


def test_agi_01_the_description_is_under_the_cap_and_names_the_owners_phrasings() -> (
    None
):
    text = flat(SKILL_DESCRIPTION)
    assert len(SKILL_DESCRIPTION) < 1536
    for phrase in (
        "questions",
        "decisions",
        "approvals",
        "on the canvas",
        "let me pick",
        "so I can comment",
        "checklist",
        "not for one-sentence answers",
    ):
        assert phrase in text, phrase  # fmt: skip


def test_agi_02_the_block_reference_opens_with_a_canvas_ask_example() -> None:
    first = _read("blocks.md").split("```html", 1)[1].split("```", 1)[0]
    assert "<canvas-ask" in first and "canvas-choices" not in first


def test_agi_02_choices_are_live_selection_and_submit_is_not_for_decisions() -> None:
    section = _read("blocks.md").split("## `canvas-choices`", 1)[1].split("\n## ", 1)[0]
    text = flat(section)
    assert "live selection" in text
    assert "not for decisions" in text and "`canvas-ask`" in text


def test_agi_02_the_ask_command_and_the_ask_card_are_related_in_one_sentence() -> None:
    assert "The `ask` command is not the `canvas-ask` card" in flat(guide_text())


def test_agi_02_which_card_comes_before_writing_pages() -> None:
    text = _read("guideline.md")
    assert text.index("Which card") < text.index("## Writing and showing pages")


def test_agi_02_the_owners_split_between_terminal_question_and_cards() -> None:
    head = flat(_read("guideline.md").split("## Writing and showing pages", 1)[0])
    for phrase in (
        "terminal question tool",
        "one quick pick",
        "needs a picture",
        "several questions",
        "can wait",
    ):
        assert phrase in head, phrase  # fmt: skip


def test_agi_02_the_compare_template_asks_with_a_canvas_ask() -> None:
    html = TEMPLATES["compare"].read_text()
    assert "<canvas-ask" in html and "canvas-choices" not in html


def test_agi_03_a_question_rule_names_what_a_good_question_has() -> None:
    text = flat(_read("guideline.md"))
    for phrase in (
        "what it is about in plain words",
        "page title the owner sees",
        "a recommendation",
        "never refers to anything not on the screen",
    ):
        assert phrase in text, phrase  # fmt: skip
    assert abs(text.index("rehearse it") - text.index("what it is about")) < 1200


def test_agi_04_the_guide_describes_the_audit_object_exactly() -> None:
    text = flat(guide_text())
    assert "an object, not a list" in text
    for key in ("`summary`", "`findings`", "`counts`", "`rule`, `severity`, `message`"):
        assert key in text, key


def test_agi_04_the_new_page_tool_lists_the_templates_that_exist() -> None:
    source = (PACKAGE_DIR / "mcp_server.py").read_text()
    listed = re.search(r"Templates: ([a-z, ]+)\.", source)
    assert listed
    assert set(listed.group(1).split(", ")) == set(TEMPLATES)


def registered_tools() -> set[str]:
    async def main() -> set[str]:
        async with Client(create_server()) as client:
            return {t.name for t in (await client.list_tools()).tools}

    return asyncio.run(main())


@pytest.mark.parametrize("path", ["plugin/README.md", "docs/opencode.md"])
def test_agi_04_the_docs_list_every_mcp_tool(path: str) -> None:
    text = (REPO_DIR / path).read_text()
    tools = registered_tools()
    assert len(tools) >= 15
    assert [t for t in sorted(tools) if f"`{t}`" not in text] == []


def test_agi_04_the_plugin_readme_counts_the_hooks_that_exist() -> None:
    text = flat((PLUGIN_DIR / "README.md").read_text())
    assert "three hooks" not in text
    assert "hooks on four events" in text
