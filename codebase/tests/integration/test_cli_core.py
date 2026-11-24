"""CLI core against a real hub: sessions, show, errors (SES, CLI, HUB, SEC)."""

from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def folder_of(project: Path, session: str) -> Path:
    return (project / ".agent-canvas" / session).resolve()


def pool_folder_of(base: Path) -> Path:
    """Return the pool folder under a project's canvas folder (POOL-01)."""
    (found,) = base.glob("pool-*")
    return found.resolve()


def page_token(cli, session: str) -> str:
    state_dir = Path(cli.environment["AGENT_CANVAS_STATE_DIR"])
    registry = json.loads((state_dir / "sessions.json").read_text())
    return registry[session]["page_token"]


def read_meta(folder: Path | str) -> dict:
    return json.loads((Path(folder) / "session.json").read_text())


# ---- SES-04 -------------------------------------------------------------


def test_ses_04_session_start_prints_uuid4_and_folder(cli) -> None:
    result = cli("session", "start", "--title", "Bracket")
    assert result.code == 0 and result.err == ""
    data = result.json
    assert set(data) == {"session", "folder", "tag"}  # POOL-01, POOL-11
    assert uuid.UUID(data["session"]).version == 4
    assert Path(data["folder"]) == pool_folder_of(cli.cwd / ".agent-canvas")
    assert Path(data["folder"]).is_dir()
    meta = read_meta(folder_of(cli.cwd, data["session"]))
    assert (meta["title"], meta["agent"]) == ("Bracket", "agent")


def test_ses_04_session_start_agent_option_and_environment(cli) -> None:
    a = cli("session", "start", "--agent", "opencode")
    b = cli("session", "start", extra_env={"AGENT_CANVAS_AGENT": "claude-code"})
    c = cli("session", "start", "--agent", "x", extra_env={"AGENT_CANVAS_AGENT": "y"})
    agents = [
        read_meta(folder_of(cli.cwd, r.json["session"]))["agent"] for r in (a, b, c)
    ]
    assert agents == ["opencode", "claude-code", "x"]


# ---- SES-02 -------------------------------------------------------------


def test_ses_02_no_session_id_exits_5_with_json_on_stderr(cli) -> None:
    result = cli("session", "path")
    assert result.code == 5 and result.out == ""
    assert result.json["error"] == "no-session"
    assert "AGENT_CANVAS_SESSION" in result.json["message"]


def test_ses_02_environment_id_is_used_and_option_wins(cli) -> None:
    env = {"AGENT_CANVAS_SESSION": "from-env"}
    assert cli("session", "path", extra_env=env).json["session"] == "from-env"
    both = cli("session", "path", "--session", "from-opt", extra_env=env)
    assert both.json["session"] == "from-opt"


@pytest.mark.parametrize("bad", ["../x", "a/b", "x" * 65, "a b"])
def test_ses_02_sec_08_malformed_id_exits_5(cli, bad: str) -> None:
    result = cli("session", "path", "--session", bad)
    assert result.code == 5 and result.out == ""
    assert not (cli.cwd / ".claude" / "x").exists()


# ---- SES-03 -------------------------------------------------------------


def test_ses_03_unknown_id_creates_only_in_creating_commands(cli) -> None:
    for command in (
        ["session", "set", "--title", "T"],
        ["session", "end"],
        ["pending"],
    ):
        result = cli(*command, "--session", "ghost")
        assert result.code == 5, command
        assert result.json["error"] == "no-session"
    assert not folder_of(cli.cwd, "ghost").exists()
    assert cli("session", "path", "--session", "made").code == 0
    assert folder_of(cli.cwd, "made").is_dir()
    # show creates an unknown session too; it then fails only for the missing file
    assert cli("show", "--session", "made-by-show").code == 1
    assert folder_of(cli.cwd, "made-by-show").is_dir()


def test_ses_03_pending_of_a_known_session_without_events_is_empty(cli) -> None:
    cli("session", "path", "--session", "a")
    result = cli("pending", "--session", "a")
    assert result.code == 0 and result.json == {
        "session": "a",
        "events": [],
        "reminders": [],
    }


def test_ses_03_project_defaults_to_cwd_without_git(cli) -> None:
    sub = cli.cwd / "deep" / "er"
    sub.mkdir(parents=True)
    data = cli("session", "path", "--session", "a", cwd=sub).json
    assert Path(data["folder"]) == pool_folder_of(sub / ".agent-canvas")
    assert folder_of(sub, "a").is_dir()


def test_ses_03_project_is_git_toplevel_when_in_a_repo(cli) -> None:
    git("init", "-q", cwd=cli.cwd)
    sub = cli.cwd / "src"
    sub.mkdir()
    data = cli("session", "path", "--session", "a", cwd=sub).json
    assert Path(data["folder"]) == pool_folder_of(cli.cwd / ".agent-canvas")
    assert folder_of(cli.cwd, "a").is_dir()


def test_ses_03_environment_project_beats_git_and_option_beats_environment(
    cli, home: Path
) -> None:
    git("init", "-q", cwd=cli.cwd)
    env_project = home / "from-env"
    opt_project = home / "from-opt"
    env_project.mkdir()
    opt_project.mkdir()
    env = {"AGENT_CANVAS_PROJECT": str(env_project)}
    a = cli("session", "path", "--session", "a", extra_env=env).json
    b = cli(
        "session", "path", "--session", "b", "--project", str(opt_project),
        extra_env=env,
    )  # fmt: skip
    assert Path(a["folder"]) == pool_folder_of(env_project / ".agent-canvas")
    assert Path(b.json["folder"]) == pool_folder_of(opt_project / ".agent-canvas")


def test_ses_03_relative_project_option_is_resolved_against_cwd(cli) -> None:
    (cli.cwd / "rel").mkdir()
    data = cli("session", "path", "--session", "a", "--project", "rel").json
    assert Path(data["folder"]) == pool_folder_of(cli.cwd / "rel" / ".agent-canvas")


def test_ses_03_home_itself_is_refused_with_exit_1(cli, home: Path) -> None:
    result = cli("session", "path", "--session", "a", cwd=home)
    assert result.code == 1 and result.out == ""
    assert "--project" in result.json["message"]
    assert not (home / ".claude").exists()


def test_ses_03_git_repo_rooted_at_home_is_refused(cli, home: Path) -> None:
    git("init", "-q", cwd=home)
    result = cli("session", "path", "--session", "a", cwd=cli.cwd)
    assert result.code == 1
    assert "--project" in result.json["message"]
    assert cli("session", "start", "--project", str(cli.cwd)).code == 0


def test_ses_03_known_session_keeps_project_when_called_from_elsewhere(
    cli, home: Path
) -> None:
    first = cli("session", "path", "--session", "a").json
    elsewhere = home / "elsewhere"
    elsewhere.mkdir()
    again = cli("session", "path", "--session", "a", cwd=elsewhere).json
    assert again == first
    assert not (elsewhere / ".claude").exists()


# ---- session commands / 5.7 shapes ---------------------------------------


def test_cli_session_set_end_and_list(cli) -> None:
    started = cli("session", "start", "--agent", "claude-code").json["session"]
    cli("session", "start")  # a second session that stays active
    renamed = cli("session", "set", "--title", "Bracket redesign", "--session", started)
    assert renamed.json == {"session": started, "title": "Bracket redesign"}
    listing = cli("session", "list").json["sessions"]
    assert {
        "id": started,
        "project": str(cli.cwd.resolve()),
        "agent": "claude-code",
        "title": "Bracket redesign",
        "state": "active",
        "listening": False,
    } in listing
    ended = cli("session", "end", "--session", started)
    assert ended.json == {"session": started, "state": "ended"}
    active_ids = {s["id"] for s in cli("session", "list").json["sessions"]}
    all_sessions = cli("session", "list", "--all").json["sessions"]
    assert started not in active_ids
    assert [s["state"] for s in all_sessions if s["id"] == started] == ["ended"]


def test_cli_session_list_project_filter(cli, home: Path) -> None:
    other = home / "other"
    other.mkdir()
    cli("session", "start")
    b = cli("session", "start", "--project", str(other)).json["session"]
    listed = cli("session", "list", "--project", str(other)).json["sessions"]
    assert [s["id"] for s in listed] == [b]  # its pool is not listed (A-1146)
    everything = cli("session", "list", "--all").json["sessions"]
    assert [s["agent"] for s in everything] == ["agent", "agent"]


def test_cli_session_list_empty(cli) -> None:
    assert cli("session", "list").json == {"sessions": []}


def test_cli_usage_errors_exit_2_with_json_on_stderr(cli) -> None:
    for args in (["session", "set"], ["bogus"], ["session", "list", "--nope"]):
        result = cli(*args)
        assert result.code == 2 and result.out == "", args
        assert result.json["error"] == "usage"


# ---- CLI-02 / CLI-16 / HUB-07 ----------------------------------------------


def test_cli_02_show_returns_5_7_shape(cli) -> None:
    folder = Path(cli("session", "path", "--session", "a").json["folder"])
    (folder / "page.html").write_text("<p>x</p>")
    data = cli("show", "--session", "a", "--title", "My page").json
    pools = json.loads(
        (Path(cli.environment["AGENT_CANVAS_STATE_DIR"]) / "sessions.json").read_text()
    )
    (pool_id,) = [s for s, entry in pools.items() if "folder" in entry]
    token = page_token(cli, pool_id)  # the page's address is the pool's (POOL-03)
    port = cli.environment["AGENT_CANVAS_PORT"]
    assert data == {
        "session": "a",
        "page": "page.html",
        "path": str(folder / "page.html"),
        "url": f"http://localhost:{port}/s/{token}/page.html",
        "version": 1,
        "window": data["window"],
        "rendered": False,
        "errors": [],
        "audit": None,  # the test environment switches the page checks off
        "next": data["next"],
    }
    assert data["window"] == "disabled"
    meta = read_meta(folder)
    assert (meta["pages"], meta["active_page"]) == (["page.html"], "page.html")
    assert read_meta(folder_of(cli.cwd, "a"))["title"] == "My page"


def test_cli_02_show_named_page_and_absolute_path_inside_folder(cli) -> None:
    folder = Path(cli("session", "path", "--session", "a").json["folder"])
    (folder / "other.html").write_text("<p>o</p>")
    assert cli("show", "other.html", "--session", "a").json["page"] == "other.html"
    absolute = cli("show", str(folder / "other.html"), "--session", "a")
    assert absolute.code == 0 and absolute.json["page"] == "other.html"


def test_cli_02_missing_file_exits_1_and_names_session_folder(cli) -> None:
    folder = cli("session", "path", "--session", "a").json["folder"]
    result = cli("show", "--session", "a")
    assert result.code == 1 and result.out == ""
    assert result.json["error"] == "failed"
    assert folder in result.json["message"]


def test_cli_02_absolute_path_outside_folder_exits_1_and_suggests_copy(
    cli, tmp_path: Path
) -> None:
    cli("session", "path", "--session", "a")
    outside = tmp_path / "outside.html"
    outside.write_text("x")
    result = cli("show", str(outside), "--session", "a")
    assert result.code == 1 and "--copy" in result.json["message"]


@pytest.mark.parametrize("name", ["../page.html", "sub/page.html", "history"])
def test_sec_08_show_rejects_traversal_names(cli, name: str) -> None:
    cli("session", "path", "--session", "a")
    result = cli("show", name, "--session", "a")
    assert result.code == 1 and result.json["error"] == "failed"


def test_cli_16_show_copy_copies_under_base_name_and_shows(cli, tmp_path: Path) -> None:
    folder = Path(cli("session", "path", "--session", "a").json["folder"])
    source = tmp_path / "ext" / "design.html"
    source.parent.mkdir()
    source.write_text("<p>copied</p>")
    result = cli("show", "--copy", str(source), "--session", "a")
    assert result.code == 0 and result.json["page"] == "design.html"
    assert (folder / "design.html").read_text() == "<p>copied</p>"


def test_cli_16_copy_of_missing_source_exits_1(cli, tmp_path: Path) -> None:
    cli("session", "path", "--session", "a")
    result = cli("show", "--copy", str(tmp_path / "none.html"), "--session", "a")
    assert result.code == 1


def test_hub_07_show_in_git_repo_lists_nothing_under_canvas(cli) -> None:
    git("init", "-q", cwd=cli.cwd)
    folder = Path(cli("session", "path", "--session", "a").json["folder"])
    (folder / "page.html").write_text("<p>x</p>")
    assert cli("show", "--session", "a").code == 0
    assert git("status", "--porcelain", cwd=cli.cwd).strip() == ""
    assert (folder.parent / ".gitignore").read_text() == "*\n"


@pytest.mark.hub_config(project_dir_name="tools/canvas")
def test_hub_07_configured_folder_and_gitignore(cli) -> None:
    git("init", "-q", cwd=cli.cwd)
    folder = Path(cli("session", "path", "--session", "a").json["folder"])
    assert folder == pool_folder_of(cli.cwd / "tools" / "canvas")
    (folder / "page.html").write_text("<p>x</p>")
    assert cli("show", "--session", "a").code == 0
    assert git("status", "--porcelain", cwd=cli.cwd).strip() == ""
    assert (folder.parent / ".gitignore").read_text() == "*\n"
    assert not (cli.cwd / ".agent-canvas").exists()


def test_hub_07_existing_gitignore_is_not_overwritten(cli) -> None:
    canvas = cli.cwd / ".agent-canvas"
    canvas.mkdir(parents=True)
    (canvas / ".gitignore").write_text("mine\n")
    cli("session", "start")
    assert (canvas / ".gitignore").read_text() == "mine\n"


# ---- CLI-15 -----------------------------------------------------------------


def test_cli_15_corrupt_key_exits_4_unauthorised(cli, hub) -> None:
    (hub.state_dir / "key").write_text("not-the-key\n")
    result = cli("session", "list")
    assert result.code == 4 and result.out == ""
    assert result.json["error"] == "unauthorised"


def test_cli_15_status_also_needs_the_key(cli, hub) -> None:
    (hub.state_dir / "key").write_text("not-the-key\n")
    assert cli("status").code == 4


# ---- status / HUB-04 ----------------------------------------------------------


def test_cli_status_reports_hub_and_session_count(cli, hub) -> None:
    cli("session", "start")
    data = cli("status").json
    assert data == {
        "hub": "running",
        "build": hub.state.build_id,
        "version": data["version"],
        "port": hub.port,
        "window_connected": False,
        "sessions": 1,  # a pool is not a session (A-1146)
    }


def test_hub_04_restart_keeps_registry(cli, hub) -> None:
    from agent_canvas.config import Config
    from agent_canvas.hub.app import create_app

    sid = cli("session", "start").json["session"]
    kept = {(s.session_id, s.page_token) for s in hub.state.sessions()}
    assert len(kept) == 2 and sid in {s for s, _ in kept}  # with its pool, A-1022
    second = create_app(Config(port=hub.port), hub.state_dir)
    sessions = second.state.hub.sessions()
    assert {(s.session_id, s.page_token) for s in sessions} == kept


# ---- CLI-12 -------------------------------------------------------------------


def test_cli_12_five_parallel_status_calls_start_exactly_one_hub(lone) -> None:
    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(lambda _: lone.run("status"), range(5)))
    assert [r.code for r in results] == [0] * 5, [r.err for r in results]
    assert all(r.json["port"] == lone.port for r in results)
    time.sleep(0.5)  # a losing hub would have exited by now
    assert len(lone.pids()) == 1


def test_cli_12_port_held_by_another_program_exits_3_naming_port(lone) -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", lone.port))
        blocker.listen(1)
        result = lone.run("status")
    assert result.code == 3 and result.out == ""
    assert result.json["error"] == "hub-unreachable"
    assert str(lone.port) in result.json["message"]
    assert lone.pids() == []


def test_cli_12_hub_log_is_created_by_auto_start(lone) -> None:
    assert lone.run("status").code == 0
    assert (lone.state_dir / "hub.log").exists()


def test_m3_done_session_start_then_show_against_auto_started_hub(lone) -> None:
    started = lone.run("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<!doctype html><title>t</title><p>hi</p>")
    shown = lone.run("show", "--session", started["session"])
    assert shown.code == 0, shown.err
    assert shown.json["page"] == "page.html"
    assert re.match(r"^http://localhost:\d+/s/[\w-]+/page\.html$", shown.json["url"])
    assert len(lone.pids()) == 1
