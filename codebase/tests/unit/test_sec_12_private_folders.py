"""Folders the hub creates for session content are private (SEC-12)."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_canvas.hub.registry import SessionRegistry
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture(autouse=True)
def usual_umask() -> Iterator[None]:
    old = os.umask(0o022)
    yield
    os.umask(old)


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionRegistry:
    home = tmp_path / "home"
    (home / "proj").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "state").mkdir()
    made = SessionRegistry(tmp_path / "state", HubState(1, "k", lambda: 0.0))
    made.load()
    return made


def test_sec_12_new_session_folder_and_its_parent_are_0700(
    registry: SessionRegistry, tmp_path: Path
) -> None:
    project = tmp_path / "home" / "proj"
    registry.create("3f2a", str(project), "claude-code", None)
    assert mode(project / ".agent-canvas") == 0o700
    assert mode(project / ".agent-canvas" / "3f2a") == 0o700


def test_sec_12_an_existing_canvas_folder_keeps_its_mode(
    registry: SessionRegistry, tmp_path: Path
) -> None:
    project = tmp_path / "home" / "proj"
    (project / ".agent-canvas").mkdir(mode=0o755)
    registry.create("3f2a", str(project), "claude-code", None)
    assert mode(project / ".agent-canvas") == 0o755
    assert mode(project / ".agent-canvas" / "3f2a") == 0o700


def test_sec_12_a_vanished_session_folder_comes_back_0700(
    registry: SessionRegistry, tmp_path: Path
) -> None:
    project = tmp_path / "home" / "proj"
    registry.create("3f2a", str(project), "claude-code", None)
    folder = project / ".agent-canvas" / "3f2a"
    shutil.rmtree(folder)
    registry.ensure("3f2a", str(project), "claude-code")
    assert mode(folder) == 0o700


def test_sec_12_helper_creates_missing_folders_0700_and_leaves_others(
    tmp_path: Path,
) -> None:
    from agent_canvas.paths import make_private_dirs

    (tmp_path / "old").mkdir(mode=0o755)
    make_private_dirs(tmp_path / "old" / "history" / "looks")
    assert mode(tmp_path / "old") == 0o755
    assert mode(tmp_path / "old" / "history") == 0o700
    assert mode(tmp_path / "old" / "history" / "looks") == 0o700
    make_private_dirs(tmp_path / "old" / "history" / "looks")  # exists: no error
