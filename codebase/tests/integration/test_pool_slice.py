"""Pooled pages end to end: one page, two sessions, one card's feedback (POOL, #2)."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from agent_canvas.config import Config
from agent_canvas.hub import comments
from agent_canvas.hub.app import create_app
from agent_canvas.hub.watcher import PageHistory

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


@pytest.fixture
def repo(home: Path) -> Path:
    """A git repository below the fake home."""
    path = home / "proj"
    path.mkdir(exist_ok=True)
    (path / ".git").mkdir()
    return path


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    client = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    client.get(hub.login_url(), follow_redirects=False)
    return client


def path_of(cli, session: str, repo: Path) -> dict:  # noqa: ANN001
    """Make ``session`` known; return the answer of ``session path``."""
    answer = cli("session", "path", "--session", session, cwd=repo)
    assert answer.code == 0, answer.err
    return answer.json


def publish(cli, session: str, repo: Path, html: str, *extra: str):  # noqa: ANN001, ANN201
    """Write ``session``'s own draft of the page and publish it."""
    found = path_of(cli, session, repo)
    draft = Path(found["folder"]) / f"dash.{found['tag']}.draft.html"
    draft.write_text(html)
    return cli(
        "show", "dash", "--publish", "--session", session, "--no-audit", *extra,
        cwd=repo,
    )  # fmt: skip


def show(cli, session: str, repo: Path):  # noqa: ANN001, ANN201
    """Show the published page as ``session``: it has now seen it."""
    return cli("show", PAGE, "--session", session, "--no-audit", cwd=repo)


def pool_of(hub, session: str) -> str:  # noqa: ANN001
    return hub.on_loop(lambda: hub.app.state.registry.pool_of(session))


def record(folder: Path) -> dict:
    """Return the page record of the pool page."""
    meta = json.loads((folder / "session.json").read_text())
    return meta["page_meta"][PAGE]


def shared_page(cli, repo: Path) -> Path:  # noqa: ANN001
    """A publishes the page, B shows it; return the pool folder."""
    assert publish(cli, "A", repo, "<title>Dash</title><p>a1</p>").code == 0
    assert show(cli, "B", repo).code == 0
    return Path(path_of(cli, "A", repo)["folder"])


def comment(owner: httpx.Client, card: str, text: str = "units?") -> None:
    made = owner.post(f"/api/sessions/{card}/comments", json={**COMMENT, "text": text})
    assert made.status_code == 200, made.text


def send(hub, card: str) -> dict:  # noqa: ANN001
    sent = httpx.post(
        f"{hub.base_url}/api/sessions/{card}/send", json=SEND, headers=hub.key_headers
    )
    assert sent.status_code == 200, sent.text
    return sent.json()["event"]


def pending(cli, session: str, repo: Path) -> list[str]:  # noqa: ANN001
    answer = cli("pending", "--session", session, cwd=repo)
    assert answer.code == 0, answer.err
    return [e["id"] for e in answer.json["events"]]


def listen(hub, session: str):  # noqa: ANN001, ANN201
    events = hub.app.state.events
    return hub.on_loop(lambda: events.add_listener(session, "ask"))


def unlisten(hub, listener) -> None:  # noqa: ANN001
    events = hub.app.state.events
    hub.on_loop(lambda: events.remove_listener(listener))


def test_pool_01_two_sessions_publish_one_page_and_it_exists_once_in_the_pool(
    cli, repo
) -> None:  # noqa: ANN001
    a, b = path_of(cli, "A", repo), path_of(cli, "B", repo)
    assert a["folder"] == b["folder"] and a["tag"] != b["tag"]
    pool = Path(a["folder"])
    assert pool.parent == repo / ".agent-canvas" and pool.name.startswith("pool-")
    assert publish(cli, "A", repo, "<p>a1</p>").code == 0
    assert show(cli, "B", repo).code == 0
    published = publish(cli, "B", repo, "<p>b1</p>")
    assert published.code == 0, published.err
    assert (pool / PAGE).read_text() == "<p>b1</p>"
    copies = [p for p in (repo / ".agent-canvas").rglob(PAGE)]
    assert copies == [pool / PAGE]
    entry = record(pool)
    assert entry["created_by"]["session"] == "A"
    assert entry["updated_by"]["session"] == "B"
    assert sorted(entry["sessions"]) == ["A", "B"]


def test_pool_01_page_data_of_b_is_in_the_pool_and_not_in_bs_own_folder(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    assert publish(cli, "B", repo, "<p>b1</p>").code == 0
    comment(owner, "B")
    send(hub, "B")
    own = repo / ".agent-canvas" / "B"
    assert (own / "session.json").is_file()  # positive control: B's folder is there
    assert sorted(p.name for p in own.iterdir()) == ["session.json"]
    meta = json.loads((own / "session.json").read_text())
    assert meta["pages"] == [] and meta["active_page"] is None
    assert not meta.get("page_meta")  # the shape check leaves an empty table
    (stored,) = comments.load(pool, PAGE)["comments"]
    assert stored["card"] == "B" and stored["sent"] is not None
    assert len(PageHistory(pool).versions(PAGE)) == 2
    assert list((pool / "history" / "sends").glob("*.json"))
    assert (pool / "events.jsonl").is_file()


def test_pool_01_two_hubs_on_one_project_get_two_pools_with_distinct_ids(
    cli, hub, repo, tmp_path
) -> None:  # noqa: ANN001
    first = Path(path_of(cli, "A", repo)["folder"])
    first_id = pool_of(hub, "A")
    other = create_app(Config(port=hub.port + 1), tmp_path / "other-state")
    second = other.state.registry.pool_session(str(repo))
    second_folder = other.state.registry.folder_of(second)
    assert first_id.startswith("project-") and second["id"].startswith("project-")
    assert first_id != second["id"]
    assert first != second_folder and second_folder.parent == first.parent
    assert second_folder.name.startswith("pool-")


def test_pool_05_a_comment_made_in_card_x_reaches_x_and_y_gets_nothing(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    shared_page(cli, repo)
    listen(hub, "A")
    listen(hub, "B")
    comment(owner, "B")
    event = send(hub, "B")
    assert event["for"] == "B"
    assert pending(cli, "A", repo) == []
    assert pending(cli, "B", repo) == [event["id"]]


def test_pool_05_send_takes_only_the_cards_own_draft_comments(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    comment(owner, "A", "from a")
    comment(owner, "B", "from b")
    event = send(hub, "B")
    assert [c["text"] for c in event["comments"]] == ["from b"]
    stored = {c["text"]: c for c in comments.load(pool, PAGE)["comments"]}
    assert stored["from a"]["card"] == "A" and stored["from a"]["sent"] is None
    assert stored["from b"]["card"] == "B" and stored["from b"]["sent"] is not None


def test_pool_05_a_listening_or_paired_card_session_receives_else_the_inbox(
    cli, hub, owner, repo, monkeypatch
) -> None:  # noqa: ANN001
    shared_page(cli, repo)
    listener = listen(hub, "B")
    comment(owner, "B", "one")
    first = send(hub, "B")["id"]
    assert pending(cli, "A", repo) == []
    assert pending(cli, "B", repo) == [first]
    unlisten(hub, listener)
    herdr = hub.app.state.services.herdr_app
    monkeypatch.setattr(herdr, "paired", lambda: {"B"})
    comment(owner, "B", "two")
    second = send(hub, "B")["id"]
    assert pending(cli, "A", repo) == []
    assert pending(cli, "B", repo) == [second]
    monkeypatch.setattr(herdr, "paired", set)
    comment(owner, "B", "three")
    third = send(hub, "B")["id"]
    assert pending(cli, "A", repo) == [third]
    assert pending(cli, "B", repo) == []


def test_pool_05_an_inbox_item_goes_only_to_a_session_that_touched_the_page(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    shared_page(cli, repo)
    pool_id = pool_of(hub, "A")
    path_of(cli, "C", repo)
    reserved = httpx.post(
        f"{hub.base_url}/api/sessions/R/reserve",
        json={"project": str(repo), "agent": "claude-code"},
        headers=hub.key_headers,
    )
    assert reserved.status_code == 200, reserved.text
    comment(owner, "A")
    sent = send(hub, "A")["id"]
    assert pending(cli, "C", repo) == []
    assert pending(cli, "R", repo) == []
    assert hub.event_state(pool_id, sent) == "queued"
    assert pending(cli, "B", repo) == [sent]
    assert hub.event_state(pool_id, sent) == "delivered"


def test_pool_06_a_publish_over_a_changed_page_is_refused_names_who_and_when_and_keeps_the_draft(  # noqa: E501
    cli, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    changed = publish(cli, "A", repo, "<p>a2</p>", "--title", "Pump model fixes")
    assert changed.code == 0, changed.err
    refused = publish(cli, "B", repo, "<p>b1</p>")
    assert refused.code == 1
    message = refused.json["message"]
    assert "dash.html was changed after you last read it" in message
    assert '"Pump model fixes" (agent)' in message and "(version 2)" in message
    when = datetime.fromisoformat(record(pool)["updated_by"]["time"]).astimezone()
    assert f"at {when:%H:%M on %-d %b}" in message
    assert "Your draft is kept" in message
    assert "agent-canvas show dash --publish" in message
    tag = path_of(cli, "B", repo)["tag"]
    assert (pool / f"dash.{tag}.draft.html").read_text() == "<p>b1</p>"
    assert (pool / PAGE).read_text() == "<p>a2</p>"


def test_pool_06_the_next_publish_goes_through_and_the_overwritten_version_is_saved(
    cli, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    assert publish(cli, "A", repo, "<p>a2</p>").code == 0
    assert publish(cli, "B", repo, "<p>b1</p>").code == 1
    again = cli("show", "dash", "--publish", "--session", "B", "--no-audit", cwd=repo)
    assert again.code == 0, again.err
    assert (pool / PAGE).read_text() == "<p>b1</p>"
    history = PageHistory(pool)
    saved = [history.read(PAGE, n) for n, _ in history.versions(PAGE)]
    assert b"<p>a2</p>" in saved and saved[-1] == b"<p>b1</p>"


def test_pool_07_a_publish_over_an_untouched_page_is_refused(cli, repo) -> None:  # noqa: ANN001
    assert publish(cli, "A", repo, "<p>a1</p>", "--title", "Pump model fixes").code == 0
    refused = publish(cli, "B", repo, "<p>b1</p>")
    assert refused.code == 1
    message = refused.json["message"]
    assert "this project already has a page dash.html" in message
    assert 'made by "Pump model fixes" (agent)' in message
    assert "which you have not read" in message and "more specific name" in message
    pool = Path(path_of(cli, "A", repo)["folder"])
    assert (pool / PAGE).read_text() == "<p>a1</p>"


def test_pool_11_drafts_of_two_sessions_for_one_page_are_two_files(cli, repo) -> None:  # noqa: ANN001
    a, b = path_of(cli, "A", repo), path_of(cli, "B", repo)
    pool = Path(a["folder"])
    (pool / f"dash.{a['tag']}.draft.html").write_text("<p>mine</p>")
    (pool / f"dash.{b['tag']}.draft.html").write_text("<p>theirs</p>")
    shown = cli("show", "dash", "--publish", "--session", "A", "--no-audit", cwd=repo)
    assert shown.code == 0, shown.err
    assert (pool / PAGE).read_text() == "<p>mine</p>"
    assert (pool / f"dash.{b['tag']}.draft.html").read_text() == "<p>theirs</p>"
    (pool / "notes.draft.html").write_text("<p>untagged</p>")
    untagged = cli("show", "notes", "--publish", "--session", "A", cwd=repo)
    assert untagged.code == 1
    assert f"notes.{a['tag']}.draft.html" in untagged.json["message"]
    assert not (pool / "notes.html").exists()


def test_pool_05_project_ids_are_still_refused(cli, hub, repo) -> None:  # noqa: ANN001
    pool = Path(path_of(cli, "A", repo)["folder"])
    pool_id = pool_of(hub, "A")
    before = (pool / "session.json").read_text()
    fake = "project-0123456789abcdef"
    attempts = [
        ("session", "end", "--session", pool_id),
        ("session", "set", "--title", "Mine", "--session", pool_id),
        ("session", "path", "--session", pool_id),
        ("show", PAGE, "--session", pool_id),
        ("pending", "--session", pool_id),
        ("session", "path", "--session", fake),
        ("show", PAGE, "--session", fake),
        ("session", "path", "--session", "Project"),
        ("session", "path", "--session", "PROJECT"),
        ("session", "path", "--session", "Project-0123456789abcdef"),
        ("watch", "--session", pool_id, "--timeout", "5"),
    ]
    for attempt in attempts:
        refused = cli(*attempt, cwd=repo)
        assert refused.code == 5, (attempt, refused.out, refused.err)
    reserved = httpx.post(
        f"{hub.base_url}/api/sessions/{fake}/reserve",
        json={"project": str(repo), "agent": "x"},
        headers=hub.key_headers,
    )
    assert reserved.status_code == 404
    assert (pool / "session.json").read_text() == before
    assert not (repo / ".agent-canvas" / fake).exists()
    assert fake not in (hub.state_dir / "sessions.json").read_text()


def agent_post(hub, card: str, route: str, body: dict) -> httpx.Response:  # noqa: ANN001
    return httpx.post(
        f"{hub.base_url}/api/sessions/{card}/comments/{route}",
        json=body,
        headers=hub.key_headers,
    )


def test_pool_05_a_session_lists_marks_replies_and_closes_only_its_cards_comments(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    comment(owner, "A", "from a")
    send(hub, "A")
    comment(owner, "B", "from b")
    send(hub, "B")
    numbers = {c["text"]: c["n"] for c in comments.load(pool, PAGE)["comments"]}
    listed = httpx.get(
        f"{hub.base_url}/api/sessions/B/comments", headers=hub.key_headers
    ).json()["comments"]
    assert [c["text"] for c in listed] == ["from b"]
    stored = {c["text"]: c for c in comments.load(pool, PAGE)["comments"]}
    assert stored["from a"]["seen"] == [] and stored["from b"]["seen"]
    theirs = {"page": PAGE, "n": numbers["from a"], "text": "mine now"}
    assert agent_post(hub, "B", "reply", theirs).status_code == 404
    done = {"page": PAGE, "n": [numbers["from a"]]}
    assert agent_post(hub, "B", "done", done).status_code == 404
    stored = {c["text"]: c for c in comments.load(pool, PAGE)["comments"]}
    assert stored["from a"]["replies"] == [] and stored["from a"]["done"] is None
    own = {"page": PAGE, "n": numbers["from b"], "text": "fixed"}
    assert agent_post(hub, "B", "reply", own).status_code == 200
    mine = {"page": PAGE, "n": [numbers["from b"]]}
    assert agent_post(hub, "B", "done", mine).status_code == 200
    a_listed = httpx.get(
        f"{hub.base_url}/api/sessions/A/comments", headers=hub.key_headers
    ).json()["comments"]
    assert [c["text"] for c in a_listed] == ["from a"]


def agent_list(hub, card: str) -> list[str]:  # noqa: ANN001
    listed = httpx.get(
        f"{hub.base_url}/api/sessions/{card}/comments", headers=hub.key_headers
    )
    return [c["text"] for c in listed.json()["comments"]]


def test_pool_05_a_session_that_took_a_cards_comment_from_the_inbox_answers_and_closes_it(  # noqa: E501
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    comment(owner, "A", "taken")
    send(hub, "A")  # A is not alive: the comment waits in the inbox
    assert len(pending(cli, "B", repo)) == 1  # B touched the page and takes it
    comment(owner, "A", "still waiting")
    send(hub, "A")  # nobody has taken this one
    numbers = {c["text"]: c["n"] for c in comments.load(pool, PAGE)["comments"]}
    assert agent_list(hub, "B") == ["taken"]
    waiting = {"page": PAGE, "n": numbers["still waiting"], "text": "mine?"}
    assert agent_post(hub, "B", "reply", waiting).status_code == 404
    assert (
        agent_post(hub, "B", "done", {**waiting, "n": [waiting["n"]]}).status_code
        == 404
    )
    taken = {"page": PAGE, "n": numbers["taken"], "text": "fixed"}
    assert agent_post(hub, "B", "reply", taken).status_code == 200
    assert (
        agent_post(hub, "B", "done", {"page": PAGE, "n": [taken["n"]]}).status_code
        == 200
    )
    stored = {c["text"]: c for c in comments.load(pool, PAGE)["comments"]}
    assert stored["taken"]["done"] is not None
    assert [r["text"] for r in stored["taken"]["replies"]] == ["fixed"]
    assert stored["still waiting"]["replies"] == []
    assert stored["taken"]["card"] == "A"  # it stays the comment of A's card


def test_pool_07_a_copy_over_a_changed_page_is_refused(cli, repo, tmp_path) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    assert publish(cli, "A", repo, "<p>a2</p>").code == 0
    source = tmp_path / "outside" / PAGE
    source.parent.mkdir()
    source.write_text("<p>copied</p>")
    copy = ("show", "--copy", str(source), "--session", "B", "--no-audit")
    refused = cli(*copy, cwd=repo)
    assert refused.code == 1, refused.out
    assert "Your file is kept" in refused.json["message"]
    assert (pool / PAGE).read_text() == "<p>a2</p>"
    again = cli(*copy, cwd=repo)
    assert again.code == 0, again.err
    assert (pool / PAGE).read_text() == "<p>copied</p>"


# ---- cases of the superseded test_proj_* files that still hold (Ruling 2) ----


def test_pool_01_two_repositories_get_two_pools_and_never_share_an_inbox(
    cli, hub, owner, repo, home
) -> None:  # noqa: ANN001
    shared_page(cli, repo)
    other = home / "other"
    other.mkdir()
    (other / ".git").mkdir()
    assert publish(cli, "C", other, "<p>c1</p>").code == 0  # the same page name
    assert pool_of(hub, "C") != pool_of(hub, "A")
    assert path_of(cli, "C", other)["folder"] != path_of(cli, "A", repo)["folder"]
    comment(owner, "A")
    sent = send(hub, "A")["id"]
    assert pending(cli, "C", other) == []
    assert pending(cli, "B", repo) == [sent]


def test_pool_05_two_pickups_at_one_moment_give_an_inbox_item_to_exactly_one(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    shared_page(cli, repo)
    comment(owner, "A")
    sent = send(hub, "A")["id"]
    results: dict[str, list[str]] = {}
    start = threading.Barrier(2)

    def pick(session: str) -> None:
        start.wait()
        answer = httpx.post(
            f"{hub.base_url}/api/sessions/{session}/pending",
            json={},
            headers=hub.key_headers,
        )
        results[session] = [e["id"] for e in answer.json()["events"]]

    threads = [threading.Thread(target=pick, args=(s,)) for s in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(results) == ["A", "B"]
    assert results["A"] + results["B"] == [sent]


def test_pool_05_a_cards_now_event_goes_to_its_watch_only_and_its_ack_marks_it(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    events = hub.app.state.events
    mine = hub.on_loop(lambda: events.add_listener("B", "watch"))
    other = hub.on_loop(lambda: events.add_listener("A", "watch"))
    comment(owner, "B")
    sent = httpx.post(
        f"{hub.base_url}/api/sessions/B/send",
        json={**SEND, "delivery": "now"},
        headers=hub.key_headers,
    ).json()["event"]["id"]
    assert [e["id"] for e in list(mine.queue._queue)] == [sent]
    assert other.queue.empty()
    assert hub.on_loop(lambda: events.ack("A", sent)) is False  # not A's to take
    assert hub.event_state(pool_of(hub, "A"), sent) == "queued"
    assert hub.on_loop(lambda: events.ack("B", sent)) is True
    assert hub.event_state(pool_of(hub, "A"), sent) == "delivered"
    (stored,) = comments.load(pool, PAGE)["comments"]
    assert stored["seen"]


def test_pool_05_an_inbox_item_is_never_pushed_to_a_watch(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    shared_page(cli, repo)
    events = hub.app.state.events
    watch = hub.on_loop(lambda: events.add_listener("B", "watch"))
    comment(owner, "A")  # A is not running: its item goes to the inbox
    sent = httpx.post(
        f"{hub.base_url}/api/sessions/A/send",
        json={**SEND, "delivery": "now"},
        headers=hub.key_headers,
    ).json()["event"]["id"]
    assert watch.queue.empty()
    assert pending(cli, "B", repo) == [sent]


def test_pool_05_own_events_still_come_when_the_pool_log_cannot_be_read(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    comment(owner, "A")
    send(hub, "A")  # the pool's log exists and is loaded
    hub.app.state.events.drop(pool_of(hub, "A"))
    own = hub.create_event("B", "custom")["id"]
    (pool / "events.jsonl").write_bytes(b"\xff\xfe not utf-8\n")
    assert pending(cli, "B", repo) == [own]
    assert hub.event_state("B", own) == "delivered"
    assert (pool / "events.jsonl").read_bytes() == b"\xff\xfe not utf-8\n"


def test_pool_cleanup_of_the_pool_is_refused_and_its_waiting_item_stays(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_page(cli, repo)
    pool_id = pool_of(hub, "A")
    comment(owner, "A")
    sent = send(hub, "A")["id"]
    refused = httpx.post(
        f"{hub.base_url}/api/cleanup",
        json={"session": pool_id, "yes": True, "force": True},
        headers=hub.key_headers,
    )
    assert refused.status_code >= 400
    assert (pool / "session.json").is_file() and (pool / PAGE).is_file()
    cleaned = cli("cleanup", "--older-than", "1s", "--yes", cwd=repo)
    assert cleaned.code == 0, cleaned.err
    assert hub.event_state(pool_id, sent) == "queued"
    assert pending(cli, "B", repo) == [sent]
