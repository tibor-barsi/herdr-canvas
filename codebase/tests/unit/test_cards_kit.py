"""Design cards in the kit, the ``cards`` template and the block guide (PLT, IMG, CARD)."""  # noqa: E501

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_canvas.templates import TEMPLATES, write_template

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "src/agent_canvas"
KIT_CSS = (PACKAGE / "static/kit/kit.css").read_text()
BLOCKS_MD = (PACKAGE / "guide/blocks.md").read_text()
GUIDELINE = (PACKAGE / "guide/guideline.md").read_text()
BADGES = (
    "recommended",
    "fallback",
    "fails",
    "placeholder",
    "ok",
    "warn",
    "bad",
    "info",
)


def test_card_01_stylesheet_has_the_card_classes_and_stays_small() -> None:
    assert len(KIT_CSS.splitlines()) < 250
    for name in ("cards", "panels", "badge", "compare"):
        assert f".{name}" in KIT_CSS, name
    assert "header" in KIT_CSS
    assert "min-width: 900px" in KIT_CSS
    assert "http://" not in KIT_CSS and "https://" not in KIT_CSS


@pytest.mark.parametrize("variant", BADGES)
def test_card_02_every_badge_variant_is_styled(variant: str) -> None:
    assert re.search(rf"\.badge\.{variant}\b", KIT_CSS), variant


def test_card_03_compare_mode_uses_subgrid() -> None:
    assert ".cards.compare" in KIT_CSS and "subgrid" in KIT_CSS


def test_card_04_template_is_listed_and_uses_the_blocks(tmp_path: Path) -> None:
    assert "cards" in TEMPLATES and TEMPLATES["cards"].description
    page = write_template(tmp_path, "c.html", "cards")
    html = page.read_text()
    assert '<link rel="stylesheet" href="/static/kit/kit.css">' in html
    for tag in ("canvas-image", "canvas-model", "canvas-plot", "canvas-table"):
        assert tag in html, tag
    assert html.count('<article class="card"') == 3
    assert "cards compare" in html  # the toggle is documented in a comment
    assert "(replace)" in html
    assert "http://" not in html and "https://" not in html


def test_card_04_assets_are_written_when_missing_and_never_replaced(
    tmp_path: Path,
) -> None:
    write_template(tmp_path, "c.html", "cards")
    html = (tmp_path / "c.html").read_text()
    sources = set(re.findall(r'"src":\s*"([^"]+)"', html))
    assert any(s.endswith(".png") for s in sources) and "part.stl" in sources
    for source in sources:
        assert (tmp_path / source).is_file(), source
    (tmp_path / "part.stl").write_text("solid mine")
    write_template(tmp_path, "c.html", "cards", force=True)
    assert (tmp_path / "part.stl").read_text() == "solid mine"


def test_card_04_the_sample_picture_is_small() -> None:
    sizes = [p.stat().st_size for p in (PACKAGE / "templates").glob("*.png")]
    assert sizes and max(sizes) < 60_000


def test_plt_and_img_guide_mentions_theme_axes_and_enlarge() -> None:
    plot = BLOCKS_MD.split("## `canvas-plot`", 1)[1].split("\n## ", 1)[0]
    for word in ('"theme": "figure"', '"axes": false', "log", "autoscale"):
        assert word in plot, word
    image = BLOCKS_MD.split("## `canvas-image`", 1)[1].split("\n## ", 1)[0]
    assert "enlarge" in image.lower() and "Esc" in image


def test_card_guideline_lists_the_cards_template_and_classes() -> None:
    assert "cards" in GUIDELINE.split("## Design kit and page templates", 1)[1]
    for name in ("cards", "panels", "badge"):
        assert f".{name}" in GUIDELINE, name
