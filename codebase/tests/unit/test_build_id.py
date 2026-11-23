"""Build identity of the served shell files (SHELL-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_canvas.hub.build import compute_build_id

pytestmark = pytest.mark.unit


def make_static(root: Path) -> Path:
    """Write a small static directory with a vendor manifest."""
    static = root / "static"
    (static / "vendor").mkdir(parents=True)
    (static / "shell.js").write_text("console.log(1)")
    (static / "blocks").mkdir()
    (static / "blocks" / "base.js").write_text("// base")
    (static / "vendor" / "MANIFEST.json").write_text(json.dumps({"a.js": "abc"}))
    (static / "vendor" / "a.js").write_text("vendored")
    return static


def test_shell_01_the_identity_is_stable(tmp_path: Path) -> None:
    static = make_static(tmp_path)
    first = compute_build_id(static, "0.2.1")
    assert first == compute_build_id(static, "0.2.1")
    assert first and first.isalnum()


def test_shell_01_a_changed_file_changes_the_identity(tmp_path: Path) -> None:
    static = make_static(tmp_path)
    before = compute_build_id(static, "0.2.1")
    (static / "blocks" / "base.js").write_text("// base, changed")
    assert compute_build_id(static, "0.2.1") != before


def test_shell_01_an_added_file_changes_the_identity(tmp_path: Path) -> None:
    static = make_static(tmp_path)
    before = compute_build_id(static, "0.2.1")
    (static / "extra.js").write_text("")
    assert compute_build_id(static, "0.2.1") != before


def test_shell_01_a_changed_version_changes_the_identity(tmp_path: Path) -> None:
    static = make_static(tmp_path)
    assert compute_build_id(static, "0.2.0") != compute_build_id(static, "0.2.1")


def test_shell_01_vendored_files_count_through_their_manifest(tmp_path: Path) -> None:
    static = make_static(tmp_path)
    before = compute_build_id(static, "0.2.1")
    (static / "vendor" / "MANIFEST.json").write_text(json.dumps({"a.js": "def"}))
    assert compute_build_id(static, "0.2.1") != before


def test_shell_01_the_real_static_directory_has_an_identity() -> None:
    from agent_canvas import __version__
    from agent_canvas.hub.app import STATIC_DIR

    assert compute_build_id(STATIC_DIR, __version__)
