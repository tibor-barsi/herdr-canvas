"""Comment routes on a real hub: drafts, limits, messages, listing (COM-04, RPL-01)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import comments
from shellfake import FakeShell

pytestmark = pytest.mark.integration

BODY = {
    "page": "page.html",
    "page_version": 1,
    "kind": "rect",
    "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "w": 30, "h": 40},
    "target": {"canvas_id": None, "selector": "#fig", "text": "Fig"},
    "text_inside": "Figure 1",
}


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    fake = FakeShell(hub)
    yield fake
    fake.close()


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    """The owner's window: the cookie and the shell origin."""
    client = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    client.get(hub.login_url(), follow_redirects=False)
    return client


@pytest.fixture
def shown(cli, hub, shell) -> dict:  # noqa: ANN001
    """A session showing ``page.html`` with the window quiet again."""
    started = cli("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<p>published</p>")
    result = cli("show", "page.html", "--session", started["session"])
    assert result.code == 0, result.err
    time.sleep(0.6)  # the first scan of the watcher and its pushes
    shell.messages.clear()
    return {"id": started["session"], "folder": folder}


def url(shown: dict, tail: str = "") -> str:
    return f"/api/sessions/{shown['id']}/comments{tail}"


def save(owner: httpx.Client, shown: dict, **changes) -> httpx.Response:  # noqa: ANN003
    return owner.post(url(shown), json={**BODY, **changes})


def test_r_16_a_comments_message_carries_the_tab_unsent_count(
    hub, owner, shell, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    (shown["folder"] / "other.html").write_text("<p>x</p>")
    assert save(owner, shown, page="other.html").status_code == 200
    hub.wait_for(lambda: shell.types() == ["comments", "comments"])
    assert shell.messages[-1]["unsent"] == {"comments": 2, "files": 2}


def test_r_16_the_unsent_count_leaves_out_pages_that_no_longer_exist(
    hub, owner, shell, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    (shown["folder"] / "other.html").write_text("<p>x</p>")
    assert save(owner, shown, page="other.html").status_code == 200
    (shown["folder"] / "page.html").unlink()
    shell.messages.clear()
    assert save(owner, shown, page="other.html").status_code == 200
    hub.wait_for(lambda: "comments" in shell.types())
    last = [m for m in shell.messages if m["type"] == "comments"][-1]
    assert last["unsent"] == {"comments": 2, "files": 1}


def test_com_16_a_repeated_request_id_is_answered_again_without_applying(
    owner, shown
) -> None:  # noqa: ANN001
    first = save(owner, shown, request_id="r-1")
    again = save(owner, shown, request_id="r-1")
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    comments.take_unsent(shown["folder"], "page.html", "now", "evt_1")
    reply = {"page": "page.html", "n": 1, "reply": "once", "request_id": "r-2"}
    owner.post(url(shown, "/edit"), json=reply)
    owner.post(url(shown, "/edit"), json=reply)
    document = comments.load(shown["folder"], "page.html")
    assert [c["n"] for c in document["comments"]] == [1]
    assert [r["text"] for r in document["comments"][0]["replies"]] == ["once"]


def test_com_04_three_saves_delete_two_save_gives_four(owner, shown) -> None:  # noqa: ANN001
    assert [save(owner, shown).json()["n"] for _ in range(3)] == [1, 2, 3]
    gone = owner.post(
        url(shown, "/edit"), json={"page": "page.html", "n": 2, "delete": True}
    )
    assert gone.status_code == 200
    assert save(owner, shown).json()["n"] == 4
    listed = owner.get(url(shown), params={"page": "page.html"}).json()
    assert [c["n"] for c in listed["comments"]] == [1, 3, 4]
    assert {c["status"] for c in listed["comments"]} == {"draft"}


def test_com_04_drafts_survive_a_reload_and_a_hub_restart(hub, owner, shown) -> None:  # noqa: ANN001
    for _ in range(3):
        save(owner, shown)
    owner.post(url(shown, "/edit"), json={"page": "page.html", "n": 2, "delete": True})
    save(owner, shown)
    hub.restart()
    fresh = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    fresh.get(hub.login_url(), follow_redirects=False)
    listed = fresh.get(url(shown), params={"page": "page.html"})
    assert [c["n"] for c in listed.json()["comments"]] == [1, 3, 4]
    assert comments.load(shown["folder"], "page.html")["next"] == 5


def test_com_04_the_agent_never_sees_drafts(cli, owner, shown) -> None:  # noqa: ANN001
    save(owner, shown)
    save(owner, shown)
    for args in (("--all",), ()):
        result = cli("comment", "list", *args, "--session", shown["id"])
        assert result.code == 0, result.err
        assert result.json == {"session": shown["id"], "comments": []}
    sent = comments.take_unsent(shown["folder"], "page.html", "now", "evt_1")
    assert len(sent) == 2
    listed = cli("comment", "list", "--all", "--session", shown["id"]).json
    assert [c["n"] for c in listed["comments"]] == [1, 2]
    assert listed["comments"][0]["path"] == str(shown["folder"] / "page.html")
    assert cli("comment", "list", "page.html", "--session", shown["id"]).code == 0


def test_com_04_the_201st_comment_is_refused_with_400(owner, shown) -> None:  # noqa: ANN001
    for _ in range(200):
        assert save(owner, shown).status_code == 200
    refused = save(owner, shown)
    assert refused.status_code == 400
    assert "200" in refused.json()["message"]


def test_com_04_limits_and_bad_input_are_400(owner, shown) -> None:  # noqa: ANN001
    assert save(owner, shown, text="x" * 4001).status_code == 400
    assert save(owner, shown, page="gone.html").status_code == 400
    assert save(owner, shown, page="../x.html").status_code == 400
    assert (
        owner.post(
            url(shown), content=b"[1]", headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert owner.get(url(shown), params={"page": "page.html"}).json()["comments"] == []


def test_com_04_one_comments_message_per_save_and_delete(
    hub, owner, shell, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    hub.wait_for(lambda: shell.types() == ["comments"])
    message = shell.messages[0]
    assert message["session"] == shown["id"] and message["page"] == "page.html"
    assert [(c["n"], c["status"]) for c in message["comments"]] == [(1, "draft")]
    owner.post(url(shown, "/edit"), json={"page": "page.html", "n": 1, "delete": True})
    hub.wait_for(lambda: shell.types() == ["comments", "comments"])
    assert shell.messages[1]["comments"] == []
    time.sleep(0.8)
    assert shell.types() == ["comments", "comments"]


def test_com_04_a_refused_save_sends_no_message(hub, owner, shell, shown) -> None:  # noqa: ANN001
    assert save(owner, shown, text="x" * 4001).status_code == 400
    time.sleep(0.5)
    assert shell.types() == []


def test_com_04_comments_files_cause_no_file_changed(hub, owner, shell, shown) -> None:  # noqa: ANN001
    picture = "iVBORw0KGgo="  # the PNG signature
    assert save(owner, shown, picture=picture).status_code == 200
    assert (shown["folder"] / ".comments" / "page.html.1.png").exists()
    time.sleep(1.2)  # longer than the watcher's scan
    assert shell.types() == ["comments"]


def test_com_04_the_window_can_ask_for_a_page(hub, owner, shell, shown) -> None:  # noqa: ANN001
    save(owner, shown)
    hub.wait_for(lambda: shell.types() == ["comments"])
    shell.messages.clear()
    shell.send({"type": "comments-get", "session": shown["id"], "page": "page.html"})
    hub.wait_for(lambda: shell.types() == ["comments"])
    assert shell.messages[0]["comments"][0]["n"] == 1
    shell.send({"type": "comments-get", "session": shown["id"], "page": "../x"})
    shell.send({"type": "comments-get", "session": "nope", "page": "page.html"})
    time.sleep(0.4)
    assert shell.types() == ["comments"]


def test_com_04_only_the_owner_changes_and_the_key_lists_only_sent(
    hub, owner, shown
) -> None:  # noqa: ANN001
    agent = httpx.Client(base_url=hub.base_url, headers=hub.key_headers)
    assert agent.post(url(shown), json=BODY).status_code == 403
    save(owner, shown)
    assert (
        agent.post(
            url(shown, "/edit"), json={"page": "page.html", "n": 1, "delete": True}
        ).status_code
        == 403
    )
    assert agent.get(url(shown)).json()["comments"] == []
    assert owner.get(url(shown)).status_code == 400  # the window names a page
    stranger = httpx.Client(base_url=hub.base_url)
    assert stranger.get(url(shown)).status_code == 401


def test_com_09_a_sent_comment_cannot_be_deleted(owner, shown) -> None:  # noqa: ANN001
    save(owner, shown)
    comments.take_unsent(shown["folder"], "page.html", "now", "evt_1")
    refused = owner.post(
        url(shown, "/edit"), json={"page": "page.html", "n": 1, "delete": True}
    )
    assert refused.status_code == 409
    other = owner.post(
        url(shown, "/edit"), json={"page": "page.html", "n": 1, "text": "new"}
    )
    assert other.status_code == 409


def test_com_03_the_comments_message_carries_next_for_the_box_number(  # noqa: ANN001
    hub, owner, shell, shown
) -> None:
    """The box is headed by the number the comment will get (never reused)."""
    for _ in range(2):
        save(owner, shown)
    owner.post(url(shown, "/edit"), json={"page": "page.html", "n": 2, "delete": True})
    hub.wait_for(lambda: shell.types().count("comments") == 3)
    last = [m for m in shell.messages if m["type"] == "comments"][-1]
    assert [c["n"] for c in last["comments"]] == [1] and last["next"] == 3


# ---- COM-09: the edit route ----------------------------------------------------


def edit(owner: httpx.Client, shown: dict, n: int, **fields) -> httpx.Response:  # noqa: ANN003
    return owner.post(url(shown, "/edit"), json={"page": "page.html", "n": n, **fields})


def stored(shown: dict) -> list[dict]:
    return comments.load(shown["folder"], "page.html")["comments"]


def test_com_09_editing_a_draft_changes_its_text_and_publishes_the_page(
    hub, owner, shell, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    hub.wait_for(lambda: shell.types().count("comments") == 1)
    reply = edit(owner, shown, 1, text="units in Hz?")
    assert reply.status_code == 200
    assert reply.json()["text"] == "units in Hz?" and reply.json()["edited"]
    assert stored(shown)[0]["text"] == "units in Hz?"
    hub.wait_for(lambda: shell.types().count("comments") == 2)
    last = [m for m in shell.messages if m["type"] == "comments"][-1]
    assert [c["text"] for c in last["comments"]] == ["units in Hz?"]


def test_com_09_a_sent_comment_is_refused_with_409_and_keeps_its_text(
    owner, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    comments.take_unsent(shown["folder"], "page.html", "now", "evt_1")
    assert edit(owner, shown, 1, text="new").status_code == 409
    assert stored(shown)[0]["text"] == "units?"


@pytest.mark.parametrize(
    "fields",
    [
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 4001},
        {"text": 5},
        {},
        {"text": "a", "delete": True},
        {"text": "a", "kind": "point"},
    ],
)
def test_com_09_a_bad_edit_is_refused_and_changes_nothing(owner, shown, fields) -> None:  # noqa: ANN001
    save(owner, shown)
    assert edit(owner, shown, 1, **fields).status_code == 400
    assert stored(shown)[0]["text"] == "units?"


def test_com_09_an_unknown_number_is_404_and_the_key_is_refused(
    hub, owner, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    assert edit(owner, shown, 7, text="x").status_code == 404
    agent = httpx.Client(base_url=hub.base_url, headers=hub.key_headers)
    assert edit(agent, shown, 1, text="x").status_code == 403
    assert stored(shown)[0]["text"] == "units?"
