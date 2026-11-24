"""The migration wired to the registry, and the liveness of a hook-only session (#2).

POOL-09: the registry records a migrated page; a project is migrated once when the
hub starts. POOL-05, design risk D.4: a live Claude Code process counts as alive.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_canvas.hub import migrate
from agent_canvas.hub.herdr_app import HerdrApp
from agent_canvas.hub.lifetime import DEFAULT_KIND
from agent_canvas.hub.migrate import LOG_NAME, migrate_at_start, migrate_project
from agent_canvas.hub.registry import _new_entry, pool_id
from agent_canvas.hub.watcher import PageHistory
from registry_env import Env, make_env

pytestmark = pytest.mark.unit

WHO = {
    "session": "old",
    "title": "Old",
    "agent": "claude",
    "time": "2026-01-01T00:00:00.000Z",
}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return make_env(tmp_path, monkeypatch)


def old_page(env: Env, sid: str, name: str, html: str) -> Path:
    """An old-style session folder holding a page with one saved version."""
    registry = env.registry
    meta, _ = registry.ensure(sid, str(env.project), "claude")
    folder = registry.folder_of(meta)
    (folder / name).write_text(html)
    PageHistory(folder).save(name, html.encode())
    registry._update(sid, pages=[*meta["pages"], name], active_page=name)
    return folder


def pool_meta(env: Env) -> dict:
    found = env.registry.get(pool_id(env.registry.pool_tag, str(env.project)))
    assert found is not None
    return dict(found.raw)


def test_pool_09_a_migrated_record_becomes_a_full_entry_and_the_page_is_listed(
    env: Env,
) -> None:
    pool = env.registry.pool_session(str(env.project))
    record = {"kind": "long-term", "set_by": "owner", "starred": True,
              "created_by": WHO, "updated_by": WHO, "digest": "d",
              "sessions": {"old": {"time": WHO["time"], "digest": "d"}}}  # fmt: skip
    assert env.registry.record_migrated(pool["id"], "dash.html", record) is True
    meta = pool_meta(env)
    assert meta["pages"] == ["dash.html"]
    entry = meta["page_meta"]["dash.html"]
    assert set(_new_entry(DEFAULT_KIND, "default")) <= set(entry)
    assert {k: entry[k] for k in record} == record


def test_pool_09_a_migrated_record_never_replaces_an_existing_one(env: Env) -> None:
    pool = env.registry.pool_session(str(env.project))
    first = {"created_by": WHO, "updated_by": WHO, "digest": "a", "sessions": {}}
    assert env.registry.record_migrated(pool["id"], "dash.html", first)
    second = {**first, "digest": "b", "kind": "single-use"}
    assert env.registry.record_migrated(pool["id"], "dash.html", second) is False
    meta = pool_meta(env)
    assert meta["pages"] == ["dash.html"]
    assert meta["page_meta"]["dash.html"]["digest"] == "a"


def test_pool_09_the_plan_of_a_project_writes_nothing_and_makes_no_pool(
    env: Env,
) -> None:
    old = old_page(env, "sess-a", "dash.html", "<p>a</p>")
    before = sorted(p.name for p in old.parent.iterdir())
    plan = migrate_project(env.registry, str(env.project), apply=False)
    assert [(m["page"], m["session"]) for m in plan["moves"]] == [
        ("dash.html", "sess-a")
    ]
    assert sorted(p.name for p in old.parent.iterdir()) == before
    assert env.registry.pool_of("sess-a") is None


def test_pool_09_applying_a_project_fills_its_pool_and_the_card_lists_the_page(
    env: Env,
) -> None:
    old_page(env, "sess-a", "dash.html", "<p>a</p>")
    done = migrate_project(env.registry, str(env.project), apply=True)
    assert done["moved"] == ["sess-a/dash.html"]
    folder = env.registry.pool_folder(str(env.project))
    assert (folder / "dash.html").read_text() == "<p>a</p>"
    assert (folder / LOG_NAME).is_file()
    meta = env.registry.get("sess-a")
    assert meta is not None
    assert env.registry.tab_of(dict(meta.raw))["pages"] == ["dash.html"]


def test_pool_09_hub_start_migrates_a_project_once_and_leaves_out_the_pool(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_page(env, "sess-a", "dash.html", "<p>a</p>")
    seen: list[set[str]] = []
    plan = migrate.plan_migration

    def spy(known, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        seen.append(set(known))
        return plan(known, *args, **kwargs)

    monkeypatch.setattr(migrate, "plan_migration", spy)
    migrate_at_start(env.registry)
    assert seen == [{"sess-a"}]  # the pool made by the run is not a known session
    folder = env.registry.pool_folder(str(env.project))
    log = (folder / LOG_NAME).read_text()
    migrate_at_start(env.registry)
    assert len(seen) == 1  # once: a project whose pool has a log is not planned again
    assert (folder / LOG_NAME).read_text() == log


def test_pool_09_a_failing_migration_at_hub_start_is_reported_not_raised(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old_page(env, "sess-a", "dash.html", "<p>a</p>")

    def broken(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(migrate, "plan_migration", broken)
    migrate_at_start(env.registry)
    assert "disk on fire" in capsys.readouterr().err


def pool_pages(env: Env) -> list[str]:
    return sorted(pool_meta(env)["page_meta"])


def test_pool_09_a_start_killed_half_way_is_finished_at_the_next_start(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_page(env, "sess-a", "dash.html", "<p>a</p>")
    old_page(env, "sess-a", "notes.html", "<p>n</p>")
    record = env.registry.record_migrated
    written: list[str] = []

    def killed_after_one(pool, name, entry):  # noqa: ANN001, ANN202
        if written:
            raise KeyboardInterrupt  # stands in for the hub being killed
        written.append(name)
        return record(pool, name, entry)

    monkeypatch.setattr(env.registry, "record_migrated", killed_after_one)
    with pytest.raises(KeyboardInterrupt):
        migrate_at_start(env.registry)
    folder = env.registry.pool_folder(str(env.project))
    assert (folder / LOG_NAME).is_file()  # the half-way log is there
    assert len(pool_pages(env)) == 1
    monkeypatch.setattr(env.registry, "record_migrated", record)
    migrate_at_start(env.registry)
    assert pool_pages(env) == ["dash.html", "notes.html"]
    assert json.loads((folder / LOG_NAME).read_text())["complete"] is True


def test_pool_09_an_error_of_the_record_writer_skips_the_page_and_the_next_start_takes_it(  # noqa: E501
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_page(env, "sess-a", "dash.html", "<p>a</p>")
    old_page(env, "sess-a", "notes.html", "<p>n</p>")
    record = env.registry.record_migrated

    def full_disk(pool, name, entry):  # noqa: ANN001, ANN202
        if name == "notes.html":
            raise OSError(28, "No space left on device")
        return record(pool, name, entry)

    monkeypatch.setattr(env.registry, "record_migrated", full_disk)
    migrate_at_start(env.registry)
    folder = env.registry.pool_folder(str(env.project))
    log = json.loads((folder / LOG_NAME).read_text())
    assert pool_pages(env) == ["dash.html"]
    assert [s["file"] for s in log["skipped"]] == ["notes.html"]
    assert not log.get("complete")
    monkeypatch.setattr(env.registry, "record_migrated", record)
    migrate_at_start(env.registry)
    assert pool_pages(env) == ["dash.html", "notes.html"]
    assert json.loads((folder / LOG_NAME).read_text())["complete"] is True


def fake_process(proc: Path, pid: int, comm: str) -> None:
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "comm").write_text(comm + "\n")


def test_pool_05_a_live_claude_code_process_counts_as_alive(tmp_path: Path) -> None:
    sessions, proc = tmp_path / "sessions", tmp_path / "proc"
    sessions.mkdir()
    fake_process(proc, os.getpid(), "claude")
    fake_process(proc, 4243, "bash")  # the pid of an ended session, reused
    (sessions / f"{os.getpid()}.json").write_text(json.dumps({"sessionId": "live"}))
    (sessions / "4243.json").write_text(json.dumps({"sessionId": "reused"}))
    (sessions / "999999.json").write_text(json.dumps({"sessionId": "stale"}))
    herdr = HerdrApp(sessions_dir=sessions, proc_dir=proc)
    assert herdr.alive("live")
    assert not herdr.alive("reused")  # that process is not Claude Code
    assert not herdr.alive("stale")  # its process is gone
    assert not herdr.alive("other")


def test_pool_05_the_claude_sessions_folder_is_that_of_the_home_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    sessions, proc = tmp_path / ".claude" / "sessions", tmp_path / "proc"
    sessions.mkdir(parents=True)
    fake_process(proc, os.getpid(), "claude")
    (sessions / f"{os.getpid()}.json").write_text(json.dumps({"sessionId": "live"}))
    assert HerdrApp(proc_dir=proc).alive("live")
