"""Safe writes and set-asides (A-760 to A-766), and the loaders that use them."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

from agent_canvas.drafts import publish_draft
from agent_canvas.files_safe import set_aside, write_safely


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def fail(*args: object) -> None:
    raise OSError("boom")


def test_files_safe_the_temporary_name_is_unique_and_beside_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Path] = []
    real = os.replace
    monkeypatch.setattr(
        os, "replace", lambda a, b: (seen.append(Path(a)), real(a, b))[1]
    )
    write_safely(tmp_path / "a.json", "1")
    write_safely(tmp_path / "a.json", "2")
    assert seen[0] != seen[1]
    assert all(p.parent == tmp_path and p.name != "a.json" for p in seen)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]


def written_under(umask: int, directory: Path, *args: object, **kwargs: bool) -> int:
    old = os.umask(umask)
    try:
        write_safely(directory / "a.json", "x", *args, **kwargs)  # type: ignore[arg-type]
    finally:
        os.umask(old)
    return mode_of(directory / "a.json")


@pytest.mark.parametrize("mode", [0o600, 0o644])
def test_files_safe_the_mode_is_as_asked_under_umask_022_despite_a_stale_temporary_file(
    tmp_path: Path, mode: int
) -> None:
    stale = tmp_path / "a.json.tmp"
    stale.write_text("stale")
    stale.chmod(0o666)
    assert written_under(0o022, tmp_path, mode) == mode


def test_files_safe_a_private_mode_stays_private_under_umask_000(
    tmp_path: Path,
) -> None:
    stale = tmp_path / "a.json.tmp"
    stale.write_text("stale")
    stale.chmod(0o666)
    assert written_under(0o000, tmp_path, 0o600) == 0o600


def test_files_safe_a_0644_request_follows_a_strict_umask(tmp_path: Path) -> None:
    assert written_under(0o077, tmp_path, 0o644) == 0o600


def test_files_safe_an_exact_mode_ignores_the_umask(tmp_path: Path) -> None:
    assert written_under(0o077, tmp_path, 0o644, exact=True) == 0o644


def test_files_safe_without_a_mode_the_umask_decides(tmp_path: Path) -> None:
    assert written_under(0o027, tmp_path) == 0o640


def test_files_safe_text_and_bytes_are_written(tmp_path: Path) -> None:
    write_safely(tmp_path / "t", "é")
    write_safely(tmp_path / "b", b"\x00\xff")
    assert (tmp_path / "t").read_bytes() == "é".encode()
    assert (tmp_path / "b").read_bytes() == b"\x00\xff"


def test_files_safe_an_error_during_the_rename_removes_the_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.json").write_text("old")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        write_safely(tmp_path / "a.json", "new")
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
    assert (tmp_path / "a.json").read_text() == "old"


def test_files_safe_an_error_during_the_write_keeps_the_old_file_and_cleans_up(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.json").write_text("old")
    with pytest.raises(TypeError):
        write_safely(tmp_path / "a.json", 5)  # type: ignore[arg-type]
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
    assert (tmp_path / "a.json").read_text() == "old"


def test_files_safe_a_write_error_after_the_open_removes_the_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "fchmod", fail)
    with pytest.raises(OSError):
        write_safely(tmp_path / "a.json", "new", 0o600, exact=True)
    assert list(tmp_path.iterdir()) == []


def test_files_safe_set_aside_renames_to_bad(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "a.json").write_text("{x")
    with caplog.at_level(logging.WARNING):
        set_aside(tmp_path / "a.json")
    assert (tmp_path / "a.json.bad").read_text() == "{x"
    assert not (tmp_path / "a.json").exists()
    assert "renamed to a.json.bad" in caplog.text


def test_files_safe_set_aside_does_not_raise_when_the_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "a.json").write_text("{x")
    monkeypatch.setattr(os, "replace", fail)
    with caplog.at_level(logging.WARNING):
        set_aside(tmp_path / "a.json")
    assert (tmp_path / "a.json").read_text() == "{x"
    assert "cannot be set aside" in caplog.text


def blocked_bad_file(path: Path) -> None:
    """A damaged file whose ``.bad`` name is a non-empty folder: the rename fails."""
    path.write_text("not json")
    (path.parent / (path.name + ".bad") / "inside").mkdir(parents=True)
    (path.parent / (path.name + ".bad") / "inside" / "f").write_text("x")


def test_files_safe_a_target_name_of_250_characters_still_gets_a_valid_temporary_name(
    tmp_path: Path,
) -> None:
    name = "a" * 246 + ".pdf"
    write_safely(tmp_path / name, b"x")
    assert (tmp_path / name).read_bytes() == b"x"


def test_files_safe_a_published_draft_is_0644_even_under_umask_077(
    tmp_path: Path,
) -> None:
    (tmp_path / "p.draft.html").write_text("<p>x</p>")
    old = os.umask(0o077)
    try:
        publish_draft(tmp_path, "p.html")
    finally:
        os.umask(old)
    assert mode_of(tmp_path / "p.html") == 0o644
