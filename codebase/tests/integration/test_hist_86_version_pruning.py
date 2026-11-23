"""Saved page versions older than 30 days are deleted by the hub (HIST-86).

Every test works in the folders of the ``hub`` fixture under ``tmp_path`` and
moves time with the test clock; version files keep their real times (A-250).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import clock
from agent_canvas.hub import comments as store
from agent_canvas.hub import purge as purge_module
from agent_canvas.hub.lifetime import DAY_SECONDS

pytestmark = pytest.mark.integration

PAGE = "<title>one</title><p>three</p>"


def shifted(monkeypatch, days: float) -> None:  # noqa: ANN001
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(days * DAY_SECONDS))


def put(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def hashes(root: Path) -> dict[str, str]:
    """Hash every file below ``root``; links are listed by their target, not read."""
    found = {}
    for p in sorted(root.rglob("*")):
        key = str(p.relative_to(root))
        if p.is_symlink():
            found[key] = f"link to {os.readlink(p)}"
        elif p.is_file():
            found[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return found


def run_purge(hub) -> list[str]:  # noqa: ANN001
    services = hub.app.state.services
    return hub.on_loop(lambda: purge_module.purge(services.registry))


def versions(folder: Path, stem: str = "one", suffix: str = ".html") -> list[str]:
    pages = folder / "history/pages"
    return sorted(p.name for p in pages.glob(f"{stem}.[0-9][0-9][0-9][0-9]{suffix}"))


def show(hub, name: str) -> None:  # noqa: ANN001
    httpx.post(
        f"{hub.base_url}/api/sessions/a/show",
        json={"name": name, "audit": False},
        headers=hub.key_headers,
        timeout=30,
    ).raise_for_status()


@pytest.fixture
def folder(hub) -> Path:  # noqa: ANN001
    """Session ``a`` with ``one.html`` in three saved versions, the newest current."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    place = Path(answer.json()["folder"])
    put(place / "one.html", PAGE)
    show(hub, "one.html")
    put(place / "history/pages/one.0001.html", "<p>one</p>")
    put(place / "history/pages/one.0002.html", "<p>two</p>")
    put(place / "history/pages/one.0003.html", PAGE)
    return place


def test_hist_86_a_31_day_old_version_of_a_page_with_newer_versions_is_deleted(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    capsys,  # noqa: ANN001
) -> None:
    shifted(monkeypatch, 31)
    capsys.readouterr()
    run_purge(hub)
    assert versions(folder) == ["one.0003.html"]
    log = capsys.readouterr().err
    assert "agent-canvas: purge: deleted a/history/pages/one.0001.html" in log
    assert (folder / "one.html").read_text() == PAGE


def test_hist_86_a_29_day_old_version_is_kept(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    shifted(monkeypatch, 29)
    run_purge(hub)
    assert versions(folder) == ["one.0001.html", "one.0002.html", "one.0003.html"]


def test_hist_86_the_age_is_each_versions_own(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    old = folder / "history/pages/one.0001.html"
    stamp = old.stat().st_mtime - 2 * DAY_SECONDS
    os.utime(old, (stamp, stamp))
    shifted(monkeypatch, 29.5)
    run_purge(hub)
    assert versions(folder) == ["one.0002.html", "one.0003.html"]


def test_hist_86_the_newest_version_of_every_page_is_kept_even_at_100_days(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    put(folder / "notes.md", "# notes")
    show(hub, "notes.md")
    put(folder / "history/pages/notes.0001.md", "# draft")
    put(folder / "history/pages/notes.0002.md", "# notes")
    put(folder / "history/pages/gone.0004.html", "a page no longer listed")
    put(folder / "history/pages/gone.0007.html", "its newest version")
    shifted(monkeypatch, 100)
    run_purge(hub)
    assert versions(folder) == ["one.0003.html"]
    assert versions(folder, "notes", ".md") == ["notes.0002.md"]
    assert versions(folder, "gone") == ["gone.0007.html"]


def comment(folder: Path, version: int, *, sent: bool, done: bool) -> int:
    record = store.create(
        folder,
        "one.html",
        {
            "kind": "point",
            "text": f"on {version}",
            "anchor": {},
            "page_version": version,
        },
    )
    if sent:
        store.take_unsent(folder, "one.html", "now", "evt_x")
    if done:
        store.set_done(folder, "one.html", record["n"], "owner")
    return record["n"]


def test_hist_86_a_version_a_comment_that_is_not_done_points_at_is_kept(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    comment(folder, 1, sent=True, done=False)
    comment(folder, 2, sent=True, done=True)
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert versions(folder) == ["one.0001.html", "one.0003.html"]


def test_hist_86_a_draft_comment_keeps_its_version(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    comment(folder, 2, sent=False, done=False)
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert versions(folder) == ["one.0002.html", "one.0003.html"]


def send(folder: Path, number: int, version: int, comment_numbers: list[int]) -> None:
    record = {
        "page": "one.html",
        "page_version": version,
        "comments": [{"n": n} for n in comment_numbers],
    }
    put(folder / f"history/sends/{number:04d}.json", json.dumps(record))


def test_hist_86_a_version_a_send_with_open_comments_points_at_is_kept(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    open_one = comment(folder, 3, sent=True, done=False)
    done_one = comment(folder, 3, sent=True, done=True)
    send(folder, 1, 1, [open_one])
    send(folder, 2, 2, [done_one])
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert versions(folder) == ["one.0001.html", "one.0003.html"]


def test_hist_86_the_version_the_owner_last_saw_is_kept(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    registry = hub.app.state.services.registry
    assert hub.on_loop(lambda: registry.note_seen("a", "one.html", 2))
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert versions(folder) == ["one.0002.html", "one.0003.html"]


def test_hist_86_nothing_but_old_saved_versions_is_ever_deleted(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    """Old files in every place the pass must not touch all survive it."""
    planted = [
        "two.html",
        "two.draft.html",
        "assets/one.0001.html",
        "assets/picture.png",
        "data.0001.csv",
        "one.0001.html",
        "history/looks/one.0001.png",
        "history/looks/one.0001.html",
        "history/sends/0001.json",
        "history/sends/0001.png",
        "history/sends/0001.c1.png",
        "history/one.0001.html",
        "history/pages/sub/one.0001.html",
        "history/pages/notes.txt",
        "history/pages/one.0001.html.bak",
        "history/pages/one.01.html",
        "history/pages/one.0001.csv",
        "history/pages/.v-0123456789ab",
        ".comments/one.html.json",
        ".comments/one.html.1.png",
        ".answers/one.html.json",
        "events.jsonl",
    ]
    for name in planted:
        put(folder / name, f"planted {name}")
    empty = {"schema": store.SCHEMA, "page": "one.html", "next": 1, "comments": []}
    put(folder / ".comments/one.html.json", json.dumps(empty))
    put(folder.parent / "other/history/pages/one.0001.html", "not ours")
    put(folder.parent / "other/history/pages/one.0002.html", "not ours")
    before = hashes(folder.parent)
    shifted(monkeypatch, 365)
    run_purge(hub)
    after = hashes(folder.parent)
    gone = {f"{folder.name}/history/pages/one.000{n}.html" for n in (1, 2)}
    assert set(before) - set(after) == gone
    assert {k: v for k, v in before.items() if k not in gone} == after
    assert len(after) >= len(planted) + 4


def test_hist_86_runs_in_the_same_pass_as_the_deletion_of_archived_pages(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    put(folder / "two.html", "<p>two</p>")
    show(hub, "two.html")
    httpx.post(
        f"{hub.base_url}/api/sessions/a/pages",
        json={"action": "archive", "name": "two.html"},
        headers=hub.key_headers,
    ).raise_for_status()
    shifted(monkeypatch, 31)
    assert run_purge(hub) == ["a/two.html"]
    assert not (folder / "two.html").exists()
    assert versions(folder) == ["one.0003.html"]


def test_hist_86_a_symbolic_link_in_saved_versions_is_neither_followed_nor_deleted(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    outside = put(folder.parent / "outside/target.html", "outside page")
    (folder / "history/pages/one.0001.html").unlink()
    (folder / "history/pages/one.0001.html").symlink_to(outside)
    (folder / "history/pages/one.0000.html").symlink_to(folder / "missing")
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert (folder / "history/pages/one.0001.html").is_symlink()
    assert (folder / "history/pages/one.0000.html").is_symlink()
    assert outside.read_text() == "outside page"
    assert not (folder / "history/pages/one.0002.html").exists()


@pytest.mark.parametrize("linked", ["history", "history/pages"])
def test_hist_86_a_linked_history_folder_is_not_entered(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    linked: str,
) -> None:
    outside = folder.parent / "outside"
    real = folder / linked
    real.rename(outside)
    real.symlink_to(outside)
    before = hashes(outside)
    assert len(before) >= 3
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert hashes(outside) == before


@pytest.mark.parametrize(
    "name",
    [
        "one.0001.html.bak",
        "one.01.html",
        "one.0001.csv",
        "notes.txt",
        ".v-0a1b2c3d4e5f",
    ],
)
def test_hist_86_a_file_not_named_like_a_version_is_left_alone(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    name: str,
) -> None:
    stray = put(folder / "history/pages" / name, "stray")
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert stray.read_text() == "stray"
    assert versions(folder) == ["one.0003.html"]


def test_hist_86_a_failure_on_one_file_is_logged_and_the_pass_goes_on(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    capsys,  # noqa: ANN001
) -> None:
    real = Path.unlink

    def failing(self: Path, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if self.name == "one.0001.html":
            raise PermissionError("refused")
        real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing)
    shifted(monkeypatch, 31)
    capsys.readouterr()
    run_purge(hub)
    assert versions(folder) == ["one.0001.html", "one.0003.html"]
    log = capsys.readouterr().err
    assert "purge: failed a/history/pages/one.0001.html: PermissionError" in log
    assert httpx.get(f"{hub.base_url}/health").status_code == 200


def test_hist_86_the_history_list_of_a_pruned_page_lists_only_kept_versions(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    shifted(monkeypatch, 31)
    run_purge(hub)
    answer = httpx.get(
        f"{hub.base_url}/api/sessions/a/versions",
        params={"page": "one.html"},
        headers=hub.key_headers,
    )
    assert answer.status_code == 200
    assert [v["version"] for v in answer.json()["versions"]] == [3]
    changes = httpx.get(
        f"{hub.base_url}/api/sessions/a/changes",
        params={"page": "one.html", "since": "1"},
        headers=hub.key_headers,
    )
    assert changes.status_code == 200
    assert changes.json()["count"] == 0


def session(hub, session_id: str) -> Path:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{session_id}/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    return Path(answer.json()["folder"])


def three_versions(folder: Path, stem: str, suffix: str = ".html") -> None:
    for number in (1, 2, 3):
        put(folder / f"history/pages/{stem}.{number:04d}{suffix}", f"{stem} {number}")


def test_hist_86_a_number_in_other_digits_is_not_a_version(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    low = put(folder / "history/pages/one.٠٠٠١.html", "stray")
    high = put(folder / "history/pages/one.٩٩٩٩.html", "stray")
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert low.read_text() == "stray" and high.read_text() == "stray"
    assert versions(folder) == ["one.0003.html"]


def test_hist_86_a_broken_comment_file_spares_its_session_and_no_other(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    capsys,  # noqa: ANN001
) -> None:
    put(folder / ".comments/one.html.json", "not json")
    other = session(hub, "b")
    three_versions(other, "two")
    shifted(monkeypatch, 31)
    capsys.readouterr()
    run_purge(hub)
    assert versions(folder) == ["one.0001.html", "one.0002.html", "one.0003.html"]
    assert versions(other, "two") == ["two.0003.html"]
    assert "purge: failed versions of a: JSONDecodeError" in capsys.readouterr().err


def test_hist_86_each_page_keeps_its_own_newest_version(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    for stem, suffix in [
        ("a", ".html"),
        ("a.0001", ".html"),
        ("report.2024", ".html"),
        ("picture", ".png"),
        ("paper", ".pdf"),
    ]:
        three_versions(folder, stem, suffix)
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert sorted(p.name for p in (folder / "history/pages").iterdir()) == [
        "a.0001.0003.html",
        "a.0003.html",
        "one.0003.html",
        "paper.0003.pdf",
        "picture.0003.png",
        "report.2024.0003.html",
    ]


def test_hist_86_a_send_whose_comment_is_gone_from_the_store_keeps_its_version(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    send(folder, 1, 1, [7])
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert versions(folder) == ["one.0001.html", "one.0003.html"]


def test_hist_86_a_session_folder_that_is_a_link_is_pruned(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    linked = session(hub, "b")
    real = hub.project_dir.parent / "real-b"
    linked.rename(real)
    linked.symlink_to(real)
    three_versions(real, "two")
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert linked.is_symlink()
    assert versions(real, "two") == ["two.0003.html"]


def test_hist_86_saved_versions_linked_to_a_folder_inside_the_session_are_not_touched(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    inside = folder / "elsewhere"
    (folder / "history/pages").rename(inside)
    (folder / "history/pages").symlink_to(inside)
    before = hashes(inside)
    assert len(before) >= 3
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert hashes(inside) == before
