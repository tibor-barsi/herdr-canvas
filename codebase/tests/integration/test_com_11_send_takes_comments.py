"""A send hands over the page's draft comments from the store.

(COM-10, COM-11, RPL-07)
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hooks import _event_lines
from agent_canvas.hub import comments
from shellfake import FakeShell

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"comment-picture"
COMMENT = {
    "page": "page.html",
    "page_version": 1,
    "kind": "rect",
    "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "w": 30, "h": 40},
    "target": {"canvas_id": None, "selector": "#fig", "text": "Fig"},
    "text_inside": "Figure 1",
    "picture": base64.b64encode(PNG).decode(),
}
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


@pytest.fixture
def shown(cli, hub) -> dict:  # noqa: ANN001
    started = cli("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<p>published</p>")
    assert cli("show", "page.html", "--session", started["session"]).code == 0
    time.sleep(0.6)
    return {"id": started["session"], "folder": folder}


def save(owner, shown, **changes):  # noqa: ANN001, ANN201
    return owner.post(
        f"/api/sessions/{shown['id']}/comments", json={**COMMENT, **changes}
    )


def post_send(hub, shown, **changes):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/{shown['id']}/send",
        headers=hub.key_headers,
        json={**SEND, **changes},
    )


def test_com_11_the_event_carries_the_stored_text_not_the_requested_one(
    hub, owner, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    forged = [{"n": 1, "kind": "text", "text": "FORGED", "picture": "/etc/passwd"}]
    answer = post_send(hub, shown, comments=forged)
    assert answer.status_code == 200, answer.text
    [comment] = answer.json()["event"]["comments"]
    assert comment["text"] == "units?" and comment["kind"] == "rect"
    assert comment["status"] == "sent" and comment["n"] == 1
    assert comment["anchor"]["w"] == 30 and comment["text_inside"] == "Figure 1"
    assert comment["target"]["selector"] == "#fig"
    for hidden in ("seen", "read", "anchored_version"):
        assert hidden not in comment


def test_com_11_the_picture_is_copied_beside_the_send_and_equals_the_comments(
    hub, owner, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    event = post_send(hub, shown).json()["event"]
    [comment] = event["comments"]
    copy = shown["folder"] / "history" / "sends" / "0001.c1.png"
    assert comment["picture"] == str(copy.resolve())
    assert copy.read_bytes() == PNG
    assert (shown["folder"] / ".comments" / "page.html.1.png").read_bytes() == PNG
    record = json.loads((copy.with_name("0001.json")).read_text())
    assert record["comments"][0]["picture"] == str(copy.resolve())
    assert record["send_id"].startswith("snd_") and record["part"] == [1, 1]
    assert event["part"] == [1, 1]


def test_com_11_the_drafts_become_sent_and_a_second_send_has_none(
    hub, owner, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    save(owner, shown, text="second")
    first = post_send(hub, shown, delivery="next-message").json()["event"]
    assert [c["n"] for c in first["comments"]] == [1, 2]
    stored = json.loads((shown["folder"] / ".comments" / "page.html.json").read_text())
    for record in stored["comments"]:
        assert record["sent"] and record["delivery"] == "next-message"
        assert record["send_event"] == first["id"]
    again = post_send(hub, shown, message="more").json()["event"]
    assert again["comments"] == []


def test_com_11_a_send_with_nothing_to_send_is_refused(hub, shown) -> None:  # noqa: ANN001
    answer = post_send(hub, shown)
    assert answer.status_code == 400
    assert not (shown["folder"] / "history" / "sends").exists()


def test_com_11_a_comment_without_picture_has_no_path(hub, owner, shown) -> None:  # noqa: ANN001
    save(owner, shown, picture=None, picture_error="timed out")
    [comment] = post_send(hub, shown).json()["event"]["comments"]
    assert comment["picture"] is None and comment["picture_error"] == "timed out"


def test_rpl_07_the_hook_text_has_one_line_per_comment() -> None:
    event = {
        "kind": "send", "message": "", "page": "page.html", "page_version": 1,
        "screenshot": None, "screenshot_error": "none", "actions": [],
        "comments": [
            {"n": 3, "kind": "rect", "text": "units?", "target": {"selector": "#fig"},
             "text_inside": "Figure 1", "picture": "/abs/0001.c3.png"},
            {"n": 4, "kind": "rect", "text": "why", "target": None,
             "text_inside": None, "picture": None, "picture_error": "timed out"},
        ],
    }  # fmt: skip
    lines = _event_lines(1, event)
    assert 'comment #3 rect on #fig text inside «Figure 1»: "units?"' in lines
    assert "   picture: /abs/0001.c3.png" in lines
    assert 'comment #4 rect on the page: "why"' in lines
    assert "   no picture (timed out)" in lines


def test_rpl_07_non_ascii_text_reaches_the_agent_unescaped() -> None:
    event = {
        "kind": "send", "message": "Zakaj č?", "page": "page.html", "page_version": 1,
        "screenshot": None, "screenshot_error": "none", "actions": [],
        "comments": [{"n": 1, "kind": "text", "text": "Zakaj č?", "target": None}],
    }  # fmt: skip
    lines = _event_lines(1, event)
    assert 'comment #1 text on the page: "Zakaj č?"' in lines
    assert any('"Zakaj č?"' in line for line in lines if "comment #" not in line)


def test_com_11_a_send_that_fails_to_store_gives_the_drafts_back(
    hub, owner, shown, monkeypatch
) -> None:  # noqa: ANN001
    save(owner, shown)

    def failing_write(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("disk full")

    monkeypatch.setattr("agent_canvas.hub.routes.sessions.store_send", failing_write)
    try:
        failed = post_send(hub, shown)
    except httpx.HTTPError:
        failed = None
    assert failed is None or failed.status_code == 500
    [comment] = comments.load(shown["folder"], "page.html")["comments"]
    assert comment["sent"] is None and comment["delivery"] is None
    assert comment["send_event"] is None
    monkeypatch.undo()
    assert post_send(hub, shown).status_code == 200


def test_arc_04_a_send_updates_the_comments_in_every_window(hub, owner, shown) -> None:  # noqa: ANN001
    first, second = FakeShell(hub), FakeShell(hub)

    def sent(shell: FakeShell) -> bool:
        return any(
            m["type"] == "comments" and [c["status"] for c in m["comments"]] == ["sent"]
            for m in list(shell.messages)
        )

    try:
        hub.wait_for(lambda: "herdr" in first.types() and "herdr" in second.types())
        save(owner, shown)
        assert post_send(hub, shown).status_code == 200
        hub.wait_for(lambda: sent(first) and sent(second))
    finally:
        first.close()
        second.close()
