# ruff: noqa: F811  # the `link` fixture is imported from test_mch_01
"""Pooled pages on another machine's canvas, seen through this hub (POOL-12, #2).

Built on the fakes of ``test_mch_01``: a second hub in this process is the canvas of
machine ``rem``; the window is a cookie WebSocket on this hub.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from tests.conftest import HubHandle
from tests.integration.test_mch_01_machine_link import Link, Window, link  # noqa: F401

from agent_canvas.hub import comments

pytestmark = pytest.mark.integration

PAGE = "dash.html"
COMMENT = {
    "page": PAGE, "page_version": 1, "kind": "point", "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
    "target": {"canvas_id": None, "selector": "#fig", "text": None},
}  # fmt: skip
SEND = {
    "delivery": "next-message", "message": "", "page": PAGE,
    "viewport": {"width": 10, "height": 10, "scroll_x": 0, "scroll_y": 0},
    "screenshot": None, "screenshot_error": "none",
}  # fmt: skip


def on_remote(link: Link, session: str, route: str, body: dict) -> dict:
    """Call a session route of the remote hub with its key, as its agent does."""
    project = link.folder / "proj"
    project.mkdir(exist_ok=True)
    answer = httpx.post(
        f"{link.remote.base_url}/api/sessions/{session}/{route}",
        headers=link.remote.key_headers,
        json={"project": str(project), "agent": "claude", **body},
        timeout=15,
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def publish(link: Link, session: str, html: str) -> Path:
    """Write ``session``'s draft of the page on the remote and publish it."""
    found = on_remote(link, session, "path", {})
    pool = Path(found["folder"])
    (pool / f"dash.{found['tag']}.draft.html").write_text(html)
    on_remote(link, session, "show", {"name": "dash", "publish": True, "audit": False})
    return pool


def shared(link: Link) -> Path:
    """On the remote, A publishes the page and B shows it; return the pool."""
    pool = publish(link, "A", "<title>Dash</title><p>a1</p>")
    on_remote(link, "B", "show", {"name": PAGE, "audit": False})
    return pool


def owner(window: Window, hub: HubHandle) -> dict[str, str]:
    return {"Cookie": window.cookie, "Origin": hub.base_url}


def comment_and_send(window: Window, hub: HubHandle, card: str) -> str:
    """Comment in a remote card and send, through this hub; return the event id."""
    base = f"{hub.base_url}/api/sessions/{card}"
    made = httpx.post(f"{base}/comments", json=COMMENT, headers=owner(window, hub))
    assert made.status_code == 200, made.text
    sent = httpx.post(f"{base}/send", json=SEND, headers=owner(window, hub))
    assert sent.status_code == 200, sent.text
    return sent.json()["event"]["id"]


def picked_up(link: Link, session: str) -> list[str]:
    """What the prompt hook of a remote session picks up."""
    events = on_remote(link, session, "pending", {"via": "hook"})["events"]
    return [e["id"] for e in events]


def cards(tabs: dict) -> dict[str, dict]:
    return {t["id"]: t for t in tabs["sessions"]}


def lists_page(*sessions: str):  # noqa: ANN202
    return lambda m: (
        m["type"] == "tabs"
        and all(PAGE in cards(m).get(s, {}).get("pages", []) for s in sessions)
    )


def test_pool_12_on_a_remote_canvas_two_sessions_share_a_page_and_a_comment_reaches_its_card_session(  # noqa: E501
    link: Link, hub: HubHandle
) -> None:
    pool = shared(link)
    window = Window(hub)
    tabs = cards(window.wait(lists_page("A", "B")))
    assert tabs["A"]["machine"] == tabs["B"]["machine"] == "rem"
    assert tabs["A"]["pool"] == tabs["B"]["pool"] is not None
    assert tabs["A"]["base"] == tabs["B"]["base"]  # one page file for both cards
    link.remote.on_loop(lambda: link.remote.state.events.add_listener("B", "ask"))
    sent = comment_and_send(window, hub, "B")
    assert picked_up(link, "A") == []
    assert picked_up(link, "B") == [sent]
    (stored,) = comments.load(pool, PAGE)["comments"]
    assert stored["card"] == "B" and stored["sent"] is not None
    window.socket.close()


def test_pool_12_a_pinned_dashboard_shows_in_a_fresh_remote_sessions_card(
    link: Link, hub: HubHandle
) -> None:
    publish(link, "A", "<title>Dash</title><p>a1</p>")
    window = Window(hub)
    window.wait(lists_page("A"))
    pin = {"session": "A", "page": PAGE, "pin": True}  # the window's pin key
    pinned = httpx.post(
        f"{hub.base_url}/api/home/pages", json=pin, headers=owner(window, hub)
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["pinned"] is True
    on_remote(link, "C", "path", {})  # C has shown nothing
    fresh = cards(window.wait(lists_page("C")))["C"]
    assert fresh["pinned"] == [PAGE] and fresh["machine"] == "rem"
    assert fresh["pages"] == [PAGE]
    assert fresh["active_page"] == PAGE  # what the card's frame loads
    window.socket.close()


def test_pool_05_a_hook_only_session_on_a_canvas_without_herdr_panes_gets_its_cards_comment(  # noqa: E501
    link: Link, hub: HubHandle, tmp_path: Path
) -> None:
    shared(link)
    window = Window(hub)
    window.wait(lists_page("A", "B"))
    # B runs in Claude Code on the remote, which sees no Herdr pane and no watch.
    sessions, proc = tmp_path / "claude-sessions", tmp_path / "proc"
    sessions.mkdir()
    (proc / str(os.getpid())).mkdir(parents=True)
    (proc / str(os.getpid()) / "comm").write_text("claude\n")
    (sessions / f"{os.getpid()}.json").write_text(json.dumps({"sessionId": "B"}))
    herdr = link.remote.app.state.services.herdr_app
    herdr.sessions_dir, herdr.proc_dir = sessions, proc
    assert link.remote.on_loop(lambda: herdr.paired()) == set()
    sent = comment_and_send(window, hub, "B")
    assert picked_up(link, "A") == []  # A touched the page too, but it is B's comment
    assert picked_up(link, "B") == [sent]
    window.socket.close()
