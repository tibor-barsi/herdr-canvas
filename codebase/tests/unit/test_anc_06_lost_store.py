"""The store of lost anchors (ANC-06): changes only, with the page version."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.hub import comments

pytestmark = pytest.mark.unit

PAGE = "page.html"


def two_comments(folder: Path) -> None:
    for _ in range(2):
        fields = {"kind": "point", "text": "q", "anchor": {"x": 1}, "page_version": 1}
        comments.create(folder, PAGE, fields)


def records(folder: Path) -> list[dict]:
    return comments.load(folder, PAGE)["comments"]


def test_anc_06_a_change_of_lost_is_stored_with_the_version(tmp_path: Path) -> None:
    two_comments(tmp_path)
    assert comments.set_lost_many(tmp_path, PAGE, [(2, True)], 5) is True
    first, second = records(tmp_path)
    assert (first["lost"], first["anchored_version"]) == (False, 1)
    assert (second["lost"], second["anchored_version"]) == (True, 5)


def test_anc_06_a_report_that_repeats_the_store_or_names_no_comment_changes_nothing(
    tmp_path: Path,
) -> None:
    two_comments(tmp_path)
    file = tmp_path / ".comments" / f"{PAGE}.json"
    before = file.read_bytes()
    assert comments.set_lost_many(tmp_path, PAGE, [(1, False), (9, True)], 3) is False
    assert file.read_bytes() == before


def test_anc_06_found_again_clears_lost_and_a_list_changes_all_at_once(
    tmp_path: Path,
) -> None:
    two_comments(tmp_path)
    assert comments.set_lost_many(tmp_path, PAGE, [(1, True), (2, True)], 2)
    assert [r["lost"] for r in records(tmp_path)] == [True, True]
    assert comments.set_lost_many(tmp_path, PAGE, [(1, False)], 3)
    assert [r["lost"] for r in records(tmp_path)] == [False, True]
