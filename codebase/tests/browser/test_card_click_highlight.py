"""Clicks in the shell select no text; the send icon and its floating message."""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE
from .test_comment_bar import herdr_with_tabs
from .test_comment_layer import comment_mode, wait_saved, write_comment

pytestmark = pytest.mark.browser

SELECTED = "() => getSelection().toString()"
OPACITY = (
    "() => Number(getComputedStyle(document.querySelector('#send-toast')).opacity)"
)
SENT = "Sent — agent will read it next turn"


def with_comment(studio):  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    page = studio.page
    page.evaluate("(h) => onHerdr(h)", herdr_with_tabs(sid, 1, 0))
    page.locator(".hv-card.focus .hv-frame").wait_for()
    comment_mode(studio)
    write_comment(studio, (60, 60), (200, 160), "units?")
    wait_saved(studio, 1)
    page.locator("#comment-panel .ent").first.wait_for()
    return sid


def test_clicks_in_panel_and_sidebar_select_no_text(studio) -> None:  # noqa: ANN001
    with_comment(studio)
    page = studio.page
    comment_mode(studio, False)
    assert page.evaluate(SELECTED) == ""
    page.locator("#comment-panel .ph .t b").click(click_count=3)
    page.locator("#comment-panel .ent .tx1, #comment-panel .ent").first.dblclick()
    page.locator(".hv-chead").dblclick()
    page.locator(".hv-side").click(click_count=3)
    page.mouse.move(700, 700)
    page.mouse.down()
    page.mouse.move(300, 60)
    page.mouse.up()
    assert page.evaluate(SELECTED) == ""


def test_comment_mode_border_still_shows(studio) -> None:  # noqa: ANN001
    with_comment(studio)
    comment_mode(studio)
    border = studio.page.evaluate(
        "() => getComputedStyle(document.querySelector('main'), '::after')"
        ".borderTopWidth"
    )
    assert border == "3px"


def test_send_icon_shows_only_while_comments_wait_and_both_ways_send(studio) -> None:  # noqa: ANN001
    sid = with_comment(studio)
    page = studio.page
    button, toast = page.locator("#send-button"), page.locator("#send-toast")
    comment_mode(studio, False)
    button.wait_for()
    assert button.inner_text().strip() == "" and button.locator("svg").count() == 1
    assert button.get_attribute("title")
    assert page.evaluate(OPACITY) == 0
    button.click()
    [first] = studio.wait_events(sid, 1)
    assert [c["text"] for c in first["comments"]] == ["units?"]
    page.wait_for_function(f"({OPACITY})() === 1")
    assert toast.inner_text() == SENT
    button.wait_for(state="hidden")
    page.wait_for_function(f"({OPACITY})() === 0", timeout=5000)  # fades off

    comment_mode(studio)
    write_comment(studio, (60, 200), (200, 260), "second")
    wait_saved(studio, 2)
    comment_mode(studio, False)
    page.keyboard.press("Control+Enter")
    studio.wait_events(sid, 2)
    page.wait_for_function(f"({OPACITY})() === 1")  # shown again
    assert toast.inner_text() == SENT
    page.wait_for_function(f"({OPACITY})() === 0", timeout=5000)
