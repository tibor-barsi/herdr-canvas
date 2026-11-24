"""Always-on core, MCP instructions, shorter skill, `guide blocks` (AGI-09..14)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from mcp import Client

from agent_canvas.cli import main
from agent_canvas.guide_text import _read, blocks_text, core_text, guide_text
from agent_canvas.hooks import closing_lines, format_events
from agent_canvas.hub.routes.sessions import _next_step
from agent_canvas.mcp_server import INSTRUCTIONS, create_server
from helpers import PLUGIN_DIR

pytestmark = pytest.mark.unit

SKILL = PLUGIN_DIR / "skills" / "agent-canvas" / "SKILL.md"
CORE_CAP = 1300
MCP_CAP = 4096
SKILL_WORD_CAP = 1700


def skill_body() -> str:
    return SKILL.read_text().split("\n---\n", 1)[1].lstrip("\n")


def loop_section() -> str:
    return guide_text().split("## The loop, worked through", 1)[1].split("\n## ", 1)[0]


def test_agi_09_the_core_is_one_file_under_the_cap() -> None:
    core = core_text()
    assert core == _read("core.md").strip()
    assert len(core) <= CORE_CAP, len(core)


def test_agi_09_the_core_names_cards_loop_and_where_answers_come_from() -> None:
    core = " ".join(core_text().split())
    for phrase in (
        "`canvas-ask`", "`canvas-do`", "`canvas-report`", "`canvas-decision`",
        "`canvas-alert`", "agent-canvas look NAME --draft",
        "agent-canvas show NAME --publish", "tell the owner the page title",
        "agent-canvas watch --timeout 540", "owner's next message", "`pending`",
        "agent-canvas guide blocks",
    ):  # fmt: skip
        assert phrase in core, phrase


def test_agi_09_the_guide_and_the_skill_start_with_the_core() -> None:
    assert guide_text().startswith(core_text() + "\n\n")
    assert skill_body().startswith(core_text() + "\n\n")


def test_agi_11_the_mcp_instructions_carry_the_core_under_the_cap() -> None:
    async def received() -> str | None:
        async with Client(create_server()) as client:
            return client.instructions

    text = asyncio.run(received())
    assert text == INSTRUCTIONS
    assert text.endswith(core_text())
    assert "session_start" in text and "`session`" in text
    assert len(text) <= MCP_CAP, len(text)


def test_agi_12_guide_blocks_prints_the_block_reference(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["guide", "blocks"]) == 0
    text = capsys.readouterr().out
    assert text == blocks_text()
    assert text.startswith("# Blocks")
    for tag in ("canvas-ask", "canvas-choices", "canvas-plot", "canvas-model"):
        assert f"## `{tag}`" in text, tag
    assert "Kit classes:" in text


def test_agi_12_guide_without_a_topic_is_the_skill_body_without_the_blocks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["guide"]) == 0
    text = capsys.readouterr().out
    assert text == skill_body()
    assert "## `canvas-" not in text
    assert "`agent-canvas guide blocks`" in text


def test_agi_13_the_skill_is_core_loop_cards_reference_in_that_order() -> None:
    body = skill_body()
    headings = re.findall(r"^## (.+)$", body, re.M)
    assert headings[:2] == ["The loop, worked through", "Which card for which need"]
    assert len(headings) > 2  # the reference follows


def test_agi_13_the_skill_stays_under_the_word_cap() -> None:
    words = len(SKILL.read_text().split())
    assert words <= SKILL_WORD_CAP, words


def test_agi_14_the_example_has_draft_look_publish_and_the_answer() -> None:
    loop = " ".join(loop_section().split())
    for phrase in (
        "infill.TAG.draft.html", "agent-canvas look infill --draft", '"png":',
        '"audit": {"findings"', "agent-canvas show infill --publish", '"next":',
        "agent-canvas watch --timeout 540", '"kind": "answer"', "owner's next message",
    ):  # fmt: skip
        assert phrase in loop, phrase


def test_agi_14_the_example_ask_is_a_valid_canvas_ask_config() -> None:
    html = loop_section().split("```html", 1)[1].split("```", 1)[0]
    assert "<title>" in html and '<canvas-ask data-canvas-id="q-infill">' in html
    config = json.loads(html.split('"application/json">', 1)[1].split("</script>")[0])
    assert set(config) <= {"question", "context", "options", "recommended", "default"}
    assert config["recommended"] in config["options"]


def test_agi_14_the_example_quotes_the_real_next_line_and_hook_text(
    tmp_path: Path,
) -> None:
    page = tmp_path / "infill.html"
    page.write_text("<title>Infill for the bracket</title>")
    quoted = 'Tell the owner the page "Infill for the bracket" is on the canvas.'
    assert _next_step("infill.html", page, None).startswith(quoted)
    assert quoted.replace('"', '\\"') in " ".join(loop_section().split())

    event = {
        "kind": "answer",
        "page": "infill.html",
        "target": {"canvas_id": "q-infill"},
        "value": {
            "question": "Which infill do we print the bracket with?",
            "form": "one",
            "answer": ["gyroid"],
            "other": None,
            "note": "fine, go on",
            "replaces": None,
        },
    }
    told = "\n".join([format_events([event]), *closing_lines([event], 0)])
    assert f"```text\n{told}\n```" in loop_section()
