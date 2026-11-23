"""The Herdr-style window parts (static/herdr-view.js) on their fixture page."""

# ruff: noqa: E501  (page-side scripts are long single lines)
from __future__ import annotations

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src/agent_canvas/static"

pytestmark = pytest.mark.browser

DEMO = (STATIC / "herdr-demo.html").as_uri()
TEXTS = "(sel) => [...document.querySelectorAll(sel)].map((e) => e.textContent.trim())"
CALLS = "() => window.calls"


@pytest.fixture
def demo(page):  # noqa: ANN001, ANN201
    """Load the demo page."""
    page.goto(DEMO)
    page.wait_for_selector(".hv-card")
    return page


def test_hv_01_sidebar_in_herdr_order_with_colours_and_counts(demo) -> None:  # noqa: ANN001
    """Spaces keep Herdr's order, tiles carry the space colour, counts are pages."""
    assert demo.evaluate(TEXTS, ".hv-row .hv-name") == [
        "data",
        "6D-sensors",
        "Not in Herdr",
    ]
    assert demo.evaluate(TEXTS, ".hv-row .hv-tile") == ["D", "6", "?"]
    colour = demo.evaluate(
        "() => getComputedStyle(document.querySelector('.hv-tile')).backgroundColor"
    )
    assert colour == "rgb(227, 129, 79)"
    # 6D-sensors: rig 2 + fem 1 pages in the active tab, cal 1 + log 2 in the other = 6
    assert demo.evaluate(TEXTS, ".hv-row .hv-cnt") == ["6", "2"]
    assert demo.evaluate(TEXTS, ".hv-row.on .hv-name") == ["6D-sensors"]


def test_hv_02_tab_pills_and_cards_of_the_focused_tab(demo) -> None:  # noqa: ANN001
    """The active space's tabs are pills; the active tab has one card per pane."""
    assert demo.evaluate(TEXTS, ".hv-pill") == ["test rig", "calibration"]
    assert demo.locator(".hv-card").count() == 2
    assert demo.evaluate(TEXTS, ".hv-chead") == ["Claude Code", "Claude"]
    assert demo.evaluate(TEXTS, ".hv-card:first-child .hv-pt") == [
        "rig-concept",
        "shaker",
    ]
    widths = demo.evaluate(
        "() => [...document.querySelectorAll('.hv-card')].map((c) => c.offsetWidth)"
    )
    assert abs(widths[0] - widths[1]) <= 1


def test_hv_03_focus_border_on_the_focused_pane(demo) -> None:  # noqa: ANN001
    """Only the card of the focused pane has the focus border."""
    assert demo.evaluate(
        "() => [...document.querySelectorAll('.hv-card')].map((c) => c.classList.contains('focus'))"
    ) == [False, True]
    border = demo.evaluate(
        "() => getComputedStyle(document.querySelector('.hv-card.focus')).borderTopColor"
    )
    assert border == "rgb(167, 180, 198)"


def test_hv_04_callbacks_fire_and_switch_the_view(demo) -> None:  # noqa: ANN001
    """Clicks call the host and the view follows (three panes, one without canvas)."""
    demo.click(".hv-pill:nth-child(2)")
    assert demo.locator(".hv-card").count() == 3
    assert demo.evaluate(TEXTS, ".hv-none") == ["no canvas"]
    demo.click(".hv-card:nth-child(3) .hv-chead")
    assert demo.evaluate(
        "() => [...document.querySelectorAll('.hv-card')].map((c) => c.classList.contains('focus'))"
    ) == [False, False, True]
    demo.click(".hv-card:nth-child(3) .hv-pt:nth-child(2)")
    assert demo.evaluate(TEXTS, ".hv-card:nth-child(3) .hv-pt.on") == ["notes"]
    demo.click(".hv-row:nth-child(1)")
    demo.click(".hv-row:nth-child(3)")
    assert demo.evaluate(TEXTS, ".hv-pill") == ["Readings 2026", "Misc"]
    demo.click(".hv-pill:nth-child(2)")
    assert demo.evaluate(CALLS) == [
        ["tab", "tb3"],
        ["pane", "t6"],
        ["page", "s-log", "notes.html"],
        ["space", "sp1"],
        ["other", "s-x1"],
        ["other", "s-x2"],
    ]


def test_hv_05_frame_slot_survives_an_update(demo) -> None:  # noqa: ANN001
    """The card keeps its frame element when the data is sent again."""
    same = demo.evaluate(
        """() => {
          const slot = document.querySelector('.hv-frame');
          slot.dataset.mark = 'kept';
          window.view.update(HERDR, SESSIONS);
          return document.querySelector('.hv-frame').dataset.mark;
        }"""
    )
    assert same == "kept"


def test_hv_06_the_fold_icon_folds_the_sidebar(demo) -> None:  # noqa: ANN001
    """The sidebar folds to a rail and back (its key is in the shell's key map)."""
    wide = demo.evaluate("() => document.querySelector('.hv-side').offsetWidth")
    demo.locator(".hv-fold").click()
    rail = demo.evaluate("() => document.querySelector('.hv-side').offsetWidth")
    assert (wide, rail) == (240, 52)
    demo.locator(".hv-fold").click()
    assert demo.evaluate("() => document.querySelector('.hv-side').offsetWidth") == 240


RECTS = "() => [...document.querySelectorAll('.hv-card')].map((c) => { const r = c.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round); })"


def test_hv_07_cards_follow_the_split_tree(demo) -> None:  # noqa: ANN001
    """One pane left, two stacked right, as in Herdr; a tab without a tree is one row."""
    demo.click(".hv-pill:nth-child(2)")
    (lx, ly, lw, lh), (rx, ry, rw, rh), (bx, by, bw, bh) = demo.evaluate(RECTS)
    assert lx < rx and rx == bx and abs(lw - rw) <= 2
    assert ry < by and abs(rh - bh) <= 2 and abs(lh - (by + bh - ry)) <= 2
    demo.screenshot(path="/tmp/claude-scratch/i-split/split.png")
    demo.click(".hv-pill:nth-child(1)")
    (ax, ay, aw, ah), (bx, by, bw, bh) = demo.evaluate(RECTS)
    assert ay == by and ah == bh and bx > ax
    demo.evaluate("() => { delete HERDR.spaces[1].tabs[1].tree; window.view.update(HERDR, SESSIONS); }")
    demo.click(".hv-pill:nth-child(2)")
    rects = demo.evaluate(RECTS)
    assert len({r[1] for r in rects}) == 1 and len({r[3] for r in rects}) == 1
    assert [r[0] for r in rects] == sorted(r[0] for r in rects)


def _shell_panes(page, ids: str) -> None:  # noqa: ANN001
    """Turn the panes with these ids into plain shells and send the data again."""
    page.evaluate(
        "(ids) => { for (const t of HERDR.spaces[1].tabs) for (const p of t.panes) if (ids.includes(p.terminal)) { p.app = null; p.session = null; } window.view.update(HERDR, SESSIONS); }",
        ids,
    )


def test_hv_08_shell_pane_gets_no_card_and_siblings_share_by_weight(demo) -> None:  # noqa: ANN001
    """A shell pane in a split is dropped; the agent cards fill the area by their weights."""
    demo.evaluate(
        "() => { const t = HERDR.spaces[1].tabs[1]; t.tree.children[0].weight = 1; t.tree.children[1].weight = 3; }"
    )
    _shell_panes(demo, ["t5"])
    demo.click(".hv-pill:nth-child(2)")
    assert demo.evaluate(TEXTS, ".hv-card .hv-chead") == ["claude", "claude"]
    (lx, ly, lw, lh), (rx, ry, rw, rh) = demo.evaluate(RECTS)
    assert ly == ry and lh == rh and lh > 300
    assert abs((rw + 6) - 3 * (lw + 6)) <= 3
    area = demo.evaluate("() => document.querySelector('.hv-cards').getBoundingClientRect().height")
    assert abs(lh - (area - 14)) <= 3
    assert demo.locator(".hv-empty").count() == 0
    demo.screenshot(path="/tmp/claude-scratch/k-panes/agent-split.png")


def test_hv_09_tab_with_only_shells_shows_one_quiet_line(demo) -> None:  # noqa: ANN001
    """All tabs stay in the bar; a tab without agent panes says so instead of showing cards."""
    _shell_panes(demo, ["t4", "t5", "t6"])
    demo.click(".hv-pill:nth-child(2)")
    assert demo.evaluate(TEXTS, ".hv-pill") == ["test rig", "calibration"]
    assert demo.locator(".hv-card").count() == 0
    assert demo.evaluate(TEXTS, ".hv-empty") == ["No agent sessions in this tab"]
    demo.screenshot(path="/tmp/claude-scratch/k-panes/no-agents.png")
    demo.click(".hv-pill:nth-child(1)")
    assert demo.locator(".hv-empty").count() == 0
    assert demo.locator(".hv-card").count() == 2


def test_hv_10_focus_on_a_shell_pane_selects_no_card(demo) -> None:  # noqa: ANN001
    """Herdr focus on a shell pane shows its tab with no card selected and sends nothing back."""
    _shell_panes(demo, ["t5"])
    demo.evaluate(
        "() => { const t = HERDR.spaces[1].tabs[1]; t.panes.forEach((p) => (p.focused = p.terminal === 't5'));"
        " HERDR.focus = { space: 'sp2', tab: 'tb3', pane: 'pnt5' }; window.view.update(HERDR, SESSIONS); }"
    )
    assert demo.evaluate(TEXTS, ".hv-pill.on") == ["calibration"]
    assert demo.locator(".hv-card").count() == 2
    assert demo.locator(".hv-card.focus").count() == 0
    assert demo.evaluate(CALLS) == []
