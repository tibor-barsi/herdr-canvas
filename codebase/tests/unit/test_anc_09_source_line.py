"""A comment on a Markdown page carries the source line of its quote (ANC-09)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_canvas.hub import comments

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parents[1] / "fixtures" / "comments" / "anc-09.md"


def save(folder: Path, page: str = "anc-09.md", **changes) -> dict:  # noqa: ANN003
    fields = {
        "kind": "text",
        "text": "why?",
        "page_version": 1,
        "anchor": {"space": "page-px", "quote": "This sentence has emphasis and code"},
        **changes,
    }
    return comments.create(folder, page, fields)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    shutil.copy(FIXTURE, tmp_path / "anc-09.md")
    return tmp_path


def test_anc_09_quote_of_a_sentence_with_emphasis_on_line_12_gives_12(
    folder: Path,
) -> None:
    assert save(folder)["source_line"] == 12


def test_anc_09_quote_starting_mid_sentence_and_wrapping_gives_its_first_line(
    folder: Path,
) -> None:
    anchor = {"space": "page-px", "quote": "code in it, wrapped onto"}
    assert save(folder, anchor=anchor)["source_line"] == 12


def test_anc_09_rectangle_uses_the_first_40_characters_of_text_inside(
    folder: Path,
) -> None:
    inside = "Filler line 5. Filler line 7. Filler line 8. Filler line 10."
    record = save(folder, kind="rect", anchor={"space": "page-px"}, text_inside=inside)
    assert record["source_line"] == 5


def test_anc_09_a_quote_not_in_the_source_gives_null(folder: Path) -> None:
    anchor = {"space": "page-px", "quote": "nowhere in the file"}
    assert save(folder, anchor=anchor)["source_line"] is None


def test_anc_09_rectangle_without_text_inside_gives_null(folder: Path) -> None:
    record = save(folder, kind="point", anchor={"space": "page-px", "x": 1, "y": 2})
    assert record["source_line"] is None


def test_anc_09_html_page_gives_null(folder: Path) -> None:
    (folder / "page.html").write_text("<p>This sentence has emphasis and code</p>")
    assert save(folder, "page.html")["source_line"] is None


def test_anc_09_the_comment_version_is_searched_when_it_is_saved(
    folder: Path,
) -> None:
    saved = folder / "history" / "pages"
    saved.mkdir(parents=True)
    (saved / "anc-09.0001.md").write_text("one\ntwo\n\nThis sentence has emphasis\n")
    (folder / "anc-09.md").write_text("changed\n")
    anchor = {"space": "page-px", "quote": "This sentence has emphasis"}
    assert save(folder, anchor=anchor)["source_line"] == 4
    assert comments.load(folder, "anc-09.md")["comments"][0]["source_line"] == 4
