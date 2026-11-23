"""A ``<style>`` block inside the page body survives the picture (LOOK-03, DRAW-05)."""

from __future__ import annotations

import pytest

from .test_look_window import TEAL, WHITE, decoded, look, near

pytestmark = pytest.mark.browser

RULE = (
    ".var-a .box { margin-left: 100px; width: 200px; height: 120px;"
    " background: var(--c); }"
)

# The colour is a custom property of :root; the rule that uses it sits in a
# <style> inside the body (the trigger) or, for the control, in the head.
IN_BODY = f"""<!doctype html><html><head><style>
:root {{ --c: #2a9d8f; }} body {{ margin: 0; background: #ffffff; }}
</style></head><body><div class="var-a"><style>{RULE}</style>
<div class="box"></div></div></body></html>"""

IN_HEAD = f"""<!doctype html><html><head><style>
:root {{ --c: #2a9d8f; }} body {{ margin: 0; background: #ffffff; }} {RULE}
</style></head><body><div class="var-a"><div class="box"></div></div></body></html>"""


def picture_of(owner, make, html: str):  # noqa: ANN001, ANN201
    """Look at ``html`` through the window renderer and return its pixel rows."""
    owner.page.set_viewport_size({"width": 1280, "height": 800})
    made = make(html)
    for _ in range(60):
        size = owner.frame.evaluate("[innerWidth, innerHeight]")
        info = owner.hub.on_loop(owner.hub.state.looks.window_info)
        if info and [info.width, info.height] == size:
            break
        owner.page.wait_for_timeout(100)
    result = look(owner, made.sid)
    assert result["source"] == "window", result
    return decoded(result)


def test_look_03_style_in_head_keeps_a_root_custom_property_colour(owner, make) -> None:  # noqa: ANN001
    rows = picture_of(owner, make, IN_HEAD)
    assert near(rows[60][200], TEAL) and near(rows[60][50], WHITE)


def test_look_03_style_in_body_keeps_a_root_custom_property_colour(owner, make) -> None:  # noqa: ANN001
    rows = picture_of(owner, make, IN_BODY)
    assert near(rows[60][200], TEAL) and near(rows[60][50], WHITE)
