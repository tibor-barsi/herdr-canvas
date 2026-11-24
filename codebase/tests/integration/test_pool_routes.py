"""The rest of the hub on the pool: answers, looks, pins, cleanup, routes (POOL, #2)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx
import pytest
from tests.integration.test_pool_slice import (
    PAGE,
    comment,
    listen,
    path_of,
    pending,
    pool_of,
    publish,
    send,
    show,
)

from agent_canvas.hub.app import event_from_shell
from agent_canvas.hub.routes.sockets import seen_from_shell
from shellfake import FakeHeadless

pytestmark = pytest.mark.integration

ITEMS_PAGE = (
    "<title>Dash</title>"
    '<canvas-ask data-canvas-id="q1"><script type="application/json">'
    '{"question": "Go on?", "options": ["yes", "no"]}</script></canvas-ask>'
    '<canvas-do data-canvas-id="d1"><script type="application/json">'
    '{"title": "Check", "steps": [{"text": "one"}, {"text": "two"}]}'
    "</script></canvas-do>"
    '<img src="data.png">'
)


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


def agent_page(hub, session: str, **body) -> httpx.Response:  # noqa: ANN001, ANN003
    """Run a page action of the agent of ``session`` (key)."""
    return httpx.post(
        f"{hub.base_url}/api/sessions/{session}/pages",
        json=body,
        headers=hub.key_headers,
    )


def tab(hub, session: str) -> dict:  # noqa: ANN001
    return hub.on_loop(lambda: hub.app.state.hub.tab_provider(session))


def tree_hash(folder: Path, leave_out: set[Path] = frozenset()) -> str:
    """Hash every file below ``folder`` with its relative path."""
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if path not in leave_out:
            digest.update(str(path.relative_to(folder)).encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def shared_items_page(cli, repo: Path) -> Path:  # noqa: ANN001
    """A publishes the page with an Ask and a Do, B shows it; return the pool."""
    assert publish(cli, "A", repo, ITEMS_PAGE).code == 0
    assert show(cli, "B", repo).code == 0
    return Path(path_of(cli, "A", repo)["folder"])


def test_pool_05_an_answer_on_a_card_reaches_that_cards_session(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_items_page(cli, repo)
    listen(hub, "A")
    listen(hub, "B")
    answered = owner.post(
        "/api/sessions/B/answers/answer",
        json={"page": PAGE, "id": "q1", "value": {"answer": "yes"}},
    )
    assert answered.status_code == 200, answered.text
    event = answered.json()["event"]
    assert pending(cli, "A", repo) == []
    assert pending(cli, "B", repo) == [event]
    stored = json.loads((pool / ".answers" / f"{PAGE}.json").read_text())
    assert stored["items"]["q1"]["state"] == "answered"
    assert not (repo / ".agent-canvas" / "B" / ".answers").exists()
    listed = httpx.get(
        f"{hub.base_url}/api/sessions/B/answers", headers=hub.key_headers
    ).json()
    assert [(i["id"], i["state"]) for i in listed["items"]] == [
        ("q1", "answered"),
        ("d1", "open"),
    ]


def test_pool_05_the_read_receipt_of_card_x_counts_its_sends_in_the_pool(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    shared_items_page(cli, repo)
    events = hub.app.state.events
    comment(owner, "B")
    sent = send(hub, "B")
    receipt = hub.on_loop(lambda: events.latest_send("B"))
    assert receipt == {"time": sent["time"], "delivery": "next-message", "read": None}
    assert hub.on_loop(lambda: events.latest_send("A")) is None
    assert tab(hub, "B")["send"] == receipt
    assert pending(cli, "B", repo) == [sent["id"]]
    read = hub.on_loop(lambda: events.latest_send("B"))["read"]
    assert read is not None
    assert tab(hub, "B")["send"]["read"] == read
    assert tab(hub, "A")["send"] is None


def test_pool_11_look_draft_renders_the_callers_own_draft_with_the_pools_files(
    cli, hub, repo
) -> None:  # noqa: ANN001
    headless = FakeHeadless()
    hub.app.state.looks.headless = headless
    a, b = path_of(cli, "A", repo), path_of(cli, "B", repo)
    pool = Path(a["folder"])
    pool_id = pool_of(hub, "B")
    (pool / f"dash.{a['tag']}.draft.html").write_text("<p>a's</p>")
    (pool / f"dash.{b['tag']}.draft.html").write_text("<p>b's</p>")
    looked = cli("look", "dash", "--draft", "--session", "B", cwd=repo)
    assert looked.code == 0, looked.err
    [job] = headless.jobs
    assert job.url == hub.state.render_url(pool_id, f"dash.{b['tag']}.draft.html")
    assert Path(looked.json["png"]).parent == pool / "history" / "looks"
    (pool / "notes.draft.html").write_text("<p>untagged</p>")
    untagged = cli("look", "notes", "--draft", "--session", "B", cwd=repo)
    assert untagged.code == 1
    assert f"notes.{b['tag']}.draft.html" in untagged.json["message"]
    assert len(headless.jobs) == 1


def test_pool_04_anyone_pins_and_unpins_and_a_pin_sets_long_term(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    assert publish(cli, "A", repo, "<p>a1</p>").code == 0
    path_of(cli, "B", repo)
    assert PAGE not in tab(hub, "B")["pages"]  # positive control: B never touched it
    pinned = agent_page(hub, "B", action="pin", name=PAGE)
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["pinned"] is True and pinned.json()["kind"] == "long-term"
    path_of(cli, "C", repo)
    fresh = tab(hub, "C")
    assert fresh["pages"] == [PAGE] and fresh["pinned"] == [PAGE]
    listed = cli("page", "list", "--session", "C", cwd=repo).json["pages"]
    assert [(p["name"], p["kind"], p["pinned"]) for p in listed] == [
        (PAGE, "long-term", True)
    ]
    unpinned = owner.post(
        "/api/home/pages", json={"session": "C", "page": PAGE, "pin": False}
    )
    assert unpinned.status_code == 200, unpinned.text
    assert tab(hub, "C")["pages"] == []
    again = owner.post(
        "/api/home/pages", json={"session": "C", "page": PAGE, "pin": True}
    )
    assert again.status_code == 200 and tab(hub, "C")["pinned"] == [PAGE]
    assert agent_page(hub, "A", action="unpin", name=PAGE).status_code == 200
    assert tab(hub, "C")["pinned"] == []


def test_pool_04_a_pinned_page_cannot_be_archived_until_unpinned(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    assert publish(cli, "A", repo, "<p>a1</p>").code == 0
    path_of(cli, "C", repo)
    assert agent_page(hub, "A", action="pin", name=PAGE).status_code == 200
    refused = agent_page(hub, "A", action="archive", name=PAGE)
    assert refused.status_code == 422 and "unpin" in refused.json()["message"]
    by_owner = owner.post(
        "/api/home/pages", json={"session": "A", "page": PAGE, "archive": True}
    )
    assert by_owner.status_code == 422 and "unpin" in by_owner.json()["message"]
    assert agent_page(hub, "C", action="unpin", name=PAGE).status_code == 200
    untouched = agent_page(hub, "C", action="archive", name=PAGE)
    assert untouched.status_code == 422
    assert "touched" in untouched.json()["message"]
    archived = agent_page(hub, "A", action="archive", name=PAGE)
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived"] is not None
    restored = owner.post(
        "/api/home/pages", json={"session": "C", "page": PAGE, "restore": True}
    )
    assert restored.status_code == 200, restored.text
    by_owner = owner.post(
        "/api/home/pages", json={"session": "C", "page": PAGE, "archive": True}
    )
    assert by_owner.status_code == 200, by_owner.text


def test_pool_cleanup_of_an_ended_session_keeps_the_pool_tree_hash(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    pool = shared_items_page(cli, repo)
    b = path_of(cli, "B", repo)
    draft = pool / f"dash.{b['tag']}.draft.html"
    draft.write_text("<p>b's draft</p>")
    comment(owner, "B")
    send(hub, "B")
    own = repo / ".agent-canvas" / "B"
    (own / "history").mkdir()
    (own / "history" / "old.txt").write_text("own history")
    assert cli("session", "end", "--session", "B", cwd=repo).code == 0
    before = tree_hash(pool, {draft})
    cleaned = cli("cleanup", "--session", "B", "--yes", cwd=repo)
    assert cleaned.code == 0, cleaned.err
    assert not own.exists()  # positive control: its own folder is removed
    assert not draft.exists()
    assert tree_hash(pool) == before
    assert str(draft) in cleaned.json["deleted"]
    assert all(
        not p.startswith(f"{pool}/") or p == str(draft) for p in cleaned.json["deleted"]
    )


def test_pool_every_page_route_called_as_b_writes_page_data_only_into_the_pool(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    hub.app.state.looks.headless = FakeHeadless()
    pool = shared_items_page(cli, repo)
    services = hub.app.state.services
    key = hub.key_headers
    base = f"{hub.base_url}/api/sessions/B"
    b = path_of(cli, "B", repo)
    (pool / f"dash.{b['tag']}.draft.html").write_text(ITEMS_PAGE + "<p>b</p>")
    assert cli("look", "dash", "--draft", "--session", "B", cwd=repo).code == 0
    assert cli("look", "dash", "--session", "B", cwd=repo).code == 0
    comment(owner, "B")
    edited = owner.post(
        "/api/sessions/B/comments/edit", json={"page": PAGE, "n": 1, "text": "units!"}
    )
    assert edited.status_code == 200, edited.text
    send(hub, "B")
    replied = httpx.post(
        f"{base}/comments/reply", json={"page": PAGE, "n": 1, "text": "ok"}, headers=key
    )
    assert replied.status_code == 200, replied.text
    done = httpx.post(
        f"{base}/comments/done", json={"page": PAGE, "n": [1]}, headers=key
    )
    assert done.status_code == 200, done.text
    for path, body in (
        ("answers/answer", {"page": PAGE, "id": "q1", "value": {"answer": "no"}}),
        ("answers/tick", {"page": PAGE, "id": "d1", "ticked": [1]}),
    ):
        answer = owner.post(f"/api/sessions/B/{path}", json=body)
        assert answer.status_code == 200, (path, answer.text)
    for action in ("pin", "unpin", "extend", "archive", "restore"):
        assert agent_page(hub, "B", action=action, name=PAGE).status_code == 200, action
    assert (
        agent_page(hub, "B", action="kind", name=PAGE, kind="single-use").status_code
        == 200
    )
    starred = owner.post(
        "/api/home/pages", json={"session": "B", "page": PAGE, "star": True}
    )
    assert starred.status_code == 200, starred.text
    hub.on_loop(
        lambda: seen_from_shell(services, {"session": "B", "page": PAGE, "version": 1})
    )
    shell_event = {
        "type": "event", "session": "B", "kind": "button", "page": PAGE,
        "value": {"label": "Go"}, "delivery": "now",
        "target": {"canvas_id": "go"},
    }  # fmt: skip
    made = hub.on_loop(
        lambda: event_from_shell(
            hub.state, services.events, shell_event, services.answers
        )
    )
    assert made is not None and made["for"] == "B"
    uploaded = owner.post(
        "/api/sessions/B/files",
        params={"name": "notes.md"},
        content=b"# Notes\n",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 200, uploaded.text
    (pool / "plan.md").write_text("# Plan\n")
    opened = owner.post("/api/sessions/B/open-file", json={"name": "plan.md"})
    assert opened.status_code == 200, opened.text
    for read in ("versions", "changes"):
        got = httpx.get(f"{base}/{read}", params={"page": PAGE}, headers=key)
        assert got.status_code == 200, (read, got.text)
    listed = httpx.get(f"{base}/sends", headers=key).json()["sends"]
    assert len(listed) == 1
    own = repo / ".agent-canvas" / "B"
    assert (own / "session.json").is_file()
    assert sorted(p.name for p in own.iterdir()) == ["session.json"]
    for found in (
        pool / ".comments" / f"{PAGE}.json",
        pool / ".answers" / f"{PAGE}.json",
        pool / "notes.md",
        pool / "events.jsonl",
    ):
        assert found.is_file(), found  # positive control: the data is in the pool
    assert list((pool / "history" / "sends").glob("*.json"))
    assert len(list((pool / "history" / "looks").glob("*.png"))) == 2
    record = json.loads((pool / "session.json").read_text())["page_meta"][PAGE]
    assert record["seen_version"] == 1 and record["starred"] is True
    assert record["kind"] == "single-use" and record["archived"] is None


def follow_a_daily_hub(hub, tmp_path: Path, repo: Path) -> Path:  # noqa: ANN001
    """Point the beside hub at a real daily state with a pool for ``repo``."""
    from agent_canvas.hub.registry import SessionRegistry, pool_key
    from agent_canvas.hub.state import HubState

    (tmp_path / "daily").mkdir()
    daily = SessionRegistry(tmp_path / "daily", HubState(1, "daily key", time.time))
    daily.create("D", str(repo), "claude-code", "D")
    pool = daily.folder_of(daily.pool_session(pool_key(str(repo))))
    registry = hub.app.state.registry
    registry.follow_file = tmp_path / "daily" / "sessions.json"
    assert hub.on_loop(registry.follow)
    return pool


@pytest.mark.hub_config(follow_state="/nonexistent/daily-state")
def test_pool_beside_mode_uses_the_daily_pool_and_makes_none(
    cli, hub, repo, home, tmp_path
) -> None:  # noqa: ANN001
    daily_pool = follow_a_daily_hub(hub, tmp_path, repo)
    assert Path(path_of(cli, "A", repo)["folder"]) == daily_pool
    other = home / "other"
    (other / ".git").mkdir(parents=True)
    refused = cli("session", "path", "--session", "B", cwd=other)
    assert refused.code == 1 and "beside" in refused.json["message"]
    assert not list(other.glob(".agent-canvas/pool-*"))
    assert not (hub.state_dir / "pool-tag").exists()


@pytest.mark.hub_config(follow_state="/nonexistent/daily-state")
def test_pool_beside_mode_refuses_publish(cli, hub, repo, tmp_path) -> None:  # noqa: ANN001
    follow_a_daily_hub(hub, tmp_path, repo)
    found = path_of(cli, "A", repo)
    pool = Path(found["folder"])
    refused = publish(cli, "A", repo, "<p>a1</p>")
    assert refused.code == 1
    assert "beside" in refused.json["message"]
    assert not (pool / PAGE).exists()
    assert (pool / f"dash.{found['tag']}.draft.html").is_file()
    outside = repo / "made.html"
    outside.write_text("<p>copied</p>")
    copied = cli("show", "--copy", str(outside), "--session", "A", cwd=repo)
    assert copied.code == 1 and "beside" in copied.json["message"]
    assert not (pool / "made.html").exists()
    (pool / "direct.html").write_text("<p>written</p>")
    shown = cli("show", "direct.html", "--session", "A", "--no-audit", cwd=repo)
    assert shown.code == 0, shown.err  # positive control: plain show still works


def test_pool_q4_the_pool_tab_lands_under_not_in_herdr(cli, hub, repo) -> None:  # noqa: ANN001
    assert publish(cli, "A", repo, "<p>a1</p>").code == 0
    pool_id = pool_of(hub, "A")
    herdr = hub.app.state.services.herdr_app
    view = hub.on_loop(herdr.snapshot)
    assert pool_id in view["other"] and "A" in view["other"]
    pool_tab = tab(hub, pool_id)
    assert pool_tab["title"] == repo.name and pool_tab["pages"] == [PAGE]
    served = httpx.get(hub.state.frame_url(pool_id, PAGE))
    assert served.status_code == 200 and b"<p>a1</p>" in served.content
    member = httpx.get(hub.state.frame_url("A", PAGE))
    assert member.status_code == 404


def window_tabs(hub) -> list[str]:  # noqa: ANN001
    return [t["id"] for t in hub.on_loop(hub.app.state.hub.tabs_provider)]


def test_pool_q4_a_pool_has_a_tab_only_while_it_has_a_live_page(cli, hub, repo) -> None:  # noqa: ANN001
    path_of(cli, "A", repo)
    pool_id = pool_of(hub, "A")
    herdr = hub.app.state.services.herdr_app
    assert pool_id is not None
    assert window_tabs(hub) == ["A"]  # the pool is made, but holds no page
    assert hub.on_loop(herdr.snapshot)["other"] == ["A"]
    assert publish(cli, "A", repo, "<p>a1</p>").code == 0
    assert window_tabs(hub) == ["A", pool_id]
    assert agent_page(hub, "A", action="archive", name=PAGE).status_code == 200
    assert window_tabs(hub) == ["A"]  # its only page is archived


def test_pool_03_the_load_report_of_a_cards_page_is_the_one_show_waits_for(
    cli, hub, repo
) -> None:  # noqa: ANN001
    assert publish(cli, "A", repo, "<p>a1</p>").code == 0
    shown = show(cli, "B", repo)
    assert shown.code == 0, shown.err
    state = hub.app.state.hub
    key = hub.on_loop(lambda: state.page_of_url(shown.json["url"]))
    assert key == (pool_of(hub, "B"), PAGE)
    hub.on_loop(lambda: state.reset_page_status(*key))
    hub.on_loop(lambda: state.record_page_report(shown.json["url"], "loaded", None))
    assert hub.on_loop(lambda: state.page_status(*key).loaded)
