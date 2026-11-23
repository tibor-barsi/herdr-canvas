"""Shared fixtures: a real hub on a free port with temporary directories (TST-01).

The hub runs in a background thread of the test process so that tests can reach
its state directly (register sessions, mint login tokens, move the clock) while
talking to it over real sockets.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import signal
import socket
import stat
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """Run ``-n auto`` on up to 20 workers; e2e runs (real agents) one at a time."""
    markers = config.getoption("markexpr") or ""
    if "e2e" in markers and "not e2e" not in markers:
        return 0
    return min(20, os.cpu_count() or 1)


@pytest.fixture(autouse=True)
def no_window_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a test find ``systemd-run`` or ``uwsm`` for the window launch."""
    monkeypatch.setattr("agent_canvas.hub.window._which", lambda name: None)


@pytest.fixture(autouse=True)
def no_real_herdr(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never let a test (or a hub it starts) reach the owner's real herdr."""
    # a `herdr-app` that always fails: the hub's Herdr link then reads "not running"
    folder = tmp_path_factory.mktemp("no-herdr-app-bin")
    fake = folder / "herdr-app"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{folder}:{os.environ['PATH']}")
    # without these no hook event names a pane, so no hub calls herdr or hyprctl
    for name in [n for n in os.environ if n.startswith("HERDR_")]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def no_real_notifications(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never let a test (or a hub it starts) reach the owner's desktop (NTF-01)."""
    # a stand-in `notify-send` first on PATH, also for hubs started as subprocesses;
    # outside tmp_path, which many tests list
    folder = tmp_path_factory.mktemp("no-notify-bin")
    fake = folder / "notify-send"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{folder}/stray-notifications.txt"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{folder}:{os.environ['PATH']}")
    monkeypatch.setenv("AGENT_CANVAS_NOTIFY_COMMAND", str(fake))


@pytest.fixture
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate HOME, XDG and AGENT_CANVAS_* variables; return the fake home."""
    for name in list(os.environ):
        if name.startswith("AGENT_CANVAS_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    return tmp_path


class FakeClock:
    """A controllable monotonic clock for token-expiry tests (SEC-04)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class HubHandle:
    """A running test hub and the directories it uses."""

    port: int
    state_dir: Path
    config_dir: Path
    project_dir: Path
    recorder: Path
    clock: FakeClock
    app: object
    server: object
    thread: threading.Thread
    key: str
    sock: socket.socket | None = None
    respawn: Callable[[socket.socket], tuple] | None = None
    sessions: dict[str, object] = field(default_factory=dict)
    project_dir_name: str = ".agent-canvas"
    notify_log: Path | None = None

    @property
    def state(self):  # noqa: ANN201
        """The hub's in-memory state object."""
        return self.app.state.hub

    @property
    def base_url(self) -> str:
        """Shell origin (owner window)."""
        return f"http://127.0.0.1:{self.port}"

    @property
    def frame_origin(self) -> str:
        """Frame site origin (pages)."""
        return f"http://localhost:{self.port}"

    @property
    def key_headers(self) -> dict[str, str]:
        """Header carrying the access key (CLI style)."""
        return {"X-Agent-Canvas-Key": self.key}

    def login_url(self) -> str:
        """Mint a one-time login URL for the owner window."""
        return f"{self.base_url}/login?t={self.state.new_login_token()}"

    def add_session(
        self, session_id: str = "s1", files: dict[str, bytes | str] | None = None
    ):  # noqa: ANN201
        """Create a session folder with ``files`` and register it."""
        folder = self.project_dir / self.project_dir_name / session_id
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in (files or {}).items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = content.encode() if isinstance(content, str) else content
            target.write_bytes(data)
        session = self.state.register_session(session_id, folder)
        self.sessions[session_id] = session
        return session

    def page_url(self, session_id: str, page: str) -> str:
        """Frame URL of ``page`` in a registered session."""
        token = self.sessions[session_id].page_token
        return f"{self.frame_origin}/s/{token}/{page}"

    @property
    def notifications(self) -> list[list[str]]:
        """Argument lists the notification recorder was started with (NTF-01)."""
        log = self.notify_log
        lines = log.read_text().splitlines() if log and log.exists() else []
        return [line.split("\t")[:-1] for line in lines]

    @property
    def launches(self) -> list[str]:
        """Argument lines the recorder script was started with."""
        log = self.recorder.parent / "launches.txt"
        return log.read_text().splitlines() if log.exists() else []

    def show(self, session_id: str, page: str) -> None:
        """Tell connected shells to load ``page`` (stand-in for ``show``)."""
        self.state.show_page(session_id, page)

    def on_loop(self, function: Callable[[], object], timeout: float = 10):  # noqa: ANN201
        """Run ``function`` on the hub's event loop and return its result."""
        done: concurrent.futures.Future = concurrent.futures.Future()

        def run() -> None:
            try:
                done.set_result(function())
            except BaseException as error:  # noqa: BLE001 - handed to the caller
                done.set_exception(error)

        self.state.loop.call_soon_threadsafe(run)
        return done.result(timeout)

    def create_event(self, session_id: str, kind: str = "send", **fields) -> dict:  # noqa: ANN003
        """
        Create an event in a session through the event service.

        For hub tests that need a ``send`` event without a browser (no record
        file, no screenshot); the real send is ``POST /api/sessions/<id>/send``.
        """
        known = ("delivery", "page", "page_version", "target", "value")
        args = {k: v for k, v in fields.items() if k in known}
        extra = {k: v for k, v in fields.items() if k not in known}
        return self.on_loop(
            lambda: self.state.events.create(session_id, kind, fields=extra, **args)
        )

    def event_state(self, session_id: str, event_id: str) -> str:
        """Return ``queued`` or ``delivered`` for an event."""
        return self.on_loop(
            lambda: self.state.events.get(session_id, event_id)["state"]
        )

    def listening(self, session_id: str) -> bool:
        """Return True while a listener is connected for the session."""
        return self.on_loop(lambda: self.state.events.listening(session_id))

    def listener_kinds(self, session_id: str) -> list[str]:
        """Return the kinds (``watch``, ``ask``) of the connected listeners."""
        return self.on_loop(
            lambda: [x.kind for x in self.state.events.listeners(session_id)]
        )

    def wait_for(self, condition: Callable[[], bool], timeout: float = 5) -> None:
        """Poll ``condition`` until it holds; fail the test after ``timeout`` s."""
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, "condition not met in time"
            time.sleep(0.01)

    def open_asks(self, session_id: str) -> list[dict]:
        """Return the open asks (cards) of a session, with their ``waiting`` flag."""
        return self.on_loop(lambda: self.state.asks.public(session_id))

    def wait_for_ask(self, session_id: str, waiting: bool = True) -> dict:
        """Wait until the session has one open ask (attached if ``waiting``)."""
        found: list[dict] = []

        def ready() -> bool:
            found[:] = [
                a for a in self.open_asks(session_id) if a["waiting"] == waiting
            ]
            return bool(found)

        self.wait_for(ready, timeout=15)
        return found[0]

    def answer_ask(self, session_id: str, ask_id: str, value) -> dict | None:  # noqa: ANN001
        """Answer a card the way the shell does; None when the hub refuses."""
        return self.on_loop(lambda: self.state.asks.answer(session_id, ask_id, value))

    def dismiss_ask(self, session_id: str, ask_id: str) -> bool:
        """Dismiss a card the way the owner does."""
        return self.on_loop(lambda: self.state.asks.dismiss(session_id, ask_id))

    def shell_event(
        self,
        session_id: str,
        kind: str,
        canvas_id: str | None,
        value,  # noqa: ANN001
        delivery: str = "now",
    ) -> dict | None:
        """Create an event as the shell relays it from a page element."""
        from agent_canvas.hub.app import event_from_shell

        target = None if canvas_id is None else {"canvas_id": canvas_id}
        message = {
            "type": "event", "session": session_id, "kind": kind, "value": value,
            "delivery": delivery, "target": target, "page": None,
        }  # fmt: skip
        return self.on_loop(
            lambda: event_from_shell(self.state, self.state.events, message)
        )

    def stop(self) -> None:
        """Stop the hub and leave the port closed."""
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.sock.close()

    def restart(self, between: Callable[[], object] | None = None) -> None:
        """Stop the hub and start a new one on the same port and state dir.

        ``between`` runs while the hub is stopped.
        """
        assert self.respawn is not None
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.sock.close()
        if between:
            between()
        self.sock = _free_socket(self.port)
        self.app, self.server, self.thread = self.respawn(self.sock)
        self.sessions.clear()


def hub_pids(state_dir: Path) -> list[int]:
    """Pids of ``agent_canvas.cli hub`` processes using ``state_dir``."""
    found = []
    marker = f"AGENT_CANVAS_STATE_DIR={state_dir}".encode()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().split(b"\0")
            environ = (entry / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        if b"agent_canvas.cli" in cmdline and b"hub" in cmdline and marker in environ:
            found.append(int(entry.name))
    return found


def kill_hubs(state_dir: Path) -> None:
    """Kill every ``agent_canvas.cli hub`` that was started under ``state_dir``."""
    for pid in hub_pids(state_dir):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _free_socket(port: int = 0) -> socket.socket:
    """Bind a loopback socket (a free port by default) for the server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(128)
    return sock


@pytest.fixture
def hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[HubHandle]:
    """
    Start a real hub on a free port with temp state, config and project dirs.

    The recorder is the ``window_command``; ``open_window`` is off unless a test
    asks for it with ``@pytest.mark.hub_config(open_window=True)`` (other
    config fields can be overridden the same way), so that ``show`` does not
    wait for a window that never comes.
    """
    import uvicorn

    from agent_canvas.config import Config
    from agent_canvas.hub.app import create_app

    state_dir = tmp_path / "state"
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    for directory in (config_dir, project_dir):
        directory.mkdir()
    monkeypatch.setenv("AGENT_CANVAS_STATE_DIR", str(state_dir))
    monkeypatch.setenv("AGENT_CANVAS_CONFIG_DIR", str(config_dir))
    recorder = tmp_path / "window-recorder.sh"
    recorder.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/launches.txt"\n')
    recorder.chmod(recorder.stat().st_mode | stat.S_IXUSR)

    sock = _free_socket()
    port = sock.getsockname()[1]
    clock = FakeClock()
    marker = request.node.get_closest_marker("hub_config")
    settings = {"open_window": False, **(marker.kwargs if marker else {})}
    # `show` runs the page checks only where a test asks for them (CHK-15).
    settings.setdefault("show_audit", False)
    settings.setdefault("window_command", f"{recorder} {{url}}")
    config = Config(port=port, **settings)

    def respawn(listening: socket.socket) -> tuple:
        app = create_app(config, state_dir, clock=clock)
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", ws="websockets-sansio")
        )
        thread = threading.Thread(
            target=lambda: asyncio.run(server.serve(sockets=[listening])), daemon=True
        )
        app.state.hub.shutdown = lambda: setattr(server, "should_exit", True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "hub did not start"
            time.sleep(0.01)
        return app, server, thread

    app, server, thread = respawn(sock)
    key = (state_dir / "key").read_text().strip()
    handle = HubHandle(
        port, state_dir, config_dir, project_dir, recorder, clock, app, server,
        thread, key, sock, respawn, project_dir_name=config.project_dir_name,
    )  # fmt: skip
    yield handle
    handle.server.should_exit = True
    handle.thread.join(timeout=10)
    handle.sock.close()
    # A CLI that raced the stop may have started a detached hub of its own.
    kill_hubs(state_dir)
