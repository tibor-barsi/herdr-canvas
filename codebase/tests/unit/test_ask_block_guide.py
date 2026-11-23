"""Block reference entry of the Ask element (ASK-01, ASK-02)."""

from __future__ import annotations

import pytest

from agent_canvas.guide_text import blocks_text
from helpers import PACKAGE_DIR, PLUGIN_DIR

pytestmark = pytest.mark.unit

WORDS = [
    "yesno", "several", "confirm", "approve", "recommended", "default",
    "answer", "replaces", "decision", "error box",
]  # fmt: skip


def test_ask_01_the_reference_has_an_entry_with_an_example_for_ask() -> None:
    text = (PACKAGE_DIR / "guide" / "blocks.md").read_text()
    assert '<canvas-ask data-canvas-id="' in text
    section = text.split("## `canvas-ask`", 1)[1].split("\n## ", 1)[0]
    for word in WORDS:
        assert word in section, word


def test_ask_01_the_generated_skill_text_carries_the_entry() -> None:
    skill = (PLUGIN_DIR / "skills" / "agent-canvas" / "SKILL.md").read_text()
    assert "## `canvas-ask`" not in skill  # in `guide blocks` (AGI-12)
    assert "## `canvas-ask`" in blocks_text()
