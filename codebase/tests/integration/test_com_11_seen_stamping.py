"""A comment is seen when its event is delivered or listed with the key (COM-11).

One test per delivery path of the CLI and the hook; the MCP paths are in
``test_mcp_server.py``, the other ``via`` values in ``tests/unit``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import comments
from shellfake import FakeShell

pytestmark = pytest.mark.integration

SESSION = "38fefe65-3f6a-4b5c-9d0e-0123456789ab"

COMMENT = {
    "page": "page.html", "page_version": 1, "kind": "point", "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
    "target": {"canvas_id": None, "selector": "#fig", "text": None},
    "picture": base64.b64encode(b"\x89PNG\r\n\x1a\nx").decode(),
}  # fmt: skip
SEND = {
    "delivery": "now", "message": "", "page": "page.html",
    "viewport": {"width": 10, "height": 10, "scroll_x": 0, "scroll_y": 0},
    "screenshot": None, "screenshot_error": "none",
}  # fmt: skip


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    client = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    client.get(hub.login_url(), follow_redirects=False)
    return client


def sent_comment(hub, owner, session: str, folder: Path) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    assert (
        owner.post(f"/api/sessions/{session}/comments", json=COMMENT).status_code == 200
    )
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{session}/send",
        headers=hub.key_headers,
        json=SEND,
    )
    assert answer.status_code == 200, answer.text
    assert status(folder) == "sent"


def status(folder: Path) -> str:
    [record] = comments.load(folder, "page.html")["comments"]
    return comments.status(record)


@pytest.fixture
def sent(cli, hub, owner) -> dict:  # noqa: ANN001
    started = cli("session", "start").json
    folder = Path(started["folder"])
    sent_comment(hub, owner, started["session"], folder)
    return {"id": started["session"], "folder": folder}


def test_com_11_watch_delivery_stamps_the_comment_seen(cli, sent) -> None:  # noqa: ANN001
    result = cli("watch", "--count", "1", "--timeout", "20", "--session", sent["id"])
    assert json.loads(result.out.splitlines()[0])["comments"][0]["text"] == "units?"
    assert status(sent["folder"]) == "seen"


def test_com_11_pending_delivery_stamps_the_comment_seen(cli, sent) -> None:  # noqa: ANN001
    assert cli("pending", "--session", sent["id"]).code == 0
    assert status(sent["folder"]) == "seen"


def test_com_11_pending_peek_leaves_the_comment_sent(cli, sent) -> None:  # noqa: ANN001
    assert cli("pending", "--peek", "--session", sent["id"]).code == 0
    assert status(sent["folder"]) == "sent"
    cli("pending", "--session", sent["id"])
    assert status(sent["folder"]) == "seen"


def test_com_11_the_hook_delivery_stamps_the_comment_seen(cli, hub, owner) -> None:  # noqa: ANN001
    def hook(name: str, **more: str) -> str:
        data = {"session_id": SESSION, "cwd": str(cli.cwd), "prompt": "go", **more}
        return cli("hook", name, input=json.dumps(data)).out

    hook("session-start", source="startup")
    cli("session", "path", extra_env={"AGENT_CANVAS_SESSION": SESSION})
    folder = cli.cwd / ".agent-canvas" / SESSION
    sent_comment(hub, owner, SESSION, folder)
    text = json.loads(hook("user-prompt-submit"))["hookSpecificOutput"][
        "additionalContext"
    ]
    assert 'comment #1 point on #fig: "units?"' in text
    assert status(folder) == "seen"


def test_com_11_listing_with_the_key_stamps_and_the_owner_stamps_nothing(
    hub, owner, sent
) -> None:  # noqa: ANN001
    url = f"/api/sessions/{sent['id']}/comments?page=page.html"
    assert owner.get(url).status_code == 200
    assert status(sent["folder"]) == "sent"
    listed = httpx.get(hub.base_url + url, headers=hub.key_headers)
    assert listed.json()["comments"][0]["text"] == "units?"
    assert status(sent["folder"]) == "seen"


def test_com_11_the_window_hears_that_the_comment_was_seen(cli, hub, sent) -> None:  # noqa: ANN001
    shell = FakeShell(hub)
    try:
        shell.messages.clear()
        cli("pending", "--session", sent["id"])
        hub.wait_for(
            lambda: any(
                m["type"] == "comments"
                and [c["status"] for c in m["comments"]] == ["seen"]
                for m in shell.messages
            )
        )
    finally:
        shell.close()
