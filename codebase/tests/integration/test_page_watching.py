"""Page watching, history versions and the show report (HUB-05, HIST, CLI-03)."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from pathlib import Path

import httpx
import pytest
from websockets.sync.client import connect

pytestmark = pytest.mark.integration


class FakeShell:
    """A WebSocket client that behaves like the owner's shell (cookie login)."""

    def __init__(self, hub) -> None:  # noqa: ANN001
        cookies = httpx.get(hub.login_url(), follow_redirects=False).cookies
        header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        self.socket = connect(
            f"ws://127.0.0.1:{hub.port}/ws/shell",
            origin=hub.base_url,
            additional_headers={"Cookie": header},
        )
        self.messages: queue.Queue[dict] = queue.Queue()
        self.auto_report: dict | None = None
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        try:
            for raw in self.socket:
                message = json.loads(raw)
                self.messages.put(message)
                if message["type"] == "show" and self.auto_report is not None:
                    self.socket.send(
                        json.dumps({**self.auto_report, "url": message["url"]})
                    )
        except Exception:  # noqa: BLE001 - socket closed at teardown
            return

    def updates(self, wait: float) -> list[dict]:
        """Collect ``update`` messages arriving within ``wait`` seconds."""
        found: list[dict] = []
        deadline = time.monotonic() + wait
        while (left := deadline - time.monotonic()) > 0:
            try:
                message = self.messages.get(timeout=left)
            except queue.Empty:
                break
            if message["type"] == "update":
                found.append(message)
        return found

    def close(self) -> None:
        self.socket.close()


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    fake = FakeShell(hub)
    yield fake
    fake.close()


def write_in_chunks(path: Path, chunks: list[str], gap: float = 0.02) -> None:
    with open(path, "w") as handle:  # truncates first, like many editors
        for chunk in chunks:
            handle.write(chunk)
            handle.flush()
            time.sleep(gap)


def test_hub_05_chunked_write_gives_exactly_one_complete_update(hub, shell) -> None:
    session = hub.add_session("w")
    chunks = [f"<p>part {i}</p>\n" * 50 for i in range(4)]
    write_in_chunks(session.folder / "page.html", chunks)
    updates = shell.updates(1.5)
    assert len(updates) == 1
    assert updates[0]["html"] == "".join(chunks)
    assert updates[0]["url"] == hub.page_url("w", "page.html")
    assert updates[0]["version"] == 1


def test_hub_05_hub_own_writes_and_ignored_files_give_no_update(hub, shell) -> None:
    session = hub.add_session("o")
    folder = session.folder
    (folder / "page.html").write_text("<p>one</p>")
    assert len(shell.updates(1.0)) == 1
    (folder / "events.jsonl").write_text("{}\n")
    (folder / "session.json").write_text("{}")
    (folder / ".hidden.html").write_text("<p>dot</p>")
    (folder / "notes.txt").write_text("text")
    (folder / "sub").mkdir()
    (folder / "sub" / "deep.html").write_text("<p>deep</p>")
    (folder / "history" / "sends").mkdir(parents=True)
    (folder / "history" / "sends" / "0001.json").write_text("{}")
    (folder / "history" / "pages" / "x.0009.html").parent.mkdir(exist_ok=True)
    (folder / "history" / "pages" / "x.0009.html").write_text("<p>h</p>")
    assert shell.updates(1.0) == []


def test_hub_05_identical_rewrite_and_empty_file_give_no_update(hub, shell) -> None:
    session = hub.add_session("i")
    page = session.folder / "page.html"
    page.write_text("<p>same</p>")
    assert len(shell.updates(1.0)) == 1
    page.write_text("<p>same</p>")
    assert shell.updates(1.0) == []
    page.write_text("")
    assert shell.updates(1.0) == []
    page.write_text("<p>same</p>")  # back to the last non-empty content
    assert shell.updates(1.0) == []


def test_hub_05_other_pages_update_with_their_own_url(hub, shell) -> None:
    session = hub.add_session("m")
    (session.folder / "b.html").write_text("<p>b</p>")
    (update,) = shell.updates(1.0)
    assert update["url"] == hub.page_url("m", "b.html")


def test_hub_05_watch_uses_lowered_debounce_and_step(monkeypatch, tmp_path) -> None:
    from agent_canvas.hub import watcher

    seen: dict = {}

    async def fake_awatch(*paths, **kwargs):  # noqa: ANN002, ANN003, ANN202
        seen.update(kwargs)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(watcher, "awatch", fake_awatch)
    # A fresh thread: a browser test earlier in the session may leave a running
    # event loop in the main thread, where asyncio.run would refuse to start.
    runner = threading.Thread(
        target=lambda: asyncio.run(
            watcher.watch_folder(tmp_path, lambda changed: None, asyncio.Event())
        )
    )
    runner.start()
    runner.join(timeout=10)
    assert (seen["debounce"], seen["step"]) == (200, 20)


def test_hist_01_three_writes_with_one_duplicate_give_two_versions(hub, shell) -> None:
    session = hub.add_session("h")
    page = session.folder / "page.html"
    saved = session.folder / "history" / "pages"
    for text, count in (("<p>A</p>", 1), ("<p>B</p>", 2)):
        page.write_text(text)
        hub.wait_for(lambda: len(list(saved.glob("page.*.html"))) == count, timeout=15)
    page.write_text("<p>B</p>")
    time.sleep(0.7)  # a third version, if one were coming, has been saved by now
    versions = sorted(saved.glob("page.*.html"))
    assert [v.name for v in versions] == ["page.0001.html", "page.0002.html"]
    assert [v.read_text() for v in versions] == ["<p>A</p>", "<p>B</p>"]
    assert [u["version"] for u in shell.updates(0.1)] == [1, 2]


def test_hist_01_versions_are_per_page_and_continue_after_restart(hub) -> None:
    session = hub.add_session("c")
    (session.folder / "a.html").write_text("<p>1</p>")
    (session.folder / "b.html").write_text("<p>1</p>")
    pages = session.folder / "history" / "pages"
    hub.wait_for(lambda: pages.is_dir() and len(list(pages.iterdir())) == 2, timeout=15)
    assert sorted(p.name for p in pages.iterdir()) == ["a.0001.html", "b.0001.html"]
    # A new watcher continues numbering and does not re-save known content.
    from agent_canvas.hub.watcher import PageHistory

    history = PageHistory(session.folder)
    assert history.latest("a.html") == (1, "<p>1</p>".encode())
    assert history.save("a.html", b"<p>1</p>") is None
    assert history.save("a.html", b"<p>2</p>") == 2


def test_hub_04_restart_resumes_watching_and_pushes_updates(cli, hub) -> None:
    import uvicorn

    from agent_canvas.config import Config
    from agent_canvas.hub.app import create_app

    sid = cli("session", "start").json["session"]
    folder = Path(cli("session", "path", "--session", sid).json["folder"])
    hub.server.should_exit = True
    hub.thread.join(timeout=10)
    assert not hub.thread.is_alive()

    # A second hub on the same state directory and port, as after a restart.
    import socket

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", hub.port))
    sock.listen(8)
    app = create_app(Config(port=hub.port), hub.state_dir)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="warning", ws="websockets-sansio")
    )
    thread = threading.Thread(
        target=lambda: asyncio.run(server.serve(sockets=[sock])), daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    try:
        hub.app = app  # login_url() reads the new in-memory state
        shell = FakeShell(hub)
        (folder / "page.html").write_text("<p>after restart</p>")
        (update,) = shell.updates(2.0)
        assert update["html"] == "<p>after restart</p>"
        shell.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def test_hist_04_a_hub_start_and_every_command_delete_only_old_page_versions(
    cli, hub
) -> None:
    """60-day-old history survives, except page versions HIST-86 lets go."""
    sid = cli("session", "start").json["session"]
    folder = Path(cli("session", "path", "--session", sid).json["folder"])
    history = folder / "history" / "pages"
    history.mkdir(parents=True)
    (folder / "history" / "sends").mkdir()
    (folder / "history" / "looks").mkdir()
    old = time.time() - 60 * 86400
    pruned = history / "page.0001.html"
    files = [
        history / "page.0002.html",
        folder / "history" / "sends" / "0001.json",
        folder / "history" / "sends" / "0001.png",
        folder / "history" / "looks" / "page.0001.png",
        folder / "history" / "notes.txt",
    ]
    for path in [pruned, *files]:
        path.write_text("<p>x</p>" if path == files[0] else "old")
        os.utime(path, (old, old))
    (folder / "page.html").write_text("<p>x</p>")
    cli("show", "--session", sid)
    hub.restart()
    deadline = time.monotonic() + 10
    while pruned.exists():
        assert time.monotonic() < deadline, "the start round kept an old version"
        time.sleep(0.05)
    cli("status")
    cli("session", "list", "--all")
    cli("session", "set", "--session", sid, "--title", "t")
    cli("show", "--session", sid)
    cli("session", "end", "--session", sid)
    for path in files:
        assert path.read_text() == ("<p>x</p>" if path == files[0] else "old")
        assert abs(path.stat().st_mtime - old) < 1


def post_show(hub, sid: str, project: Path) -> dict:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/show",
        headers=hub.key_headers,
        json={"project": str(project)},
        timeout=15,
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def new_session(hub, home: Path) -> tuple[str, Path]:  # noqa: ANN001
    project = home / "proj"
    project.mkdir(exist_ok=True)
    answer = httpx.post(
        f"{hub.base_url}/api/sessions",
        headers=hub.key_headers,
        json={"project": str(project)},
    )
    return answer.json()["session"], Path(answer.json()["folder"])


def test_cli_03_show_returns_real_version_and_false_rendered_without_window(
    hub, home
) -> None:
    sid, folder = new_session(hub, home)
    page = folder / "page.html"
    page.write_text("<p>1</p>")
    first = post_show(hub, sid, home / "proj")
    assert (first["version"], first["rendered"], first["errors"]) == (1, False, [])
    page.write_text("<p>2</p>")
    assert post_show(hub, sid, home / "proj")["version"] == 2
    assert post_show(hub, sid, home / "proj")["version"] == 2  # unchanged


def test_cli_03_show_is_pending_when_a_shell_does_not_report_a_load(hub, home) -> None:
    sid, folder = new_session(hub, home)
    (folder / "page.html").write_text("<p>1</p>")
    shell = FakeShell(hub)
    try:
        started = time.monotonic()
        answer = post_show(hub, sid, home / "proj")
        assert answer["rendered"] == "pending"
        assert 1.8 < time.monotonic() - started < 4
    finally:
        shell.close()


def test_cli_03_show_waits_for_load_and_lists_errors(hub, home) -> None:
    sid, folder = new_session(hub, home)
    (folder / "page.html").write_text("<p>1</p>")
    shell = FakeShell(hub)
    error = {
        "source": "script",
        "message": "x is not defined",
        "line": 12,
        "canvas_id": None,
    }

    def reply(url: str) -> None:
        shell.socket.send(
            json.dumps(
                {"type": "page-report", "url": url, "name": "error", "data": error}
            )
        )
        shell.socket.send(
            json.dumps(
                {"type": "page-report", "url": url, "name": "loaded", "data": {}}
            )
        )

    def pump() -> None:
        while True:
            message = shell.messages.get()
            if message["type"] == "show":
                reply(message["url"])
                return

    threading.Thread(target=pump, daemon=True).start()
    try:
        started = time.monotonic()
        answer = post_show(hub, sid, home / "proj")
        assert time.monotonic() - started < 1.5
        assert answer["rendered"] is True
        assert answer["errors"] == [error]
    finally:
        shell.close()


def _ended_session_with_page(cli, shell) -> tuple[str, Path]:  # noqa: ANN001
    """Start a session, see version 1 of its page, end it; return id and folder."""
    sid = cli("session", "start").json["session"]
    folder = Path(cli("session", "path", "--session", sid).json["folder"])
    (folder / "page.html").write_text("<p>one</p>")
    assert [u["version"] for u in shell.updates(1.5)] == [1]
    assert cli("session", "end", "--session", sid).code == 0
    time.sleep(0.5)
    return sid, folder


def test_ses_08_an_agent_call_on_an_ended_session_watches_it_again(
    cli, hub, shell
) -> None:
    sid, folder = _ended_session_with_page(cli, shell)
    assert cli("session", "path", "--session", sid).code == 0
    (folder / "page.html").write_text("<p>two</p>")
    assert [u["version"] for u in shell.updates(2.0)] == [2]


def test_ses_08_a_show_on_an_ended_session_watches_it_again(cli, hub, shell) -> None:
    sid, folder = _ended_session_with_page(cli, shell)
    assert cli("show", "--session", sid).code == 0
    shell.updates(1.0)
    (folder / "page.html").write_text("<p>two</p>")
    assert [u["version"] for u in shell.updates(2.0)] == [2]


def test_ses_08_an_ask_on_an_ended_session_watches_it_again(cli, hub, shell) -> None:
    from test_ans_answers import spawn

    sid, folder = _ended_session_with_page(cli, shell)
    process = spawn(cli, "ask", "Which?", "--choice", "A", "--session", sid)
    try:
        hub.wait_for_ask(sid)
        (folder / "page.html").write_text("<p>two</p>")
        assert [u["version"] for u in shell.updates(2.0)] == [2]
    finally:
        process.kill()


def test_cli_14_a_watch_does_not_revive_an_ended_session(cli, hub, shell) -> None:
    sid, folder = _ended_session_with_page(cli, shell)
    cli("watch", "--session", sid, "--timeout", "1")
    (folder / "page.html").write_text("<p>two</p>")
    assert shell.updates(1.0) == []
