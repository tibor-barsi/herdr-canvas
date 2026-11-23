"""The send button, Ctrl+Enter and the draft of page actions (M9, FB-04)."""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE

pytestmark = pytest.mark.browser

SEND = "#send-button"


def test_fb_04_unsent_actions_alone_show_the_button(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    assert studio.page.locator(SEND).is_hidden()
    studio.frame.click("#b")
    studio.page.wait_for_function(f"window.__drafts['{sid}'].actions.length === 1")
    assert studio.page.locator(SEND).is_enabled()


def test_fb_04_actions_that_became_events_do_not_show_the_button(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.frame.evaluate("agentCanvas.emit('pick', 1)")
    studio.wait_events(sid, 1)
    studio.page.wait_for_function(
        f"window.__drafts['{sid}'].actions.some((a) => a.event)"
    )
    assert studio.page.locator(SEND).is_hidden()


def test_fb_04_send_button_creates_a_now_send_and_clears_the_draft(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.frame.click("#b")
    studio.page.click(SEND)
    [event] = studio.wait_events(sid, 1)
    assert event["kind"] == "send" and event["delivery"] == "now"
    assert event["message"] == ""
    assert [a["kind"] for a in event["actions"]] == ["click"]
    assert event["page"] == "page.html"
    studio.page.wait_for_function(f"window.__drafts['{sid}'].actions.length === 0")
    draft = studio.page.evaluate(f"window.__drafts['{sid}']")
    assert draft["actions"] == [] and draft["actions_dropped"] == 0
    studio.page.locator(SEND).wait_for(state="hidden")


def test_fb_04_ctrl_enter_inside_the_frame_sends_now(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.frame.click("#b")
    studio.frame.click("#t")
    studio.page.keyboard.type("page typing")
    studio.page.keyboard.press("Control+Enter")
    [event] = studio.wait_events(sid, 1)
    assert event["delivery"] == "now" and len(event["actions"]) >= 1


def test_fb_04_ctrl_enter_with_an_empty_draft_sends_nothing(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.page.keyboard.press("Control+Enter")
    studio.frame.focus("#plain")
    studio.page.keyboard.press("Control+Enter")
    studio.page.wait_for_timeout(500)
    assert studio.events(sid) == []


def test_fb_04_a_refused_upload_keeps_the_draft_and_tells_the_owner(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.frame.click("#b")
    studio.page.wait_for_function(f"window.__drafts['{sid}'].actions.length === 1")
    studio.page.route(
        "**/api/sessions/*/send", lambda route: route.fulfill(status=500, body="{}")
    )
    studio.page.click(SEND)
    studio.page.wait_for_selector("#send-toast.visible")
    assert "not sent" in studio.page.inner_text("#send-toast").lower()
    assert len(studio.page.evaluate(f"window.__drafts['{sid}'].actions")) == 1
    assert studio.events(sid) == []


def test_sec_09_a_forged_send_message_from_the_page_creates_nothing(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.frame.evaluate(
        "window.parent.postMessage({type: 'send', delivery: 'now', message: 'x'}, '*')"
    )
    studio.page.wait_for_timeout(500)
    assert studio.events(sid) == []
    assert studio.page.evaluate("window.__guard.dropped.type") >= 1
