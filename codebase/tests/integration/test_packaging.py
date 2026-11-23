"""Wheel contents (OPS-01) and tool installation from the project path."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from helpers import CODEBASE_DIR, VENDOR_DIR

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(CODEBASE_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return next(out.glob("*.whl"))


def test_ops_01_wheel_contains_every_manifest_file(wheel: Path) -> None:
    manifest = json.loads((VENDOR_DIR / "MANIFEST.json").read_text("utf-8"))
    expected = {"agent_canvas/static/vendor/MANIFEST.json"}
    for lib in manifest["libraries"]:
        expected.update(
            f"agent_canvas/static/vendor/{rel}"
            for rel in lib["license_files"] + [f["path"] for f in lib["files"]]
        )
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert expected <= names, sorted(expected - names)


def test_ops_01_tool_install_exposes_command(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "UV_TOOL_DIR": str(tmp_path / "tools"),
        "UV_TOOL_BIN_DIR": str(tmp_path / "bin"),
    }
    subprocess.run(
        ["uv", "tool", "install", str(CODEBASE_DIR)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    result = subprocess.run(
        [str(tmp_path / "bin" / "agent-canvas"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage: agent-canvas" in result.stdout
