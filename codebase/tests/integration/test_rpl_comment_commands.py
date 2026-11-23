"""Agent comment commands, the key/cookie permission matrix (RPL-01 to -03, -06)."""

from __future__ import annotations

import base64
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import comments

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"picture"
COMMENT = {
    "page": "page.html", "page_version": 1, "kind": "point", "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
    "target": {"canvas_id": None, "selector": "#fig", "text": None},
    "picture": base64.b64encode(PNG).decode(),
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


@pytest.fixture
def agent(hub) -> httpx.Client:  # noqa: ANN001
    return httpx.Client(base_url=hub.base_url, headers=hub.key_headers)


class Scene:
    """A session with comments 1 and 2 sent and comment 3 still a draft."""

    def __init__(self, hub, cli, owner, agent) -> None:  # noqa: ANN001
        started = cli("session", "start").json
        self.id = started["session"]
        self.folder = Path(started["folder"])
        (self.folder / "page.html").write_text("<p>x</p>")
        self.hub, self.cli, self.owner, self.agent = hub, cli, owner, agent
        self.base = f"/api/sessions/{self.id}/comments"
        for _ in range(2):
            self.save()
        self.send()
        self.save()

    def save(self) -> None:
        answer = self.owner.post(self.base, json=COMMENT)
        assert answer.status_code == 200, answer.text

    def send(self) -> dict:
        answer = self.agent.post(f"/api/sessions/{self.id}/send", json=SEND)
        assert answer.status_code == 200, answer.text
        return answer.json()["event"]

    def record(self, number: int) -> dict:
        found = comments.load(self.folder, "page.html")["comments"]
        return next(c for c in found if c["n"] == number)

    def run(self, *args: str):  # noqa: ANN202
        return self.cli("comment", *args, "--session", self.id)


@pytest.fixture
def scene(hub, cli, owner, agent) -> Scene:  # noqa: ANN001
    return Scene(hub, cli, owner, agent)


# ---- RPL-01 -----------------------------------------------------------------


def test_rpl_01_list_gives_the_open_sent_comments_with_the_5_7_fields(scene) -> None:  # noqa: ANN001
    result = scene.run("list")
    assert result.code == 0, result.err
    assert result.json["session"] == scene.id
    listed = result.json["comments"]
    assert [c["n"] for c in listed] == [1, 2]  # comment 3 is a draft
    first = listed[0]
    assert first["page"] == "page.html"
    assert first["path"] == str(scene.folder / "page.html")
    assert first["open"] is True and first["status"] == "seen"
    assert first["picture"] == str(scene.folder / ".comments" / "page.html.1.png")
    assert {"seen", "read", "anchored_version"}.isdisjoint(first)


def test_rpl_01_open_filter_hides_answered_and_done_all_shows_them(scene) -> None:  # noqa: ANN001
    assert scene.run("reply", "page.html", "1", "fixed").code == 0
    assert scene.run("done", "page.html", "2").code == 0
    assert scene.run("list").json["comments"] == []
    everything = scene.run("list", "--all").json["comments"]
    assert [(c["n"], c["open"]) for c in everything] == [(1, False), (2, False)]
    assert [c["status"] for c in everything] == ["answered", "done"]


def test_rpl_01_page_argument_limits_the_listing(scene) -> None:  # noqa: ANN001
    assert len(scene.run("list", "page.html").json["comments"]) == 2
    assert scene.run("list", "other.html").json["comments"] == []


def test_rpl_01_listing_marks_seen_and_drafts_never_appear(scene) -> None:  # noqa: ANN001
    assert scene.record(1)["seen"] == []
    scene.run("list")
    assert len(scene.record(1)["seen"]) == 1
    assert scene.record(3)["seen"] == []
    assert 3 not in [c["n"] for c in scene.run("list", "--all").json["comments"]]


def test_rpl_01_an_unsent_owner_reply_is_not_listed(scene, owner) -> None:  # noqa: ANN001
    answer = owner.post(
        scene.base + "/edit", json={"page": "page.html", "n": 1, "reply": "also"}
    )
    assert answer.status_code == 200
    [first, _] = scene.run("list", "--all").json["comments"]
    assert first["replies"] == [] and first["status"] == "seen"


# ---- RPL-02 -----------------------------------------------------------------


def test_rpl_02_reply_uses_the_agent_name_or_from(scene) -> None:  # noqa: ANN001
    shown = scene.run("reply", "page.html", "1", "fixed")
    assert shown.code == 0, shown.err
    assert shown.json == {"page": "page.html", "n": 1, "replies": 1, "done": False}
    scene.run("reply", "page.html", "1", "and more", "--from", "  Reviewer  ")
    names = [r["from"] for r in scene.record(1)["replies"]]
    [mine] = [
        s for s in scene.cli("session", "list").json["sessions"] if s["id"] == scene.id
    ]
    assert names == [mine["agent"], "Reviewer"]


def test_rpl_02_reply_done_marks_it_done_by_the_agent(scene) -> None:  # noqa: ANN001
    shown = scene.run("reply", "page.html", "2", "fixed", "--done")
    assert shown.json == {"page": "page.html", "n": 2, "replies": 1, "done": True}
    assert scene.record(2)["done"]["by"] == "agent"
    assert scene.record(2)["last_done"] == scene.record(2)["done"]["at"]


@pytest.mark.parametrize(
    "name", ["", "   ", "x" * 41, "owner", "OWNER", "You", "mE", " me "]
)
def test_rpl_02_a_bad_from_exits_2_and_stores_nothing(scene, name: str) -> None:  # noqa: ANN001
    result = scene.run("reply", "page.html", "1", "t", "--from", name)
    assert result.code == 2, result.err
    assert scene.record(1)["replies"] == []


def test_rpl_02_a_from_of_40_characters_is_allowed(scene) -> None:  # noqa: ANN001
    assert scene.run("reply", "page.html", "1", "t", "--from", "x" * 40).code == 0


@pytest.mark.parametrize(
    "args",
    [("other.html", "1"), ("page.html", "9"), ("page.html", "3")],
    ids=["unknown page", "unknown number", "draft"],
)
def test_rpl_02_unknown_page_number_or_draft_exits_1(scene, args) -> None:  # noqa: ANN001
    assert scene.run("reply", *args, "t").code == 1
    assert scene.run("done", *args).code == 1
    assert scene.record(3)["replies"] == [] and scene.record(3)["done"] is None


def test_rpl_02_done_takes_several_numbers_and_is_all_or_nothing(scene) -> None:  # noqa: ANN001
    assert scene.run("done", "page.html", "1", "9").code == 1
    assert scene.record(1)["done"] is None
    shown = scene.run("done", "page.html", "1", "2")
    assert shown.json == {"page": "page.html", "done": [1, 2]}
    assert scene.record(2)["done"]["by"] == "agent"


def test_rpl_02_done_on_a_done_comment_changes_nothing(scene) -> None:  # noqa: ANN001
    scene.run("done", "page.html", "1")
    before = scene.record(1)
    assert scene.run("done", "page.html", "1").code == 0
    assert scene.record(1) == before


def test_rpl_02_an_agent_reply_keeps_a_done_comment_done(scene) -> None:  # noqa: ANN001
    scene.run("done", "page.html", "1")
    scene.run("reply", "page.html", "1", "one more thing")
    assert scene.record(1)["done"] is not None


def test_rpl_02_reopen_keeps_it_closed_for_the_agent_until_the_owner_replies(
    scene, owner
) -> None:  # noqa: ANN001
    scene.run("done", "page.html", "1")
    edit = scene.base + "/edit"
    assert (
        owner.post(edit, json={"page": "page.html", "n": 1, "reopen": True}).status_code
        == 200
    )
    assert 1 not in [c["n"] for c in scene.run("list").json["comments"]]
    owner.post(edit, json={"page": "page.html", "n": 1, "reply": "not fixed"})
    assert 1 not in [c["n"] for c in scene.run("list").json["comments"]]  # unsent
    scene.send()
    [again] = [c for c in scene.run("list").json["comments"] if c["n"] == 1]
    assert again["open"] is True
    assert (
        again["replies"][-1]["text"] == "not fixed"
        and again["replies"][-1]["from"] is None
    )


# ---- RPL-03: who may do what ------------------------------------------------

EDIT = "/edit"
P = {"page": "page.html"}
# (name, method, tail, body, key status, cookie status); n 1 is sent, n 3 a draft
MATRIX = [
    ("list", "GET", "", None, 200, 200),
    ("create", "POST", "", COMMENT, 403, 200),
    ("edit text", "POST", EDIT, {**P, "n": 3, "text": "t"}, 403, 200),
    ("delete", "POST", EDIT, {**P, "n": 3, "delete": True}, 403, 200),
    ("owner reply", "POST", EDIT, {**P, "n": 1, "reply": "r"}, 403, 200),
    ("edit done", "POST", EDIT, {**P, "n": 1, "done": True}, 403, 200),
    ("reopen", "POST", EDIT, {**P, "n": 1, "reopen": True}, 403, 200),
    ("read", "POST", EDIT, {**P, "n": 1, "read": True}, 403, 200),
    ("lost", "POST", "/lost", {**P, "reports": []}, 403, 200),
    ("agent reply", "POST", "/reply", {**P, "n": 1, "text": "r"}, 200, 403),
    ("done", "POST", "/done", {**P, "n": [1]}, 200, 200),
]  # fmt: skip


def snapshot(scene: Scene) -> str:
    return json.dumps(comments.load(scene.folder, "page.html"), sort_keys=True)


@pytest.mark.parametrize("who", ["key", "cookie"])
@pytest.mark.parametrize("row", MATRIX, ids=[row[0] for row in MATRIX])
def test_rpl_03_permission_matrix(scene, hub, row, who: str) -> None:  # noqa: ANN001
    name, method, tail, body, key_status, cookie_status = row
    client = scene.agent if who == "key" else scene.owner
    expected = key_status if who == "key" else cookie_status
    before = snapshot(scene)
    params = {"page": "page.html"} if method == "GET" else None
    answer = client.request(method, scene.base + tail, json=body, params=params)
    assert answer.status_code == expected, (name, who, answer.text)
    if expected == 403:
        assert snapshot(scene) == before, "a refused request must change nothing"


def test_rpl_03_done_is_by_whoever_the_credential_names(scene, hub, owner) -> None:  # noqa: ANN001
    both = httpx.Client(
        base_url=hub.base_url, headers={**hub.key_headers, "Origin": hub.base_url}
    )
    both.cookies = owner.cookies
    wrong = httpx.Client(
        base_url=hub.base_url,
        headers={"Origin": hub.base_url, "X-Agent-Canvas-Key": "wrong"},
    )
    wrong.cookies = owner.cookies
    body = {**P, "n": [1]}
    assert scene.owner.post(scene.base + "/done", json=body).status_code == 200
    assert scene.record(1)["done"]["by"] == "owner"
    assert (
        scene.agent.post(scene.base + "/done", json={**P, "n": [2]}).status_code == 200
    )
    assert scene.record(2)["done"]["by"] == "agent"
    comments.reopen(scene.folder, "page.html", 1)
    assert both.post(scene.base + "/done", json=body).status_code == 200
    assert scene.record(1)["done"]["by"] == "agent"  # the key is looked at first
    comments.reopen(scene.folder, "page.html", 1)
    assert wrong.post(scene.base + "/done", json=body).status_code == 200
    assert scene.record(1)["done"]["by"] == "owner"  # a wrong key is no key


@pytest.mark.parametrize("row", MATRIX, ids=[row[0] for row in MATRIX])
def test_rpl_03_without_credentials_every_route_is_refused(scene, hub, row) -> None:  # noqa: ANN001
    name, method, tail, body, _, _ = row
    stranger = httpx.Client(base_url=hub.base_url)
    answer = stranger.request(method, scene.base + tail, json=body)
    assert answer.status_code == 401, name


def test_rpl_03_the_owner_reply_has_no_author_and_the_key_listing_has_no_page_need(
    scene, owner, agent
) -> None:  # noqa: ANN001
    edit = scene.base + "/edit"
    owner.post(edit, json={"page": "page.html", "n": 1, "reply": "mine"})
    assert scene.record(1)["replies"][0]["from"] is None
    listed = agent.get(scene.base).json()
    assert [c["n"] for c in listed["comments"]] == [1, 2]


def test_rpl_03_the_owner_marks_done_by_owner_and_reply_clears_it(scene, owner) -> None:  # noqa: ANN001
    edit = scene.base + "/edit"
    owner.post(edit, json={"page": "page.html", "n": 2, "done": True})
    assert scene.record(2)["done"]["by"] == "owner"
    owner.post(edit, json={"page": "page.html", "n": 2, "reply": "wait"})
    assert scene.record(2)["done"] is None
    owner.post(edit, json={"page": "page.html", "n": 1, "read": True})
    assert scene.record(1)["read"] is not None


@pytest.mark.parametrize(
    "extra",
    [{}, {"text": "a", "done": True}, {"done": False}, {"nope": True}, {"reply": " "}],
)
def test_rpl_03_edit_needs_exactly_one_valid_action(scene, owner, extra) -> None:  # noqa: ANN001
    body = {"page": "page.html", "n": 1, **extra}
    assert owner.post(scene.base + "/edit", json=body).status_code == 400


def test_rpl_03_owner_actions_on_unsent_or_unknown_comments(scene, owner) -> None:  # noqa: ANN001
    edit = scene.base + "/edit"
    assert (
        owner.post(edit, json={"page": "page.html", "n": 3, "done": True}).status_code
        == 409
    )
    assert (
        owner.post(edit, json={"page": "page.html", "n": 3, "reply": "x"}).status_code
        == 409
    )
    assert (
        owner.post(edit, json={"page": "page.html", "n": 9, "done": True}).status_code
        == 404
    )


# ---- RPL-06 -----------------------------------------------------------------


def test_rpl_06_watch_count_1_returns_all_three_comments_with_pictures(
    hub, cli, owner, agent
) -> None:  # noqa: ANN001
    started = cli("session", "start").json
    session, folder = started["session"], Path(started["folder"])
    (folder / "page.html").write_text("<p>x</p>")
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", "watch", "--count", "1",
         "--timeout", "30", "--session", session],
        cwd=cli.cwd, env=cli.environment, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(
        target=lambda: [lines.put(line) for line in process.stdout], daemon=True
    ).start()
    try:
        hub.wait_for(lambda: hub.listening(session), timeout=15)
        for _ in range(3):
            owner.post(f"/api/sessions/{session}/comments", json=COMMENT)
        agent.post(f"/api/sessions/{session}/send", json=SEND)
        event = json.loads(lines.get(timeout=15))
        assert [c["n"] for c in event["comments"]] == [1, 2, 3]
        assert all(Path(c["picture"]).read_bytes() == PNG for c in event["comments"])
        last = json.loads(lines.get(timeout=15))
        assert last["type"] == "watch-ended" and last["reason"] == "count"
    finally:
        process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()
