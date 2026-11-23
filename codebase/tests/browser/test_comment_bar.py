"""The send button below the page and the comment panel follow the comments (FB-04).

FB-04 (changed: no draft bar, one "Send to agent" button) is owned here; COM-10 is a
slice (one page, ``part`` [1, 1], closed in P22.5).
"""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE
from .test_comment_layer import comment_file, comment_mode, wait_saved, write_comment

pytestmark = pytest.mark.browser


def test_fb_04_panel_and_send_button_appear_with_a_comment_and_go_after_ctrl_enter(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    page = studio.page
    assert page.locator("#tools, #draft-bar, #draft-message, #next-button").count() == 0
    assert page.locator("#comment-panel").is_hidden()
    assert page.locator("#send-button").is_hidden()
    comment_mode(studio)
    assert page.locator(
        "#comment-panel"
    ).is_hidden()  # comment mode alone shows nothing
    write_comment(studio, (60, 60), (200, 160), "units?")
    wait_saved(studio, 1)
    page.locator("#comment-panel .ent").first.wait_for()
    button = page.locator("#send-button")
    button.wait_for()
    assert button.inner_text().strip() == ""  # an icon, no text
    assert "Ctrl+Enter" in button.get_attribute("title")
    assert page.locator("#send-bar").count() == 0
    comment_mode(studio, False)
    page.keyboard.press("Control+Enter")
    [event] = studio.wait_events(sid, 1)
    assert [c["text"] for c in event["comments"]] == ["units?"]
    assert event["part"] == [1, 1] and event["delivery"] == "now"
    button.wait_for(state="hidden")
    assert page.locator(
        "#comment-panel"
    ).is_visible()  # the sent comment is still listed
    assert all(c["sent"] for c in comment_file(studio)["comments"])
    page.evaluate(
        "(sid) => onCommentsMessage({type: 'comments', session: sid, page: 'page.html',"
        " next: 2, comments: []})",
        sid,
    )
    page.locator("#comment-panel").wait_for(state="hidden")


def test_fb_04_ctrl_enter_sends_the_comments_without_a_message(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    comment_mode(studio)
    write_comment(studio, (60, 60), (200, 160), "units?")
    wait_saved(studio, 1)
    studio.page.keyboard.press("Control+Enter")
    [event] = studio.wait_events(sid, 1)
    assert event["message"] == "" and len(event["comments"]) == 1
    assert event["comments"][0]["picture"].endswith("0001.c1.png")


def test_com_12_a_rectangle_around_a_paragraph_by_its_bounding_box_saves(
    studio,
) -> None:  # noqa: ANN001
    """The owner steps of the end-to-end run (tests/e2e/test_com_tracer.py)."""
    studio.make(
        '<h1 id="title">Beam test</h1><p id="claim">The first bending mode of the '
        "clamped beam is 83.5 Hz.</p>"
    )
    comment_mode(studio)  # the panel opens and narrows the frame: measure after it
    studio.page.wait_for_timeout(300)
    box = studio.frame.locator("#claim").bounding_box()
    origin = studio.page.locator("#frame").bounding_box()
    start = (box["x"] - origin["x"] - 4, box["y"] - origin["y"] - 4)
    end = (start[0] + box["width"] + 8, start[1] + box["height"] + 8)
    write_comment(studio, start, end, "units?")
    wait_saved(studio, 1)
    [saved] = comment_file(studio)["comments"]
    assert saved["kind"] == "rect" and "83.5 Hz" in saved["text_inside"]


def herdr_with_tabs(sid: str, count: int, focus: int) -> dict:
    """A Herdr view with one space of ``count`` tabs; tab 0 holds the session."""
    tabs = [
        {
            "id": f"tb{i}",
            "name": f"tab number {i}",
            "active": i == focus,
            "panes": [
                {
                    "pane": f"p{i}",
                    "terminal": f"t{i}",
                    "name": "claude",
                    "status": "working" if i == 0 else "idle",
                    "app": "claude-code",
                    "focused": True,
                    "session": sid if i == 0 else None,
                }
            ],
        }
        for i in range(count)
    ]
    return {
        "available": True,
        "focus": {"space": "sp1", "tab": f"tb{focus}", "pane": f"p{focus}"},
        "spaces": [
            {"id": "sp1", "name": "s", "color": "#888", "active": True, "tabs": tabs}
        ],
        "other": [],
    }


def not_prevented(target, selector: str) -> bool:  # noqa: ANN001
    """Whether a right-click event on ``selector`` keeps the browser's own menu."""
    return target.evaluate(
        """(s) => document.querySelector(s).dispatchEvent(new MouseEvent('contextmenu',
             {bubbles: true, cancelable: true, button: 2}))""",
        selector,
    )


def test_tab_bar_scrolls_spinner_turns_right_click_is_native_and_no_history(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    page = studio.page
    page.set_viewport_size({"width": 960, "height": 1000})
    page.evaluate("(h) => onHerdr(h)", herdr_with_tabs(sid, 15, 0))
    page.locator(".hv-card.focus .hv-frame").wait_for()
    assert page.locator(".hv-act, #history-panel, #version-bar").count() == 0
    bar = page.locator(".hv-bar")
    pills = page.locator(".hv-pill")
    assert pills.count() == 15
    assert bar.evaluate("(b) => b.scrollWidth > b.clientWidth + 200")

    def inside(index: int) -> bool:
        box, pill = bar.bounding_box(), pills.nth(index).bounding_box()
        return (
            box["x"] - 1 <= pill["x"]
            and pill["x"] + pill["width"] <= box["x"] + box["width"] + 1
        )

    assert inside(0) and not inside(14)
    page.mouse.move(700, 20)
    page.mouse.wheel(0, 4000)
    page.wait_for_function(
        "(() => { const b = document.querySelector('.hv-bar');"
        " return b.scrollLeft + b.clientWidth >= b.scrollWidth - 1; })()"
    )
    assert inside(14) and not inside(0)
    page.mouse.wheel(0, -4000)
    page.wait_for_function("document.querySelector('.hv-bar').scrollLeft === 0")
    assert inside(0)
    # a new active tab is scrolled into view
    page.evaluate("(h) => onHerdr(h)", herdr_with_tabs(sid, 15, 14))
    page.wait_for_function(
        "document.querySelector('.hv-pill.on').textContent === 'tab number 14'"
    )
    assert inside(14)
    page.evaluate("(h) => onHerdr(h)", herdr_with_tabs(sid, 15, 0))
    page.locator(".hv-card.focus .hv-frame").wait_for()
    assert inside(0)
    # Herdr's working mark: the ring turns once every 0.9 s
    spin = page.locator(".hv-card.focus .hv-spin")
    assert spin.evaluate("(e) => getComputedStyle(e).animationDuration") == "0.9s"
    assert spin.evaluate("(e) => e.getAnimations()[0].playState") == "running"
    # the browser's own context menu everywhere, in comment mode too
    for selector in [".hv-row", ".hv-pill", ".hv-chead", ".hv-pt", "#content"]:
        assert not_prevented(page, selector), selector
    assert not_prevented(studio.frame, "#b")
    comment_mode(studio)
    assert not_prevented(studio.frame, "#b")
