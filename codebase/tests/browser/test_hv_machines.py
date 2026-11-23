"""Machine groups in the Herdr-style sidebar (static/herdr-view.js, herdr-canvas package T)."""

# ruff: noqa: E501  (page-side scripts are long single lines)
from __future__ import annotations

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src/agent_canvas/static"

pytestmark = pytest.mark.browser

DEMO = (STATIC / "herdr-demo.html").as_uri()
TEXTS = "(sel) => [...document.querySelectorAll(sel)].map((e) => e.textContent.trim())"
CALLS = "() => window.calls"
SHOT = "/tmp/claude-scratch/t"

# One remote machine "devbox": one space with one agent card, one session outside Herdr.
REMOTE = """
(state) => {
  HERDR.spaces.push({ id: 'devbox/sp1', machine: 'devbox', name: 'sim', color: '#5b8def', active: false,
    tabs: [{ id: 'devbox/tb1', name: 'run', active: true, panes: [pane('rt1', 'Claude Code', 'working', 's-remote', true)] }] });
  HERDR.spaces.forEach((s) => { s.machine = s.machine ?? null; });
  SESSIONS.push({ id: 's-remote', title: 'Sim', state: 'active', pages: ['run.html'], active_page: 'run.html', machine: 'devbox', project: 'p', agent: 'claude-code' });
  SESSIONS.push({ id: 's-rx', title: 'Remote extra', state: 'active', pages: ['x.html'], active_page: 'x.html', machine: 'devbox', project: 'p', agent: 'claude-code' });
  HERDR.machines = [{ name: 'devbox', state: state.state, detail: state.detail, other: ['s-rx'] }];
  window.view.update(HERDR, SESSIONS);
}
"""
OFFLINE = {
    "state": "offline",
    "detail": "devbox cannot be reached; showing what Herdr knows.",
}
ONLINE = {"state": "online", "detail": None}
SET_STATE = "(s) => { HERDR.machines[0].state = s.state; HERDR.machines[0].detail = s.detail; window.view.update(HERDR, SESSIONS); }"


@pytest.fixture
def demo(page):  # noqa: ANN001, ANN201
    """Load the demo page."""
    page.goto(DEMO)
    page.wait_for_selector(".hv-card")
    return page


def test_hvm_01_without_machines_the_sidebar_has_no_headings(demo) -> None:  # noqa: ANN001
    """No `machines`: no heading, the rows are as before."""
    assert demo.locator(".hv-mhead").count() == 0
    assert demo.evaluate(TEXTS, ".hv-row .hv-name") == [
        "data",
        "6D-sensors",
        "Not in Herdr",
    ]


def test_hvm_02_spaces_are_grouped_under_machine_headings(demo) -> None:  # noqa: ANN001
    """This computer first, then the machines; each group has its spaces and its Not in Herdr row."""
    demo.evaluate(REMOTE, ONLINE)
    assert demo.evaluate(
        "() => [...document.querySelectorAll('.hv-rows > *')].map((e) => e.classList.contains('hv-mhead') ? '#' + e.textContent.trim().slice(0, 20) : e.querySelector('.hv-name').textContent)"
    ) == [
        "#This computer",
        "data",
        "6D-sensors",
        "Not in Herdr",
        "#devbox",
        "sim",
        "Not in Herdr",
    ]
    assert demo.locator(".hv-mnote").count() == 0
    demo.screenshot(path=f"{SHOT}/grouped-online.png")


def test_hvm_03_offline_machine_shows_its_detail_and_a_note_instead_of_frames(
    demo,
) -> None:  # noqa: ANN001
    """The detail sits under the heading, the spaces stay, the card says why it has no frame."""
    demo.evaluate(REMOTE, ONLINE)
    demo.click("text=sim")
    assert demo.locator(".hv-card .hv-frame").count() == 1
    demo.evaluate(SET_STATE, OFFLINE)
    assert demo.evaluate(TEXTS, ".hv-mnote") == [OFFLINE["detail"]]
    assert demo.evaluate(TEXTS, ".hv-mstate") == ["offline"]
    assert "sim" in demo.evaluate(TEXTS, ".hv-row .hv-name")
    assert demo.locator(".hv-card .hv-frame").count() == 0
    assert demo.evaluate(TEXTS, ".hv-card .hv-none") == [OFFLINE["detail"]]
    demo.screenshot(path=f"{SHOT}/grouped-offline.png")
    demo.evaluate(SET_STATE, {"state": "offline", "detail": None})
    assert demo.evaluate(TEXTS, ".hv-card .hv-none") == ["devbox is offline"]


def test_hvm_04_remote_sessions_not_in_herdr_sit_in_their_machines_group(demo) -> None:  # noqa: ANN001
    """The remote Not in Herdr row lists only that machine's sessions."""
    demo.evaluate(REMOTE, ONLINE)
    demo.locator(".hv-mhead ~ .hv-row:has-text('Not in Herdr')").last.click()
    assert demo.evaluate(TEXTS, ".hv-pill") == ["Remote extra"]
    assert demo.evaluate(CALLS)[-1] == ["other", "s-rx"]
    demo.locator(".hv-row:has-text('Not in Herdr')").first.click()
    assert demo.evaluate(TEXTS, ".hv-pill") == ["Readings 2026", "Misc"]


def test_hvm_05_coming_back_online_reports_the_machines_sessions(demo) -> None:  # noqa: ANN001
    """onMachineOnline fires once on offline -> online, not on the first update or while online."""
    demo.evaluate("() => { window.back = []; window.view.destroy(); }")
    demo.goto(DEMO)
    demo.evaluate(
        """() => {
          window.back = [];
          window.view = HerdrView.mount(document.getElementById('root'), { onMachineOnline: (m, ids) => window.back.push([m, ids]) });
        }"""
    )
    demo.evaluate(REMOTE, OFFLINE)
    assert demo.evaluate("() => window.back") == []
    demo.evaluate(SET_STATE, ONLINE)
    assert demo.evaluate("() => window.back") == [["devbox", ["s-remote", "s-rx"]]]
    demo.evaluate(SET_STATE, ONLINE)
    assert len(demo.evaluate("() => window.back")) == 1


def test_hvm_06_space_keys_cross_groups_and_fold_key_hides_a_group(demo) -> None:  # noqa: ANN001
    """goSpace walks the sidebar order over group borders; foldMachine folds the shown space's group."""
    demo.evaluate(REMOTE, ONLINE)
    demo.evaluate("() => window.view.goSpace(1)")  # 6D-sensors -> its Not in Herdr row
    assert demo.evaluate(TEXTS, ".hv-row.on .hv-name") == ["Not in Herdr"]
    demo.evaluate("() => window.view.goSpace(1)")  # -> sim (devbox)
    assert demo.evaluate(TEXTS, ".hv-row.on .hv-name") == ["sim"]
    assert demo.evaluate(CALLS)[-1] == ["space", "devbox/sp1"]
    demo.evaluate("() => window.view.goSpace(1)")
    demo.evaluate("() => window.view.goSpace(1)")  # wraps to data
    assert demo.evaluate(TEXTS, ".hv-row.on .hv-name") == ["data"]
    demo.evaluate("() => window.view.goSpace(0, 4)")
    demo.evaluate("() => window.view.foldMachine()")
    assert demo.evaluate(TEXTS, ".hv-row .hv-name") == [
        "data",
        "6D-sensors",
        "Not in Herdr",
    ]
    demo.evaluate(
        "() => window.view.goSpace(-1)"
    )  # moving into a folded group opens it
    demo.evaluate("() => window.view.goSpace(1)")
    assert demo.evaluate(TEXTS, ".hv-row .hv-name") == [
        "data",
        "6D-sensors",
        "Not in Herdr",
        "sim",
        "Not in Herdr",
    ]


def test_hvm_07_a_click_on_the_heading_folds_its_group(demo) -> None:  # noqa: ANN001
    """Folding by click keeps the heading and hides the group's rows."""
    demo.evaluate(REMOTE, ONLINE)
    demo.click(".hv-mhead[data-machine='devbox']")
    assert demo.evaluate(TEXTS, ".hv-row .hv-name") == [
        "data",
        "6D-sensors",
        "Not in Herdr",
    ]
    demo.click(".hv-mhead[data-machine='devbox']")
    assert "sim" in demo.evaluate(TEXTS, ".hv-row .hv-name")
