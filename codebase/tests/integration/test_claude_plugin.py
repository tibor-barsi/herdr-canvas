"""The plugin passes Claude Code's own validator (PLG-01)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import PLUGIN_DIR

pytestmark = pytest.mark.integration


def validate(target: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``claude plugin validate --strict`` without touching the real home."""
    claude = shutil.which("claude")
    if claude is None:
        pytest.skip("the claude command is not installed")
    if "/mise/shims/" in claude:
        # A mise shim under the fake HOME refuses the real mise config as untrusted.
        found = subprocess.run(
            ["mise", "which", "claude"], capture_output=True, text=True
        )
        claude = found.stdout.strip() or claude
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-config"),
    }
    return subprocess.run(
        [claude, "plugin", "validate", str(target), "--strict"],
        env=environment, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip


def copy_plugin(tmp_path: Path, name: str, keep_marketplace: bool) -> Path:
    target = tmp_path / name
    shutil.copytree(PLUGIN_DIR, target)
    if not keep_marketplace:
        (target / ".claude-plugin" / "marketplace.json").unlink()
    return target


def test_plg_01_claude_plugin_validate_strict_passes(tmp_path: Path) -> None:
    done = validate(PLUGIN_DIR, tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr


def test_plg_01_the_plugin_manifest_itself_validates_strict(tmp_path: Path) -> None:
    # With a marketplace.json present the validator reads only that file, so
    # check the plugin manifest in a copy that has none.
    done = validate(copy_plugin(tmp_path, "plain", keep_marketplace=False), tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr


def test_plg_01_validate_can_fail_on_either_manifest(tmp_path: Path) -> None:
    """The checks above are only worth something if the validator can fail."""
    plain = copy_plugin(tmp_path, "plain", keep_marketplace=False)
    (plain / ".claude-plugin" / "plugin.json").write_text("{not json")
    assert validate(plain, tmp_path).returncode != 0
    market = copy_plugin(tmp_path, "market", keep_marketplace=True)
    (market / ".claude-plugin" / "marketplace.json").write_text("{not json")
    assert validate(market, tmp_path).returncode != 0
