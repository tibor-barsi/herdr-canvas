"""Beside mode: follow another hub's session list read-only; no purge."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from agent_canvas.config import Config
from agent_canvas.hub import app as app_module
from agent_canvas.hub.registry import SessionRegistry
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit


def registry_in(state_dir: Path) -> SessionRegistry:
    state_dir.mkdir(parents=True, exist_ok=True)
    return SessionRegistry(state_dir, HubState(1, "k", lambda: 0.0))


def test_follow_adds_new_sessions_and_never_writes_the_daily_file(
    tmp_path: Path,
) -> None:
    daily = registry_in(tmp_path / "daily")
    fork = registry_in(tmp_path / "fork")
    fork.follow_file = tmp_path / "daily" / "sessions.json"
    assert fork.follow() is False  # no file yet

    project = tmp_path / "project"
    project.mkdir()
    daily.create("aaa", str(project), "claude-code", "A")
    before = fork.follow_file.read_bytes()
    assert fork.follow() is True
    assert fork.get("aaa").title == "A"
    assert fork.follow() is False  # unchanged

    daily.create("bbb", str(project), "claude-code", "B")
    stat = fork.follow_file.stat()
    os.utime(fork.follow_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    assert fork.follow() is True
    assert {t["id"] for t in fork.tabs()} == {"aaa", "bbb"}
    assert fork.follow_file.read_bytes() != before
    assert json.loads((tmp_path / "fork" / "sessions.json").read_text()).keys() == {
        "aaa",
        "bbb",
    }


def test_follow_off_does_nothing(tmp_path: Path) -> None:
    assert registry_in(tmp_path / "fork").follow() is False


@pytest.mark.parametrize("follow", [True, False])
def test_purge_runs_only_when_not_following(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, follow: bool
) -> None:
    started: list[bool] = []

    async def fake_purge(services) -> None:  # noqa: ANN001
        started.append(True)

    monkeypatch.setattr(app_module, "_purge_archived", fake_purge)
    monkeypatch.setenv("AGENT_CANVAS_STATE_DIR", str(tmp_path / "state"))
    config = Config(
        port=1,
        open_window=False,
        show_audit=False,
        follow_state=str(tmp_path / "daily") if follow else "",
    )
    app = app_module.create_app(config, tmp_path / "state", build_id="test")
    with TestClient(app):
        pass
    assert started == ([] if follow else [True])


def test_pool_beside_mode_takes_the_daily_pool_tag_and_never_makes_a_pool(
    tmp_path: Path,
) -> None:
    from agent_canvas.hub.registry import RegistryError, pool_key

    daily = registry_in(tmp_path / "daily")
    fork_dir = tmp_path / "fork"
    fork_dir.mkdir()
    fork = SessionRegistry(fork_dir, HubState(1, "another key", lambda: 0.0))
    fork.follow_file = tmp_path / "daily" / "sessions.json"
    pooled, bare = tmp_path / "pooled", tmp_path / "bare"
    pooled.mkdir()
    bare.mkdir()
    daily.create("aaa", str(pooled), "claude-code", "A")
    pool = daily.pool_session(pool_key(str(pooled)))
    assert fork.follow() is True
    assert fork.pool_tag == daily.pool_tag
    assert fork.pool_of("aaa") == pool["id"]
    assert fork.pool_session(pool_key(str(pooled)))["id"] == pool["id"]
    fork.create("bbb", str(bare), "claude-code", "B")
    with pytest.raises(RegistryError, match="beside"):
        fork.pool_session(pool_key(str(bare)))
    assert not list((bare / ".agent-canvas").glob("pool-*"))
    assert not (fork_dir / "pool-tag").exists()
