"""One status rule for every comment (COM-08) and the rest of the store."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.hub import comments
from agent_canvas.hub.comments import CommentError

pytestmark = pytest.mark.unit

PAGE = "page.html"


class Clock:
    """A fake clock: every call is one second later."""

    def __init__(self) -> None:
        self.second = 0

    def __call__(self) -> str:
        self.second += 1
        return f"2026-11-09T10:{self.second // 60:02d}:{self.second % 60:02d}.000Z"


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(comments, "now_iso", fake)
    return fake


def new(folder: Path) -> int:
    fields = {
        "kind": "point",
        "text": "q",
        "anchor": {"x": 1, "y": 2},
        "page_version": 1,
    }
    return comments.create(folder, PAGE, fields)["n"]


def sent(folder: Path) -> int:
    number = new(folder)
    comments.take_unsent(folder, PAGE, "now", "evt_1")
    return number


def record(folder: Path, number: int = 1) -> dict:
    return next(c for c in comments.load(folder, PAGE)["comments"] if c["n"] == number)


def status(folder: Path, number: int = 1) -> str:
    return comments.status(record(folder, number))


def test_com_08_unsent_comment_is_draft(tmp_path: Path) -> None:
    new(tmp_path)
    assert status(tmp_path) == "draft"
    assert comments.open(record(tmp_path)) is False


def test_com_08_sent_comment_is_sent_and_open(tmp_path: Path) -> None:
    sent(tmp_path)
    assert status(tmp_path) == "sent"
    assert comments.open(record(tmp_path)) is True


def test_com_08_seen_after_delivery_not_before(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.listing(tmp_path)
    assert status(tmp_path) == "sent"
    comments.listing(tmp_path, mark_seen=True)
    assert status(tmp_path) == "seen"
    assert comments.open(record(tmp_path)) is True


def test_com_08_agent_reply_makes_it_answered_and_not_open(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.listing(tmp_path, mark_seen=True)
    comments.reply(tmp_path, PAGE, 1, "fixed", "claude-code")
    assert status(tmp_path) == "answered"
    assert comments.open(record(tmp_path)) is False


def test_com_08_owner_reply_unsent_is_draft_then_sent_again_and_open(
    tmp_path: Path,
) -> None:
    sent(tmp_path)
    comments.reply(tmp_path, PAGE, 1, "fixed", "claude-code")
    comments.reply(tmp_path, PAGE, 1, "thanks, also Table 2")
    assert status(tmp_path) == "draft"
    assert comments.open(record(tmp_path)) is False
    comments.take_unsent(tmp_path, PAGE, "now", "evt_2")
    assert status(tmp_path) == "sent"
    assert comments.open(record(tmp_path)) is True


def test_com_08_seen_before_an_owner_reply_does_not_count(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.listing(tmp_path, mark_seen=True)
    comments.reply(tmp_path, PAGE, 1, "again")
    comments.take_unsent(tmp_path, PAGE, "now", "evt_2")
    assert status(tmp_path) == "sent"
    comments.listing(tmp_path, mark_seen=True)
    assert status(tmp_path) == "seen"


def test_com_08_agent_reply_before_the_owners_newest_reply_is_not_answered(
    tmp_path: Path,
) -> None:
    sent(tmp_path)
    comments.reply(tmp_path, PAGE, 1, "a", "claude-code")
    comments.reply(tmp_path, PAGE, 1, "b")
    comments.take_unsent(tmp_path, PAGE, "now", "evt_2")
    assert status(tmp_path) == "sent"
    comments.reply(tmp_path, PAGE, 1, "c", "claude-code")
    assert status(tmp_path) == "answered"


def test_com_08_done_wins_over_answered_and_seen(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.listing(tmp_path, mark_seen=True)
    comments.reply(tmp_path, PAGE, 1, "a", "claude-code")
    comments.set_done(tmp_path, PAGE, 1, "owner")
    assert status(tmp_path) == "done"
    assert comments.open(record(tmp_path)) is False


def test_com_08_draft_wins_over_done(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.set_done(tmp_path, PAGE, 1, "agent")
    comments.reply(tmp_path, PAGE, 1, "no, still wrong")
    assert record(tmp_path)["done"] is None  # an owner reply clears done (A-55)
    assert status(tmp_path) == "draft"


def test_com_08_the_order_puts_draft_before_done_on_a_hand_made_record() -> None:
    owner_reply = {"from": None, "text": "x", "at": "2026-11-09T10:00:05.000Z"}
    shown = {
        "sent": "2026-11-09T10:00:01.000Z",
        "seen": [],
        "read": None,
        "replies": [{**owner_reply, "sent": None}],
        "done": {"at": "2026-11-09T10:00:03.000Z", "by": "owner"},
        "last_done": "2026-11-09T10:00:03.000Z",
    }
    assert comments.status(shown) == "draft"
    shown["replies"][0]["sent"] = owner_reply["at"]
    assert comments.status(shown) == "done"


def test_com_08_agent_reply_to_a_done_comment_keeps_it_done(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.set_done(tmp_path, PAGE, 1, "owner")
    comments.reply(tmp_path, PAGE, 1, "ok", "claude-code")
    assert status(tmp_path) == "done"


def test_com_08_reopen_alone_is_not_open_for_the_agent(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.set_done(tmp_path, PAGE, 1, "owner")
    last = record(tmp_path)["last_done"]
    assert last == record(tmp_path)["done"]["at"]
    comments.reopen(tmp_path, PAGE, 1)
    shown = record(tmp_path)
    assert shown["done"] is None and shown["last_done"] == last
    assert status(tmp_path) == "sent"
    assert comments.open(shown) is False


def test_com_08_open_again_after_the_owners_next_sent_reply(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.set_done(tmp_path, PAGE, 1, "agent")
    comments.reopen(tmp_path, PAGE, 1)
    comments.reply(tmp_path, PAGE, 1, "not fixed")
    assert comments.open(record(tmp_path)) is False  # unsent reply: a draft
    comments.take_unsent(tmp_path, PAGE, "now", "evt_2")
    assert comments.open(record(tmp_path)) is True


def test_com_08_agent_done_closes_it_for_the_agent(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.set_done(tmp_path, PAGE, 1, "agent")
    assert record(tmp_path)["done"]["by"] == "agent"
    assert comments.open(record(tmp_path)) is False


def test_com_08_lost_flag_goes_with_the_status(tmp_path: Path) -> None:
    sent(tmp_path)
    comments.set_lost(tmp_path, PAGE, 1, True, 3)
    shown = record(tmp_path)
    assert shown["lost"] is True and shown["anchored_version"] == 3
    assert status(tmp_path) == "sent"
    message = comments.with_status(comments.load(tmp_path, PAGE))[0]
    assert message["lost"] is True and message["status"] == "sent"
    comments.set_lost(tmp_path, PAGE, 1, False, 4)
    assert record(tmp_path)["lost"] is False


def test_com_08_unread_after_an_agent_reply_until_the_owner_reads(
    tmp_path: Path,
) -> None:
    sent(tmp_path)
    assert comments.unread(record(tmp_path)) is False
    comments.mark_read(tmp_path, PAGE, 1)
    comments.reply(tmp_path, PAGE, 1, "fixed", "claude-code")
    assert comments.unread(record(tmp_path)) is True
    comments.mark_read(tmp_path, PAGE, 1)
    assert comments.unread(record(tmp_path)) is False


def test_com_08_unread_after_the_agent_marks_done_but_not_the_owner(
    tmp_path: Path,
) -> None:
    sent(tmp_path)
    comments.mark_read(tmp_path, PAGE, 1)
    comments.set_done(tmp_path, PAGE, 1, "owner")
    assert comments.unread(record(tmp_path)) is False
    comments.reopen(tmp_path, PAGE, 1)
    comments.set_done(tmp_path, PAGE, 1, "agent")
    assert comments.unread(record(tmp_path)) is True


def test_com_08_never_read_comment_with_an_agent_reply_is_unread(
    tmp_path: Path,
) -> None:
    sent(tmp_path)
    comments.reply(tmp_path, PAGE, 1, "fixed", "claude-code")
    assert record(tmp_path)["read"] is None
    assert comments.unread(record(tmp_path)) is True


def test_com_08_window_message_carries_status_and_unread(tmp_path: Path) -> None:
    sent(tmp_path)
    new(tmp_path)
    comments.reply(tmp_path, PAGE, 1, "fixed", "claude-code")
    first, second = comments.with_status(comments.load(tmp_path, PAGE))
    assert (first["status"], first["unread"]) == ("answered", True)
    assert (second["status"], second["unread"]) == ("draft", False)


def test_com_08_listing_uses_the_same_status_and_filters_open(tmp_path: Path) -> None:
    for _ in range(3):
        new(tmp_path)
    comments.take_unsent(tmp_path, PAGE, "now", "evt_1")
    comments.reply(tmp_path, PAGE, 2, "a", "claude-code")
    comments.set_done(tmp_path, PAGE, 3, "owner")
    assert [c["n"] for c in comments.listing(tmp_path)] == [1]
    everything = comments.listing(tmp_path, include_all=True)
    assert [(c["n"], c["status"], c["open"]) for c in everything] == [
        (1, "sent", True),
        (2, "answered", False),
        (3, "done", False),
    ]
    assert not {"seen", "read", "anchored_version"} & set(everything[0])


def test_rpl_01_listing_never_shows_an_owner_reply_that_is_not_sent(
    tmp_path: Path,
) -> None:
    sent(tmp_path)
    comments.reply(tmp_path, PAGE, 1, "fixed", "claude-code")
    comments.reply(tmp_path, PAGE, 1, "OWNER-DRAFT-REPLY")
    assert status(tmp_path) == "draft"
    listed = comments.listing(tmp_path, include_all=True)
    assert [(c["n"], c["status"]) for c in listed] == [(1, "answered")]
    assert [r["text"] for r in listed[0]["replies"]] == ["fixed"]
    assert "OWNER-DRAFT-REPLY" not in str(listed)
    comments.take_unsent(tmp_path, PAGE, "now", "evt_2")
    again = comments.listing(tmp_path)
    assert [r["text"] for r in again[0]["replies"]] == ["fixed", "OWNER-DRAFT-REPLY"]


def test_com_08_listing_marks_seen_only_the_listed_comments(tmp_path: Path) -> None:
    for _ in range(2):
        new(tmp_path)
    comments.take_unsent(tmp_path, PAGE, "now", "evt_1")
    comments.set_done(tmp_path, PAGE, 2, "owner")
    comments.listing(tmp_path, mark_seen=True)
    assert len(record(tmp_path, 1)["seen"]) == 1
    assert record(tmp_path, 2)["seen"] == []


def test_com_08_an_agent_reply_or_done_needs_a_sent_comment(tmp_path: Path) -> None:
    new(tmp_path)
    for call in (
        lambda: comments.reply(tmp_path, PAGE, 1, "x", "claude-code"),
        lambda: comments.set_done(tmp_path, PAGE, 1, "agent"),
    ):
        with pytest.raises(CommentError) as refused:
            call()
        assert refused.value.status == 409
    with pytest.raises(CommentError) as unknown:
        comments.reply(tmp_path, PAGE, 9, "x")
    assert unknown.value.status == 404


def test_com_08_edit_changes_a_draft_only(tmp_path: Path) -> None:
    new(tmp_path)
    comments.edit(tmp_path, PAGE, 1, "better")
    assert record(tmp_path)["text"] == "better"
    assert record(tmp_path)["edited"] is not None
    comments.take_unsent(tmp_path, PAGE, "now", "evt_1")
    with pytest.raises(CommentError) as refused:
        comments.edit(tmp_path, PAGE, 1, "late")
    assert refused.value.status == 409
    assert record(tmp_path)["text"] == "better"


def test_r_16_unsent_counts_drafts_and_unsent_owner_replies_over_all_pages(
    tmp_path: Path,
) -> None:
    for name in (PAGE, "other.html"):
        (tmp_path / name).write_text("<p>page</p>")
    assert comments.unsent(tmp_path) == {"comments": 0, "files": 0}
    sent(tmp_path)
    assert comments.unsent(tmp_path) == {"comments": 0, "files": 0}
    new(tmp_path)
    comments.reply(tmp_path, PAGE, 1, "an owner reply, not sent")
    fields = {"kind": "point", "text": "q", "anchor": {"x": 1, "y": 2}}
    comments.create(tmp_path, "other.html", fields | {"page_version": 1})
    assert comments.unsent(tmp_path) == {"comments": 3, "files": 2}
    (tmp_path / "other.html").unlink()  # drafts of a deleted page no longer count
    assert comments.unsent(tmp_path) == {"comments": 2, "files": 1}


def test_com_08_texts_longer_than_4000_are_refused(tmp_path: Path) -> None:
    sent(tmp_path)
    new(tmp_path)
    with pytest.raises(CommentError):
        comments.reply(tmp_path, PAGE, 1, "x" * 4001)
    with pytest.raises(CommentError):
        comments.edit(tmp_path, PAGE, 2, "x" * 4001)
