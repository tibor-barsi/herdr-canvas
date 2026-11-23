# ruff: noqa: E501
"""canvas-animation: video and picture sequence with controls, no sound, no autoplay (CNT-02, BLK-06).

Fixtures: ``tests/fixtures/animation`` (20 frames at 10 fps, 160 x 90; frame ``i`` has a red
bar ``8 * (i + 1)`` px wide, so the bar tells which frame is on screen).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from helpers import CODEBASE_DIR, decode_png

from .support import block
from .test_heavy_blocks import near
from .test_look_window import look

pytestmark = pytest.mark.browser

FIXTURES = CODEBASE_DIR / "tests" / "fixtures" / "animation"
FRAMES = [f"frame-{i:02d}.png" for i in range(20)]
FILES = {name: (FIXTURES / name).read_bytes() for name in [*FRAMES, "bars.webm"]}
RED = (229, 72, 77)
SHOTS = os.environ.get("AC_P312_SHOTS")


def video(canvas_id: str = "v", **config) -> str:  # noqa: ANN003
    return block("canvas-animation", canvas_id, {"src": "bars.webm", **config})


def frames(canvas_id: str = "f", **config) -> str:  # noqa: ANN003
    return block("canvas-animation", canvas_id, {"frames": FRAMES, **config})


def wait_ready(owner, count: int = 1) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        """(n) => { const all = [...document.querySelectorAll('canvas-animation')];
          return all.length === n && all.every((e) => e.renderIdle && e.shadowRoot
            && e.shadowRoot.querySelector('.anim-stage video, .anim-stage img, .block-error')); }""",
        arg=count,
    )


def read(owner, canvas_id: str) -> dict:  # noqa: ANN001
    return owner.frame.evaluate(
        """(id) => { const e = document.querySelector(`[data-canvas-id="${id}"]`);
          const v = e.shadowRoot.querySelector('video');
          const q = (s) => e.shadowRoot.querySelector(s);
          return {video: !!v, t: v ? v.currentTime : null, paused: v ? v.paused : null,
            muted: v ? v.muted : null, volume: v ? v.volume : null,
            controls: v ? v.hasAttribute('controls') : null, rate: v ? v.playbackRate : null,
            loop: v ? v.loop : null, position: e.position, playing: e.playing,
            play: q('button').textContent, where: q('.anim-where').textContent,
            slider: Number(q('.anim-slider').value), error: !!q('.block-error')}; }""",
        canvas_id,
    )


def press(owner, canvas_id: str, name: str) -> None:  # noqa: ANN001
    root = f'[data-canvas-id="{canvas_id}"]'
    selector = {
        "play": 'button:text-is("Play"), button:text-is("Pause")',
        "back": 'button[aria-label="One frame back"]',
        "next": 'button[aria-label="One frame forward"]',
        "loop": 'button:text-is("Loop")',
    }[name]
    owner.frame.locator(f"{root} >> {selector}").click()


def test_cnt_02_nothing_plays_by_itself_and_the_video_is_muted(owner, make) -> None:  # noqa: ANN001
    make(video() + frames(), files=FILES)
    wait_ready(owner, 2)
    owner.page.wait_for_timeout(800)
    one, two = read(owner, "v"), read(owner, "f")
    assert one["t"] == 0 and one["paused"] is True and one["play"] == "Play"
    assert (
        two["position"] == 0
        and two["playing"] is False
        and two["where"] == "frame 1 / 20"
    )
    assert one["muted"] is True and one["volume"] == 0 and one["controls"] is False


def test_cnt_02_autoplay_starts_both_kinds(owner, make) -> None:  # noqa: ANN001
    make(
        video(autoplay=True, loop=True) + frames(autoplay=True, loop=True), files=FILES
    )
    wait_ready(owner, 2)
    owner.frame.wait_for_function(
        """() => { const [a, b] = document.querySelectorAll('canvas-animation');
          return a.shadowRoot.querySelector('video').currentTime > 0.3 && b.position > 3; }"""
    )
    assert read(owner, "v")["muted"] is True


def test_cnt_02_play_and_pause_buttons(owner, make) -> None:  # noqa: ANN001
    make(video(loop=True) + frames(loop=True), files=FILES)
    wait_ready(owner, 2)
    for canvas_id in ("v", "f"):
        press(owner, canvas_id, "play")
        owner.frame.wait_for_function(
            """(id) => { const e = document.querySelector(`[data-canvas-id="${id}"]`);
              const v = e.shadowRoot.querySelector('video');
              return (v ? v.currentTime : e.position) > 0.3; }""",
            arg=canvas_id,
        )
        assert read(owner, canvas_id)["play"] == "Pause"
        press(owner, canvas_id, "play")
        stopped = read(owner, canvas_id)
        owner.page.wait_for_timeout(400)
        later = read(owner, canvas_id)
        assert stopped["play"] == "Play"
        assert (later["t"], later["position"]) == (stopped["t"], stopped["position"])


def test_cnt_02_step_moves_one_frame_and_stops_at_the_ends(owner, make) -> None:  # noqa: ANN001
    make(video(fps=10) + frames(), files=FILES)
    wait_ready(owner, 2)
    press(owner, "f", "back")
    assert read(owner, "f")["where"] == "frame 1 / 20"
    press(owner, "f", "next")
    press(owner, "f", "next")
    assert read(owner, "f")["where"] == "frame 3 / 20"
    press(owner, "f", "back")
    assert read(owner, "f")["where"] == "frame 2 / 20"
    press(owner, "v", "next")
    owner.frame.wait_for_function(
        "Math.abs(document.querySelector('[data-canvas-id=v]').shadowRoot.querySelector('video').currentTime - 0.1) < 0.02"
    )
    press(owner, "v", "back")
    assert abs(read(owner, "v")["t"]) < 0.02


def test_cnt_02_stepping_while_playing_pauses(owner, make) -> None:  # noqa: ANN001
    make(frames(loop=True), files=FILES)
    wait_ready(owner)
    press(owner, "f", "play")
    press(owner, "f", "next")
    state = read(owner, "f")
    assert state["playing"] is False and state["play"] == "Play"


def test_cnt_02_slider_sets_the_position(owner, make) -> None:  # noqa: ANN001
    make(video() + frames(), files=FILES)
    wait_ready(owner, 2)
    owner.frame.locator('[data-canvas-id="f"] >> .anim-slider').fill("12")
    assert read(owner, "f")["where"] == "frame 13 / 20"
    owner.frame.locator('[data-canvas-id="v"] >> .anim-slider').fill("500")
    owner.frame.wait_for_function(
        "Math.abs(document.querySelector('[data-canvas-id=v]').shadowRoot.querySelector('video').currentTime - 1) < 0.1"
    )


def test_cnt_02_speed_changes_the_rate(owner, make) -> None:  # noqa: ANN001
    make(video(loop=True) + frames(loop=True, fps=5), files=FILES)
    wait_ready(owner, 2)
    owner.frame.locator('[data-canvas-id="v"] >> select').select_option("4")
    assert read(owner, "v")["rate"] == 4
    owner.frame.locator('[data-canvas-id="v"] >> select').select_option("0.25")
    assert read(owner, "v")["rate"] == 0.25
    moved = {}
    for speed in ("4", "1"):
        owner.frame.locator('[data-canvas-id="f"] >> select').select_option(speed)
        owner.frame.evaluate(
            "document.querySelector('[data-canvas-id=f]').position = 0"
        )
        press(owner, "f", "play")
        owner.page.wait_for_timeout(500)
        moved[speed] = read(owner, "f")["position"]
        press(owner, "f", "play")
    assert moved["4"] > 2 * moved["1"] > 2, moved


def test_cnt_02_loop_wraps_and_without_loop_the_sequence_stops_at_the_end(
    owner, make
) -> None:  # noqa: ANN001
    make(
        frames("looped", loop=True, fps=50, autoplay=True) + frames("once", fps=50),
        files=FILES,
    )
    wait_ready(owner, 2)
    press(owner, "once", "play")
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=once]').position === 19 && !document.querySelector('[data-canvas-id=once]').playing"
    )
    assert read(owner, "once")["play"] == "Play"
    owner.page.wait_for_timeout(900)  # looped has run past 40 frames
    state = read(owner, "looped")
    assert state["playing"] is True and state["position"] < 20


def test_cnt_02_video_loop_follows_the_button_and_the_config(owner, make) -> None:  # noqa: ANN001
    make(video(loop=True), files=FILES)
    wait_ready(owner)
    assert read(owner, "v")["loop"] is True
    press(owner, "v", "loop")
    assert read(owner, "v")["loop"] is False


def test_cnt_02_a_missing_file_and_a_bad_config_show_an_error_box(owner, make) -> None:  # noqa: ANN001
    make(
        block("canvas-animation", "a", {"src": "none.webm"})
        + block("canvas-animation", "b", {"src": "bars.webm", "frames": FRAMES})
        + block("canvas-animation", "c", {"frames": ["nope.png"]}),
        files=FILES,
    )
    owner.frame.wait_for_function(
        "document.querySelectorAll('canvas-animation').length === 3 && [...document.querySelectorAll('canvas-animation')].every((e) => e.shadowRoot && e.shadowRoot.querySelector('.block-error'))"
    )
    texts = " | ".join(
        owner.frame.locator("canvas-animation .block-error").all_inner_texts()
    )
    assert "none.webm" in texts and "either" in texts and "nope.png" in texts


def test_cnt_02_a_rewrite_keeps_the_position_and_the_playing_state(owner, make) -> None:  # noqa: ANN001
    made = make(frames("f", alt="one"), files=FILES)
    wait_ready(owner)
    press(owner, "f", "next")
    press(owner, "f", "next")
    made.rewrite(frames("f", alt="two"))
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=f]').shadowRoot.querySelector('.anim-stage img').getAttribute('aria-label') === 'two'"
    )
    assert read(owner, "f")["where"] == "frame 3 / 20"


def test_cnt_02_a_changed_frame_file_reloads_and_keeps_the_position(
    owner, make
) -> None:  # noqa: ANN001
    made = make(frames("f"), files=FILES)
    wait_ready(owner)
    press(owner, "f", "next")
    before = owner.frame.evaluate(
        "document.querySelector('[data-canvas-id=f]').revision"
    )
    (made.folder / "frame-00.png").write_bytes((FIXTURES / "frame-19.png").read_bytes())
    owner.frame.wait_for_function(
        "(n) => document.querySelector('[data-canvas-id=f]').revision > n", arg=before
    )
    wait_ready(owner)
    assert read(owner, "f")["where"] == "frame 2 / 20"


# ---- BLK-06: the current frame in the screenshot ------------------------------------------


def snapshot_bar(owner, canvas_id: str) -> int:  # noqa: ANN001
    """Red pixels along the middle row of the image the block's snapshot function returns."""
    return owner.frame.evaluate(
        """async (id) => { const e = document.querySelector(`[data-canvas-id="${id}"]`);
          const {image, rect} = await e.snapshot();
          const c = document.createElement('canvas'); c.width = image.width || rect.width;
          c.height = image.height || rect.height;
          c.getContext('2d').drawImage(image, 0, 0);
          const row = c.getContext('2d').getImageData(0, Math.floor(c.height / 2), c.width, 1).data;
          let n = 0; for (let x = 0; x < c.width; x++) if (row[4 * x] > 180 && row[4 * x + 1] < 120) n++;
          return Math.round(n * 160 / c.width); }""",
        canvas_id,
    )


def test_blk_06_snapshot_returns_the_frame_on_screen(owner, make) -> None:  # noqa: ANN001
    make(video() + frames(), files=FILES)
    wait_ready(owner, 2)
    assert abs(snapshot_bar(owner, "f") - 8) <= 4
    assert abs(snapshot_bar(owner, "v") - 8) <= 8
    for _ in range(5):
        press(owner, "f", "next")
    owner.frame.locator('[data-canvas-id="v"] >> .anim-slider').fill("500")
    owner.frame.wait_for_function(
        "!document.querySelector('[data-canvas-id=v]').shadowRoot.querySelector('video').seeking"
    )
    assert abs(snapshot_bar(owner, "f") - 48) <= 4  # frame 6
    assert abs(snapshot_bar(owner, "v") - 88) <= 12  # frame 10 at 1.0 s


def bar_in_shot(rows, rect: dict) -> float:  # noqa: ANN001
    y = int(rect["y"] + rect["h"] / 2)
    x0 = int(rect["x"])
    scale = rect["w"] / 160
    return sum(near(rows[y][x0 + dx], RED, 40) for dx in range(int(rect["w"]))) / scale


def media_rect(frame, canvas_id: str) -> dict:  # noqa: ANN001
    return frame.evaluate(
        """(id) => { const e = document.querySelector(`[data-canvas-id="${id}"]`);
          const r = e.shadowRoot.querySelector('.anim-stage video, .anim-stage img').getBoundingClientRect();
          return {x: r.left, y: r.top, w: r.width, h: r.height}; }""",
        canvas_id,
    )


def test_cnt_02_the_send_screenshot_shows_the_current_frame(studio) -> None:  # noqa: ANN001
    studio.page.set_viewport_size({"width": 1000, "height": 1000})
    sid = studio.make(video() + frames(), files=FILES)
    wait_ready(studio.owner, 2)
    for _ in range(14):
        press(studio.owner, "f", "next")  # frame 15: bar 120
    studio.frame.locator('[data-canvas-id="v"] >> .anim-slider').fill("500")
    studio.frame.wait_for_function(
        "!document.querySelector('[data-canvas-id=v]').shadowRoot.querySelector('video').seeking"
    )
    studio.frame.evaluate("window.scrollTo(0, 0)")
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    assert event["screenshot_error"] is None, event
    assert studio.send_record(event)["screenshot_warnings"] == []
    _, _, rows = decode_png(studio.screenshot(event))
    assert abs(bar_in_shot(rows, media_rect(studio.frame, "f")) - 120) <= 8
    assert abs(bar_in_shot(rows, media_rect(studio.frame, "v")) - 88) <= 12
    if SHOTS:
        shutil.copy(event["screenshot"], Path(SHOTS) / "send.png")


# ---- looks: light and dark, outside and inside a card -------------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_cnt_02_looks_the_same_inside_and_outside_a_card_and_passes_contrast(
    owner, make, scheme: str
) -> None:  # noqa: ANN001
    inside = block(
        "canvas-report",
        "r",
        {"type": "result", "title": "Mode shape"},
        video("v2") + frames("f2"),
    )
    made = make(video() + frames() + inside, files=FILES)
    wait_ready(owner, 4)
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.wait_for_timeout(300)
    result = look(owner, made.sid, width=900, height=1400, scheme=scheme)
    assert [f for f in result["audit"]["findings"] if f["rule"] == "contrast"] == []
    outer = owner.frame.evaluate(
        "() => [...document.querySelectorAll('canvas-animation')].map((e) => [e.dataset.canvasId,"
        " e.shadowRoot.querySelector('.anim-bar').getBoundingClientRect().height])"
    )
    heights = {name: h for name, h in outer}
    assert (
        abs(heights["v"] - heights["v2"]) < 1 and abs(heights["f"] - heights["f2"]) < 1
    )
    if SHOTS:
        shutil.copy(result["png"], Path(SHOTS) / f"look-{scheme}.png")


def test_cnt_02_the_controls_work_inside_a_card(owner, make) -> None:  # noqa: ANN001
    make(
        block(
            "canvas-report",
            "r",
            {"type": "result", "title": "Mode shape"},
            frames("f2"),
        ),
        files=FILES,
    )
    wait_ready(owner)
    press(owner, "f2", "next")
    assert read(owner, "f2")["where"] == "frame 2 / 20"
