"""The guideline, the skill, the plugin files and the opencode document.

Covers PLG-01 (files), PLG-03 (guideline), PLG-03a (README rule), PLG-07
(opencode) and CLI-13 (``guide`` equals the skill body).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import agent_canvas
from agent_canvas import __version__
from agent_canvas.cli import main
from helpers import PLUGIN_DIR, REPO_DIR

pytestmark = pytest.mark.unit

SKILL = PLUGIN_DIR / "skills" / "agent-canvas" / "SKILL.md"


def guide_output(capsys: pytest.CaptureFixture[str]) -> str:
    assert main(["guide"]) == 0
    return capsys.readouterr().out


def flat(text: str) -> str:
    """Collapse line breaks so that key phrases survive re-wrapping."""
    return " ".join(text.split())


def skill_body() -> str:
    text = SKILL.read_text()
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[1].lstrip("\n")


# ---- CLI-13 -------------------------------------------------------------


def test_cli_13_guide_equals_the_skill_body(capsys: pytest.CaptureFixture[str]) -> None:
    assert guide_output(capsys) == skill_body()


def test_cli_13_skill_front_matter_names_the_skill() -> None:
    front = SKILL.read_text().split("\n---\n", 1)[0]
    assert "name: agent-canvas" in front and "description:" in front


def test_cli_13_guide_covers_agents_with_and_without_monitor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = guide_output(capsys)
    assert "Monitor" in text and "wait_for_feedback" in text


def test_cli_13_guide_blocks_prints_the_block_reference_agi_12(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["guide", "blocks"]) == 0
    text = capsys.readouterr().out
    for tag in ("canvas-choices", "canvas-plot", "canvas-model"):
        assert f"<{tag}" in text


# ---- PLG-03: one assertion group per numbered instruction ---------------

INSTRUCTIONS = {
    1: ["mentions the canvas", "plot, picture or document says more than text",
        "questions, decisions, approvals", "One-sentence answers",
        "stay in the terminal"],  # the core (AGI-09) says when to use it
    2: ["agent-canvas session path", "<project>/.agent-canvas/<session>/",
        "an `id`", "blocks", "never load anything from the internet"],
    3: ["SessionStart context", "session id as `session`", "AGENT_CANVAS_SESSION",
        "session_start"],
    4: ["ToolSearch", "select:Monitor", "agent-canvas watch", "under Monitor",
        "10 minutes", "`timeout_ms` 600000", "--timeout 540", "watch-ended",
        '"renew": true'],
    5: ["Without Monitor", "blocking `ask`", "agent-canvas watch --count 1 --timeout",
        "wait_for_feedback", "`pending` at the start of every turn"],
    6: ["Bash timeout above its own `--timeout`"],
    7: ["carries an `event` id", "Do not act on it a second time"],
}  # fmt: skip


@pytest.mark.parametrize("number", sorted(INSTRUCTIONS))
def test_plg_03_instruction_is_present(
    number: int, capsys: pytest.CaptureFixture[str]
) -> None:
    text = flat(guide_output(capsys))
    for phrase in INSTRUCTIONS[number]:
        assert phrase in text, (number, phrase)


def test_plg_03_ask_watch_pending_are_told_apart(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = flat(guide_output(capsys))
    for phrase in ("`ask` puts one question", "`watch` streams", "`pending` returns"):
        assert phrase in text


def test_plg_03_refused_write_tells_the_owner_the_allow_rule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = flat(guide_output(capsys))
    assert "Edit(**/.agent-canvas/**)" in text and "refused" in text


def test_plg_03_page_is_written_with_the_file_tool_not_the_shell(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = flat(guide_output(capsys))
    assert "with your own file-writing tool (Claude Code: Write/Edit)" in text
    assert "not with shell commands such as `cat > file` or heredocs" in text


# ---- PLG-01: plugin files -----------------------------------------------


def load(path: str) -> dict:
    return json.loads((PLUGIN_DIR / path).read_text())


def test_plg_01_plugin_files_exist() -> None:
    for name in (
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".mcp.json",
        "skills/agent-canvas/SKILL.md",
        "hooks/hooks.json",
        "README.md",
    ):
        assert (PLUGIN_DIR / name).is_file(), name


def test_plg_01_manifest_keys() -> None:
    manifest = load(".claude-plugin/plugin.json")
    assert manifest["name"] == "agent-canvas"
    assert manifest["version"] == __version__
    assert manifest["description"] and manifest["author"]["name"]


def test_plg_01_marketplace_lists_the_plugin() -> None:
    market = load(".claude-plugin/marketplace.json")
    assert [p["name"] for p in market["plugins"]] == ["agent-canvas"]


def test_plg_01_mcp_config_starts_agent_canvas_mcp() -> None:
    server = load(".mcp.json")["mcpServers"]["agent-canvas"]
    line = " ".join([server["command"], *server.get("args", [])])
    assert "agent-canvas mcp" in line
    assert "command -v agent-canvas" in line  # a clear message when it is missing


def test_plg_01_hooks_call_the_cli_directly_without_plugin_root() -> None:
    hooks = load("hooks/hooks.json")["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "SessionEnd", "Stop"}
    expected = {
        "SessionStart": "agent-canvas hook session-start",
        "UserPromptSubmit": "agent-canvas hook user-prompt-submit",
        "SessionEnd": "agent-canvas hook session-end",
    }
    for event, call in expected.items():
        commands = [h["command"] for g in hooks[event] for h in g["hooks"]]
        assert any(call in c for c in commands), event
        assert not any("CLAUDE_PLUGIN_ROOT" in c for c in commands)


def test_plg_01_hooks_say_so_when_the_command_is_missing() -> None:
    hooks = load("hooks/hooks.json")["hooks"]
    command = hooks["SessionStart"][0]["hooks"][0]["command"]
    assert "command -v agent-canvas" in command and "uv tool install" in command


def test_plg_01_skill_is_generated_from_the_package_sources() -> None:
    from agent_canvas.guide_text import skill_text

    assert SKILL.read_text() == skill_text()


# ---- PLG-03a: README ----------------------------------------------------


def test_plg_03a_readme_names_the_allow_rule_and_the_folder() -> None:
    text = (PLUGIN_DIR / "README.md").read_text()
    assert "Edit(**/.agent-canvas/**)" in text
    assert ".agent-canvas" in text and "~/.claude/settings.json" in text
    assert "Write(" in text  # says that a Write(...) path rule does not cover it
    assert "uv tool install" in text and "/plugin marketplace add" in text
    assert "/plugin install" in text


# ---- PLG-07: opencode ---------------------------------------------------


def opencode_text() -> str:
    return (REPO_DIR / "docs" / "opencode.md").read_text()


def test_plg_07_opencode_document_points() -> None:
    text = opencode_text()
    assert "agent-canvas session start --agent opencode --title" in text
    assert "agent-canvas guide" in text
    for route in ("`ask`", "watch --count 1 --timeout", "wait_for_feedback"):
        assert route in text, route
    assert "next-message" in text and "`pending`" in text


def test_plg_07_opencode_json_snippet_parses_and_starts_the_mcp_server() -> None:
    blocks = re.findall(r"```json\n(.*?)```", opencode_text(), re.S)
    assert blocks, "no json snippet"
    config = json.loads(blocks[0])
    entry = config["mcp"]["agent-canvas"]
    assert entry["type"] == "local" and entry["command"] == ["agent-canvas", "mcp"]


# ---- KIT-06 ------------------------------------------------------------


def test_kit_06_guideline_names_the_kit_templates_and_only_real_classes() -> None:
    from agent_canvas.templates import TEMPLATES
    from helpers import PACKAGE_DIR

    text = flat(guide_output_text())
    assert "/static/kit/kit.css" in text
    assert "agent-canvas new" in text and "new_page" in text
    assert all(name in text for name in TEMPLATES)
    css = (PACKAGE_DIR / "static" / "kit" / "kit.css").read_text()
    reference = flat((PACKAGE_DIR_GUIDE / "blocks.md").read_text())  # AGI-12
    line = next(row for row in reference.split("Kit classes:")[1:2])
    listed = re.findall(r"`\.?([a-z][a-z0-9-]*)`", line.split(". ")[0])
    assert len(listed) >= 12
    elements = {"figure", "figcaption", "details", "summary"}  # styled by tag
    for name in listed:
        assert (name in css) if name in elements else (f".{name}" in css), name


def guide_output_text() -> str:
    return (PACKAGE_DIR_GUIDE / "guideline.md").read_text()


PACKAGE_DIR_GUIDE = REPO_DIR / "codebase" / "src" / "agent_canvas" / "guide"


# ---- CHK-16 ------------------------------------------------------------


def test_chk_16_guideline_says_to_fix_errors_and_warnings_before_ready() -> None:
    text = flat(guide_output_text())
    assert "`look` and `show` also report `audit`" in text
    paragraph = text.split("`look` and `show` also report `audit`")[1].split("##")[0]
    assert "`error` and `warn`" in paragraph and "ready" in paragraph
    assert "`info` items are judgement calls" in paragraph
    assert "--no-audit" in paragraph
    assert len(paragraph.split(". ")) <= 4  # a few lines, no design advice


# ---- VIEW-14 -----------------------------------------------------------


REASONS = ("pdf-corrupt", "pdf-password", "image-undecodable", "image-too-large")


@pytest.mark.parametrize("source", ["guide/guideline.md", "mcp_server.py", "cli.py"])
def test_view_14_agent_texts_name_viewer_error_and_its_reasons(source: str) -> None:
    text = flat((Path(agent_canvas.__file__).parent / source).read_text())
    assert "viewer_error" in text
    if source != "cli.py":
        assert all(reason in text for reason in REASONS)
