"""Draft naming, atomic publishing and template drafts (DRAFT-01, 03, 04)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from agent_canvas.drafts import (
    DraftError,
    draft_name_for,
    is_draft_name,
    publish_draft,
    published_name_for,
)
from agent_canvas.hub.watcher import is_asset_path, is_page_name
from agent_canvas.templates import TemplateExistsError, write_template

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("given", "draft"),
    [
        ("report.html", "report.draft.html"),
        ("report", "report.draft.html"),
        ("report.draft.html", "report.draft.html"),
        ("a.b.html", "a.b.draft.html"),
    ],
)
def test_draft_01_the_draft_of_a_page_sits_next_to_it(given: str, draft: str) -> None:
    assert draft_name_for(given) == draft
    assert is_draft_name(draft)


@pytest.mark.parametrize(
    ("given", "published"),
    [("report.draft.html", "report.html"), ("report.html", "report.html")],
)
def test_draft_01_the_published_name_drops_the_draft_suffix(
    given: str, published: str
) -> None:
    assert published_name_for(given) == published


@pytest.mark.parametrize(
    "name", ["report.html", "draft.html", ".draft.html", "a.draft.txt", "x.DRAFT"]
)
def test_draft_01_other_names_are_not_drafts(name: str) -> None:
    assert not is_draft_name(name)


def test_draft_01_a_draft_is_not_a_page_and_not_an_asset(tmp_path: Path) -> None:
    assert is_page_name("report.html") and not is_page_name("report.draft.html")
    assert not is_page_name("REPORT.DRAFT.HTML")
    assert not is_asset_path(tmp_path, tmp_path / "report.draft.html")
    assert not is_asset_path(tmp_path, tmp_path / "REPORT.Draft.Html")
    assert is_asset_path(tmp_path, tmp_path / "data.csv")


def test_draft_03_publish_copies_the_draft_and_keeps_it(tmp_path: Path) -> None:
    (tmp_path / "p.draft.html").write_text("<p>new</p>")
    (tmp_path / "p.html").write_text("<p>old</p>")
    path = publish_draft(tmp_path, "p.html")
    assert path == tmp_path / "p.html"
    assert path.read_text() == "<p>new</p>"
    assert (tmp_path / "p.draft.html").read_text() == "<p>new</p>"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.draft.html", "p.html"]


def test_draft_03_publish_of_a_missing_draft_names_it(tmp_path: Path) -> None:
    (tmp_path / "p.html").write_text("<p>old</p>")
    with pytest.raises(DraftError, match=r"p\.draft\.html"):
        publish_draft(tmp_path, "p.html")
    assert (tmp_path / "p.html").read_text() == "<p>old</p>"


def test_draft_03_publish_goes_through_a_temporary_dotfile_and_a_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "p.draft.html").write_text("<p>new</p>")
    seen: list[tuple[str, str]] = []
    real = os.replace

    def spy(source, target):  # noqa: ANN001, ANN202
        seen.append((Path(source).name, Path(target).name))
        assert Path(source).parent == Path(target).parent == tmp_path
        assert Path(source).read_text() == "<p>new</p>"  # complete before the rename
        return real(source, target)

    monkeypatch.setattr(os, "replace", spy)
    publish_draft(tmp_path, "p.html")
    [(source, target)] = seen
    assert target == "p.html" and source.startswith(".") and source != "p.html"


def test_draft_03_a_reader_never_sees_a_half_written_page(tmp_path: Path) -> None:
    old, new = "<p>old</p>" * 20_000, "<p>new</p>" * 20_000
    (tmp_path / "p.html").write_text(old)
    stop = threading.Event()
    seen: set[str] = set()

    def read() -> None:
        while not stop.is_set():
            seen.add((tmp_path / "p.html").read_text())

    reader = threading.Thread(target=read)
    reader.start()
    try:
        for i in range(60):
            (tmp_path / "p.draft.html").write_text(new if i % 2 == 0 else old)
            publish_draft(tmp_path, "p.html")
    finally:
        stop.set()
        reader.join()
    assert seen <= {old, new}


def test_draft_03_the_temporary_file_is_removed_when_the_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "p.draft.html").write_text("<p>new</p>")

    def refuse(source, target):  # noqa: ANN001, ANN202
        raise OSError("disk says no")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(DraftError, match="disk says no"):
        publish_draft(tmp_path, "p.html")
    assert [p.name for p in tmp_path.iterdir()] == ["p.draft.html"]


def test_draft_04_a_template_can_be_written_as_a_draft(tmp_path: Path) -> None:
    path = write_template(tmp_path, "p.draft.html", "compare")
    assert path == tmp_path / "p.draft.html" and "(replace)" in path.read_text()
    with pytest.raises(TemplateExistsError):
        write_template(tmp_path, "p.draft.html", "compare")
