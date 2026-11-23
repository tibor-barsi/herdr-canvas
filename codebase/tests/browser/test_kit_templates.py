"""The four page templates render cleanly with the design kit (KIT-02, KIT-05)."""

from __future__ import annotations

import pytest

from agent_canvas.templates import TEMPLATES, write_template

from .support import call
from .test_heavy_blocks import wait_model, wait_plot
from .test_scene_block import wait_scene

pytestmark = pytest.mark.browser

SIZES = (1280, 700)
SCHEMES = ("light", "dark")
READY = {
    "compare": "canvas-ask",
    "results": "canvas-plot",
    "run": "canvas-progress",
    "geometry": "canvas-scene",
    "cards": "canvas-plot",
}


def wait_rendered(owner, template: str) -> None:  # noqa: ANN001
    """Wait until the heavy blocks of ``template`` have drawn."""
    owner.frame.wait_for_function("window.agentCanvas !== undefined")
    owner.frame.locator(READY[template]).first.wait_for()
    if template == "results":
        wait_plot(owner, "response")
    if template == "geometry":
        wait_scene(owner, canvas_id="part")
    if template == "cards":
        wait_plot(owner, "plot-a")
        wait_model(owner, "model-a")


def horizontal_overflow(owner) -> int:  # noqa: ANN001
    """Pixels by which the page is wider than its window (0 = none)."""
    return owner.frame.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_kit_05_template_renders_without_errors_or_overflow(
    owner,
    make,  # noqa: ANN001
    tmp_path,  # noqa: ANN001
    template: str,
) -> None:
    made = make("<p>start</p>")
    write_template(made.folder, "tpl.html", template)
    body = {"project": str(tmp_path / "alpha"), "name": "tpl.html"}
    shown = call(owner, "POST", f"/api/sessions/{made.sid}/show", json=body)
    assert shown["errors"] == []
    wait_rendered(owner, template)
    for scheme in SCHEMES:
        owner.page.emulate_media(color_scheme=scheme)
        for width in SIZES:
            owner.page.set_viewport_size({"width": width, "height": 900})
            owner.page.wait_for_timeout(400)
            where = f"{template} {scheme} {width}px"
            assert horizontal_overflow(owner) <= 0, where
            assert owner.frame.locator(".block-error").count() == 0, where
            assert owner.page.evaluate("window.__errors") == [], where
            assert owner.page.locator("#tab-badge:visible").count() == 0, where
    owner.page.emulate_media(color_scheme="light")
    owner.page.set_viewport_size({"width": SIZES[0], "height": 900})
    owner.page.wait_for_timeout(500)
    owner.page.screenshot(path=f"/tmp/ac-kit-{template}.png")
