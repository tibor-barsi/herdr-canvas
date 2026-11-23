"""Collapse the comment panel and fold single entries (COM-20, COM-21; D-61)."""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE
from .test_comment_layer import comment_mode
from .test_comment_panel import (
    entries,
    marker_report,
    prepare_links,
    record,
    show_comments,
)

pytestmark = pytest.mark.browser

LONG = "first words of a long comment " + "and then more text " * 8
RECORDS = [
    record(1, "sent", text=LONG),
    record(
        2,
        "answered",
        text="second",
        replies=[
            {
                "from": "claude-code",
                "text": "ok",
                "at": "2026-11-09T14:06:00",
                "sent": None,
            }
        ],
    ),
]


def frame_width(studio) -> float:  # noqa: ANN001
    return studio.page.locator("#frame").bounding_box()["width"]


def collapse(studio) -> None:  # noqa: ANN001
    studio.page.locator("#comment-panel .collapse").click()
    studio.page.wait_for_selector("#comment-panel.strip")


def reopen(studio, sid: str) -> None:  # noqa: ANN001
    """Reload the window, visit the session and hand it the comments again."""
    studio.page.reload()
    studio.owner.visit(sid)
    show_comments(studio, sid, RECORDS)


def test_com_20_collapse_gives_the_frame_the_width_and_expand_brings_the_panel_back(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, RECORDS)
    full = frame_width(studio)
    collapse(studio)
    assert frame_width(studio) > full + 200
    assert studio.page.locator("#comment-panel .stripbutton .cn").inner_text() == "2"
    studio.page.locator("#comment-panel .stripbutton").click()
    studio.page.wait_for_selector("#comment-panel:not(.strip) .ent")
    assert frame_width(studio) == full


def test_com_20_the_choice_survives_a_tab_switch_and_a_reload(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, RECORDS)
    collapse(studio)
    other = studio.make(SCROLL_PAGE, name="beta")
    show_comments(studio, other, RECORDS)
    assert studio.page.locator("#comment-panel.strip").count() == 1
    reopen(studio, sid)
    assert studio.page.locator("#comment-panel.strip").count() == 1
    studio.page.locator("#comment-panel .stripbutton").click()
    studio.page.wait_for_selector("#comment-panel:not(.strip) .ent")
    reopen(studio, sid)
    assert studio.page.locator("#comment-panel:not(.strip) .ent").count() == 2


def test_com_21_fold_shows_one_line_and_a_click_unfolds(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, RECORDS)
    assert entries(studio).locator(".tx").count() == 2
    entries(studio).nth(1).locator(".fold").click()
    second = entries(studio).nth(1)
    assert second.get_attribute("class").split().count("folded") == 1
    assert second.locator(".tx").count() == 0
    assert second.locator(".rp").count() == 0
    assert second.locator(".cn").inner_text() == "2"
    assert second.locator(".tx1").inner_text() == "second"
    assert second.locator(".rc").inner_text() == "↩1"
    assert second.bounding_box()["height"] < 40
    # the other comment is not touched, and a new one arrives unfolded
    assert entries(studio).nth(0).locator(".tx").count() == 1
    show_comments(studio, sid, [*RECORDS, record(3, "sent")])
    assert entries(studio).nth(2).locator(".tx").count() == 1
    assert entries(studio).nth(1).locator(".tx1").count() == 1  # holds across a push
    entries(studio).nth(1).click()
    assert entries(studio).nth(1).locator(".tx").count() == 1
    assert entries(studio).nth(1).locator(".rp").count() == 1


def test_com_21_fold_all_and_unfold_all(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, RECORDS)
    studio.page.locator("#comment-panel .foldall").click()
    assert entries(studio).locator(".tx").count() == 0
    assert studio.page.locator("#comment-panel .foldall").inner_text() == "Unfold all"
    studio.page.locator("#comment-panel .foldall").click()
    assert entries(studio).locator(".tx").count() == 2


def test_com_20_a_marker_click_opens_the_collapsed_panel_on_its_unfolded_entry(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    tokens = prepare_links(studio, sid, RECORDS)
    studio.page.locator("#comment-panel .foldall").click()
    collapse(studio)
    marker_report(studio, tokens[2], "click")
    studio.page.wait_for_selector("#comment-panel:not(.strip) .ent.sel")
    selected = studio.page.locator("#comment-panel .ent.sel")
    assert selected.get_attribute("data-n") == "2"
    assert selected.locator(".tx").count() == 1
    assert entries(studio).nth(0).locator(".tx").count() == 0
    comment_mode(studio, False)


def test_com_20_collapsing_keeps_a_reply_being_typed_and_the_markers(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    tokens = prepare_links(studio, sid, RECORDS)
    entries(studio).nth(0).get_by_text("Reply").click()
    studio.page.keyboard.type("half a reply")
    collapse(studio)
    studio.page.locator("#comment-panel .stripbutton").click()
    field = studio.page.locator("#comment-panel .rform textarea")
    assert field.input_value() == "half a reply"
    last = studio.frame.evaluate(
        "window.__got.filter((m) => m.type === 'comment-markers').pop()"
    )
    assert sorted(m["n"] for m in last["markers"]) == sorted(tokens)
