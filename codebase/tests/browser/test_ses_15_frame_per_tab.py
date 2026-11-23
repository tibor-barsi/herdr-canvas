"""Each open page keeps its own frame across tab switches (SES-15, #8)."""

from __future__ import annotations

import re

import pytest

from .test_do_card import page as do_page
from .test_do_card import wait_card

pytestmark = pytest.mark.browser

FORM = (
    "<input id=t><details id=d><summary>more</summary>inside</details>"
    "<div style='height:4000px'>tall</div>"
)
FRAMES = (
    "Array.from(document.querySelectorAll('main iframe'),"
    " (f) => [f.id, f.inert, getComputedStyle(f).visibility])"
)


def settle(owner) -> None:  # noqa: ANN001
    # The window loads a new page a second time just after `show`; act after that.
    owner.page.wait_for_timeout(1000)


def test_ses_15_typed_text_and_open_sections_survive_a_tab_switch(make, owner) -> None:  # noqa: ANN001
    first = make(FORM)
    settle(owner)
    owner.frame.fill("#t", "typed by the owner")
    owner.frame.evaluate("document.getElementById('d').open = true; window.__kept = 1")
    make("<p>other</p>", name="beta")
    owner.visit(first.sid)
    assert owner.frame.input_value("#t") == "typed by the owner"
    assert owner.frame.evaluate(
        "[document.getElementById('d').open, window.__kept]"
    ) == [
        True,
        1,
    ]


def test_ses_15_the_inactive_frame_is_hidden_and_inert(make, owner) -> None:  # noqa: ANN001
    make(FORM)
    make("<p>other</p>", name="beta")
    frames = sorted(owner.page.evaluate(FRAMES))
    assert frames == [["", True, "hidden"], ["frame", False, "visible"]]
    assert owner.frame.evaluate("document.body.textContent") == "other"


def test_ses_15_a_hidden_frame_reports_nothing_to_the_shown_page(make, owner) -> None:  # noqa: ANN001
    make(FORM)
    settle(owner)
    hidden = owner.frame
    make("<p>other</p>", name="beta")
    hidden.evaluate("setTimeout(() => { throw new Error('late failure'); }, 0)")
    owner.page.wait_for_timeout(300)
    assert owner.page.evaluate("window.__errors.length") == 0
    # Owner input from a frame that is not shown is not the owner's: no action anywhere.
    hidden.evaluate("agentCanvas.emit('ghost', 1)")
    owner.page.wait_for_timeout(300)
    actions = owner.page.evaluate(
        "Object.values(window.__drafts).map((d) => (d.actions || []).length)"
    )
    assert sum(actions) == 0


def test_ses_15_a_hidden_frame_leaves_comment_mode(make, owner) -> None:  # noqa: ANN001
    second = make("<p>other</p>", name="beta")
    first = make(FORM)
    settle(owner)
    hidden = owner.frame
    owner.page.locator("body").press("c")
    commenting = "document.documentElement.hasAttribute('data-ac-commenting')"
    hidden.wait_for_function(commenting)
    owner.visit(second.sid)
    owner.frame.wait_for_function(commenting)
    assert hidden.evaluate(commenting) is False
    owner.visit(first.sid)
    hidden.wait_for_function(commenting)


def test_ses_15_only_eight_frames_live_and_a_dropped_one_comes_back_at_its_place(
    make, owner
) -> None:  # noqa: ANN001
    first = make(FORM)
    settle(owner)
    owner.frame.evaluate("window.scrollTo(0, 1500); window.__kept = 1")
    owner.page.wait_for_timeout(400)
    for n in range(8):
        make(f"<p>page {n}</p>", name=f"s{n}")
    assert len(owner.page.evaluate(FRAMES)) == 8
    owner.visit(first.sid)
    owner.frame.wait_for_function("window.agentCanvas !== undefined")
    owner.frame.wait_for_function("Math.abs(window.scrollY - 1500) < 5")
    assert owner.frame.evaluate("window.__kept") is None
    assert len(owner.page.evaluate(FRAMES)) == 8


def test_ses_15_a_copy_result_goes_to_the_frame_that_asked(make, owner) -> None:  # noqa: ANN001
    owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    make(do_page())
    wait_card(owner)
    asking = owner.frame
    held: list = []
    owner.context.route(re.compile(r"/answers/copy"), lambda route: held.append(route))
    asking.locator("canvas-do .cmd button").click()
    for _ in range(100):
        if held:
            break
        owner.page.wait_for_timeout(50)
    assert held, "the copy was never asked for"
    make("<p>other</p>", name="beta")
    held[0].continue_()
    label = (
        "document.querySelector('canvas-do').shadowRoot.querySelector('.cmd button')"
    )
    asking.wait_for_function(f"{label}.textContent !== 'Copy'", polling=50)
