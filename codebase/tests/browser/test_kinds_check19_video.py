# ruff: noqa: E501
"""Early check 19 (P31.2): video in the sandboxed frame, and its capture in screenshots.

Fixtures: ``tests/fixtures/animation/bars.{webm,mp4}``, 20 frames at 10 fps; frame ``i``
has a red bar ``8 * (i + 1)`` px wide on teal. Positive controls: the WebM plays under
the page CSP and its frame can be drawn on a canvas. Negative controls: a video from
outside the session folder is blocked by ``media-src``; a canvas drawn from a video
loaded without ``crossorigin`` is tainted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import CODEBASE_DIR, decode_png

from .test_heavy_blocks import near
from .test_look_window import look

pytestmark = pytest.mark.browser

FIXTURES = CODEBASE_DIR / "tests" / "fixtures" / "animation"
RED, TEAL = (229, 72, 77), (42, 157, 143)
PAGE = (
    "<style>body{margin:8px;background:#fff}video{display:block;width:320px;height:180px}</style>"
    '<video id="w" src="bars.webm" muted crossorigin="anonymous"></video>'
    '<video id="m" src="bars.mp4" muted preload="auto"></video>'
    '<video id="plain" src="bars.webm" muted></video>'
)
FILES = {
    "bars.webm": (FIXTURES / "bars.webm").read_bytes(),
    "bars.mp4": (FIXTURES / "bars.mp4").read_bytes(),
}


def state(frame, selector: str) -> dict:  # noqa: ANN001
    return frame.evaluate(
        "(s) => { const v = document.querySelector(s); return {ready: v.readyState,"
        " w: v.videoWidth, error: v.error && v.error.code, t: v.currentTime,"
        " paused: v.paused, muted: v.muted}; }",
        selector,
    )


def test_check19_webm_plays_in_the_frame_under_the_csp(owner, make) -> None:  # noqa: ANN001
    make(PAGE, files=FILES)
    frame = owner.frame
    frame.wait_for_function("document.getElementById('w').readyState >= 2")
    before = state(frame, "#w")
    frame.evaluate("document.getElementById('w').play()")
    frame.wait_for_function("document.getElementById('w').currentTime > 0.5")
    after = state(frame, "#w")
    print("webm:", before, after)
    assert before["w"] == 160 and before["error"] is None
    assert after["t"] > 0.5 and after["paused"] is False and after["muted"] is True


def test_check19_mp4_h264_in_playwrights_chromium(owner, make) -> None:  # noqa: ANN001
    make(PAGE, files=FILES)
    frame = owner.frame
    verdict = frame.evaluate(
        "({webm: document.createElement('video').canPlayType('video/webm; codecs=vp8'),"
        " mp4: document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')})"
    )
    frame.wait_for_function(
        "document.getElementById('m').readyState >= 2 || document.getElementById('m').error"
    )
    print("canPlayType:", verdict, "mp4 element:", state(frame, "#m"))
    assert verdict["webm"] in ("probably", "maybe")


def test_check19_negative_control_a_video_outside_the_session_folder_is_blocked(
    owner, make
) -> None:  # noqa: ANN001
    make(PAGE, files=FILES)
    frame = owner.frame
    frame.evaluate(
        """(url) => { window.__csp = []; document.addEventListener('securitypolicyviolation',
          (e) => window.__csp.push(e.violatedDirective));
          const v = document.createElement('video'); v.id = 'outside'; v.src = url;
          document.body.append(v); }""",
        f"http://localhost:{owner.hub.port}/static/vendor/none.webm",
    )
    frame.wait_for_function("window.__csp.length > 0")
    print("csp:", frame.evaluate("window.__csp"))
    assert frame.evaluate("window.__csp")[0].startswith("media-src")


def test_check19_canvas_from_a_video_needs_crossorigin(owner, make) -> None:  # noqa: ANN001
    make(PAGE, files=FILES)
    frame = owner.frame
    frame.wait_for_function("document.getElementById('plain').readyState >= 2")
    frame.wait_for_function("document.getElementById('w').readyState >= 2")
    probe = """(id) => { const v = document.getElementById(id);
      const c = document.createElement('canvas'); c.width = 160; c.height = 90;
      const g = c.getContext('2d'); g.drawImage(v, 0, 0, 160, 90);
      try { const d = g.getImageData(150, 45, 1, 1).data; return {ok: true, px: [...d]}; }
      catch (e) { return {ok: false, error: e.name}; } }"""
    with_attr = frame.evaluate(probe, "w")
    without = frame.evaluate(probe, "plain")
    print("crossorigin:", with_attr, "none:", without)
    assert with_attr["ok"] is True and near(with_attr["px"], TEAL, 40)
    assert without["ok"] is False


def seek_all(frame, seconds: float) -> None:  # noqa: ANN001
    frame.evaluate(
        "(t) => { for (const v of document.querySelectorAll('video')) v.currentTime = t; }",
        seconds,
    )
    frame.wait_for_function(
        "[...document.querySelectorAll('video')].every((v) => !v.seeking && v.readyState >= 2)"
    )


def bar_width(rows, left: int, top: int) -> float:  # noqa: ANN001
    """Width of the red bar in source pixels, read along the middle row of a 320 px video."""
    y = top + 90
    return sum(near(rows[y][left + x], RED, 40) for x in range(320)) / 2


def test_check19_how_the_send_screenshot_and_look_see_a_paused_video(studio) -> None:  # noqa: ANN001
    studio.page.set_viewport_size({"width": 1000, "height": 900})
    sid = studio.make(PAGE, files=FILES)
    frame = studio.frame
    frame.wait_for_function("document.getElementById('w').readyState >= 2")
    seek_all(frame, 1.0)  # frame 10: bar 88 px of 160
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    _, _, rows = decode_png(studio.screenshot(event))
    sent = bar_width(rows, 8, 8)
    result = look(studio.owner, sid, width=1000, height=900)
    _, _, look_rows = decode_png(Path(result["png"]).read_bytes())
    fresh = bar_width(look_rows, 8, 8)
    print(
        f"send: red bar {sent} px of 160 (frame 10 = 88); look: {fresh} (frame 0 = 8)"
    )
    assert abs(sent - 88) <= 8  # the paused frame, not the first one
    assert abs(fresh - 8) <= 8  # negative control: a fresh render starts at frame 0
