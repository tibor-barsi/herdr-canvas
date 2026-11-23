"""A paused animation keeps its position across a tab switch (CNT-02, D-55)."""

from __future__ import annotations

import pytest

from .support import block
from .test_animation import FILES, FRAMES, press, read, wait_ready

pytestmark = pytest.mark.browser

PAGE = block("canvas-animation", "v", {"src": "bars.webm"}) + block(
    "canvas-animation", "f", {"frames": FRAMES}
)


def leave_and_return(studio, first: str) -> None:  # noqa: ANN001
    studio.make("<p>other</p>", name="beta")
    studio.owner.visit(first)
    wait_ready(studio.owner, 2)


def test_cnt_02_a_paused_animation_comes_back_on_the_same_frame_paused(
    studio,
) -> None:  # noqa: ANN001
    first = studio.make(PAGE, files=FILES)
    owner = studio.owner
    wait_ready(owner, 2)
    owner.frame.locator("[data-canvas-id=v] >> .anim-slider").fill("500")
    owner.frame.locator("[data-canvas-id=f] >> .anim-slider").fill("7")
    before = read(owner, "v")
    assert before["t"] > 0.8
    leave_and_return(studio, first)
    video, pictures = read(owner, "v"), read(owner, "f")
    assert abs(video["t"] - before["t"]) < 0.1 and video["paused"] is True
    assert pictures["position"] == 7 and pictures["playing"] is False
    assert pictures["where"] == "frame 8 / 20"


def test_cnt_02_a_playing_animation_comes_back_paused_near_where_it_was(
    studio,
) -> None:  # noqa: ANN001
    first = studio.make(PAGE, files=FILES)
    owner = studio.owner
    wait_ready(owner, 2)
    owner.frame.locator("[data-canvas-id=f] >> .anim-slider").fill("3")
    press(owner, "f", "play")
    owner.page.wait_for_timeout(1200)
    leave_and_return(studio, first)
    pictures = read(owner, "f")
    assert pictures["playing"] is False and pictures["position"] > 3
    assert read(owner, "v")["t"] == 0
