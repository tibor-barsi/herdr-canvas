"""Send screenshot, failure paths and sends in history (M9, DRAW-05, HIST-03)."""

from __future__ import annotations

import pytest

from helpers import decode_png

from .support import FILLER, RED, SCROLL_PAGE, TEAL

pytestmark = pytest.mark.browser


def near(pixel, colour, tolerance: int = 12) -> bool:  # noqa: ANN001
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


def send_scrolled(studio, sid: str):  # noqa: ANN001, ANN201
    """Scroll to 340, add a red element at (400,40)-(520,120), send; the event."""
    studio.frame.evaluate(
        "document.body.insertAdjacentHTML('beforeend', '<div id=\"red\" style=\""
        "position:absolute;left:400px;top:380px;width:120px;height:80px;"
        f"background:rgb{RED}\"></div>')"
    )
    studio.frame.evaluate("window.scrollTo(0, 340)")
    studio.frame.wait_for_function("window.scrollY === 340")
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    return event


def test_draw_05_png_has_viewport_size_page_pixels_and_a_red_element_in_place(
    studio,
) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.queue_action()  # measured with the send button shown, as at the send
    viewport = studio.frame.evaluate("[innerWidth, innerHeight]")
    event = send_scrolled(studio, sid)
    assert event["screenshot_error"] is None, event
    record = studio.send_record(event)
    width, height, rows = decode_png(studio.screenshot(event))
    assert [width, height] == viewport
    assert record["viewport"] == {
        "width": viewport[0], "height": viewport[1], "scroll_x": 0, "scroll_y": 340,
    }  # fmt: skip
    # Page content at the scrolled position: filler above row 60, target below.
    assert near(rows[30][200], FILLER) and near(rows[58][200], FILLER)
    assert near(rows[62][200], TEAL) and near(rows[120][200], TEAL)
    assert near(rows[178][200], TEAL) and near(rows[185][200], (255, 255, 255))
    assert near(rows[120][95], FILLER) is False and near(rows[120][95], (255,) * 3)
    # The red element at known page coordinates: x 400 to 520, y 40 to 120 here.
    assert near(rows[80][460], RED) and near(rows[41][401], RED)
    assert near(rows[119][519], RED) and near(rows[30][460], FILLER)
    white = (255, 255, 255)
    assert near(rows[130][460], white) and near(rows[80][530], white)


def test_draw_05_record_matches_the_event_and_the_files(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    event = send_scrolled(studio, sid)
    record = studio.send_record(event)
    assert record["schema"] == "agent-canvas/send@1"
    assert record["event"] == event["id"] and record["message"] == ""
    assert record["screenshot"] == "0001.png" and record["screenshot_warnings"] == []
    assert "marks" not in record
    assert event["screenshot"].endswith("history/sends/0001.png")


def test_draw_05_failing_capture_still_delivers_with_screenshot_error(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.frame.evaluate("agentCanvas.captureFailure = 'snapdom exploded'")
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    assert event["screenshot"] is None
    assert "snapdom exploded" in event["screenshot_error"]
    record = studio.send_record(event)
    assert record["screenshot"] is None
    assert "snapdom exploded" in record["screenshot_error"]
    studio.page.wait_for_selector("#send-toast.visible")
    notice = studio.page.inner_text("#send-toast")
    assert "without a screenshot" in notice.lower() and "snapdom exploded" in notice
    studio.page.wait_for_function(
        "window.__shell.draftOf(window.__shell.activeTab().id).actions.length === 0"
    )  # the send itself went out


def test_draw_05_a_hanging_capture_times_out_and_the_send_still_goes_out(
    studio,
) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.page.evaluate("window.__captureTimeoutMs = 600")
    studio.frame.evaluate("agentCanvas.captureHang = true")
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    assert event["screenshot"] is None
    assert "timed out" in event["screenshot_error"]


def test_draw_05_capture_uses_the_page_at_send_time_not_a_cached_image(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    studio.frame.evaluate(
        "document.getElementById('target').style.background = '#ff00ff'"
    )
    studio.frame.evaluate("window.scrollTo(0, 340)")
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    _, _, rows = decode_png(studio.screenshot(event))
    assert near(rows[120][200], (255, 0, 255))


def test_draw_05_blocks_inside_shadow_roots_appear_in_the_screenshot(studio) -> None:
    sid = studio.make(
        '<body style="margin:0"><canvas-progress data-canvas-id="job">'
        '<script type="application/json">{"value": 1, "max": 1, "label": "Full"}'
        "</script></canvas-progress></body>"
    )
    studio.frame.wait_for_function(
        "document.querySelector('canvas-progress').shadowRoot !== null"
    )
    studio.page.wait_for_timeout(1000)  # the bar animates to its width
    box = studio.frame.locator("canvas-progress").bounding_box()
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    _, _, rows = decode_png(studio.screenshot(event))
    ox, oy = studio.origin()  # the box is in window coordinates
    x, y = int(box["x"] - ox), int(box["y"] - oy)
    w, h = int(box["width"]), int(box["height"])
    # The card has a border and a filled bar: more than one colour in its box.
    colours = {p[:3] for row in rows[y : y + h] for p in row[x : x + w]}
    assert len(colours) > 3
    saturated = [c for c in colours if max(c) - min(c) > 60]  # the coloured bar
    assert saturated


def test_draw_05_block_width_in_the_png_matches_its_width_on_screen(studio) -> None:
    sid = studio.make(
        '<body style="margin:24px;max-width:720px"><h1 id="h">Title</h1>'
        '<canvas-progress data-canvas-id="job"><script type="application/json">'
        '{"value": 7, "max": 10, "label": "Mesh"}</script></canvas-progress></body>'
    )
    studio.frame.wait_for_function(
        "document.querySelector('canvas-progress').shadowRoot !== null"
    )
    studio.page.wait_for_timeout(1000)
    box = studio.frame.evaluate(
        "(() => { const r = document.querySelector('canvas-progress')"
        ".getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()"
    )
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    _, _, rows = decode_png(studio.screenshot(event))
    left, top, width, height = (int(v) for v in box)
    # The card's border is the only non-white pixel run on a row through its
    # middle: its right edge sits at left + width, whatever the capture scale.
    middle = rows[top + height // 2]
    edges = [x for x, p in enumerate(middle) if not near(p, (255, 255, 255), 3)]
    assert abs(max(edges) - (left + width)) <= 3, (max(edges), left + width)
