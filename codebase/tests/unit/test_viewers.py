"""Viewer types, page-type rule and extension-keeping history (VIEW-01, VIEW-11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.hub.viewers import viewer_document, viewer_type
from agent_canvas.hub.watcher import PageHistory
from agent_canvas.paths_safe import UnsafePathError, validate_page_type

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "name",
    ["a.html", "a.HTML", "n.md", "n.markdown", "r.pdf", "p.png", "p.JPG", "p.jpeg",
     "p.gif", "p.webp", "p.svg"],
)  # fmt: skip
def test_view_01_allowed_page_types(name: str) -> None:
    assert validate_page_type(name) == name


@pytest.mark.parametrize("name", ["d.csv", "noext", "x.txt", ".h.md", "x.pdf.exe"])
def test_view_01_other_types_are_refused_naming_the_allowed(name: str) -> None:
    with pytest.raises(UnsafePathError) as error:
        validate_page_type(name)
    assert ".markdown" in str(error.value) and ".html" in str(error.value)


@pytest.mark.parametrize(
    ("name", "kind"),
    [("n.md", "markdown"), ("n.MARKDOWN", "markdown"), ("r.pdf", "pdf"),
     ("p.webp", "image"), ("p.svg", "image"), ("a.html", None), ("d.csv", None)],
)  # fmt: skip
def test_view_01_type_table(name: str, kind: str | None) -> None:
    assert viewer_type(name) == kind


def test_view_02_document_has_one_script_of_its_type_and_escapes_the_name() -> None:
    text = viewer_document('a"<b>.md').decode()
    assert text.count("/static/viewer/markdown.js") == 1
    assert "<b>" not in text and text.count('src="/static/helper.js"') == 1
    with pytest.raises(ValueError):
        viewer_document("a.html")


def test_view_11_history_keeps_the_extension_and_separates_equal_stems(
    tmp_path: Path,
) -> None:
    history = PageHistory(tmp_path)
    assert history.save("r.pdf", b"1") == 1
    assert history.save("r.pdf", b"1") is None
    assert history.save("r.pdf", b"2") == 2
    assert history.save("r.html", b"h") == 1  # a clash is refused by show, not here
    names = sorted(p.name for p in (tmp_path / "history" / "pages").iterdir())
    assert names == ["r.0001.html", "r.0001.pdf", "r.0002.pdf"]
    assert history.read("r.pdf", 1) == b"1"
    assert [n for n, _ in history.versions("r.pdf")] == [1, 2]
