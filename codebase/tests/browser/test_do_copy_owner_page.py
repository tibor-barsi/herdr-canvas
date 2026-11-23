# ruff: noqa: E501, F811
"""Copy on the owner's checks page, and why a refused Copy failed (DO-02, SEC-09).

Fixture: ``tests/fixtures/copy/owner-checks.html``, version 4 of the page on which
the owner's Copy of the Do ``kinds-setup`` showed nothing in the real window
(2026-11-11, A-440).
"""

from __future__ import annotations

import pytest

from agent_canvas.hub.answers import scan
from helpers import CODEBASE_DIR

from .test_do_card import card, clipboard, copy_requests, made  # noqa: F401

pytestmark = pytest.mark.browser

PAGE = (CODEBASE_DIR / "tests" / "fixtures" / "copy" / "owner-checks.html").read_text()
ITEMS = scan(PAGE).items
LAST_DO = [i for i in ITEMS.values() if i.kind == "do"][-1].id


def copied(owner) -> str:  # noqa: ANN001
    owner.page.wait_for_selector("#copied.visible", timeout=10000)
    return owner.page.inner_text("#copied")


@pytest.mark.parametrize(
    ("card_id", "height"),
    [("kinds-setup", 1080), ("kinds-setup", 600), (LAST_DO, 1080)],
)
def test_do_02_copy_on_the_owner_checks_page_puts_the_whole_run_on_the_clipboard(
    owner, make, card_id, height
) -> None:  # noqa: ANN001
    owner.page.set_viewport_size({"width": 1920, "height": height})
    owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    owner.page.evaluate("navigator.clipboard.writeText('before')")
    make(PAGE)
    selector = f"[data-canvas-id={card_id}]"
    owner.frame.wait_for_function(
        "(s) => { const e = document.querySelector(s);"
        " return e && e.renderIdle && e.shadowRoot.querySelector('.cmd button'); }",
        arg=selector,
    )
    button = owner.frame.locator(f"{selector} .cmd button >> nth=0")
    button.scroll_into_view_if_needed()
    box = button.bounding_box()
    owner.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    run = ITEMS[card_id].step_runs[0]
    assert copied(owner).startswith(f"Copied: {run.splitlines()[0][:40]}")
    assert clipboard(owner) == run


def test_do_02_a_copy_the_hub_refuses_says_why(owner, made) -> None:  # noqa: ANN001
    owner.page.evaluate(
        "(m) => privateMessage(m)", {"type": "copy", "id": "w1", "step": 1}
    )
    assert copied(owner) == "Copy failed: That step has no command to copy."


def test_do_02_a_copy_long_after_the_last_click_says_why(owner, made) -> None:  # noqa: ANN001
    owner.page.evaluate(
        "setTimeout(() => privateMessage({type: 'copy', id: 'w1', step: 2}), 6000)"
    )
    owner.page.wait_for_timeout(6800)  # waiting for a selector would count as a click
    assert copied(owner) == (
        "Copy failed: the browser did not count it as your click; press Copy again."
    )
    assert copy_requests(owner) == []


def test_do_02_a_copy_a_page_script_asks_for_shows_nothing(owner, made) -> None:  # noqa: ANN001
    owner.frame.evaluate(
        "window.agentCanvas.copy(document.querySelector('canvas-do'), 2)"
    )
    owner.frame.evaluate("parent.postMessage({type: 'copy', id: 'w1', step: 2}, '*')")
    owner.page.wait_for_timeout(800)
    assert owner.page.locator("#copied.visible").count() == 0
    assert copy_requests(owner) == []


def test_do_02_a_click_on_a_copy_button_that_is_not_shown_says_why_in_the_console(
    owner, made
) -> None:  # noqa: ANN001
    messages: list[str] = []
    owner.page.on("console", lambda message: messages.append(message.text))
    owner.frame.evaluate(
        "document.querySelector('canvas-do').shadowRoot.querySelector('.cmd button')"
        ".style.opacity = '0'"
    )
    card(owner, ".cmd button").click()
    owner.page.wait_for_timeout(500)
    assert "agent-canvas: Copy refused: the button is not shown." in messages
    assert copy_requests(owner) == []


def test_do_02_copy_works_on_the_same_page_after_the_hub_restarted(owner, made) -> None:  # noqa: ANN001
    messages: list[str] = []
    owner.page.on("console", lambda message: messages.append(message.text))
    owner.hub.restart()
    owner.page.wait_for_selector("#offline.visible", state="hidden", timeout=15000)
    card(owner, ".cmd button").click()
    assert copied(owner) == "Copied: uv run check\u2026"
    assert clipboard(owner) == "uv run check\n--port 1"
    assert [m for m in messages if "Copy refused" in m] == []


def test_do_02_the_copy_button_itself_says_copied_and_then_copy_again(
    owner, made
) -> None:  # noqa: ANN001
    button = card(owner, ".cmd button")
    button.click()
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-do').shadowRoot"
        ".querySelector('.cmd button').textContent === 'Copied'"
    )
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-do').shadowRoot"
        ".querySelector('.cmd button').textContent === 'Copy'"
    )
