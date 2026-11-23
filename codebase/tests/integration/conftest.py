"""Fixtures for CLI tests: subprocess runner, fake home, spawned-hub cleanup."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.conftest import hub_pids


@dataclass
class CliResult:
    """Outcome of one CLI run."""

    code: int
    out: str
    err: str

    @property
    def json(self) -> dict:
        """Parsed stdout (exit 0, 6, 7) or stderr (exit 1-5)."""
        return json.loads(self.out if self.out else self.err)


class CliRunner:
    """Run ``python -m agent_canvas.cli`` with an isolated environment."""

    def __init__(self, environment: dict[str, str], cwd: Path) -> None:
        self.environment = environment
        self.cwd = cwd

    def __call__(
        self,
        *args: str,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
        timeout: float = 60,
        input: str | None = None,  # noqa: A002 - mirrors subprocess.run
    ) -> CliResult:
        merged = {**self.environment, **(extra_env or {})}
        done = subprocess.run(
            [sys.executable, "-m", "agent_canvas.cli", *args],
            cwd=cwd or self.cwd,
            env=merged,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input,
            stdin=None if input is not None else subprocess.DEVNULL,
        )
        return CliResult(done.returncode, done.stdout, done.stderr)


def build_environment(tmp_path: Path, port: int, state_dir: Path) -> dict[str, str]:
    """Environment for CLI subprocesses: no real dirs, no inherited variables."""
    result = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AGENT_CANVAS_", "XDG_"))
    }
    result.update(
        HOME=str(tmp_path / "home"),
        AGENT_CANVAS_PORT=str(port),
        AGENT_CANVAS_STATE_DIR=str(state_dir),
        AGENT_CANVAS_CONFIG_DIR=str(tmp_path / "config"),
        AGENT_CANVAS_WINDOW_COMMAND="true",
        AGENT_CANVAS_SHOW_AUDIT="0",  # a test hub never starts a headless browser
        GIT_CONFIG_NOSYSTEM="1",
    )
    return result


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake ``$HOME`` for the test process (and so for an in-process hub)."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def cli(hub, home: Path, tmp_path: Path) -> CliRunner:
    """CLI runner talking to the in-process test hub; cwd is ``$HOME/proj``."""
    project = home / "proj"
    project.mkdir(exist_ok=True)
    return CliRunner(build_environment(tmp_path, hub.port, hub.state_dir), project)


@dataclass
class LoneHub:
    """Environment for tests that let the CLI start its own hub."""

    run: CliRunner
    port: int
    state_dir: Path
    home: Path

    def pids(self) -> list[int]:
        """Pids of hubs started for this environment."""
        return hub_pids(self.state_dir)


@pytest.fixture
def lone(home: Path, tmp_path: Path) -> Iterator[LoneHub]:
    """No hub running; any hub the CLI spawns is killed at teardown."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    state_dir = tmp_path / "state"
    project = home / "proj"
    project.mkdir()
    handle = LoneHub(
        CliRunner(build_environment(tmp_path, port, state_dir), project),
        port,
        state_dir,
        home,
    )
    yield handle
    for pid in handle.pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
