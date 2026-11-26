"""A press anywhere in a card selects it, once, and still reaches the page."""

from __future__ import annotations

import copy

import pytest

from .support import call
from .test_hcw_01_herdr_window import pane, session

pytestmark = pytest.mark.browser

BUTTON = '<button id="b" onclick="parent.postMessage({probe: 1}, \'*\')">press</button>'


def test_press_in_card_selects_it_once_and_page_gets_click(owner, tmp_path) -> None:  # noqa: ANN001
    while not owner.hub.state.shells:
        owner.page.wait_for_timeout(25)
    a, b = session(owner, tmp_path, "alpha"), session(owner, tmp_path, "beta")
    (owner.hub.state.session_of(owner.hub.pool_of(b)).folder / "beta.html").write_text(
        BUTTON
    )
    tab = {
        "id": "tb1",
        "name": "rig",
        "active": True,
        "panes": [pane("t1", a, True), pane("t2", b, False)],
    }
    herdr = {
        "available": True,
        "focus": {"space": "sp1", "tab": "tb1", "pane": "pt1"},
        "spaces": [
            {
                "id": "sp1",
                "name": "lab",
                "color": "#22a99a",
                "active": True,
                "tabs": [tab],
            }
        ],
        "other": [],
    }
    sent: list[tuple[str, str]] = []
    app = owner.hub.app.state.services.herdr_app
    app.snapshot = lambda: copy.deepcopy(herdr)
    app.focus = lambda _snapshot, key, value: sent.append((key, value)) or True
    page = owner.page
    page.wait_for_function("(id) => activeId === id", arg=a)
    page.evaluate(
        "() => { window.__probes = 0; addEventListener('message', (e) => e.data?.probe && window.__probes++); }"
    )
    card_b = page.locator(f'.hv-card[data-session="{b}"]')
    card_b.locator("iframe").wait_for()
    page.frame_locator(f'.hv-card[data-session="{b}"] iframe').locator("#b").wait_for()

    # A press in the other card's page selects it and asks Herdr once.
    page.frame_locator(f'.hv-card[data-session="{b}"] iframe').locator("#b").click()
    page.wait_for_function("(id) => activeId === id", arg=b)
    page.wait_for_timeout(300)
    assert sent == [("terminal", "t2")]
    assert page.evaluate("() => window.__probes") == 1
    assert page.locator(f'.hv-card.focus[data-session="{b}"]').count() == 1

    # Presses in the selected card send nothing more.
    page.locator(
        f'.hv-card[data-session="{b}"] .hv-ptabs, .hv-card.focus .hv-chead'
    ).first.click()
    page.locator("#frame").click(position={"x": 5, "y": 5}, force=True)
    page.wait_for_timeout(300)
    assert sent == [("terminal", "t2")]

    herdr["focus"]["pane"] = "pt2"
    page.wait_for_timeout(1500)

    # A press in the other card's strip or header selects it by the same rule.
    page.locator(f'.hv-card[data-session="{a}"] .hv-ptabs').click(
        position={"x": 2, "y": 2}, force=True
    )
    page.wait_for_function("(id) => activeId === id", arg=a)
    page.wait_for_timeout(300)
    assert sent == [("terminal", "t2"), ("terminal", "t1")]
