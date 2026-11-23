"""Enlarging a ``canvas-image`` in an overlay (IMG-01 to IMG-03)."""

from __future__ import annotations

import pytest

from .test_heavy_blocks import (
    IMAGE_H,
    IMAGE_W,
    image_page,
    image_rect,
    to_window,
    wait_image,
)

pytestmark = pytest.mark.browser

OVERLAY = ".ac-image-overlay"


def overlay_rect(owner) -> dict:  # noqa: ANN001
    """The picture in the overlay, in frame-viewport pixels."""
    return owner.frame.evaluate(
        "(() => { const r = document.querySelector('.ac-image-overlay')"
        ".shadowRoot.querySelector('img').getBoundingClientRect();"
        " return {left: r.left, top: r.top, width: r.width, height: r.height}; })()"
    )


def open_overlay(owner) -> None:  # noqa: ANN001
    """Click the enlarge button and wait for the overlay picture."""
    owner.frame.locator("canvas-image button.enlarge").click()
    owner.frame.wait_for_function(
        "(() => { const o = document.querySelector('.ac-image-overlay');"
        " const i = o && o.shadowRoot.querySelector('img');"
        " return !!i && i.complete && i.naturalWidth > 0; })()"
    )
    # The picture is fitted to the overlay in a later frame: measure after it.
    owner.frame.evaluate(
        "new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


def overlay_count(owner) -> int:  # noqa: ANN001
    """How many overlays the page holds."""
    return owner.frame.locator(OVERLAY).count()


def test_img_01_the_button_opens_a_full_frame_overlay(owner, make) -> None:  # noqa: ANN001
    image_page(make)
    wait_image(owner)
    small = image_rect(owner)["width"]
    assert overlay_count(owner) == 0
    open_overlay(owner)
    size = owner.frame.evaluate("[innerWidth, innerHeight]")
    box = owner.frame.evaluate(
        "(() => { const r = document.querySelector('.ac-image-overlay')"
        ".getBoundingClientRect(); return [r.width, r.height]; })()"
    )
    assert box == size
    assert overlay_rect(owner)["width"] > small * 1.5


def test_img_01_enter_on_the_focused_picture_opens_it(owner, make) -> None:  # noqa: ANN001
    image_page(make)
    wait_image(owner)
    owner.frame.locator("canvas-image .image-view").press("Enter")
    owner.frame.wait_for_selector(OVERLAY)
    assert overlay_count(owner) == 1


def test_img_01_overlay_zooms_with_the_wheel_and_resets_on_double_click(
    owner, make
) -> None:  # noqa: ANN001
    image_page(make)
    wait_image(owner)
    open_overlay(owner)
    start = overlay_rect(owner)
    centre = to_window(
        owner, start["left"] + start["width"] / 2, start["top"] + start["height"] / 2
    )
    owner.page.mouse.move(*centre)
    owner.page.mouse.wheel(0, -500)
    owner.frame.wait_for_function(
        "(w) => document.querySelector('.ac-image-overlay').shadowRoot"
        ".querySelector('img').getBoundingClientRect().width > w * 1.3",
        arg=start["width"],
    )
    owner.page.mouse.dblclick(*centre)
    owner.frame.wait_for_function(
        "(w) => Math.abs(document.querySelector('.ac-image-overlay').shadowRoot"
        ".querySelector('img').getBoundingClientRect().width - w) < 2",
        arg=start["width"],
    )


def test_img_02_escape_and_the_close_button_close_it(owner, make) -> None:  # noqa: ANN001
    image_page(make)
    wait_image(owner)
    open_overlay(owner)
    owner.page.keyboard.press("Escape")
    owner.frame.wait_for_function("!document.querySelector('.ac-image-overlay')")
    open_overlay(owner)
    owner.frame.locator(f"{OVERLAY} button.close").click()
    owner.frame.wait_for_function("!document.querySelector('.ac-image-overlay')")
    focused = owner.frame.evaluate(
        "document.querySelector('canvas-image').shadowRoot.activeElement.className"
    )
    assert "enlarge" in focused


def test_img_02_a_changed_config_closes_the_overlay(owner, make) -> None:  # noqa: ANN001
    made = image_page(make)
    wait_image(owner)
    open_overlay(owner)
    made.rewrite(
        made.folder.joinpath("page.html").read_text().replace("red and", "RED")
    )
    owner.frame.wait_for_function("!document.querySelector('.ac-image-overlay')")


def test_img_03_a_click_in_the_overlay_gives_the_same_image_pixels(owner, make) -> None:  # noqa: ANN001
    made = image_page(make)
    wait_image(owner)
    open_overlay(owner)
    rect = overlay_rect(owner)
    owner.page.mouse.click(
        *to_window(
            owner,
            rect["left"] + rect["width"] * 0.25,
            rect["top"] + rect["height"] * 0.5,
        )
    )
    [first] = made.wait_action("image-click")
    assert first["target"]["canvas_id"] == "pic"
    assert abs(first["value"]["x"] - 50) <= 1 and abs(first["value"]["y"] - 50) <= 1
    # The draft bar resizes the frame: measure again, then zoom about the centre.
    owner.page.wait_for_timeout(300)
    rect = overlay_rect(owner)
    centre = to_window(
        owner, rect["left"] + rect["width"] / 2, rect["top"] + rect["height"] / 2
    )
    owner.page.mouse.move(*centre)
    owner.page.mouse.wheel(0, -400)
    owner.frame.wait_for_function(
        "(w) => document.querySelector('.ac-image-overlay').shadowRoot"
        ".querySelector('img').getBoundingClientRect().width > w * 1.2",
        arg=rect["width"],
    )
    # Screen pixels per image pixel now; the zoom is about the centre of the picture.
    per_pixel = overlay_rect(owner)["width"] / IMAGE_W
    owner.page.mouse.click(centre[0] + 20, centre[1] + 10)
    second = made.wait_action("image-click", 2)[1]["value"]
    assert abs(second["x"] - (IMAGE_W / 2 + 20 / per_pixel)) <= 1
    assert abs(second["y"] - (IMAGE_H / 2 + 10 / per_pixel)) <= 1
