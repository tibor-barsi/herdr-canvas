"""A comment and a send leave a paused animation where it is (check 19, CNT-02)."""

from __future__ import annotations

import pytest

from helpers import decode_png

from .support import block
from .test_animation import FILES, bar_in_shot, media_rect, read, wait_ready
from .test_comment_layer import comment_mode, drag, wait_saved

pytestmark = pytest.mark.browser


def pause_at_half_and_comment(studio) -> str:  # noqa: ANN001
    """Play, pause the video at half its length, draw a rectangle comment over it."""
    studio.page.set_viewport_size({"width": 1000, "height": 800})
    page = (
        "<div style='height:300px'>top</div>"
        + block("canvas-animation", "v", {"src": "bars.webm", "loop": True})
        + "<div style='height:1500px'>bottom</div>"
    )
    sid = studio.make(page, files=FILES)
    owner = studio.owner
    wait_ready(owner)
    owner.frame.locator('[data-canvas-id=v] >> button:text-is("Play")').click()
    owner.frame.locator('[data-canvas-id=v] >> button:text-is("Pause")').click()
    owner.frame.locator("[data-canvas-id=v] >> .anim-slider").fill("500")
    owner.frame.wait_for_function(
        "!document.querySelector('[data-canvas-id=v]').shadowRoot.querySelector('video').seeking"
    )
    comment_mode(studio)
    rect = media_rect(owner.frame, "v")
    drag(studio, (rect["x"] + 20, rect["y"] + 20), (rect["x"] + 150, rect["y"] + 100))
    studio.page.fill(".cbox textarea", "paused")
    studio.page.keyboard.press("Enter")
    wait_saved(studio, 1)
    comment_mode(studio, False)
    return sid


@pytest.mark.parametrize("scrolled_out", [False, True])
def test_cnt_02_a_comment_and_a_send_keep_a_paused_video_where_it_is(
    studio,
    scrolled_out: bool,  # noqa: FBT001
) -> None:
    sid = pause_at_half_and_comment(studio)
    owner = studio.owner
    before = read(owner, "v")
    assert before["paused"] and 0.8 < before["t"] < 1.2
    if scrolled_out:
        owner.frame.evaluate(
            "window.scrollTo(0, document.querySelector('[data-canvas-id=v]')"
            ".getBoundingClientRect().bottom + scrollY - 100)"
        )
    studio.page.wait_for_timeout(1500)
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    after = read(owner, "v")
    assert (after["t"], after["paused"], after["where"], after["slider"]) == (
        before["t"], True, before["where"], before["slider"],
    )  # fmt: skip
    _, _, rows = decode_png(studio.screenshot(event))
    if not scrolled_out:
        assert abs(bar_in_shot(rows, media_rect(owner.frame, "v")) - 88) <= 12
