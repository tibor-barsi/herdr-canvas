"""Page templates and the design kit stylesheet (KIT-01 to KIT-03)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.paths_safe import UnsafePathError
from agent_canvas.templates import (
    TEMPLATES,
    TemplateError,
    page_name_for,
    write_template,
)

pytestmark = pytest.mark.unit

KIT_CSS = Path(__file__).resolve().parents[2] / "src/agent_canvas/static/kit/kit.css"


def test_kit_01_stylesheet_is_small_offline_and_follows_the_color_scheme() -> None:
    css = KIT_CSS.read_text()
    assert len(css.splitlines()) < 250
    assert "prefers-color-scheme: dark" in css
    assert "max-width: 700px" in css
    assert "http://" not in css and "https://" not in css and "@import" not in css
    assert "@font-face" not in css
    for name in ("page", "columns", "card", "tile", "callout", "muted", "lead"):
        assert f".{name}" in css, name


def test_kit_02_the_templates_have_descriptions() -> None:
    assert list(TEMPLATES)[:4] == ["compare", "results", "run", "geometry"]
    assert "cards" in TEMPLATES
    assert all(template.description for template in TEMPLATES.values())


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_kit_02_every_template_links_the_kit_and_loads_no_remote_resource(
    name: str, tmp_path: Path
) -> None:
    path = write_template(tmp_path, "mine.html", name)
    html = path.read_text()
    assert path == tmp_path / "mine.html"
    assert '<link rel="stylesheet" href="/static/kit/kit.css">' in html
    assert "http://" not in html and "https://" not in html
    assert "(replace)" in html


def test_kit_02_templates_use_the_blocks_that_fit() -> None:
    texts = {name: t.read_text() for name, t in TEMPLATES.items()}
    assert "canvas-ask" in texts["compare"]
    assert "canvas-plot" in texts["results"] and "canvas-table" in texts["results"]
    assert "canvas-progress" in texts["run"]
    assert '"stop"' in texts["run"] and "canvas-buttons" in texts["run"]
    assert "canvas-scene" in texts["geometry"]


def test_kit_03_refuses_to_overwrite_unless_forced(tmp_path: Path) -> None:
    target = write_template(tmp_path, "mine.html", "compare")
    target.write_text("owner's edit")
    with pytest.raises(TemplateError, match="already exists"):
        write_template(tmp_path, "mine.html", "results")
    assert target.read_text() == "owner's edit"
    write_template(tmp_path, "mine.html", "results", force=True)
    assert "canvas-plot" in target.read_text()


def test_kit_03_unknown_template_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TemplateError, match="Unknown template"):
        write_template(tmp_path, "mine.html", "poster")
    assert list(tmp_path.iterdir()) == []


def test_kit_03_geometry_adds_a_sample_model_without_replacing_yours(
    tmp_path: Path,
) -> None:
    write_template(tmp_path, "g.html", "geometry")
    assert (tmp_path / "part.stl").read_text().startswith("solid")
    (tmp_path / "part.stl").write_text("solid mine")
    write_template(tmp_path, "g.html", "geometry", force=True)
    assert (tmp_path / "part.stl").read_text() == "solid mine"


@pytest.mark.parametrize(
    ("given", "expected"),
    [("mine", "mine.html"), ("mine.html", "mine.html"), ("a-b_c.2", "a-b_c.2.html")],
)
def test_kit_03_page_names_get_the_html_suffix(given: str, expected: str) -> None:
    assert page_name_for(given) == expected


@pytest.mark.parametrize("bad", ["", "../x", "a/b", ".hidden", "a\\b"])
def test_kit_03_bad_page_names_are_refused(bad: str) -> None:
    with pytest.raises((UnsafePathError, TemplateError)):
        page_name_for(bad)
