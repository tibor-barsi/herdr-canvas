"""The pool and its page record in the registry (POOL-01 to -03, -11, PROJ-05; #2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_canvas.drafts import draft_name_for, published_name_for, session_tag
from agent_canvas.hub.registry import RegistryError, SessionRegistry
from agent_canvas.hub.state import HubState
from agent_canvas.hub.watcher import PageHistory
from registry_env import Env, make_env

pytestmark = pytest.mark.unit


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """A registry with the read-only view and an agent table."""
    return make_env(tmp_path, monkeypatch)


def publish_as(env: Env, session_id: str, html: str, name: str = "dash.html") -> Path:
    """Write ``html`` into the pool as ``session_id`` and show it; return the pool."""
    env.registry.ensure(session_id, str(env.project), "claude-code")
    pool = env.registry.folder_of(env.registry.pool_session(str(env.project)))
    (pool / name).write_text(html)
    env.registry.show(session_id, name, None, None)
    return pool


def entry(env: Env, name: str = "dash.html") -> dict:
    pool = env.registry.pool_session(str(env.project))
    return pool["page_meta"][name]


def test_pool_01_the_folder_carries_the_hubs_tag_and_the_id_is_stable(
    env: Env,
) -> None:
    tag = env.registry.pool_tag
    assert len(tag) == 8 and int(tag, 16) >= 0
    meta = env.registry.pool_session(str(env.project))
    assert meta["id"].startswith("project-") and len(meta["id"]) == 24
    assert meta["agent"] == "project" and meta["title"] == "proj"
    assert env.registry.folder_of(meta) == env.project / ".agent-canvas" / f"pool-{tag}"
    assert env.registry.pool_session(str(env.project))["id"] == meta["id"]
    entries = json.loads((env.state_dir / "sessions.json").read_text())
    assert entries[meta["id"]]["folder"] == f"pool-{tag}"


def test_pool_01_another_key_gives_another_tag_pool_and_id(
    env: Env, tmp_path: Path
) -> None:
    other_state = tmp_path / "other-state"
    other_state.mkdir()
    other = SessionRegistry(other_state, HubState(2, "other key", lambda: 0.0))
    mine = env.registry.pool_session(str(env.project))
    theirs = other.pool_session(str(env.project))
    assert other.pool_tag != env.registry.pool_tag
    assert theirs["id"] != mine["id"]
    assert other.folder_of(theirs) != env.registry.folder_of(mine)


def test_pool_01_the_pool_survives_a_reload_under_its_saved_folder_name(
    env: Env,
) -> None:
    meta = env.registry.pool_session(str(env.project))
    again = SessionRegistry(env.state_dir, HubState(1, "k", lambda: 0.0))
    again.load()
    assert again.get(meta["id"]).agent == "project"
    assert again.folder_of(meta) == env.registry.folder_of(meta)


def test_pool_01_a_symlinked_pool_folder_is_refused(env: Env, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (env.project / ".agent-canvas").mkdir()
    (env.project / ".agent-canvas" / f"pool-{env.registry.pool_tag}").symlink_to(target)
    with pytest.raises(RegistryError):
        env.registry.pool_session(str(env.project))
    assert list(target.iterdir()) == []


def test_pool_01_a_shown_page_goes_to_the_pool_and_the_session_lists_none(
    env: Env,
) -> None:
    pool = publish_as(env, "a", "<p>a</p>")
    member = env.registry.get("a")
    assert member.pages == () and member.active_page is None
    assert env.registry.get(env.registry.pool_of("a")).pages == ("dash.html",)
    assert not (env.project / ".agent-canvas" / "a" / "dash.html").exists()
    assert (pool / "dash.html").is_file()


def test_pool_02_the_record_names_creator_updater_and_every_touch(env: Env) -> None:
    publish_as(env, "a", "<p>a</p>")
    first = entry(env)
    assert first["created_by"]["session"] == first["updated_by"]["session"] == "a"
    assert first["created_by"]["agent"] == "claude-code"
    env.registry.ensure("b", str(env.project), "opencode")
    env.registry.show("b", "dash.html", None, None)
    unchanged = entry(env)
    assert unchanged["updated_by"]["session"] == "a"  # showing is not changing
    assert sorted(unchanged["sessions"]) == ["a", "b"]
    assert unchanged["sessions"]["b"]["time"].endswith("Z")
    publish_as(env, "b", "<p>b</p>")
    assert entry(env)["updated_by"]["session"] == "b"
    assert entry(env)["created_by"]["session"] == "a"


def test_pool_03_a_members_tab_lists_its_pages_and_the_pools_address(
    env: Env,
) -> None:
    publish_as(env, "a", "<p>a</p>")
    publish_as(env, "a", "<p>other</p>", "other.html")
    env.registry.ensure("b", str(env.project), "opencode")
    env.registry.show("b", "dash.html", None, None)
    pool_id = env.registry.pool_of("b")
    tab = env.registry.tab_of(env.registry.get("b").raw)
    assert tab["pool"] == pool_id and tab["pinned"] == []
    assert tab["pages"] == ["dash.html"] and tab["active_page"] == "dash.html"
    assert tab["base"] == env.registry.tab_of(env.registry.get(pool_id).raw)["base"]
    assert env.registry.tab_of(env.registry.get("a").raw)["pages"] == [
        "dash.html",
        "other.html",
    ]


def test_pool_04_pool_pages_get_the_default_kind(env: Env) -> None:
    publish_as(env, "a", "<p>a</p>")
    (row,) = env.registry.page_list(env.registry.pool_of("a"))
    assert (row["kind"], row["set_by"]) == ("transitional", "default")


def test_pool_05_an_ordinary_id_with_the_prefix_is_refused(env: Env) -> None:
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


def test_pool_05_end_title_ensure_and_show_of_the_pool_are_refused(env: Env) -> None:
    meta = env.registry.pool_session(str(env.project))
    path = env.registry.folder_of(meta) / "session.json"
    before = path.read_text()
    for attempt in (
        lambda: env.registry.end(meta["id"]),
        lambda: env.registry.set_title(meta["id"], "Mine"),
        lambda: env.registry.ensure(meta["id"], str(env.project), "a"),
        lambda: env.registry.show(meta["id"], "dash.html", None, None),
    ):
        with pytest.raises(RegistryError) as refused:
            attempt()
        assert refused.value.code == "no-session"
    assert path.read_text() == before


def test_pool_11_draft_names_carry_the_sessions_tag() -> None:
    tag = session_tag("ebdc387a-0000")
    assert len(tag) == 8 and tag != session_tag("other")
    assert draft_name_for("dash.html", tag) == f"dash.{tag}.draft.html"
    assert draft_name_for("dash", tag) == f"dash.{tag}.draft.html"
    assert published_name_for(f"dash.{tag}.draft.html") == "dash.html"
    assert published_name_for("dash.draft.html") == "dash.html"


def test_pool_11_a_page_name_ending_in_a_known_sessions_tag_is_refused(
    env: Env,
) -> None:
    env.registry.ensure("b", str(env.project), "claude-code")
    tag = session_tag("b")
    with pytest.raises(RegistryError) as refused:
        publish_as(env, "a", "<p>a</p>", f"dash.{tag}.html")
    assert tag in str(refused.value)


def test_pool_01_a_damaged_pool_record_is_set_aside_before_a_new_one(env: Env) -> None:
    pool = publish_as(env, "a", "<p>a</p>")
    (pool / "session.json").write_text("{not json")
    env.registry.pool_session(str(env.project))
    assert (pool / "session.json.bad").read_text() == "{not json"
    assert json.loads((pool / "session.json").read_text())["agent"] == "project"


def test_pool_01_a_hub_restarted_with_another_key_finds_the_same_pools(
    env: Env,
) -> None:
    publish_as(env, "a", "<p>a</p>")
    pool_id = env.registry.pool_of("a")
    tag = env.registry.pool_tag
    again = SessionRegistry(env.state_dir, HubState(1, "a new key", lambda: 0.0))
    again.load()
    assert again.pool_tag == tag
    assert again.pool_of("a") == pool_id
    assert again.pool_session(str(env.project))["id"] == pool_id
    fresh_state = env.state_dir.parent / "fresh"
    fresh_state.mkdir()
    fresh = SessionRegistry(fresh_state, HubState(1, "a new key", lambda: 0.0))
    assert fresh.pool_tag != tag  # positive control: the key alone gives another


def test_pool_02_a_restarted_hub_keeps_the_record_and_resolves_the_pool(
    env: Env,
) -> None:
    pool = publish_as(env, "a", "<p>a</p>")
    pool_id = env.registry.pool_of("a")
    again = SessionRegistry(env.state_dir, HubState(1, "k", lambda: 0.0))
    again.load()
    assert again.pool_of("a") == pool_id
    record = again.get(pool_id).page_meta["dash.html"]
    assert record["created_by"]["session"] == "a" and "a" in record["sessions"]
    draft = pool / draft_name_for("dash.html", session_tag("a"))
    draft.write_text("<p>a2</p>")
    again.show("a", "dash.html", None, None, publish=True)  # a has seen it: no refusal
    assert (pool / "dash.html").read_text() == "<p>a2</p>"


def test_pool_01_a_session_in_a_sub_folder_shares_the_pool_at_the_git_top(
    env: Env,
) -> None:
    (env.project / ".git").mkdir()
    sub = env.project / "sub" / "deeper"
    sub.mkdir(parents=True)
    pool = publish_as(env, "t", "<p>t</p>")
    env.registry.ensure("s", str(sub), "claude-code")
    shown, _, path = env.registry.show("s", "dash.html", None, None)
    assert env.registry.pool_of("s") == env.registry.pool_of("t") == shown["id"]
    assert path == pool / "dash.html" and pool.parent == env.project / ".agent-canvas"
    assert not (sub / ".agent-canvas" / pool.name).exists()


def test_pool_01_a_repository_at_home_falls_back_to_the_sessions_project(
    env: Env,
) -> None:
    home = env.project.parent
    (home / ".git").mkdir()
    pool = publish_as(env, "a", "<p>a</p>")
    assert pool.parent == env.project / ".agent-canvas"
    assert not (home / ".agent-canvas").exists()


def test_pool_06_a_page_written_directly_is_named_so_and_kept_as_a_version(
    env: Env,
) -> None:
    pool = publish_as(env, "a", "<p>a</p>")
    (pool / "dash.html").write_text("<p>direct</p>")
    (pool / draft_name_for("dash.html", session_tag("a"))).write_text("<p>a2</p>")
    with pytest.raises(RegistryError) as refused:
        env.registry.show("a", "dash.html", None, None, publish=True)
    assert "written directly" in str(refused.value)
    assert "claude-code" not in str(refused.value)  # not a's doing
    env.registry.show("a", "dash.html", None, None, publish=True)
    history = PageHistory(pool)
    saved = [history.read("dash.html", n) for n, _ in history.versions("dash.html")]
    assert b"<p>direct</p>" in saved
    assert (pool / "dash.html").read_text() == "<p>a2</p>"


def test_pool_11_a_date_like_page_name_is_kept(env: Env) -> None:
    pool = publish_as(env, "a", "<p>report</p>", "report.20261124.html")
    assert (pool / "report.20261124.html").is_file()
    tag = session_tag("a")
    draft = pool / draft_name_for("report.20261124.html", tag)
    assert draft.name == f"report.20261124.{tag}.draft.html"
    draft.write_text("<p>report 2</p>")
    env.registry.show("a", "report.20261124.html", None, None, publish=True)
    assert (pool / "report.20261124.html").read_text() == "<p>report 2</p>"
