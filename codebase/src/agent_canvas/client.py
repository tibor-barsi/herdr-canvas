"""Hub client shared by the CLI, the MCP wrapper and the hooks (requirements 5.6).

Uses only the standard library so that short commands stay fast (NFR-04). All
traffic goes to the hub over HTTP with the access key; nothing reads hub state
from disk.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import http.client
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agent_canvas import service
from agent_canvas.config import Config
from agent_canvas.output import ERROR_EXIT_CODES, CliError

KEY_HEADER = "X-Agent-Canvas-Key"
HEALTH_TIMEOUT_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30.0
START_WAIT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.05


def health_proof(key: str, port: int, challenge: str) -> str:
    """
    Return the hub's answer to a ``/health`` challenge (SEC-13).

    Only a holder of the key can compute it, so the client can tell the
    owner's hub from another program on the port before it sends the key. The
    port is part of it so that a hub on another port cannot answer for this one.

    Parameters
    ----------
    key : str
        The access key.
    port : int
        Port the hub listens on.
    challenge : str
        Random text chosen by the client.

    Returns
    -------
    str
        Hex HMAC-SHA256 of the port and the challenge under the key.
    """
    message = f"health-proof-v1:{port}:{challenge}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def git_toplevel(cwd: Path) -> Path | None:
    """
    Return the git top-level directory of ``cwd``, or None (SES-03).

    Parameters
    ----------
    cwd : pathlib.Path
        Working directory.

    Returns
    -------
    pathlib.Path | None
        None when ``cwd`` is not in a repository or git is not installed.
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = done.stdout.strip()
    return Path(top) if done.returncode == 0 and top else None


def resolve_project(option: str | None, environ: dict[str, str], cwd: Path) -> str:
    """
    Resolve the project directory (SES-03).

    Order: ``--project``, ``AGENT_CANVAS_PROJECT``, git top-level of ``cwd``,
    ``cwd`` itself. Relative values are taken relative to ``cwd``.

    Parameters
    ----------
    option : str | None
        Value of ``--project``.
    environ : dict[str, str]
        Environment variables.
    cwd : pathlib.Path
        Working directory.

    Returns
    -------
    str
        Absolute project path (not yet checked against ``$HOME``; the hub does that).
    """
    chosen = option or environ.get("AGENT_CANVAS_PROJECT")
    if chosen:
        return str((cwd / chosen).resolve())
    return str((git_toplevel(cwd) or cwd).resolve())


def client_from_environment() -> HubClient:
    """
    Build a hub client from the config file and environment.

    Returns
    -------
    HubClient
        Client for the configured port and state directory.

    Raises
    ------
    CliError
        ``failed`` when the config file is invalid.
    """
    from agent_canvas.config import ConfigError, load_config
    from agent_canvas.paths import state_dir

    try:
        return HubClient(load_config(), state_dir())
    except ConfigError as error:
        raise CliError("failed", str(error)) from error


class HubClient:
    """
    Talk to the hub, starting it when it is not running (CLI-12, CLI-15).

    Parameters
    ----------
    config : Config
        Effective configuration (port).
    state_dir : pathlib.Path
        State directory with the access key, ``hub.log`` and the start lock.
    """

    def __init__(self, config: Config, state_dir: Path) -> None:
        self.config = config
        self.state_dir = state_dir

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        start: bool = True,
        timeout: float | None = None,
    ) -> Any:
        """
        Send one request to the hub and return the decoded JSON answer.

        Parameters
        ----------
        method : str
            HTTP method.
        path : str
            Path with query string, e.g. ``/api/sessions``.
        body : dict[str, Any] | None, optional
            JSON body.
        start : bool, optional
            Start the hub when it is not running (CLI-12). Hooks pass False:
            they must never start it (PLG-04, PLG-05).
        timeout : float | None, optional
            Seconds to wait for the answer. Default is 30 s.

        Returns
        -------
        Any
            The decoded JSON response.

        Raises
        ------
        CliError
            ``hub-unreachable`` (hub cannot be reached or started),
            ``unauthorised`` (key rejected), or the code the hub reports
            (``failed``, ``no-session``).
        """
        self._ensure_or_require_hub(start)
        headers = {KEY_HEADER: self._read_key()}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        try:
            status, text = self._http(method, path, payload, headers, timeout)
        except (OSError, http.client.HTTPException) as error:
            raise CliError("hub-unreachable", f"Hub request failed: {error}") from error
        return self._decode(status, text)

    def open_watch(self, session_id: str, *, start: bool = True) -> Any:
        """
        Open the watch WebSocket of a session (CLI-07).

        Parameters
        ----------
        session_id : str
            Existing session.
        start : bool, optional
            Start the hub if it is not running (CLI-12). A reconnect passes
            False so that it never revives a hub that was stopped.

        Returns
        -------
        websockets.sync.client.ClientConnection
            The connected socket; the hub sends event objects and expects
            ``{"type": "ack", "id": ...}`` after each one is written.

        Raises
        ------
        CliError
            ``hub-unreachable`` when the hub cannot be reached.
        """
        return self._open(f"/api/sessions/{session_id}/watch", start)

    def open_ask(self, session_id: str, *, start: bool = True) -> Any:
        """
        Open the ask WebSocket of a session (CLI-04).

        The CLI sends one ``ask`` message first; the hub answers with
        ``registered`` and later ``result``.

        Parameters
        ----------
        session_id : str
            Existing session.
        start : bool, optional
            Start the hub if it is not running; False for a reconnect.

        Returns
        -------
        websockets.sync.client.ClientConnection
            The connected socket.

        Raises
        ------
        CliError
            ``hub-unreachable`` when the hub cannot be reached.
        """
        return self._open(f"/api/sessions/{session_id}/ask", start)

    def open_answers_wait(self, session_id: str, *, start: bool = True) -> Any:
        """
        Open the socket of ``answers --wait`` (ANS-05).

        The CLI sends the ids and the timeout once; the hub answers with one
        ``result`` message. The open socket counts as a listener (FB-06).

        Raises
        ------
        CliError
            ``hub-unreachable`` when the hub cannot be reached.
        """
        return self._open(f"/api/sessions/{session_id}/answers/wait", start)

    def ensure_hub(self) -> None:
        """
        Make sure an agent-canvas hub answers on the port, starting one if needed.

        Concurrent callers serialise on a lock file, so exactly one hub starts.

        Raises
        ------
        CliError
            ``hub-unreachable`` if another program holds the port or the hub
            does not come up within 5 s.
        """
        state = self._probe()
        if state == "ok":
            return
        self._refuse(state)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.state_dir / "hub.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._probe()
            self._refuse(state)
            if state == "absent":
                self._start_and_wait()

    # ---- internals ---------------------------------------------------------

    def _ensure_or_require_hub(self, start: bool) -> None:
        """Make sure the owner's hub listens before the key is sent (SEC-13)."""
        if start:
            self.ensure_hub()
            return
        state = self._probe()
        self._refuse(state)
        if state == "absent":
            raise CliError("hub-unreachable", "The hub is not running.")

    def _refuse(self, state: str) -> None:
        """Raise for a listener that is not the owner's hub (SEC-13)."""
        if state == "foreign":
            raise self._port_in_use()
        if state == "unproven":
            raise CliError(
                "unauthorised",
                f"The program on port {self.config.port} did not prove that it "
                f"holds the access key in {self.state_dir / 'key'}, so the key "
                "was not sent. It may be a hub with another key, a hub older "
                "than this client, or another program. After an upgrade, stop "
                "the old hub (with the old tool or by ending its process), then "
                "start the new one; see 'Upgrading' in docs/install.md.",
            )

    def _open(self, path: str, start: bool) -> Any:
        """Connect a WebSocket with the key header."""
        from websockets.exceptions import WebSocketException
        from websockets.sync.client import connect

        self._ensure_or_require_hub(start)
        url = f"ws://127.0.0.1:{self.config.port}{path}"
        try:
            return connect(url, additional_headers={KEY_HEADER: self._read_key()})
        except (OSError, WebSocketException) as error:
            raise CliError("hub-unreachable", f"Connection failed: {error}") from error

    def _http(
        self,
        method: str,
        path: str,
        payload: str | None,
        headers: dict[str, str],
        timeout: float | None = None,
    ) -> tuple[int, str]:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.config.port, timeout=timeout or REQUEST_TIMEOUT_SECONDS
        )
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8", "replace")
        finally:
            connection.close()

    def _probe(self) -> str:
        """
        Return ``ok``, ``absent`` (refused), ``foreign`` or ``unproven``.

        ``ok`` is an agent-canvas hub that answered the challenge with the
        proof of the key in the state dir (SEC-13); ``unproven`` claims to be
        one but did not.
        """
        challenge = secrets.token_urlsafe(16)
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.config.port, timeout=HEALTH_TIMEOUT_SECONDS
        )
        try:
            connection.request("GET", f"/health?challenge={challenge}")
            response = connection.getresponse()
            data = json.loads(response.read().decode("utf-8", "replace"))
        except ConnectionRefusedError:
            return "absent"
        except (OSError, http.client.HTTPException, ValueError):
            return "foreign"
        finally:
            connection.close()
        is_hub = response.status == 200 and (
            isinstance(data, dict) and data.get("app") == "agent-canvas"
        )
        if not is_hub:
            return "foreign"
        expected = health_proof(self._read_key(), self.config.port, challenge)
        proof = data.get("proof")
        if isinstance(proof, str) and hmac.compare_digest(
            proof.encode(), expected.encode()
        ):
            return "ok"
        return "unproven"

    def stop(self) -> bool:
        """
        Ask a running hub to shut down and wait until the port is free (M3).

        Returns
        -------
        bool
            True if a hub answered and has stopped; False if none was running.

        Raises
        ------
        CliError
            ``hub-unreachable`` if the hub is still there after 5 s.
        """
        state = self._probe()
        if state == "unproven":
            self._refuse(state)
        if state != "ok":
            return False
        self.request("POST", "/api/shutdown", {}, start=False)
        deadline = time.monotonic() + START_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self._probe() != "ok":
                return True
            time.sleep(POLL_INTERVAL_SECONDS)
        raise CliError("hub-unreachable", "The hub did not stop within 5 s.")

    def _start_and_wait(self) -> None:
        """Start the hub (service if enabled, else detached); wait up to 5 s."""
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log = self.state_dir / "hub.log"
        process = None
        if not service.start_enabled_service():
            process = self._spawn_detached(log)
        deadline = time.monotonic() + START_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self._probe() == "ok":
                return
            if process is not None and process.poll() is not None:
                break
            time.sleep(POLL_INTERVAL_SECONDS)
        port = self.config.port
        where = log if process is not None else "`journalctl --user -u agent-canvas`"
        raise CliError(
            "hub-unreachable",
            f"The hub did not start on port {port}; see {where} "
            "(is the port used by another program?).",
        )

    @staticmethod
    def _spawn_detached(log: Path) -> subprocess.Popen[bytes]:
        """Spawn ``agent-canvas hub`` in its own session, output to ``log``."""
        with log.open("ab") as log_handle:
            return subprocess.Popen(
                # -P: keep the caller's working directory off the module path.
                [sys.executable, "-P", "-m", "agent_canvas.cli", "hub"],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
                close_fds=True,
                env=os.environ.copy(),
            )

    def _port_in_use(self) -> CliError:
        port = self.config.port
        return CliError(
            "hub-unreachable",
            f"Port {port} is in use by another program (it is not an "
            "agent-canvas hub). Set AGENT_CANVAS_PORT or the port in config.toml.",
        )

    def _read_key(self) -> str:
        try:
            return (self.state_dir / "key").read_text().strip()
        except OSError:
            return ""

    def _decode(self, status: int, text: str) -> Any:
        if status == 401:
            raise CliError(
                "unauthorised",
                f"The hub rejected the access key in {self.state_dir / 'key'}.",
            )
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if 200 <= status < 300:
            return data
        if isinstance(data, dict) and data.get("error") in ERROR_EXIT_CODES:
            raise CliError(data["error"], str(data.get("message", "")))
        raise CliError("failed", f"Hub answered HTTP {status}: {text[:200]}")
