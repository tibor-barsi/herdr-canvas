"""The canvases of other machines: link, login, merge and routing (multi-machine, S2).

For every machine ``hc machine ls`` lists (temporary ones skipped) this hub asks
the machine's own hub for its port (``agent-canvas status`` through ``hc exec``),
forwards that port to the same local port over SSH, logs in with a one-time link
from ``agent-canvas open --print-url`` and keeps one WebSocket to its
``/ws/shell``. The remote sessions join this hub's ``tabs`` with ``machine`` set,
the remote pushes pass to the windows, and what the window sends about a remote
session goes to that machine's hub with its cookie and its own Origin. The cookie
never leaves this process and is never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import json
import re
import socket
import subprocess
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from agent_canvas.hub.auth import cookie_name
from agent_canvas.hub.messages import WINDOW_MESSAGES
from agent_canvas.hub.state import HubState

# Module attributes so that tests can point them at fakes; FORWARD None means the
# remote hubs are reachable on this computer already (no SSH).
HC = "hc"
FORWARD: list[str] | None = [
    "ssh", "-S", "none", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
    "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=2", "-L", "{port}:127.0.0.1:{port}", "{target}",
]  # fmt: skip
LIST_SECONDS = 10.0
HC_SECONDS = 30.0
HTTP_SECONDS = 30.0
FORWARD_WAIT_SECONDS = 15.0
MAX_BACKOFF_SECONDS = 30.0
OUTBOX_SIZE = 200
NEVER_PASSED = {"hello", "render", "herdr"}  # remote tabs are merged, not passed
PASSED_HEADERS = ("content-type", "content-disposition", "cache-control")
SESSION_PATH = re.compile(r"/api/sessions/([^/]+)(?:/.*)?")
BODY_SESSION_PATH = "/api/home/pages"  # the window's pin key names the session here


@dataclass
class Machine:
    """One other machine and the state of its canvas link."""

    name: str
    target: str
    reachable: bool
    state: str = "connecting"
    detail: str | None = None
    port: int | None = None
    cookie: str | None = None
    sessions: list[dict[str, Any]] = field(default_factory=list)
    closed: list[dict[str, Any]] = field(default_factory=list)
    outbox: asyncio.Queue[str] | None = None
    forward: subprocess.Popen[bytes] | None = None
    task: asyncio.Task[None] | None = None


class Machines:
    """
    The links to the other machines' hubs.

    Parameters
    ----------
    state : HubState
        This hub's state: its port, credentials and window channel.
    """

    def __init__(self, state: HubState) -> None:
        self.state = state
        self.machines: dict[str, Machine] = {}

    async def run(self) -> None:
        """Follow ``hc machine ls`` and keep one link per listed machine."""
        try:
            while True:
                listed = await asyncio.to_thread(_listed)
                if listed is not None:
                    self._follow(listed)
                await asyncio.sleep(LIST_SECONDS)
        finally:
            for machine in list(self.machines.values()):
                self._drop(machine)

    def tabs(self) -> list[dict[str, Any]]:
        """Return the remote sessions' tabs, machine by machine."""
        return [t for m in self.machines.values() for t in m.sessions]

    def closed(self) -> list[dict[str, Any]]:
        """Return the remote closed tabs, machine by machine."""
        return [t for m in self.machines.values() for t in m.closed]

    def owner_of(self, session_id: Any) -> Machine | None:
        """Return the machine that holds ``session_id``, or None for this one."""
        for machine in self.machines.values():
            if any(t["id"] == session_id for t in machine.sessions + machine.closed):
                return machine
        return None

    def herdr_view(self, last: dict[str, Any]) -> dict[str, Any]:
        """Return the ``herdr`` message with each machine's canvas state and others."""
        entries = last.get("machines")
        if entries is None:
            entries = [{"name": name} for name in self.machines]
        machines = []
        for entry in entries:
            machine = self.machines.get(entry["name"])
            if machine is None:
                machines.append({**entry, "state": "connecting", "other": []})
                machines[-1]["detail"] = f"Looking for {entry['name']}'s canvas."
                continue
            paired = {
                pane["session"]
                for space in last.get("spaces", [])
                if space.get("machine") == machine.name
                for tab in space["tabs"]
                for pane in tab["panes"]
                if pane.get("session")
            }
            other = [t["id"] for t in machine.sessions if t["id"] not in paired]
            machines.append(
                {
                    **entry,
                    "state": machine.state,
                    "detail": machine.detail,
                    "other": other,
                }
            )
        return {"type": "herdr", **last, "machines": machines}

    def route(self, message: dict[str, Any]) -> bool:
        """
        Pass a window message about a remote session to its machine's hub.

        A ``page-report`` names its page by URL; the URL's port says the machine.

        Returns
        -------
        bool
            True when the message belongs to another machine (sent, or dropped
            while that machine is not connected).
        """
        machine = self.owner_of(message.get("session"))
        if machine is None and message.get("type") == "page-report":
            port = urlsplit(str(message.get("url", ""))).port
            found = [m for m in self.machines.values() if port and m.port == port]
            machine = found[0] if found else None
        if machine is None:
            return False
        if machine.outbox is not None:
            with contextlib.suppress(asyncio.QueueFull):
                machine.outbox.put_nowait(json.dumps(message))
        return True

    async def request(self, machine: Machine, request: Request) -> Response:
        """Send a window's HTTP request to the machine's hub; answer with its reply."""
        body = await request.body()
        target = request.url.path + (
            f"?{request.url.query}" if request.url.query else ""
        )
        for attempt in range(2):
            if machine.port is None or machine.cookie is None:
                break
            headers = {
                "Origin": f"http://127.0.0.1:{machine.port}",
                "Cookie": f"{cookie_name(machine.port)}={machine.cookie}",
            }
            if "content-type" in request.headers:
                headers["Content-Type"] = request.headers["content-type"]
            try:
                status, answer_headers, data = await asyncio.to_thread(
                    _http, machine.port, request.method, target, headers, body
                )
            except OSError:
                break
            if status == 401 and attempt == 0:
                await self._login(machine)  # the remote key changed
                continue
            kept = {k: v for k, v in answer_headers if k.lower() in PASSED_HEADERS}
            return Response(data, status_code=status, headers=kept)
        message = f"The canvas on {machine.name} cannot be reached."
        return JSONResponse(
            {"error": "machine-offline", "message": message}, status_code=502
        )

    def _follow(self, listed: list[tuple[str, str, bool]]) -> None:
        names = {name for name, _, _ in listed}
        for machine in [m for m in self.machines.values() if m.name not in names]:
            self._drop(machine)
            del self.machines[machine.name]
            self._publish("tabs", "herdr")
        for name, target, reachable in listed:
            machine = self.machines.get(name)
            if machine is None:
                machine = self.machines[name] = Machine(name, target, reachable)
                machine.detail = f"Looking for {name}'s canvas."
                machine.task = asyncio.create_task(self._link(machine))
                self._publish("herdr")
            machine.reachable = reachable

    def _drop(self, machine: Machine) -> None:
        if machine.task is not None:
            machine.task.cancel()
        _stop(machine)

    async def _link(self, machine: Machine) -> None:
        """Keep the machine's link up, retrying with a growing pause."""
        pause = 1.0
        try:
            while True:
                state, detail = await self._attempt(machine)
                if machine.state == "online":
                    pause = 1.0
                if state in ("no-canvas", "port-clash") and machine.sessions:
                    machine.sessions, machine.closed = [], []
                    self._publish("tabs")
                self._set(machine, state, detail)
                await asyncio.sleep(pause)
                pause = min(pause * 2, MAX_BACKOFF_SECONDS)
        finally:
            _stop(machine)

    async def _attempt(self, machine: Machine) -> tuple[str, str]:
        """Connect once; return the state and detail once it is not online."""
        name = machine.name
        if not machine.reachable:
            return "offline", f"Herdr cannot reach {name} right now."
        done = await self._hc(machine, "status")
        if isinstance(done, tuple):
            return done
        port = done.get("port")
        if not isinstance(port, int):
            return "no-canvas", f"The canvas hub on {name} gives no port."
        clash = self._clash(machine, port)
        if clash:
            return "port-clash", clash
        if machine.port != port:
            _stop(machine)
            machine.port, machine.cookie = port, None
        if FORWARD is not None and (problem := await self._forward(machine)):
            return problem
        if machine.cookie is None and (problem := await self._login(machine)):
            return problem
        assert machine.cookie is not None
        return await self._connected(machine, port, machine.cookie)

    async def _connected(
        self, machine: Machine, port: int, cookie: str
    ) -> tuple[str, str]:
        """Hold the WebSocket to the machine's hub until it closes."""
        try:
            async with connect(
                f"ws://127.0.0.1:{port}/ws/shell",
                origin=f"http://127.0.0.1:{port}",  # type: ignore[arg-type]
                additional_headers={"Cookie": f"{cookie_name(port)}={cookie}"},
                proxy=None,
                max_size=None,
                open_timeout=10,
            ) as websocket:
                machine.outbox = asyncio.Queue(OUTBOX_SIZE)
                writer = asyncio.create_task(_write(websocket, machine.outbox))
                try:
                    async for text in websocket:
                        self._receive(machine, json.loads(text))
                finally:
                    machine.outbox = None
                    writer.cancel()
                if websocket.close_code == 4401:  # the cookie was refused
                    machine.cookie = None
                    return "connecting", f"Logging in to {machine.name}'s canvas again."
        except (OSError, TimeoutError, InvalidHandshake, ConnectionClosed, ValueError):
            pass
        return "offline", f"The link to {machine.name}'s canvas is down; retrying."

    def _receive(self, machine: Machine, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "tabs":
            before = [t["id"] for t in machine.sessions]
            machine.sessions = _marked(message.get("sessions"), machine.name)
            machine.closed = _marked(message.get("closed"), machine.name)
            changed = before != [t["id"] for t in machine.sessions]
            if machine.state != "online":
                self._set(machine, "online", None)  # the windows reload its frames
            else:
                self._publish("tabs", *(("herdr",) if changed else ()))
            return
        if kind in NEVER_PASSED or kind not in WINDOW_MESSAGES:
            return
        if isinstance(message.get("tab"), dict):
            message["tab"] = {**message["tab"], "machine": machine.name}
        self.state.channel.broadcast(message)

    def _set(self, machine: Machine, state: str, detail: str | None) -> None:
        if (machine.state, machine.detail) == (state, detail):
            return
        came_online = state == "online"
        machine.state, machine.detail = state, detail
        self._publish(*(("tabs", "herdr") if came_online else ("herdr",)))

    def _clash(self, machine: Machine, port: int) -> str | None:
        """Return why ``port`` cannot be used for ``machine``, or None."""
        uses = f"{machine.name}'s canvas uses port {port}"
        fix = (
            f"set a free `port` in {machine.name}'s "
            "~/.config/agent-canvas/config.toml and restart its hub."
        )
        if port == self.state.port:
            return f"{uses}, as this hub does; {fix}"
        for other in self.machines.values():
            if other is machine:
                break
            if other.port == port and other.state != "port-clash":
                return f"{uses}, as {other.name}'s does; {fix}"
        if FORWARD is not None and machine.forward is None and _taken(port):
            return f"{uses}, which another program here holds; {fix}"
        return None

    async def _forward(self, machine: Machine) -> tuple[str, str] | None:
        """Start the SSH forward unless it runs; wait until its port answers."""
        if machine.forward is not None and machine.forward.poll() is None:
            return None
        assert FORWARD is not None and machine.port is not None
        argv = [
            part.format(port=machine.port, target=machine.target) for part in FORWARD
        ]
        machine.forward = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        loop = asyncio.get_running_loop()
        end = loop.time() + FORWARD_WAIT_SECONDS
        while loop.time() < end and machine.forward.poll() is None:
            if await asyncio.to_thread(_answers, machine.port):
                return None
            await asyncio.sleep(0.2)
        _stop(machine)
        return "offline", f"The SSH forward to {machine.target} failed; retrying."

    async def _login(self, machine: Machine) -> tuple[str, str] | None:
        """Log in with a one-time link from the machine; keep only the cookie."""
        machine.cookie = None
        done = await self._hc(machine, "open", "--print-url")
        if isinstance(done, tuple):
            return done
        assert machine.port is not None
        url = urlsplit(done["url"])
        try:
            _, headers, _ = await asyncio.to_thread(
                _http, machine.port, "GET", f"{url.path}?{url.query}", {}, b""
            )
            jar = SimpleCookie()
            for name, value in headers:
                if name.lower() == "set-cookie":
                    jar.load(value)
        except (OSError, CookieError):
            return "offline", f"The link to {machine.name}'s canvas is down; retrying."
        morsel = jar.get(cookie_name(machine.port))
        if morsel is None:
            return "no-canvas", f"The canvas hub on {machine.name} refused the login."
        machine.cookie = morsel.value
        return None

    async def _hc(
        self, machine: Machine, *arguments: str
    ) -> dict[str, Any] | tuple[str, str]:
        """Run ``agent-canvas ARGUMENTS`` on the machine; its JSON, or a state."""
        name = machine.name
        argv = [HC, "exec", "--on", name, "agent-canvas", *arguments]
        try:
            done = await asyncio.to_thread(
                subprocess.run, argv, capture_output=True, text=True, timeout=HC_SECONDS
            )
        except (OSError, subprocess.TimeoutExpired):
            return "offline", f"Herdr cannot run commands on {name} right now."
        if done.returncode == 0:
            if arguments[0] == "open":
                return {"url": done.stdout.strip()}
            with contextlib.suppress(ValueError):
                answer = json.loads(done.stdout)
                if isinstance(answer, dict):
                    return answer
            return (
                "no-canvas",
                f"The canvas on {name} gave an answer this hub cannot read.",
            )
        try:
            error = json.loads(done.stderr.strip().splitlines()[-1])["error"]
        except (ValueError, IndexError, KeyError, TypeError):
            error = None
        if isinstance(error, dict):  # Herdr's own error, not agent-canvas's
            if error.get("kind") == "spawn_failed":
                return "no-canvas", f"agent-canvas is not installed on {name}."
            return "offline", f"Herdr cannot run commands on {name} right now."
        return "no-canvas", f"The canvas hub on {name} does not start or is too old."

    def _publish(self, *views: str) -> None:
        for view in views:
            self.state.channel.publish(view)


class MachineRouter:
    """
    Pure-ASGI middleware: the window's requests about a remote session go there.

    Only requests that carry this hub's owner cookie (the window) are passed on;
    an agent's key never reaches another machine.

    Parameters
    ----------
    app : ASGIApp
        The wrapped application.
    machines : Machines
        The links to the other machines.
    """

    def __init__(self, app: ASGIApp, machines: Machines) -> None:
        self.app = app
        self.machines = machines

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer a remote session's request from its machine, else pass it on."""
        match = (
            SESSION_PATH.fullmatch(scope["path"]) if scope["type"] == "http" else None
        )
        session = match[1] if match else None
        if (
            scope["type"] == "http"
            and scope["path"] == BODY_SESSION_PATH
            and self.machines.machines
        ):
            body = await _read_body(receive)
            receive = _replayed(body, receive)
            session = _session_in(body)
        machine = self.machines.owner_of(session) if session else None
        if machine is not None:
            request = Request(scope, receive)
            state = self.machines.state
            if state.credentials.cookie_ok(
                request.cookies.get(cookie_name(state.port))
            ):
                response = await self.machines.request(machine, request)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def _read_body(receive: Receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            return body


def _replayed(body: bytes, receive: Receive) -> Receive:
    """Return a ``receive`` that gives the body read already, then the real one."""
    given = False

    async def replay() -> Message:
        nonlocal given
        if given:
            return await receive()
        given = True
        return {"type": "http.request", "body": body, "more_body": False}

    return replay


def _session_in(body: bytes) -> Any:
    try:
        return json.loads(body).get("session")
    except (ValueError, AttributeError):
        return None


def _marked(tabs: Any, name: str) -> list[dict[str, Any]]:
    """Return the remote tabs with ``machine`` set."""
    return [{**t, "machine": name} for t in tabs or [] if isinstance(t, dict)]


def _listed() -> list[tuple[str, str, bool]] | None:
    """Return (name, ssh target, connected) per non-temporary machine; None on error."""
    try:
        done = subprocess.run(
            [HC, "machine", "ls", "--json"],
            capture_output=True,
            text=True,
            timeout=HC_SECONDS,
            check=True,
        )
        listed = json.loads(done.stdout)["machines"]
        return sorted(
            (m["name"], m.get("target") or m["name"], m.get("state") == "connected")
            for m in listed
            if not m.get("temporary")
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


async def _write(websocket: Any, outbox: asyncio.Queue[str]) -> None:
    with contextlib.suppress(ConnectionClosed):
        while True:
            await websocket.send(await outbox.get())


def _http(
    port: int, method: str, target: str, headers: dict[str, str], body: bytes
) -> tuple[int, list[tuple[str, str]], bytes]:
    """Make one HTTP request to ``127.0.0.1:port``; status, headers and body."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=HTTP_SECONDS)
    try:
        connection.request(method, target, body or None, headers)
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        connection.close()


def _answers(port: int) -> bool:
    """Return True when something accepts connections on ``127.0.0.1:port``."""
    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), 1):
        return True
    return False


def _taken(port: int) -> bool:
    """Return True when ``127.0.0.1:port`` cannot be bound here."""
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _stop(machine: Machine) -> None:
    """End the machine's SSH forward, if it runs."""
    if machine.forward is not None:
        machine.forward.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            machine.forward.wait(5)
        machine.forward = None
