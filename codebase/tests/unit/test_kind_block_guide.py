"""Block reference entries of the card elements Report and Alert (KIND-06, KIND-01)."""

from __future__ import annotations

import pytest

from agent_canvas.guide_text import blocks_text
from helpers import PACKAGE_DIR, PLUGIN_DIR

pytestmark = pytest.mark.unit

GUIDE = PACKAGE_DIR / "guide" / "blocks.md"
ENTRIES = {
    "canvas-report": [
        "type",
        "plan",
        "result",
        "finding",
        "title",
        "text",
        "never HTML",
    ],
    "canvas-alert": ["title", "text", "needs action", "no action needed", "error box"],
}


def test_kind_06_the_reference_has_an_entry_with_an_example_for_report_and_alert() -> (
    None
):
    text = GUIDE.read_text()
    for tag, words in ENTRIES.items():
        assert f"<{tag} data-canvas-id=" in text, tag
        section = text.split(f"## `{tag}`", 1)[1].split("\n## ", 1)[0]
        for word in words:
            assert word in section, (tag, word)


def test_kind_06_the_generated_skill_text_carries_the_entries() -> None:
    skill = (PLUGIN_DIR / "skills" / "agent-canvas" / "SKILL.md").read_text()
    assert "## `canvas-report`" not in skill  # in `guide blocks` (AGI-12)
    text = blocks_text()
    assert "## `canvas-report`" in text and "## `canvas-alert`" in text


LONG_JOB_ENTRIES = {
    "canvas-decision": [
        "text",
        "why",
        "ref",
        "date",
        "Change…",
        "300",
        "change",
        "reason",
    ],
    "canvas-live": [
        "updated",
        "stale_after",
        "600",
        "stale since",
        "updated 2 min ago",
    ],
    "canvas-progress": [
        "started",
        "eta",
        "log",
        "5 lines",
        "stop",
        "Stop the run?",
        "page folder",
    ],
}


def test_kind_07_08_cnt_07_the_reference_teaches_the_three_entries() -> None:
    text = GUIDE.read_text()
    assert (
        "<canvas-decision data-canvas-id=" in text
        and "<canvas-live data-canvas-id=" in text
    )
    for tag, words in LONG_JOB_ENTRIES.items():
        section = text.split(f"## `{tag}`", 1)[1].split("\n## ", 1)[0]
        for word in words:
            assert word in section, (tag, word)
