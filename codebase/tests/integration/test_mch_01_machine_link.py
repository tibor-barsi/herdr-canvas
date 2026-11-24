"""Other machines' canvases through this hub (multi-machine contract, package S2).

Two hubs run in this process: the test ``hub`` ("this hub") and a "remote" hub on
another local port. A fake ``hc`` lists one machine ``rem`` and answers ``exec``
from files; no SSH forward runs (``machines.FORWARD = None``).
"""

from __future__ import annotations

import asyncio
import http.client
import json
import queue
import stat
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from tests.conftest import FakeClock, HubHandle, _free_socket
from websockets.sync.client import connect

from agent_canvas.hub import machines

pytestmark = pytest.mark.integration

FAKE_HC = r"""
import http.client, json, sys
from pathlib import Path
folder = Path(__file__).parent
args = sys.argv[1:]
with open(folder / "calls.log", "a") as log:
    log.write(" ".join(args) + "\n")
if args[:2] == ["machine", "ls"]:
    print((folder / "machines.json").read_text())
    sys.exit(0)
name, command = args[2], args[4:]
if (folder / f"{name}.down").exists():
    sys.stderr.write(json.dumps({"error": {"kind": "unreachable", "message": "x"}}))
    sys.exit(4)
if (folder / f"{name}.missing").exists():
    sys.stderr.write(json.dumps({"error": {"kind": "spawn_failed", "message": "x"}}))
    sys.exit(1)
status = json.loads((folder / f"{name}.status").read_text())
if command == ["status"]:
    print(json.dumps(status))
    sys.exit(0)
key = (folder / f"{name}.key").read_text().strip()
connection = http.client.HTTPConnection("127.0.0.1", status["hub_port"])
connection.request("POST", "/api/open", json.dumps({"print_url": True}),
                   {"X-Agent-Canvas-Key": key, "Content-Type": "application/json"})
print(json.loads(connection.getresponse().read())["url"])
"""


def start_remote(tmp_path: Path) -> HubHandle:
    """Start a second hub in this process; the handle the ``hub`` fixture gives."""
    import uvicorn

    from agent_canvas.config import Config
    from agent_canvas.hub.app import create_app

    root = tmp_path / "remote"
    state_dir, config_dir, project_dir = (root / n for n in ("state", "c", "p"))
    for directory in (config_dir, project_dir):
        directory.mkdir(parents=True)
    sock = _free_socket()
    port = sock.getsockname()[1]
    config = Config(port=port, open_window=False, show_audit=False)
    clock = FakeClock()

    def respawn(listening):  # noqa: ANN001, ANN202
        app = create_app(config, state_dir, clock=clock)
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", ws="websockets-sansio")
        )
        thread = threading.Thread(
            target=lambda: asyncio.run(server.serve(sockets=[listening])), daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "remote hub did not start"
            time.sleep(0.01)
        return app, server, thread

    app, server, thread = respawn(sock)
    key = (state_dir / "key").read_text().strip()
    return HubHandle(
        port, state_dir, config_dir, project_dir, root, clock, app, server, thread,
        key, sock, respawn,
    )  # fmt: skip


class Link:
    """The remote hub and the files that steer the fake ``hc``."""

    def __init__(self, remote: HubHandle, folder: Path) -> None:
        self.remote = remote
        self.folder = folder

    def status(self, port: int) -> None:
        """Make ``agent-canvas status`` on ``rem`` report ``port``."""
        answer = {"hub": "running", "version": "0.4.0", "port": port}
        (self.folder / "rem.status").write_text(
            json.dumps({**answer, "hub_port": self.remote.port})
        )

    def flag(self, name: str, on: bool) -> None:
        """Set or clear ``rem.down`` / ``rem.missing``."""
        path = self.folder / f"rem.{name}"
        if on:
            path.touch()
        else:
            path.unlink(missing_ok=True)

    def session(self, html: str = "<p>v1</p>") -> tuple[str, Path]:
        """Create a session with ``page.html`` on the remote hub and show it."""
        base = self.remote.base_url
        headers = self.remote.key_headers
        project = self.folder / "proj"
        project.mkdir(exist_ok=True)
        made = httpx.post(
            f"{base}/api/sessions", headers=headers, json={"project": str(project)}
        ).json()
        folder = Path(made["folder"])
        (folder / "page.html").write_text(html)
        shown = httpx.post(
            f"{base}/api/sessions/{made['session']}/show",
            headers=headers,
            json={"project": str(project)},
            timeout=15,
        )
        assert shown.status_code == 200, shown.text
        return made["session"], folder


@pytest.fixture
def link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Link]:
    """A remote hub, a fake ``hc`` naming it ``rem``; ask for it before ``hub``."""
    folder = tmp_path / "fake-hc"
    folder.mkdir()
    script = folder / "hc"
    script.write_text(f"#!{sys.executable}\n{FAKE_HC}")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    machine = {"name": "rem", "target": "rem", "state": "connected"}
    (folder / "machines.json").write_text(json.dumps({"machines": [machine]}))
    remote = start_remote(tmp_path)
    (folder / "rem.key").write_text(remote.key)
    monkeypatch.setattr(machines, "HC", str(script))
    monkeypatch.setattr(machines, "FORWARD", None)
    monkeypatch.setattr(machines, "MAX_BACKOFF_SECONDS", 0.3)
    found = Link(remote, folder)
    found.status(remote.port)
    yield found
    remote.stop()


class Window:
    """The owner's window on this hub: a cookie WebSocket that keeps every message."""

    def __init__(self, hub: HubHandle) -> None:
        cookies = httpx.get(hub.login_url(), follow_redirects=False).cookies
        self.cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())
        self.socket = connect(
            f"ws://127.0.0.1:{hub.port}/ws/shell",
            origin=hub.base_url,
            additional_headers={"Cookie": self.cookie},
            max_size=None,
        )
        self.messages: queue.Queue[dict] = queue.Queue()
        self.seen: list[dict] = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        try:
            for raw in self.socket:
                self.messages.put(json.loads(raw))
        except Exception:  # noqa: BLE001 - closed at teardown
            return

    def wait(self, test: Callable[[dict], bool], timeout: float = 10) -> dict:
        """Return the first new message passing ``test``."""
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            try:
                message = self.messages.get(timeout=left)
            except queue.Empty:
                break
            self.seen.append(message)
            if test(message):
                return message
        raise AssertionError("no such message")

    def send(self, message: dict) -> None:
        self.socket.send(json.dumps(message))


def machine_entry(message: dict) -> dict | None:
    """The ``rem`` entry of a ``herdr`` message."""
    if message["type"] != "herdr":
        return None
    return next((m for m in message["machines"] if m["name"] == "rem"), None)


def in_state(state: str) -> Callable[[dict], bool]:
    return lambda m: (machine_entry(m) or {}).get("state") == state


def with_session(session: str) -> Callable[[dict], bool]:
    return lambda m: (
        m["type"] == "tabs" and any(t["id"] == session for t in m["sessions"])
    )


def test_mch_01_remote_sessions_updates_comments_and_send_pass_through(
    link: Link, hub: HubHandle, tmp_path: Path
) -> None:
    remote_id, folder = link.session()
    local = httpx.post(
        f"{hub.base_url}/api/sessions",
        headers=hub.key_headers,
        json={"project": str(tmp_path)},
    ).json()["session"]
    window = Window(hub)
    tabs = window.wait(with_session(remote_id))
    by_id = {t["id"]: t for t in tabs["sessions"]}
    assert by_id[remote_id]["machine"] == "rem"
    assert by_id[remote_id]["base"].startswith(f"http://localhost:{link.remote.port}/")
    assert by_id[local]["machine"] is None
    pool = by_id[remote_id]["pool"]  # the project's pool is a tab of its own (Q4)
    assert pool.startswith("project-") and by_id[pool]["machine"] == "rem"
    entry = machine_entry(window.wait(in_state("online")))
    entry["other"] = sorted(entry["other"])
    assert entry == {"name": "rem", "state": "online", "detail": None,
                     "other": sorted([remote_id, pool])}  # fmt: skip

    (folder / "page.html").write_text("<p>v2 remote</p>")
    update = window.wait(lambda m: m["type"] == "update" and "v2" in m["html"])
    assert f":{link.remote.port}/" in update["url"]

    owner = {"Cookie": window.cookie, "Origin": hub.base_url}
    comment = {
        "page": "page.html", "kind": "rect", "text": "routed comment",
        "anchor": {"space": "page-px", "x": 1, "y": 1, "w": 20, "h": 20,
                   "fx": 0, "fy": 0, "fw": 0.1, "fh": 0.1},
        "target": {"canvas_id": None, "selector": "html", "text": "v2"},
        "page_version": 2, "picture_error": "test: no picture",
    }  # fmt: skip
    path = f"/api/sessions/{remote_id}/comments"
    saved = httpx.post(hub.base_url + path, json=comment, headers=owner)
    assert saved.status_code == 200, saved.text
    assert saved.json()["text"] == "routed comment"
    # a GET goes there too: the window's own comment list of the remote page
    stored = httpx.get(f"{hub.base_url}{path}?page=page.html", headers=owner).json()
    assert [c["text"] for c in stored["comments"]] == ["routed comment"]
    # an agent's key is never passed to another machine
    keyed = httpx.post(hub.base_url + path, json=comment, headers=hub.key_headers)
    assert keyed.status_code == 403  # this hub's own refusal: owner only
    again = httpx.get(f"{hub.base_url}{path}?page=page.html", headers=owner).json()
    assert len(again["comments"]) == 1

    window.send({"type": "comments-get", "session": remote_id, "page": "page.html"})
    got = window.wait(lambda m: m["type"] == "comments" and m["session"] == remote_id)
    assert got["comments"][0]["text"] == "routed comment"

    send = {
        "delivery": "now", "message": "routed send", "page": "page.html",
        "pages": [], "actions": [], "actions_dropped": 0,
        "viewport": {"width": 900, "height": 500, "scroll_x": 0, "scroll_y": 0},
        "screenshot": None, "screenshot_error": "test: no screenshot",
        "screenshot_warnings": [],
    }  # fmt: skip
    sent = httpx.post(f"{hub.base_url}/api/sessions/{remote_id}/send",
                      json=send, headers=owner)  # fmt: skip
    assert sent.status_code == 200, sent.text
    state = window.wait(lambda m: m["type"] == "send-state")
    assert state["session"] == remote_id
    on_remote = link.remote.on_loop(
        lambda: link.remote.state.events.latest_send(remote_id)
    )
    assert on_remote == state["send"] and on_remote["delivery"] == "now"
    hellos = [m for m in window.seen if m["type"] == "hello"]
    assert [m["build"] for m in hellos] == [hub.state.build_id]  # this hub's only
    window.socket.close()


def test_mch_02_remote_hello_render_and_herdr_never_reach_the_window() -> None:
    sent: list[dict] = []

    class Channel:
        def broadcast(self, message: dict) -> None:
            sent.append(message)

        def publish(self, view: str) -> None:
            pass

    class State:
        channel = Channel()
        port = 1

    links = machines.Machines(State())  # type: ignore[arg-type]
    machine = machines.Machine("rem", "rem", True, state="online")
    for kind in ("hello", "render", "herdr", "made-up"):
        links._receive(machine, {"type": kind})
    links._receive(machine, {"type": "listening", "session": "x"})
    tab = {"id": "x"}
    links._receive(machine, {"type": "show", "session": "x", "tab": tab})
    assert [m["type"] for m in sent] == ["listening", "show"]
    assert sent[1]["tab"] == {"id": "x", "machine": "rem"}


def test_mch_03_link_drop_goes_offline_and_back_resends_tabs(
    link: Link, hub: HubHandle
) -> None:
    remote_id, _ = link.session()
    window = Window(hub)
    window.wait(in_state("online"))
    link.flag("down", True)
    offline: list[dict] = []
    link.remote.restart(lambda: offline.append(window.wait(in_state("offline"))))
    assert "retrying" in machine_entry(offline[0])["detail"]
    link.flag("down", False)
    mark = len(window.seen)
    window.wait(in_state("online"), timeout=15)
    tabs = [m for m in window.seen[mark:] if with_session(remote_id)(m)][-1]
    machines_of = {t["id"]: t["machine"] for t in tabs["sessions"]}
    pool = next(t["pool"] for t in tabs["sessions"] if t["id"] == remote_id)
    assert machines_of == {remote_id: "rem", pool: "rem"}  # with its pool (Q4)


def test_mch_04_port_clash_and_no_canvas_say_why(link: Link, hub: HubHandle) -> None:
    link.status(hub.port)
    window = Window(hub)
    clash = machine_entry(window.wait(in_state("port-clash")))
    assert f"port {hub.port}" in clash["detail"]
    assert "config.toml" in clash["detail"]
    link.flag("missing", True)
    missing = machine_entry(window.wait(in_state("no-canvas")))
    assert missing["detail"] == "agent-canvas is not installed on rem."


def test_mch_05_no_machines_leaves_this_hub_as_it_was(
    hub: HubHandle, tmp_path: Path
) -> None:
    sid = httpx.post(
        f"{hub.base_url}/api/sessions",
        headers=hub.key_headers,
        json={"project": str(tmp_path)},
    ).json()["session"]
    window = Window(hub)
    tabs = window.wait(with_session(sid))
    machines_of = {t["id"]: t["machine"] for t in tabs["sessions"]}
    assert machines_of == {sid: None}  # its pool holds no page, so no tab (A-1144)
    herdr = window.wait(lambda m: m["type"] == "herdr")
    assert herdr["machines"] == []
    connection = http.client.HTTPConnection("127.0.0.1", hub.port)
    connection.request("GET", f"/api/sessions/{sid}", headers=hub.key_headers)
    assert connection.getresponse().status == 200
