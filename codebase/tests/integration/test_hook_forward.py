"""The forwarding hook (PLG-08) and its registration in the plugin (PLG-09)."""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from agent_canvas.client import health_proof

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
FEED = ROOT / "codebase" / "tests" / "fixtures" / "hooks" / "pretooluse-agent.jsonl"
HOOKS_JSON = ROOT / "plugin" / "hooks" / "hooks.json"
KEY = "test-key-0123456789"
HERDR = {
    "HERDR_PANE_ID": "w41:p1",
    "HERDR_TAB_ID": "w41:t1",
    "HERDR_WORKSPACE_ID": "w41",
    "HERDR_SOCKET_PATH": "/run/user/1000/herdr.sock",
}
FORBIDDEN = [
    "starlette",
    "uvicorn",
    "mcp",
    "watchfiles",
    "playwright",
    "agent_canvas.hub",
]
KEPT_RESPONSE_KEYS = {"agentId", "status", "isAsync", "description"}


class FakeHub:
    """A recording stand-in for the intake route, on a free port."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.bodies: list[dict] = []
        self.keys: list[str | None] = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                hub.keys.append(self.headers.get("X-Agent-Canvas-Key"))
                hub.bodies.append(json.loads(raw))
                if hub.mode == "hang":
                    time.sleep(3)
                    return
                status = {"ok": 204, "500": 500, "key": 401}[hub.mode]
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                # /health with the key proof, so the hook sends the key (SEC-13)
                challenge = parse_qs(urlsplit(self.path).query)["challenge"][0]
                proof = health_proof(KEY, hub.port, challenge)
                body = json.dumps({"app": "agent-canvas", "proof": proof}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_hub():  # noqa: ANN201
    fake = FakeHub()
    yield fake
    fake.close()


@pytest.fixture
def env(tmp_path: Path, fake_hub: FakeHub) -> dict[str, str]:
    state = tmp_path / "state"
    state.mkdir()
    (state / "key").write_text(KEY + "\n")
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AGENT_CANVAS_", "XDG_", "HERDR_"))
    }
    base.update(
        HOME=str(tmp_path / "home"),
        AGENT_CANVAS_PORT=str(fake_hub.port),
        AGENT_CANVAS_STATE_DIR=str(state),
        AGENT_CANVAS_CONFIG_DIR=str(tmp_path / "config"),
    )
    return base


def forward(
    stdin: str, env: dict[str, str], timeout: float = 20
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_canvas.cli", "hook", "forward"],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def expected_input(line: dict) -> dict:
    """The line trimmed per requirements 5.8 / A-08 (written independently)."""

    def cut(value):  # noqa: ANN001, ANN202
        if isinstance(value, str):
            return value[:1000]
        if isinstance(value, list):
            return [cut(v) for v in value]
        if isinstance(value, dict):
            return {k: cut(v) for k, v in value.items()}
        return value

    out = {k: cut(v) for k, v in line.items() if k != "last_assistant_message"}
    if isinstance(line.get("tool_response"), dict):
        out["tool_response"] = {
            k: cut(v)
            for k, v in line["tool_response"].items()
            if k in KEPT_RESPONSE_KEYS
        }
    return out


def assert_silent(done: subprocess.CompletedProcess) -> None:
    assert done.returncode == 0
    assert done.stdout == "" and done.stderr == ""


# ---- PLG-08 ---------------------------------------------------------------


@pytest.mark.timing
def test_plg_08_median_wall_time_is_at_most_150_ms(fake_hub, env) -> None:  # noqa: ANN001
    line = FEED.read_text().splitlines()[0]
    forward(line, env)
    times = []
    for _ in range(20):
        started = time.perf_counter()
        forward(line, env)
        times.append(time.perf_counter() - started)
    median = statistics.median(times)
    p95 = sorted(times)[18]
    print(
        f"forwarder median {median * 1000:.0f} ms p95 {p95 * 1000:.0f} ms "
        f"load {os.getloadavg()}"
    )
    assert median <= 0.150


# ---- PLG-09 ---------------------------------------------------------------

FORWARD_COMMAND = (
    "command -v agent-canvas >/dev/null 2>&1 || exit 0; "
    "agent-canvas hook forward || exit 0"
)
OLD_COMMANDS = {
    "SessionStart": "command -v agent-canvas >/dev/null 2>&1 || { echo '{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"additionalContext\":\"agent-canvas is not installed, so the canvas is unavailable. If the owner asks for it, tell them to run: uv tool install <path to agent-canvas>/codebase (see the plugin README).\"}}'; exit 0; }; agent-canvas hook session-start || exit 0",  # noqa: E501
    "UserPromptSubmit": "command -v agent-canvas >/dev/null 2>&1 || exit 0; agent-canvas hook user-prompt-submit || exit 0",  # noqa: E501
    "SessionEnd": "command -v agent-canvas >/dev/null 2>&1 || exit 0; agent-canvas hook session-end || exit 0",  # noqa: E501
    "Stop": "command -v agent-canvas >/dev/null 2>&1 || exit 0; agent-canvas hook stop || exit 0",  # noqa: E501
}  # fmt: skip
EVENTS = (
    "SessionStart UserPromptSubmit PreToolUse PostToolUse PermissionRequest "
    "Notification SubagentStart SubagentStop Stop SessionEnd"
).split()


def entries() -> list[tuple[str, str | None, dict]]:
    hooks = json.loads(HOOKS_JSON.read_text())["hooks"]
    return [
        (event, group.get("matcher"), hook)
        for event, groups in hooks.items()
        for group in groups
        for hook in group["hooks"]
    ]


def test_plg_09_the_three_existing_hooks_are_unchanged() -> None:
    old = {
        e[0]: e[2]
        for e in entries()
        if not e[2]["command"].endswith("hook forward || exit 0")
    }
    assert {k: v["command"] for k, v in old.items()} == OLD_COMMANDS
    assert all(v["timeout"] == 5 and v["type"] == "command" for v in old.values())


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed")
def test_plg_09_the_plugin_validates_strictly() -> None:
    done = subprocess.run(
        ["claude", "plugin", "validate", str(ROOT / "plugin"), "--strict"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr


# ---- PLG-12 (#57) ----------------------------------------------------------


@pytest.mark.parametrize(
    "event", ["SessionStart", "Stop", "SessionEnd", "UserPromptSubmit"]
)
def test_plg_12_a_plugin_ahead_of_an_older_command_exits_0_silently(
    tmp_path, event: str
) -> None:
    old = tmp_path / "agent-canvas"
    old.write_text(
        "#!/bin/sh\necho 'usage: agent-canvas hook: invalid choice' >&2\nexit 2\n"
    )
    old.chmod(0o755)
    commands = [e[2]["command"] for e in entries() if e[0] == event]
    assert commands
    for command in commands:
        done = subprocess.run(
            ["sh", "-c", command],
            input="{}",
            capture_output=True,
            text=True,
            env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        )
        assert done.returncode == 0 and done.stdout == ""


def test_plg_12_the_current_command_keeps_its_output(tmp_path) -> None:  # noqa: ANN001
    fake = tmp_path / "agent-canvas"
    fake.write_text("#!/bin/sh\necho blocked\nexit 0\n")
    fake.chmod(0o755)
    stop = next(e[2]["command"] for e in entries() if e[0] == "Stop")
    done = subprocess.run(
        ["sh", "-c", stop],
        capture_output=True,
        text=True,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )
    assert done.stdout == "blocked\n"
