"""Draw mode is gone (revision 12, D-31): DRAW-01 to 04, 07 and 08 withdrawn."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[2] / "src" / "agent_canvas" / "static"

pytestmark = pytest.mark.unit

# One pattern per leftover of draw mode; each is checked on every static file.
LEFTOVERS = {
    "perfect-freehand": r"perfect-freehand|getStroke",
    "drawing tool button or swatch": r"data-tool|data-colour\b|draw-tools|draw-button",
    "drawing overlay": r"id=\"overlay\"|getElementById\(\"overlay\"\)|#overlay\b",
    "draw-mode message": r"draw-mode|drawMode|setDrawing",
    "mark-target wiring": r"targetAtPoint|dataBboxFor",
    "D key handler": r"toLowerCase\(\)\s*===\s*\"d\"|\[\"d\",\s*\"u\"\]",
}


def static_files() -> list[Path]:
    """Every text file under ``static/`` except the vendored libraries' contents."""
    files = [
        p
        for p in STATIC.rglob("*")
        if p.is_file()
        and p.suffix in {".js", ".mjs", ".html", ".css", ".json", ".md"}
        and p.relative_to(STATIC).parts[0] != "vendor"
    ]
    assert files  # a vacuous scan must fail
    return files


@pytest.mark.parametrize("name", LEFTOVERS)
def test_draw_withdrawn_no_leftover_in_static(name: str) -> None:
    """No drawing tool, overlay, ``D`` handler or mark-target wiring remains."""
    pattern = re.compile(LEFTOVERS[name])
    hits = [
        str(p.relative_to(STATIC))
        for p in static_files()
        if pattern.search(p.read_text())
    ]
    assert hits == [], f"{name} still in {hits}"


def test_draw_withdrawn_perfect_freehand_is_not_vendored() -> None:
    """The library, its licence and its manifest entry are gone."""
    assert not (STATIC / "vendor" / "perfect-freehand").exists()
    assert not (STATIC / "vendor" / "licenses" / "perfect-freehand.LICENSE").exists()
    assert "perfect-freehand" not in (STATIC / "vendor" / "MANIFEST.json").read_text()


def test_draw_withdrawn_plot_keeps_its_axis_conversion() -> None:
    """R-10: the plot's pixel-to-data conversion stays for the later anchors."""
    assert "p2d" in (STATIC / "blocks" / "plot.js").read_text()
