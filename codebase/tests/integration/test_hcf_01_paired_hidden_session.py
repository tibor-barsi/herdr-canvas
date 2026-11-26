"""A session closed in the daily hub still shows in the Herdr pane that holds it."""

from __future__ import annotations

import queue
import time

import httpx
import pytest
from test_page_watching import FakeShell, new_session, post_show

pytestmark = pytest.mark.integration


def snapshot(session: str | None) -> dict:
    """A Herdr view with one pane holding ``session``."""
    pane = {
        "pane": "p1",
        "terminal": "t2",
        "name": "claude",
        "status": "idle",
        "app": "claude-code",
        "focused": True,
        "session": session,
    }
    tab = {"id": "tb1", "name": "1", "active": True, "panes": [pane]}
    space = {"id": "sp1", "name": "data", "color": "#e3814f", "active": True}
    return {
        "available": True,
        "focus": {"space": "sp1", "tab": "tb1", "pane": "p1"},
        "spaces": [{**space, "tabs": [tab]}],
        "other": [],
    }


def next_tabs(shell: FakeShell, wait: float = 5) -> list[str]:
    """Return the session ids of the next ``tabs`` message, the pool's tab left out."""
    deadline = time.monotonic() + wait
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = shell.messages.get(timeout=left)
        except queue.Empty:
            break
        if message["type"] == "tabs":
            return [t["id"] for t in message["sessions"] if t["agent"] != "project"]
    raise AssertionError("no tabs message")


def test_hcf_01_a_hidden_session_in_a_pane_gets_its_tab(hub, home) -> None:  # noqa: ANN001
    sid, folder = new_session(hub, home)
    (folder / "page.html").write_text("<p>x</p>")
    post_show(hub, sid, home / "proj")
    hidden = httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/hide", headers=hub.key_headers, json={}
    )
    assert hidden.status_code == 200
    shell = FakeShell(hub)
    try:
        assert next_tabs(shell) == []
        herdr = hub.app.state.services.herdr_app
        herdr.snapshot = lambda: snapshot(sid)
        assert next_tabs(shell) == [sid]
        [card] = [t for t in hub.state.tabs_message()["sessions"] if t["id"] == sid]
        assert card["pages"] == ["page.html"]
        herdr.snapshot = lambda: snapshot(None)
        assert next_tabs(shell) == []
    finally:
        shell.close()
