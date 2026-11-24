"""The migration through the hub, at start, by command and in ``page list``.

POOL-09, #2. The old session folders are made with the hub's own registry, comment,
answer and page-history code, as a canvas before the pool left them.
"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
from tests.conftest import HubHandle
from tests.integration.test_mch_01_machine_link import Window, with_session

from agent_canvas.hub import clock, comments
from agent_canvas.hub.answers import AnswerStore
from agent_canvas.hub.migrate import LOG_NAME
from agent_canvas.hub.registry import SessionRegistry
from agent_canvas.hub.state import HubState
from agent_canvas.hub.watcher import PageHistory
from agent_canvas.output import CliError

pytestmark = pytest.mark.integration

ASK = (
    '<canvas-ask data-canvas-id="q1"><script type="application/json">'
    '{"question": "Keep it?", "options": ["keep", "change"]}</script></canvas-ask>'
)
DASH_A = f"<title>Dash</title><p>a2</p>{ASK}"


@pytest.fixture
def repo(home: Path) -> Path:
    """The project the ``cli`` fixture runs in, a git repository."""
    path = home / "proj"
    path.mkdir(exist_ok=True)
    (path / ".git").mkdir()
    return path


def old_page(
    registry: SessionRegistry, sid: str, repo: Path, name: str, versions: list[str]
) -> Path:
    """Write a page with its versions into a session's own folder, as before."""
    meta, _ = registry.ensure(sid, str(repo), "claude")
    folder = registry.folder_of(meta)
    for content in versions:
        PageHistory(folder).save(name, content.encode())
    (folder / name).write_text(versions[-1])
    registry._update(sid, pages=[*meta["pages"], name], active_page=name)
    registry.note_pages(sid)
    return folder


def made_at(folder: Path, name: str, seconds: int) -> None:
    """Give a page the recorded time the migration orders copies by."""
    path = folder / "session.json"
    document = json.loads(path.read_text())
    document["page_meta"][name]["counted_from"] = clock.iso(seconds)
    path.write_text(json.dumps(document))


def build_old(state_dir: Path, repo: Path) -> None:
    """A: dash.html (newest, two versions, a comment, an answer) and notes.html.

    B: an older dash.html that stays where it is.
    """
    registry = SessionRegistry(state_dir, HubState(1, "k", lambda: 0.0))
    registry.load()
    a = old_page(registry, "A", repo, "dash.html", ["<p>a1</p>", DASH_A])
    old_page(registry, "A", repo, "notes.html", ["<p>notes</p>"])
    b = old_page(registry, "B", repo, "dash.html", ["<p>b1</p>"])
    made_at(a, "dash.html", 2_000_000)
    made_at(b, "dash.html", 1_000_000)
    fields = {"kind": "text", "text": "from a", "anchor": {}, "page_version": 2}
    comments.create(a, "dash.html", fields)
    answers = AnswerStore(lambda sid: a, lambda sid: ["dash.html"], lambda *x: None)
    item = answers.item_of("A", "dash.html", "q1")
    answers.record(
        "A", "dash.html", item, state="answered", value="keep", event="evt_1",
        time=clock.iso(2_000_100),
    )  # fmt: skip


def tree_hash(root: Path, skip: Path | None = None) -> str:
    """Hash every name and content below ``root``, folders included."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if skip and (path == skip or skip in path.parents):
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        if path.is_file() and not path.is_symlink():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def pool_folder(hub: HubHandle, repo: Path) -> Path:
    registry = hub.app.state.registry
    return hub.on_loop(lambda: registry.pool_folder(str(repo)))


def settled(hub: HubHandle) -> None:
    """Wait until the hub's first scan of the watched folders is done."""
    watcher = hub.app.state.watcher
    hub.wait_for(lambda: hub.on_loop(watcher.scanned.is_set), timeout=10)


def owner_get(window: Window, hub: HubHandle, path: str) -> dict:
    headers = {"Cookie": window.cookie, "Origin": hub.base_url}
    answer = httpx.get(hub.base_url + path, headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_pool_09_hub_start_moves_old_pages_into_the_right_cards_once_and_keeps_old_folders(  # noqa: E501
    hub: HubHandle, repo: Path, cli
) -> None:  # noqa: ANN001
    canvas = repo / ".agent-canvas"
    hub.restart(between=lambda: build_old(hub.state_dir, repo))
    settled(hub)
    pool = pool_folder(hub, repo)
    old = tree_hash(canvas, skip=pool)
    assert (pool / "dash.html").read_text() == DASH_A
    window = Window(hub)
    tabs = {t["id"]: t for t in window.wait(with_session("A"))["sessions"]}
    assert sorted(tabs["A"]["pages"]) == ["dash.html", "notes.html"]  # newest first
    assert tabs["B"]["pages"] == []  # its older copy stayed in its own folder
    assert tabs["A"]["pool"] == tabs["B"]["pool"] is not None
    listed = owner_get(window, hub, "/api/sessions/A/comments?page=dash.html")
    assert [c["text"] for c in listed["comments"]] == ["from a"]
    versions = owner_get(window, hub, "/api/sessions/A/versions?page=dash.html")
    assert [v["version"] for v in versions["versions"]] == [1, 2]
    store = AnswerStore(lambda sid: pool, lambda sid: ["dash.html"], lambda *x: None)
    assert store.entries("A", "dash.html")["q1"]["value"] == "keep"
    left = cli("page", "list", "--session", "B", cwd=repo)
    assert left.code == 0, left.err
    assert left.json["left_behind"] == [
        {"page": "dash.html", "session": "B", "why": "older",
         "folder": str(canvas / "B")},
    ]  # fmt: skip
    window.socket.close()

    log = (pool / LOG_NAME).read_text()
    pooled = tree_hash(pool, skip=pool / "session.json")
    record = json.loads((pool / "session.json").read_text())["page_meta"]
    hub.restart()
    settled(hub)
    assert tree_hash(canvas, skip=pool) == old
    assert (pool / LOG_NAME).read_text() == log
    assert tree_hash(pool, skip=pool / "session.json") == pooled
    assert json.loads((pool / "session.json").read_text())["page_meta"] == record


@pytest.mark.hub_config(follow_state="/nonexistent/daily-state")
def test_pool_09_hub_start_migrates_once_and_beside_mode_does_not(
    hub: HubHandle, repo: Path
) -> None:
    hub.restart(between=lambda: build_old(hub.state_dir, repo))
    settled(hub)
    assert not list((repo / ".agent-canvas").glob("pool-*"))
    assert hub.on_loop(lambda: hub.app.state.registry.pool_of("A")) is None


def test_pool_09_pages_migrate_shows_the_plan_and_applies_it_with_yes(
    hub: HubHandle, repo: Path, cli
) -> None:  # noqa: ANN001
    registry = hub.app.state.registry
    folder = hub.on_loop(
        lambda: old_page(registry, "A", repo, "dash.html", ["<p>a1</p>"])
    )
    settled(hub)
    before = tree_hash(repo / ".agent-canvas")
    plan = cli("pages", "migrate", "--project", str(repo), cwd=repo)
    assert plan.code == 0, plan.err
    assert plan.json["moves"] == [{"page": "dash.html", "session": "A", "files": 2}]
    assert tree_hash(repo / ".agent-canvas") == before
    assert not list((repo / ".agent-canvas").glob("pool-*"))
    done = cli("pages", "migrate", "--project", str(repo), "--yes", cwd=repo)
    assert done.code == 0, done.err
    assert done.json["moved"] == ["A/dash.html"]
    pool = pool_folder(hub, repo)
    assert (pool / "dash.html").read_text() == "<p>a1</p>"
    assert (folder / "dash.html").read_text() == "<p>a1</p>"  # the old one stays
    listed = cli("page", "list", "--session", "A", cwd=repo)
    assert [p["name"] for p in listed.json["pages"]] == ["dash.html"]
    assert "left_behind" not in listed.json


def test_pool_09_the_migrate_route_takes_only_a_project_this_hub_knows(
    hub: HubHandle, repo: Path, home: Path
) -> None:
    registry = hub.app.state.registry
    hub.on_loop(lambda: old_page(registry, "A", repo, "dash.html", ["<p>a1</p>"]))

    def migrate(project: str) -> httpx.Response:
        return httpx.post(
            f"{hub.base_url}/api/pages/migrate",
            json={"project": project, "yes": False},
            headers=hub.key_headers,
        )

    (repo / "sub").mkdir()
    planned = migrate(f"{repo}/sub/..")  # resolved to the known project
    assert planned.status_code == 200, planned.text
    assert planned.json()["project"] == str(repo)
    stranger = home / "stranger"
    (stranger / ".git").mkdir(parents=True)
    refused = migrate(str(stranger))
    assert refused.status_code == 422
    assert "No session" in refused.json()["message"]
    assert not (stranger / ".agent-canvas").exists()


def test_pool_09_a_second_hub_started_during_a_slow_migration_does_not_migrate(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_canvas.client import HubClient
    from agent_canvas.config import Config
    from agent_canvas.hub import app as hub_app

    entered, release = threading.Event(), threading.Event()
    runs: list[str] = []

    def slow_migration(registry) -> None:  # noqa: ANN001
        runs.append(threading.current_thread().name)
        entered.set()
        release.wait(20)

    monkeypatch.setattr(hub_app, "migrate_at_start", slow_migration)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = Config(port=port, open_window=False, show_audit=False)
    state = clean_env / "state"
    first = threading.Thread(
        target=hub_app.run_hub, args=(config, state), name="first", daemon=True
    )
    first.start()
    try:
        assert entered.wait(10)
        client = HubClient(config, state)
        assert client._probe() == "busy"  # the port is held, the hub not yet serving
        with pytest.raises(CliError, match="does not answer yet"):
            client.ensure_hub()  # a client starts no second hub meanwhile
        with pytest.raises(OSError):
            hub_app.run_hub(config, state)  # a second hub stops before migrating
        assert runs == ["first"]
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while client._probe() != "ok":
        assert time.monotonic() < deadline, "the first hub never served"
        time.sleep(0.05)
    client.request("POST", "/api/shutdown", {}, start=False)
    first.join(10)
    assert not first.is_alive()
