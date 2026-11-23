"""The page keeps the wheel while it scrolls past images and 3D views (IMG-04, #71)."""

from __future__ import annotations

import pytest

from .support import block
from .test_heavy_blocks import (
    MODEL_SIZE,
    cube_stl,
    image_file,
    image_rect,
    wait_image,
    wait_model,
)
from .test_scene_block import FILES, SCENE, parts_of, run, scene_page, wait_scene

pytestmark = pytest.mark.browser

SPACER = '<div style="height:{}px"></div>'
CAMERA = "[...document.querySelector('canvas-model').camera.matrix.elements]"


def scroll_y(owner) -> float:  # noqa: ANN001
    return owner.frame.evaluate("window.scrollY")


def point_in_frame(owner) -> tuple[float, float]:  # noqa: ANN001
    """A pointer position in window pixels, a little above the frame's middle."""
    frame = owner.frame.frame_element().bounding_box()
    block_box = owner.frame.evaluate(
        "(() => { const e = document.querySelector("
        "'canvas-image, canvas-model, canvas-scene');"
        " const c = e.shadowRoot && e.shadowRoot.querySelector('canvas');"
        " const r = (c || e).getBoundingClientRect(); return [r.left, r.width]; })()"
    )
    return frame["x"] + block_box[0] + 20, frame["y"] + frame["height"] / 3


def scroll_until_under_pointer(owner, selector: str) -> None:  # noqa: ANN001
    """Wheel the page up from its end in quick steps until ``selector`` is under it."""
    x, y = point_in_frame(owner)
    owner.page.mouse.move(x, y)
    owner.frame.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    covers = (
        "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
        f" return r.bottom > {y - owner.frame.frame_element().bounding_box()['y']}; }}"
    )
    for _ in range(80):
        if owner.frame.evaluate(covers, selector):
            return
        owner.page.mouse.wheel(0, -60)
        owner.page.wait_for_timeout(40)
    raise AssertionError("the block never reached the pointer")


def scrolling_page(make, tag: str, files: dict) -> None:  # noqa: ANN001
    make(SPACER.format(3000) + tag + SPACER.format(900), files=files)


def test_img_04_a_picture_sliding_under_the_pointer_does_not_zoom(owner, make) -> None:  # noqa: ANN001
    scrolling_page(
        make,
        block("canvas-image", "pic", {"src": "pic.png"}),
        {"pic.png": image_file()},
    )
    wait_image(owner)
    before = image_rect(owner)["width"]
    scroll_until_under_pointer(owner, "canvas-image")
    start = scroll_y(owner)
    for _ in range(5):
        owner.page.mouse.wheel(0, -60)
        owner.page.wait_for_timeout(40)
    assert scroll_y(owner) < start
    assert image_rect(owner)["width"] == before


def test_img_04_a_wheel_started_over_the_picture_after_a_pause_zooms_it(
    owner, make
) -> None:  # noqa: ANN001
    scrolling_page(
        make,
        block("canvas-image", "pic", {"src": "pic.png"}),
        {"pic.png": image_file()},
    )
    wait_image(owner)
    before = image_rect(owner)["width"]
    scroll_until_under_pointer(owner, "canvas-image")
    owner.page.wait_for_timeout(700)
    owner.page.mouse.wheel(0, -300)
    owner.frame.wait_for_function(
        "(w) => document.querySelector('canvas-image').shadowRoot"
        ".querySelector('img').getBoundingClientRect().width > w",
        arg=before,
    )


def test_img_04_a_3d_view_sliding_under_the_pointer_does_not_zoom(owner, make) -> None:  # noqa: ANN001
    config = {"src": "cube.stl", "colour": "#2a9d8f"}
    scrolling_page(
        make, block("canvas-model", "part", config), {"cube.stl": cube_stl(MODEL_SIZE)}
    )
    wait_model(owner)
    before = owner.frame.evaluate(CAMERA)
    scroll_until_under_pointer(owner, "canvas-model")
    start = scroll_y(owner)
    for _ in range(5):
        owner.page.mouse.wheel(0, -60)
        owner.page.wait_for_timeout(40)
    assert scroll_y(owner) < start
    assert owner.frame.evaluate(CAMERA) == pytest.approx(before, abs=1e-6)
    owner.page.wait_for_timeout(700)
    owner.page.mouse.wheel(0, -300)
    owner.frame.wait_for_function(
        f"(b) => JSON.stringify({CAMERA}) !== JSON.stringify(b)", arg=before
    )


def test_img_04_a_scene_sliding_under_the_pointer_does_not_zoom(owner, make) -> None:  # noqa: ANN001
    scrolling_page(make, scene_page(parts_of("a.stl")), FILES)
    wait_scene(owner)
    read = "return [...el.camera.matrix.elements]"
    before = run(owner, read)
    scroll_until_under_pointer(owner, "canvas-scene")
    start = scroll_y(owner)
    for _ in range(5):
        owner.page.mouse.wheel(0, -60)
        owner.page.wait_for_timeout(40)
    assert scroll_y(owner) < start
    assert run(owner, read) == pytest.approx(before, abs=1e-6)
    owner.page.wait_for_timeout(700)
    owner.page.mouse.wheel(0, -300)
    owner.frame.wait_for_function(
        f"(b) => {{ const el = {SCENE};"
        " return JSON.stringify([...el.camera.matrix.elements])"
        " !== JSON.stringify(b); }",
        arg=before,
    )


def test_img_04_opening_the_overlay_clears_the_latch(owner, make) -> None:  # noqa: ANN001
    scrolling_page(
        make,
        block("canvas-image", "pic", {"src": "pic.png"}),
        {"pic.png": image_file()},
    )
    wait_image(owner)
    scale = owner.frame.evaluate(
        """() => {
            const ev = () => new WheelEvent('wheel', {deltaY: -500, bubbles: true,
                composed: true, cancelable: true});
            const block = document.querySelector('canvas-image');
            document.body.dispatchEvent(ev());
            block.shadowRoot.querySelector('button.enlarge').click();
            const view = document.querySelector('.ac-image-overlay')
                .shadowRoot.querySelector('.image-view');
            view.dispatchEvent(ev());
            return block.overlay.view.zoom.scale;
        }"""
    )
    assert scale > 1
