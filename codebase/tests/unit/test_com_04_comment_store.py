"""Comment store: numbering, limits, atomic writes, drafts (COM-04, 09, 5.13)."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from agent_canvas.hub import comments
from agent_canvas.hub.comments import CommentError

pytestmark = pytest.mark.unit

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def fields(**changes) -> dict:  # noqa: ANN003
    base = {
        "page_version": 1,
        "kind": "rect",
        "text": "units?",
        "anchor": {"space": "page-px", "x": 1, "y": 2, "w": 30, "h": 40},
        "target": {"canvas_id": None, "selector": "#fig", "text": "Fig"},
        "text_inside": "Figure 1",
    }
    return {**base, **changes}


def save(folder: Path, **changes) -> dict:  # noqa: ANN003
    return comments.create(folder, "page.html", fields(**changes))


def numbers(folder: Path) -> list[int]:
    return [c["n"] for c in comments.load(folder, "page.html")["comments"]]


def test_com_04_numbers_one_to_three_delete_two_save_gives_four(tmp_path: Path) -> None:
    for expected in (1, 2, 3):
        assert save(tmp_path)["n"] == expected
    comments.delete(tmp_path, "page.html", 2)
    assert numbers(tmp_path) == [1, 3]
    assert save(tmp_path)["n"] == 4
    assert numbers(tmp_path) == [1, 3, 4]


def test_com_04_next_never_decreases_even_after_deleting_the_last(
    tmp_path: Path,
) -> None:
    save(tmp_path)
    save(tmp_path)
    comments.delete(tmp_path, "page.html", 2)
    assert comments.load(tmp_path, "page.html")["next"] == 3
    assert save(tmp_path)["n"] == 3


def test_com_04_file_follows_the_5_13_format(tmp_path: Path) -> None:
    record = save(tmp_path)
    path = tmp_path / ".comments" / "page.html.json"
    data = json.loads(path.read_text())
    assert data["schema"] == "agent-canvas/comments@1"
    assert data["page"] == "page.html" and data["next"] == 2
    stored = data["comments"][0]
    assert stored == record
    assert stored["id"].startswith("cmt_") and stored["n"] == 1
    assert stored["sent"] is None and stored["delivery"] is None
    assert stored["seen"] == [] and stored["replies"] == []
    assert stored["done"] is None and stored["lost"] is False
    assert stored["picture"] is None and stored["created"].endswith("Z")
    assert stored["text_inside"] == "Figure 1"


def test_com_04_a_new_comment_is_a_draft(tmp_path: Path) -> None:
    assert comments.status(save(tmp_path)) == "draft"


def test_com_04_a_picture_is_written_beside_the_file(tmp_path: Path) -> None:
    encoded = base64.b64encode(PNG).decode()
    record = save(tmp_path, picture=encoded)
    assert record["picture"] == ".comments/page.html.1.png"
    assert (tmp_path / record["picture"]).read_bytes() == PNG


@pytest.mark.parametrize(
    "picture",
    ["not base64 !!", base64.b64encode(b"GIF89a....").decode(), 5],
)
def test_com_04_a_bad_picture_is_refused_and_nothing_is_stored(
    tmp_path: Path, picture: object
) -> None:
    with pytest.raises(CommentError):
        save(tmp_path, picture=picture)
    assert numbers(tmp_path) == []
    assert not list((tmp_path / ".comments").glob("*.png"))


def test_com_04_a_picture_over_10_mb_is_refused(tmp_path: Path) -> None:
    big = PNG + b"\0" * (10 * 1024 * 1024)
    with pytest.raises(CommentError):
        save(tmp_path, picture=base64.b64encode(big).decode())


def test_com_04_the_201st_comment_is_refused(tmp_path: Path) -> None:
    for _ in range(200):
        save(tmp_path)
    with pytest.raises(CommentError) as refused:
        save(tmp_path)
    assert refused.value.status == 400
    assert len(numbers(tmp_path)) == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "x" * 4001},
        {"text": 5},
        {"kind": "arrow"},
        {"anchor": "nowhere"},
        {"anchor": {"quote": "q" * 1001}},
        {"text_inside": "t" * 501},
        {"kind": "lasso", "anchor": {"points": [[0, 0]] * 201}},
        {"target": "x"},
        {"page_version": "two"},
    ],
)
def test_com_04_limits_and_shapes_are_answered_400(
    tmp_path: Path, changes: dict
) -> None:
    with pytest.raises(CommentError) as refused:
        save(tmp_path, **changes)
    assert refused.value.status == 400
    assert numbers(tmp_path) == []


def test_com_04_the_limits_themselves_are_accepted(tmp_path: Path) -> None:
    save(
        tmp_path,
        text="x" * 4000,
        text_inside="t" * 500,
        anchor={"quote": "q" * 1000, "points": [[0, 0]] * 200},
    )
    assert numbers(tmp_path) == [1]


def test_com_04_an_interrupted_write_leaves_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save(tmp_path)
    path = tmp_path / ".comments" / "page.html.json"
    before = path.read_bytes()

    def broken(*args: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        save(tmp_path)
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["page.html.json"]
    assert save(tmp_path)["n"] == 2


def test_com_09_delete_removes_the_draft_and_its_picture(tmp_path: Path) -> None:
    record = save(tmp_path, picture=base64.b64encode(PNG).decode())
    picture = tmp_path / record["picture"]
    comments.delete(tmp_path, "page.html", 1)
    assert numbers(tmp_path) == [] and not picture.exists()


def test_com_09_an_unknown_number_is_404_and_a_sent_comment_409(
    tmp_path: Path,
) -> None:
    save(tmp_path)
    with pytest.raises(CommentError) as unknown:
        comments.delete(tmp_path, "page.html", 7)
    assert unknown.value.status == 404
    comments.take_unsent(tmp_path, "page.html", "now", "evt_1")
    with pytest.raises(CommentError) as sent:
        comments.delete(tmp_path, "page.html", 1)
    assert sent.value.status == 409
    assert numbers(tmp_path) == [1]


def test_com_08_take_unsent_marks_the_drafts_sent_once(tmp_path: Path) -> None:
    save(tmp_path)
    save(tmp_path)
    taken = comments.take_unsent(tmp_path, "page.html", "next-message", "evt_9")
    assert [c["n"] for c in taken] == [1, 2]
    assert all(comments.status(c) == "sent" for c in taken)
    assert taken[0]["delivery"] == "next-message" and taken[0]["send_event"] == "evt_9"
    assert taken[0]["sent"] == taken[1]["sent"] and taken[0]["sent"].endswith("Z")
    assert comments.load(tmp_path, "page.html")["comments"] == taken
    assert comments.take_unsent(tmp_path, "page.html", "now", "evt_10") == []
    third = save(tmp_path)
    again = comments.take_unsent(tmp_path, "page.html", "now", "e")
    assert [c["n"] for c in again] == [third["n"]]


def test_rpl_01_listing_has_sent_comments_only_with_the_agent_fields(
    tmp_path: Path,
) -> None:
    save(tmp_path)
    assert comments.listing(tmp_path) == []
    comments.take_unsent(tmp_path, "page.html", "now", "evt_1")
    save(tmp_path)  # a second one stays a draft
    listed = comments.listing(tmp_path)
    assert [c["n"] for c in listed] == [1]
    first = listed[0]
    assert first["page"] == "page.html"
    assert first["path"] == str(tmp_path / "page.html")
    assert first["open"] is True and first["status"] == "sent"
    assert not {"seen", "read", "anchored_version"} & set(first)


def test_rpl_01_listing_marks_seen_only_when_asked(tmp_path: Path) -> None:
    save(tmp_path)
    comments.take_unsent(tmp_path, "page.html", "now", "evt_1")
    comments.listing(tmp_path)
    assert comments.load(tmp_path, "page.html")["comments"][0]["seen"] == []
    comments.listing(tmp_path, mark_seen=True)
    assert len(comments.load(tmp_path, "page.html")["comments"][0]["seen"]) == 1


def test_rpl_01_listing_of_one_page_and_of_all_pages(tmp_path: Path) -> None:
    comments.create(tmp_path, "a.html", fields())
    comments.create(tmp_path, "b.pdf", fields())
    for page in ("a.html", "b.pdf"):
        comments.take_unsent(tmp_path, page, "now", "e")
    assert [c["page"] for c in comments.listing(tmp_path)] == ["a.html", "b.pdf"]
    assert [c["page"] for c in comments.listing(tmp_path, "b.pdf")] == ["b.pdf"]


def test_com_04_a_page_name_cannot_leave_the_folder(tmp_path: Path) -> None:
    with pytest.raises(CommentError):
        comments.create(tmp_path, "../x.html", fields())


def test_com_12_a_comment_without_picture_keeps_the_reason(tmp_path: Path) -> None:
    """Slice of COM-12 (P21.3): ``picture`` null with ``picture_error``."""
    record = save(tmp_path, picture_error="picture failed: snapdom exploded")
    assert record["picture"] is None
    assert record["picture_error"] == "picture failed: snapdom exploded"
    assert comments.load(tmp_path, "page.html")["comments"][0] == record


def test_com_12_a_picture_wins_over_a_picture_error(tmp_path: Path) -> None:
    record = save(
        tmp_path,
        picture=base64.b64encode(PNG).decode(),
        picture_error="stale",
    )
    assert record["picture"] and record["picture_error"] is None


def test_com_12_the_picture_error_is_limited(tmp_path: Path) -> None:
    with pytest.raises(CommentError):
        save(tmp_path, picture_error="x" * 301)
    assert numbers(tmp_path) == []
