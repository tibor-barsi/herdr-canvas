"""Validation of ids, page names and paths (SEC-08, SES-02, SES-03)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.paths_safe import (
    InvalidSessionId,
    UnsafePathError,
    ensure_inside,
    resolve_page,
    resolve_session_id,
    validate_page_name,
    validate_project,
    validate_session_id,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ["a", "3f2a-b_C9", "x" * 64])
def test_ses_02_valid_ids_are_accepted(value: str) -> None:
    assert validate_session_id(value) == value


@pytest.mark.parametrize(
    "value", ["", "x" * 65, "a/b", "..", "a b", "a.b", "/abs", "a\x00", "é", "a\n"]
)
def test_ses_02_sec_08_invalid_ids_are_rejected(value: str) -> None:
    with pytest.raises(InvalidSessionId):
        validate_session_id(value)


def test_ses_02_option_beats_environment() -> None:
    assert resolve_session_id("from-opt", {"AGENT_CANVAS_SESSION": "from-env"}) == (
        "from-opt"
    )


def test_ses_02_environment_used_without_option() -> None:
    assert resolve_session_id(None, {"AGENT_CANVAS_SESSION": "from-env"}) == "from-env"


@pytest.mark.parametrize("env", [{}, {"AGENT_CANVAS_SESSION": ""}])
def test_ses_02_neither_source_raises(env: dict[str, str]) -> None:
    with pytest.raises(InvalidSessionId, match="No session id"):
        resolve_session_id(None, env)


def test_ses_02_malformed_resolved_id_raises() -> None:
    with pytest.raises(InvalidSessionId):
        resolve_session_id("../x", {})


@pytest.mark.parametrize("name", ["page.html", "other.htm", "a b.html", "x"])
def test_sec_08_plain_page_names_are_accepted(name: str) -> None:
    assert validate_page_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../x.html", "a/b.html", "/etc/passwd", "a\\b.html", "a\x00.html"]
    + ["history", "x" * 256],
)
def test_sec_08_page_names_with_separators_or_traversal_are_rejected(
    name: str,
) -> None:
    with pytest.raises(UnsafePathError):
        validate_page_name(name)


def test_sec_08_resolve_page_accepts_absolute_inside_folder(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    (folder / "page.html").write_text("x")
    name, path = resolve_page(folder, str(folder / "page.html"))
    assert (name, path) == ("page.html", (folder / "page.html").resolve())


def test_cli_02_resolve_page_rejects_absolute_outside_folder(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    outside = tmp_path / "x.html"
    outside.write_text("x")
    with pytest.raises(UnsafePathError, match="--copy"):
        resolve_page(folder, str(outside))


def test_sec_08_resolve_page_rejects_nested_absolute_path(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "p.html").write_text("x")
    with pytest.raises(UnsafePathError):
        resolve_page(folder, str(folder / "sub" / "p.html"))


def test_sec_08_resolve_page_rejects_symlink_leaving_folder(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    secret = tmp_path / "secret.html"
    secret.write_text("x")
    (folder / "page.html").symlink_to(secret)
    with pytest.raises(UnsafePathError):
        resolve_page(folder, "page.html")


def test_sec_08_ensure_inside_blocks_escape(tmp_path: Path) -> None:
    base = tmp_path / "b"
    base.mkdir()
    assert ensure_inside(base, base / "x" / "y") == (base / "x" / "y").resolve()
    for bad in (base / ".." / "z", tmp_path / "other", Path("/etc/passwd")):
        with pytest.raises(UnsafePathError):
            ensure_inside(base, bad)


def test_ses_03_project_must_be_absolute_existing_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "p").mkdir(parents=True)
    assert validate_project(str(home / "p"), home) == (home / "p").resolve()
    for bad in ("relative/dir", str(home / "missing"), "", "a\x00b"):
        with pytest.raises(UnsafePathError):
            validate_project(bad, home)


def test_ses_03_home_and_its_ancestors_are_refused(tmp_path: Path) -> None:
    home = tmp_path / "a" / "home"
    home.mkdir(parents=True)
    for refused in (home, home.parent, Path("/")):
        with pytest.raises(UnsafePathError, match="--project"):
            validate_project(str(refused), home)


def test_ses_03_directory_below_home_is_allowed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "sub").mkdir(parents=True)
    assert validate_project(str(home / "sub"), home) == (home / "sub").resolve()
