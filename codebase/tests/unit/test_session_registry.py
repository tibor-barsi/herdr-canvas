"""Session registry: session.json, .gitignore, persistence (SES, HUB-04/07)."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

import pytest

from agent_canvas.hub.registry import RegistryError, SessionRegistry
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit

STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    project = home / "proj"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    def make(
        project_dir_name: str = ".agent-canvas",
    ) -> tuple[SessionRegistry, HubState]:
        state = HubState(1, "k", lambda: 0.0)
        registry = SessionRegistry(state_dir, state, project_dir_name)
        registry.load()
        return registry, state

    registry, state = make()
    return registry, state, project, state_dir, make


def test_ses_01_session_json_has_exactly_the_documented_fields(env) -> None:
    registry, _, project, _, _ = env
    meta = registry.create("3f2a", str(project), "claude-code", "Bracket")
    on_disk = json.loads((project / ".agent-canvas/3f2a/session.json").read_text())
    assert on_disk == meta
    assert set(on_disk) == {
        "schema", "id", "agent", "title", "owner_title", "project", "state",
        "hidden", "pages", "active_page", "created", "updated", "open_asks",
    }  # fmt: skip
    assert on_disk["schema"] == "agent-canvas/session@1"
    assert (on_disk["id"], on_disk["agent"], on_disk["title"]) == (
        "3f2a", "claude-code", "Bracket"
    )  # fmt: skip
    assert on_disk["project"] == str(project.resolve())
    assert (on_disk["state"], on_disk["hidden"]) == ("active", False)
    assert (on_disk["pages"], on_disk["active_page"]) == ([], None)
    assert on_disk["owner_title"] is None and on_disk["open_asks"] == []
    assert STAMP.match(on_disk["created"]) and STAMP.match(on_disk["updated"])


def test_ses_04_start_uses_uuid4(env) -> None:
    registry, _, project, _, _ = env
    meta = registry.start(str(project), "agent", None)
    assert uuid.UUID(meta["id"]).version == 4
    assert registry.folder_of(meta).is_dir()


def test_hub_07_gitignore_is_created_with_star(env) -> None:
    registry, _, project, _, _ = env
    registry.create("a", str(project), "agent", None)
    assert (project / ".agent-canvas/.gitignore").read_text() == "*\n"


def test_ses_03_default_folder_is_agent_canvas_not_claude(env) -> None:
    registry, _, project, _, _ = env
    meta = registry.create("a", str(project), "agent", None)
    assert registry.folder_of(meta) == project.resolve() / ".agent-canvas" / "a"
    assert not (project / ".claude").exists()


def test_ses_03_configured_folder_name(env) -> None:
    *_, project, _, make = env
    registry, _ = make("tools/canvas")
    meta = registry.create("a", str(project), "agent", None)
    assert registry.folder_of(meta) == project.resolve() / "tools/canvas/a"
    assert (project / "tools/canvas/a/session.json").is_file()
    assert (project / "tools/canvas/.gitignore").read_text() == "*\n"
    assert not (project / ".agent-canvas").exists()


def test_hub_07_existing_gitignore_is_left_unchanged(env) -> None:
    registry, _, project, _, _ = env
    canvas = project / ".agent-canvas"
    canvas.mkdir(parents=True)
    (canvas / ".gitignore").write_text("custom\n")
    registry.create("a", str(project), "agent", None)
    registry.create("b", str(project), "agent", None)
    assert (canvas / ".gitignore").read_text() == "custom\n"


def test_ses_03_known_session_keeps_recorded_project(env, tmp_path: Path) -> None:
    registry, _, project, _, _ = env
    other = tmp_path / "home" / "other"
    other.mkdir()
    registry.create("a", str(project), "agent", None)
    meta, created = registry.ensure("a", str(other), "agent")
    assert not created
    assert meta["project"] == str(project.resolve())


def test_ses_03_home_is_refused(env, tmp_path: Path) -> None:
    registry = env[0]
    with pytest.raises(RegistryError) as excinfo:
        registry.create("a", str(tmp_path / "home"), "agent", None)
    assert excinfo.value.code == "failed"
    assert "--project" in str(excinfo.value)


def test_hub_04_registry_is_persisted_and_reloaded(env) -> None:
    registry, state, project, state_dir, make = env
    registry.create("a", str(project), "agent", None)
    token = state.sessions()[0].page_token
    entry = json.loads((state_dir / "sessions.json").read_text())["a"]
    assert entry == {"project": str(project.resolve()), "page_token": token}

    registry2, state2 = make()
    assert [s.session_id for s in state2.sessions()] == ["a"]
    assert state2.sessions()[0].page_token == token
    assert registry2.get("a").id == "a"


def test_hub_04_corrupt_registry_names_the_file(env) -> None:
    _, _, _, state_dir, make = env
    (state_dir / "sessions.json").write_text("{nope")
    with pytest.raises(RegistryError, match="sessions.json"):
        make()


def test_hub_04_entry_without_session_file_is_skipped_not_fatal(env) -> None:
    registry, _, project, _, make = env
    registry.create("a", str(project), "agent", None)
    (project / ".agent-canvas/a/session.json").unlink()
    _, state2 = make()
    assert state2.sessions() == []


def test_sec_08_registry_rejects_bad_ids(env) -> None:
    registry, _, project, _, _ = env
    with pytest.raises(RegistryError) as excinfo:
        registry.create("../x", str(project), "agent", None)
    assert excinfo.value.code == "no-session"
    assert not (project / ".claude" / "x").exists()


def test_cli_02_sec_08_show_rejects_page_outside_folder(env, tmp_path: Path) -> None:
    registry, _, project, _, _ = env
    registry.create("a", str(project), "agent", None)
    outside = tmp_path / "x.html"
    outside.write_text("x")
    with pytest.raises(RegistryError, match="--copy") as excinfo:
        registry.show("a", str(outside), None, None)
    assert excinfo.value.code == "failed"


def test_cli_02_show_missing_file_names_the_folder(env) -> None:
    registry, _, project, _, _ = env
    registry.create("a", str(project), "agent", None)
    with pytest.raises(RegistryError) as excinfo:
        registry.show("a", "nope.html", None, None)
    pool = registry.pool_session(str(project))  # POOL-01: pages are the pool's
    assert str(registry.folder_of(pool)) in str(excinfo.value)


def test_cli_02_show_records_page_and_active_page(env) -> None:
    registry, state, project, _, _ = env
    registry.create("a", str(project), "agent", None)
    pool = registry.pool_session(str(project))  # POOL-01: show answers the pool
    (registry.folder_of(pool) / "page.html").write_text("<p>x</p>")
    meta, page, path = registry.show("a", None, "T", None)
    assert page == "page.html" and path.name == "page.html"
    assert (meta["pages"], meta["active_page"]) == (["page.html"], "page.html")
    assert registry.get("a").title == "T"
    assert state.active_url.endswith("/page.html")


def test_cli_16_show_copy_places_file_under_base_name(env, tmp_path: Path) -> None:
    registry, _, project, _, _ = env
    registry.create("a", str(project), "agent", None)
    source = tmp_path / "ext" / "design.html"
    source.parent.mkdir()
    source.write_text("<p>hi</p>")
    meta, page, path = registry.show("a", None, None, str(source))
    assert page == "design.html"  # POOL-01: copied into the pool
    assert (registry.folder_of(meta) / "design.html").read_text() == "<p>hi</p>"


def test_ses_01_hidden_flag_cleared_by_show(env) -> None:
    registry, _, project, _, _ = env
    registry.create("a", str(project), "agent", None)
    pool = registry.pool_session(str(project))  # POOL-01
    (registry.folder_of(pool) / "page.html").write_text("x")
    registry.set_hidden("a", True)
    assert registry.get("a").hidden is True
    registry.show("a", None, None, None)
    assert registry.get("a").hidden is False


def test_session_list_filters_ended_and_project(env, tmp_path: Path) -> None:
    registry, _, project, _, _ = env
    other = tmp_path / "home" / "other"
    other.mkdir()
    registry.create("a", str(project), "agent", None)
    registry.create("b", str(project), "agent", None)
    registry.create("c", str(other), "agent", None)
    registry.end("b")
    assert {m["id"] for m in registry.list(False, None)} == {"a", "c"}
    assert {m["id"] for m in registry.list(True, None)} == {"a", "b", "c"}
    assert {m["id"] for m in registry.list(True, str(other))} == {"c"}


# ---- SES-10 reserved sessions ----------------------------------------------


def test_ses_10_reserve_creates_no_folder_tab_or_watch_target(env) -> None:
    registry, state, project, state_dir, _ = env
    assert registry.reserve("r1", str(project), "claude-code") is True
    assert not (project / ".agent-canvas").exists()
    assert registry.list(True, None) == [] and registry.tabs() == []
    assert state.sessions() == []
    entry = json.loads((state_dir / "sessions.json").read_text())["r1"]
    assert entry["project"] == str(project) and "reserved" in entry
    assert registry.reserve("r1", str(project), "claude-code") is False


def test_ses_10_first_use_makes_it_a_real_session(env) -> None:
    registry, state, project, state_dir, _ = env
    registry.reserve("r2", str(project), "claude-code")
    meta, created = registry.ensure("r2", "", "claude-code")
    assert created and meta["project"] == str(project)
    assert (project / ".agent-canvas" / "r2" / "session.json").is_file()
    assert [s.session_id for s in state.sessions()] == ["r2"]
    assert "reserved" not in json.loads((state_dir / "sessions.json").read_text())["r2"]


def test_ses_10_unused_reservations_are_pruned_after_the_age_limit(env) -> None:
    registry, _, project, state_dir, make = env
    registry.reserve("old", str(project), "claude-code")
    registry.reserve("new", str(project), "claude-code")
    index = json.loads((state_dir / "sessions.json").read_text())
    index["old"]["reserved"] = "2000-01-01T00:00:00.000Z"
    (state_dir / "sessions.json").write_text(json.dumps(index))
    fresh, _ = make()  # load prunes and does not warn about the missing folder
    assert sorted(json.loads((state_dir / "sessions.json").read_text())) == ["new"]
    assert fresh.prune_reserved(0, now=time.time() + 10) == 1
    assert json.loads((state_dir / "sessions.json").read_text()) == {}


def test_ses_10_a_reservation_survives_a_hub_restart(env) -> None:
    registry, _, project, _, make = env
    registry.reserve("keep", str(project), "claude-code")
    again, state = make()
    assert again.is_reserved("keep") and state.sessions() == []


def test_sec_08_an_edited_id_or_project_in_session_json_is_ignored(env) -> None:
    registry, _, project, _, _ = env
    registry.create("honest", str(project), "agent", None)
    path = project / ".agent-canvas" / "honest" / "session.json"
    meta = json.loads(path.read_text())
    path.write_text(json.dumps({**meta, "id": "other", "project": "/elsewhere"}))
    found = registry.get("honest")
    assert (found.id, found.project) == ("honest", str(project))
    assert registry.folder_of(found) == path.parent


# ---- SES-18 a reserved id whose folder exists (#63) -------------------------


def _synced_folder(env) -> tuple[Path, str]:
    """Create a session under another state dir; return its project and id."""
    registry, _, project, state_dir, make = env
    registry.create("synced", str(project), "claude-code", "Synced")
    (state_dir / "sessions.json").unlink()
    return project, "synced"


def test_ses_18_reserved_id_with_existing_folder_is_registered(env) -> None:
    project, sid = _synced_folder(env)
    registry, state = env[4]()
    assert registry.reserve(sid, str(project), "claude-code") is True
    assert [t["id"] for t in registry.tabs()] == [sid]
    assert not registry.is_reserved(sid)
    assert state.session_of(sid).folder == (project / ".agent-canvas" / sid).resolve()


def test_ses_18_load_registers_reserved_entry_with_existing_folder(env) -> None:
    project, sid = _synced_folder(env)
    registry, _ = env[4]()
    registry.reserve(sid, str(project), "claude-code")
    registry, state = env[4]()
    assert [t["id"] for t in registry.tabs()] == [sid]
    assert state.session_of(sid)


def test_ses_18_unresolvable_session_is_skipped_by_tabs(env) -> None:
    registry, state, project, _, _ = env
    registry.create("good", str(project), "claude-code", None)
    registry.create("bad", str(project), "claude-code", None)
    state.unregister_session("bad")
    assert [t["id"] for t in registry.tabs()] == ["good"]


def test_ses_18_load_keeps_every_entry_on_disk(env) -> None:
    project, sid = _synced_folder(env)
    registry, _, _, state_dir, make = env
    registry, _ = make()
    registry.create("first", str(project), "claude-code", None)
    registry.create("last", str(project), "claude-code", None)
    index = json.loads((state_dir / "sessions.json").read_text())
    index = {
        "first": index["first"],
        sid: {"project": str(project), "agent": "claude-code", "reserved": "2026-11-16T13:42:00.000Z"},
        "last": index["last"],
    }
    (state_dir / "sessions.json").write_text(json.dumps(index))
    make()
    on_disk = json.loads((state_dir / "sessions.json").read_text())
    assert set(on_disk) == {"first", sid, "last"}
    assert "reserved" not in on_disk[sid]
