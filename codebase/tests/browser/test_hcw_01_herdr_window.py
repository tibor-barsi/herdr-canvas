"""The window follows Herdr and Herdr follows the window (herdr-canvas C2)."""

from __future__ import annotations

import copy

import pytest

from .support import call

pytestmark = pytest.mark.browser

ACTIVE = "() => activeId"


def session(owner, tmp_path, name: str) -> str:  # noqa: ANN001
    """Create a session that shows one page."""
    directory = tmp_path / name
    directory.mkdir()
    body = {"project": str(directory), "agent": "claude", "title": name}
    sid = call(owner, "POST", "/api/sessions", json=body)["session"]
    (
        owner.hub.state.session_of(owner.hub.pool_of(sid)).folder / f"{name}.html"
    ).write_text(f"<p>{name}</p>")
    show = {"project": str(directory), "name": f"{name}.html"}
    call(owner, "POST", f"/api/sessions/{sid}/show", json=show)
    return sid


def pane(terminal: str, sid: str | None, focused: bool) -> dict:
    """One Herdr pane as the hub reports it."""
    return {
        "pane": "p" + terminal,
        "terminal": terminal,
        "name": terminal,
        "status": "idle",
        "app": "claude-code" if sid else None,
        "focused": focused,
        "session": sid,
    }


def test_hcw_01_cards_and_focus_follow_herdr_both_ways(owner, tmp_path) -> None:  # noqa: ANN001
    while not owner.hub.state.shells:
        owner.page.wait_for_timeout(25)
    a, b = session(owner, tmp_path, "alpha"), session(owner, tmp_path, "beta")
    herdr = {
        "available": True,
        "focus": {"space": "sp1", "tab": "tb1", "pane": "pt1"},
        "spaces": [
            {
                "id": "sp1",
                "name": "lab",
                "color": "#22a99a",
                "active": True,
                "tabs": [
                    {
                        "id": "tb1",
                        "name": "rig",
                        "active": True,
                        "panes": [pane("t1", a, True), pane("t2", b, False)],
                    },
                    {
                        "id": "tb2",
                        "name": "shell",
                        "active": False,
                        "panes": [pane("t3", None, True)],
                    },
                ],
            }
        ],
        "other": [],
    }
    sent: list[tuple[str, str]] = []
    app = owner.hub.app.state.services.herdr_app
    app.snapshot = lambda: copy.deepcopy(herdr)
    app.focus = lambda _snapshot, key, value: sent.append((key, value)) or True
    page = owner.page

    # The hub's poll sends the herdr view: one space, two cards, the focused one shown.
    page.wait_for_selector(".hv-row .hv-name >> text=lab")
    page.wait_for_function("(id) => activeId === id", arg=a)
    # Each project's pool holds a page, no pane holds it: "Not in Herdr" (A-1144).
    assert page.locator(".hv-row .hv-name").all_inner_texts() == ["lab", "Not in Herdr"]
    assert page.locator(".hv-card").count() == 2
    assert page.locator(f'.hv-card[data-session="{b}"] .hv-frame iframe').count() == 1
    assert page.locator(f'.hv-card[data-session="{a}"] .hv-frame iframe').count() == 0
    assert "alpha.html" in page.locator("#frame").get_attribute("src")

    # A click on the other card's header shows it at once and asks Herdr to follow.
    page.locator(f'.hv-card[data-session="{b}"] .hv-chead').click()
    assert page.evaluate(ACTIVE) == b
    page.wait_for_function("(id) => activeId === id", arg=b)
    assert "beta.html" in page.locator("#frame").get_attribute("src")
    for _ in range(100):
        if sent:
            break
        page.wait_for_timeout(25)
    assert sent == [("terminal", "t2")]

    # Herdr reports the focus it was asked for, then moves it back by itself: the
    # window follows and sends nothing back.
    herdr["focus"]["pane"] = "pt2"
    page.wait_for_timeout(1500)
    assert page.evaluate(ACTIVE) == b
    herdr["focus"]["pane"] = "pt1"
    page.wait_for_function("(id) => activeId === id", arg=a, timeout=5000)
    assert page.locator(f'.hv-card.focus[data-session="{a}"]').count() == 1
    page.wait_for_timeout(1500)
    assert sent == [("terminal", "t2")]

    # A tab pill asks Herdr to show that tab.
    page.locator(".hv-pill", has_text="shell").click()
    for _ in range(100):
        if len(sent) > 1:
            break
        page.wait_for_timeout(25)
    assert sent[1:] == [("tab", "tb2")]
