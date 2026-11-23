"""The compact block reference an agent reads (BLK-01, PLG-03 item 2)."""

from __future__ import annotations

import pytest

from helpers import PACKAGE_DIR

pytestmark = pytest.mark.unit

GUIDE = PACKAGE_DIR / "guide" / "blocks.md"

# tag -> config keys and the events or actions it produces (requirements 6.5)
BLOCKS = {
    "canvas-choices": ["mode", "options", "submit", "select", "choice"],
    "canvas-buttons": ["buttons", "style", "danger", "button"],
    "canvas-textbox": ["label", "placeholder", "multiline", "submit", "text", "input"],
    "canvas-table": ["columns", "rows", "key", "select"],
    "canvas-progress": ["value", "max", "label", "status", "detail"],
    "canvas-markdown": ["text", "src", "text/markdown", "$$"],
    "canvas-plot": [
        "data",
        "layout",
        "src",
        "plot-click",
        "plot-select",
        "data coordinates",
    ],
    "canvas-image": ["src", "alt", "image-click", "zoom"],
    "canvas-model": ["src", ".stl", ".step", "units", "colour", "model-mark"],
    "canvas-scene": ["parts", "manifest", "split", "group", "opacity", "scene-mark"],
    "canvas-animation": [
        "src",
        "frames",
        "fps",
        "autoplay",
        "loop",
        "speed",
        "WebM",
        "sound",
    ],
    "canvas-document": ["src", "height", ".pdf", "Open", "scroll", "clean"],
    "canvas-file": ["path", "size", "machine", "note", "Copy", "Open", "badge"],
    "canvas-source": [
        "claim",
        "source",
        "status",
        "disputed",
        "quote",
        "Doubt",
        "text",
    ],
    "canvas-metrics": [
        "tiles",
        "value",
        "unit",
        "min",
        "max",
        "previous",
        "near",
        "state",
    ],
    "canvas-compare": [
        "before",
        "after",
        "mode",
        "slider",
        "before_label",
        "canvas-ask",
    ],
}


def test_blk_01_guide_covers_every_block() -> None:
    text = GUIDE.read_text()
    for tag, words in BLOCKS.items():
        assert f"<{tag}" in text, tag
        section = text.split(f"## `{tag}`", 1)[1].split("\n## ", 1)[0]
        for word in words:
            assert word in section, (tag, word)


def test_blk_01_guide_states_the_declaration_style_once() -> None:
    text = GUIDE.read_text()
    assert "data-canvas-id" in text and "application/json" in text
    assert len(text) < 18000  # compact: `agent-canvas guide blocks` (AGI-12)


def test_ask_05_06_guide_names_the_point_and_fields_forms() -> None:
    text = GUIDE.read_text()
    section = text.split("## `canvas-ask`", 1)[1].split("\n## ", 1)[0]
    for word in ("`point`", "`fields`", "changed", "`submit?`", "canvas-scene"):
        assert word in section, word
