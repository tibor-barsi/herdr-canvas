"""SessionStart gives the core in every session, also after compaction (AGI-10)."""

from __future__ import annotations

import json

import pytest
from test_hooks import SESSION, start_hook

from agent_canvas.guide_text import core_text

pytestmark = pytest.mark.integration

ID_LINE = (
    f"Your agent-canvas session id is {SESSION}; pass it as `session` to "
    "agent-canvas MCP tools. AGENT_CANVAS_SESSION is set for Bash."
)


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact"])
def test_agi_10_session_start_gives_the_id_line_and_the_core(
    lone, tmp_path, source: str
) -> None:  # noqa: ANN001
    result, _ = start_hook(lone.run, tmp_path, source)
    assert result.code == 0 and result.err == ""
    context = json.loads(result.out)["hookSpecificOutput"]["additionalContext"]
    assert context == ID_LINE + "\n\n" + core_text()
    assert len(context) < 10_000  # Claude Code's cap for additionalContext
