"""The what's new signs and the comment markers follow their element (NEW-04, #7)."""

from __future__ import annotations

import pytest

from .test_comment_layer import comment_mode, wait_saved, write_comment
from .test_new_whats_new import (
    SIGNS,
    seen_first,
    seen_of,
    set_visible,
    sign_list,
    wait_until,
    write_version,
)

pytestmark = pytest.mark.browser

INNER = (
    "<!doctype html><title>t</title><body style='margin:0'>"
    "<div id='pane' style='height:300px;overflow:auto'>"
    "<section data-canvas-id='a' style='height:80px'>Alpha</section>"
    "<section id='target' data-canvas-id='b' style='height:80px;background:#9cf'>"
    "Beta</section><div style='height:1200px'></div></div></body>"
)
GROWING = (
    "<!doctype html><title>t</title>"
    "<style>html,body{height:100%;margin:0;overflow:hidden}</style>"
    "<div id='above' style='height:40px'>above</div>"
    "<section id='target' data-canvas-id='b' style='height:80px;background:#9cf'>"
    "Beta</section>"
)
TOP = "(s) => document.querySelector(s).getBoundingClientRect().top"
SIGN_TOP = (
    "() => document.querySelector('[data-ac-comment-host]').shadowRoot"
    ".querySelector('.sign-box').getBoundingClientRect().top"
)


def open_with_sign(owner, make, html: str):  # noqa: ANN001, ANN201
    made = seen_first(owner, make, html)
    set_visible(owner, False)
    write_version(owner, made, "page.html", html.replace("Beta", "Beta two"), 2)
    set_visible(owner, True)
    owner.visit(made.sid)
    owner.frame.wait_for_function(f"({SIGNS})().length === 1")
    wait_until(owner, lambda: seen_of(made) == 2)
    return made


def test_new_04_a_sign_follows_its_element_when_an_inner_container_scrolls(
    owner,
    make,  # noqa: ANN001
) -> None:
    open_with_sign(owner, make, INNER)
    before = owner.frame.evaluate(SIGN_TOP)
    owner.frame.evaluate("document.getElementById('pane').scrollTop = 50")
    owner.frame.wait_for_function(f"({SIGN_TOP})() !== {before}")
    target = owner.frame.evaluate(TOP, "#target")
    assert abs(owner.frame.evaluate(SIGN_TOP) - target) <= 1
    assert len(sign_list(owner)) == 1


def test_new_04_a_sign_follows_its_element_when_an_element_above_expands(
    owner,
    make,  # noqa: ANN001
) -> None:
    open_with_sign(owner, make, GROWING)
    owner.frame.evaluate("document.getElementById('above').style.height = '200px'")
    owner.frame.wait_for_function(f"Math.abs(({SIGN_TOP})() - ({TOP})('#target')) < 1")


def test_new_04_a_comment_marker_follows_its_element_in_an_inner_container(
    studio,
) -> None:
    studio.make(INNER)
    comment_mode(studio)
    box = studio.frame.locator("#target").bounding_box()
    left, top = studio.origin()
    x, y = box["x"] - left, box["y"] - top
    write_comment(studio, (x + 10, y + 10), (x + 100, y + 60), "inner")
    wait_saved(studio, 1)
    mark = '[data-ac-comment-host] .box[data-n="1"]'
    studio.frame.locator(mark).wait_for()
    studio.frame.evaluate("document.getElementById('pane').scrollTop = 50")
    studio.frame.wait_for_function(
        "() => { const m = document.querySelector('[data-ac-comment-host]')"
        ".shadowRoot.querySelector('.box[data-n=\"1\"]').getBoundingClientRect().top;"
        f" return Math.abs(m - ({TOP})('#target') - 10) < 2; }}"
    )


def test_new_04_a_comment_marker_follows_when_an_element_above_expands(
    studio,
) -> None:
    studio.make(GROWING)
    comment_mode(studio)
    box = studio.frame.locator("#target").bounding_box()
    left, top = studio.origin()
    x, y = box["x"] - left, box["y"] - top
    write_comment(studio, (x + 10, y + 10), (x + 100, y + 60), "grown")
    wait_saved(studio, 1)
    studio.frame.locator('[data-ac-comment-host] .box[data-n="1"]').wait_for()
    studio.frame.evaluate("document.getElementById('above').style.height = '200px'")
    studio.frame.wait_for_function(
        "() => { const m = document.querySelector('[data-ac-comment-host]')"
        ".shadowRoot.querySelector('.box[data-n=\"1\"]').getBoundingClientRect().top;"
        f" return Math.abs(m - ({TOP})('#target') - 10) < 2; }}"
    )
