"""Project pages: ids, folder, refusals, updater, default kind, snapshot (PROJ, #87)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_canvas.hub.registry import RegistryError, SessionRegistry
from agent_canvas.hub.state import HubState
from registry_env import Env, make_env

pytestmark = pytest.mark.unit


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """A registry with the read-only view and an agent table."""
    return make_env(tmp_path, monkeypatch)


def second_project(env: Env) -> Path:
    """Return another project folder next to the first."""
    other = env.project.parent / "other"
    other.mkdir()
    return other.resolve()


def test_proj_01_id_is_sha256_of_the_project_key_and_the_folder_is_project(
    env: Env,
) -> None:
    meta = env.registry.project_session(str(env.project))
    digest = hashlib.sha256(str(env.project).encode()).hexdigest()[:16]
    assert meta["id"] == f"project-{digest}"
    assert env.registry.folder_of(meta) == env.project / ".agent-canvas" / "project"
    assert env.registry.project_session(str(env.project))["id"] == meta["id"]


def test_proj_01_two_repos_get_different_ids_and_both_folders_are_project(
    env: Env,
) -> None:
    other = second_project(env)
    first = env.registry.project_session(str(env.project))
    second = env.registry.project_session(str(other))
    assert first["id"] != second["id"]
    assert env.registry.folder_of(first).name == "project"
    assert env.registry.folder_of(second) == other / ".agent-canvas" / "project"


def test_proj_02_creates_session_json_with_agent_project_and_survives_a_reload(
    env: Env, tmp_path: Path
) -> None:
    meta = env.registry.project_session(str(env.project))
    on_disk = json.loads(
        (env.project / ".agent-canvas/project/session.json").read_text()
    )
    assert on_disk["agent"] == "project" and on_disk["title"] == "Project pages"
    assert on_disk["state"] == "active" and on_disk["project"] == str(env.project)
    again = SessionRegistry(env.state_dir, HubState(1, "k", lambda: 0.0))
    again.load()
    assert again.get(meta["id"]).agent == "project"
    assert again.folder_of(meta) == env.registry.folder_of(meta)


def test_proj_05_an_ordinary_id_with_the_prefix_is_refused(env: Env) -> None:
    for session_id in ("project-0123456789abcdef", "project-x", "project"):
        with pytest.raises(RegistryError) as refused:
            env.registry.create(session_id, str(env.project), "a", None)
        assert refused.value.code == "no-session"
        with pytest.raises(RegistryError):
            env.registry.reserve(session_id, str(env.project), "a")
        with pytest.raises(RegistryError):
            env.registry.ensure(session_id, str(env.project), "a")
    assert not (env.project / ".agent-canvas").exists()
    assert not env.state_dir.joinpath("sessions.json").exists()


def test_proj_05_end_and_title_of_project_pages_are_refused_and_write_nothing(
    env: Env,
) -> None:
    meta = env.registry.project_session(str(env.project))
    path = env.registry.folder_of(meta) / "session.json"
    before = path.read_text()
    with pytest.raises(RegistryError) as ended:
        env.registry.end(meta["id"])
    with pytest.raises(RegistryError) as titled:
        env.registry.set_title(meta["id"], "Mine")
    assert ended.value.code == titled.value.code == "no-session"
    assert path.read_text() == before


def test_proj_04_a_later_updater_replaces_the_earlier_one(env: Env) -> None:
    project_id = env.registry.project_session(str(env.project))["id"]
    env.add_page(project_id, "plan.html")
    for session_id, agent in (("a", "claude-code"), ("b", "opencode")):
        env.registry.create(
            session_id, str(env.project), agent, f"Session {session_id}"
        )
        who = env.registry.updater(session_id)
        env.registry.note_updater(project_id, "plan.html", who)
        stored = env.registry.get(project_id).page_meta["plan.html"]["updated_by"]
        assert stored == who
        assert stored["session"] == session_id and stored["agent"] == agent
        assert stored["title"] == f"Session {session_id}"
        assert stored["time"].endswith("Z")
    listed = env.registry.page_list(project_id)
    assert listed[0]["updated_by"]["session"] == "b"


def test_proj_04_the_updater_of_a_reserved_session_has_its_agent_and_no_title(
    env: Env,
) -> None:
    env.registry.reserve("r1", str(env.project), "claude-code")
    who = env.registry.updater("r1")
    assert (who["session"], who["agent"], who["title"]) == ("r1", "claude-code", None)
    assert env.registry.updater("nobody") is None
    assert env.registry.project_of("r1") == str(env.project)


def test_proj_06_a_new_project_page_is_long_term_by_default(env: Env) -> None:
    project_id = env.registry.project_session(str(env.project))["id"]
    env.add_page(project_id, "plan.html")
    (row,) = env.registry.page_list(project_id)
    assert (row["kind"], row["set_by"]) == ("long-term", "default")
    env.registry.set_kind(project_id, "plan.html", "single-use")
    assert env.registry.page_list(project_id)[0]["kind"] == "single-use"


def test_proj_06_pages_of_ordinary_sessions_keep_the_default_kind(env: Env) -> None:
    env.add_page("s1", "plan.html")
    assert env.registry.page_list("s1")[0]["kind"] == "transitional"
    assert "updated_by" not in env.registry.page_list("s1")[0]
