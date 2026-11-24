"""The three Claude Code hooks (PLG-04, PLG-05, PLG-06) and their safety rules."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

SESSION = "38fefe65-3f6a-4b5c-9d0e-0123456789ab"


def stdin_for(event: str, cwd: Path, source: str = "startup", **more) -> str:  # noqa: ANN003
    """Hook input as Claude Code sends it."""
    base = {
        "session_id": SESSION,
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": str(cwd),
        "hook_event_name": event,
    }
    if event == "SessionStart":
        base["source"] = source
    if event == "UserPromptSubmit":
        base.update(prompt_id="p1", permission_mode="default", prompt="go on")
    base.update(more)
    return json.dumps(base)


def start_hook(runner, tmp_path: Path, source: str = "startup"):  # noqa: ANN001, ANN201
    env_file = tmp_path / "claude-env.sh"
    result = runner(
        "hook", "session-start",
        input=stdin_for("SessionStart", runner.cwd, source),
        extra_env={"CLAUDE_ENV_FILE": str(env_file)},
    )  # fmt: skip
    return result, env_file


# ---- PLG-04 ---------------------------------------------------------------


@pytest.mark.parametrize("source", ["startup", "resume"])
def test_plg_04_session_start_writes_the_env_lines_and_the_context(
    lone, tmp_path, source
) -> None:  # noqa: ANN001
    started = time.monotonic()
    result, env_file = start_hook(lone.run, tmp_path, source)
    assert time.monotonic() - started < 1.0  # hub down
    assert result.code == 0 and result.err == ""
    assert env_file.read_text().splitlines() == [
        f"export AGENT_CANVAS_SESSION={SESSION}",
        "export AGENT_CANVAS_AGENT=claude-code",
        f"export AGENT_CANVAS_PROJECT={lone.run.cwd}",
    ]
    output = json.loads(result.out)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert output["additionalContext"].startswith(  # then the core (AGI-10)
        f"Your agent-canvas session id is {SESSION}; pass it as `session` to "
        "agent-canvas MCP tools. AGENT_CANVAS_SESSION is set for Bash."
    )
    assert lone.pids() == []  # it never starts the hub


def test_plg_04_the_env_file_is_appended_to_not_replaced(lone, tmp_path) -> None:  # noqa: ANN001
    env_file = tmp_path / "claude-env.sh"
    env_file.write_text("export OTHER=1\n")
    start_hook(lone.run, tmp_path)
    assert env_file.read_text().startswith("export OTHER=1\n")


def test_plg_04_without_an_env_file_it_still_prints_the_context(lone) -> None:  # noqa: ANN001
    result = lone.run(
        "hook", "session-start", input=stdin_for("SessionStart", lone.run.cwd)
    )
    assert result.code == 0 and SESSION in result.out


def test_plg_04_paths_with_spaces_are_quoted_for_the_shell(lone, tmp_path) -> None:  # noqa: ANN001
    import shlex

    spaced = lone.home / "my proj"
    spaced.mkdir()
    env_file = tmp_path / "env.sh"
    lone.run(
        "hook", "session-start", input=stdin_for("SessionStart", spaced),
        extra_env={"CLAUDE_ENV_FILE": str(env_file)},
    )  # fmt: skip
    last = shlex.split(env_file.read_text().splitlines()[-1])
    assert last == ["export", f"AGENT_CANVAS_PROJECT={spaced}"]


def test_plg_04_ses_10_the_hook_reserves_but_creates_no_folder_or_tab(
    cli, hub, tmp_path
) -> None:  # noqa: ANN001
    result, _ = start_hook(cli, tmp_path)
    assert result.code == 0
    assert cli("session", "list", "--all").json["sessions"] == []
    assert not (cli.cwd / ".agent-canvas").exists()
    assert hub.state.sessions() == []
    assert hub.app.state.registry.is_reserved(SESSION)


def test_ses_10_the_first_show_makes_the_reserved_session_real(
    cli, hub, tmp_path
) -> None:  # noqa: ANN001
    start_hook(cli, tmp_path)
    env = {"AGENT_CANVAS_SESSION": SESSION, "AGENT_CANVAS_AGENT": "claude-code"}
    folder = Path(cli("session", "path", extra_env=env).json["folder"])
    (folder / "page.html").write_text("<p>x</p>")
    assert cli("show", extra_env=env).code == 0
    listed = cli("session", "list").json["sessions"]
    [found] = [s for s in listed if s["agent"] != "project"]  # not the pool, A-1022
    assert found["id"] == SESSION and found["agent"] == "claude-code"
    assert Path(found["project"]) == cli.cwd


def test_ses_10_pending_and_end_of_a_reserved_session_create_nothing(
    cli, hub, tmp_path
) -> None:  # noqa: ANN001
    start_hook(cli, tmp_path)
    prompt = cli(
        "hook", "user-prompt-submit", input=stdin_for("UserPromptSubmit", cli.cwd)
    )
    ended = cli("hook", "session-end", input=stdin_for("SessionEnd", cli.cwd))
    assert prompt.code == 0 and ended.code == 0 and prompt.out == ""
    assert cli("pending", extra_env={"AGENT_CANVAS_SESSION": SESSION}).json == {
        "session": SESSION,
        "events": [],
        "reminders": [],
    }
    assert not (cli.cwd / ".agent-canvas").exists()


def test_ses_10_a_watch_is_a_use_and_creates_the_session(cli, hub, tmp_path) -> None:  # noqa: ANN001
    start_hook(cli, tmp_path)
    cli("watch", "--timeout", "0.5", extra_env={"AGENT_CANVAS_SESSION": SESSION})
    assert [s["id"] for s in cli("session", "list").json["sessions"]] == [SESSION]


def test_plg_04_resume_keeps_the_same_session(cli, hub, tmp_path) -> None:  # noqa: ANN001
    start_hook(cli, tmp_path, "startup")
    start_hook(cli, tmp_path, "resume")
    cli("session", "path", extra_env={"AGENT_CANVAS_SESSION": SESSION})
    listed = cli("session", "list").json["sessions"]
    assert [s["id"] for s in listed].count(SESSION) == 1


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"cwd": "/x"}'])
def test_plg_04_bad_input_never_breaks_the_session(lone, text) -> None:  # noqa: ANN001
    result = lone.run("hook", "session-start", input=text)
    assert result.code == 0


# ---- PLG-05 ---------------------------------------------------------------


@pytest.fixture
def known(cli, hub, tmp_path):  # noqa: ANN001, ANN201
    start_hook(cli, tmp_path)
    # The hook only reserves the id; the first use makes the session (SES-10).
    cli("session", "path", extra_env={"AGENT_CANVAS_SESSION": SESSION})
    return SESSION


def prompt_hook(runner):  # noqa: ANN001, ANN201
    return runner("hook", "user-prompt-submit",
                  input=stdin_for("UserPromptSubmit", runner.cwd))  # fmt: skip


def events_log(runner) -> str:  # noqa: ANN001
    folder = runner.cwd / ".agent-canvas" / SESSION
    return (folder / "events.jsonl").read_text()


def test_plg_05_queued_events_become_additional_context(cli, hub, known) -> None:  # noqa: ANN001
    send = hub.create_event(
        SESSION, "send", message="why this peak?", screenshot="/abs/0003.png",
        actions=[{"kind": "click", "target": {"selector": "#go"}, "value": None,
                  "event": None},
                 {"kind": "button", "target": {"canvas_id": "stop"},
                  "value": "stop", "event": "evt_before"}],
        marks=[{"id": 1, "type": "pen", "bbox": [412, 96, 180, 140], "text": None,
                "target": {"canvas_id": "spectrum",
                           "data_bbox": {"x": [3.1, 4.4], "y": [0.2, 0.9]}}}],
        page="page.html",
    )  # fmt: skip
    choice = hub.create_event(
        SESSION, "choice", target={"canvas_id": "design"}, value=["b"],
        delivery="next-message",
    )  # fmt: skip
    result = prompt_hook(cli)
    assert result.code == 0 and result.err == ""
    output = json.loads(result.out)["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    text = output["additionalContext"]
    for needle in (
        "why this peak?",
        "/abs/0003.png",
        "#go",
        "pen",
        "spectrum",
        "3.1",
        "4.4",
        "design",
        '"b"',
        "evt_before",
    ):
        assert needle in text, needle
    assert hub.event_state(SESSION, send["id"]) == "delivered"
    assert hub.event_state(SESSION, choice["id"]) == "delivered"
    assert '"via":"hook"' in events_log(cli)


def test_plg_05_a_missing_screenshot_gives_the_reason(cli, hub, known) -> None:  # noqa: ANN001
    hub.create_event(SESSION, "send", message="m", screenshot=None,
                     screenshot_error="capture timed out")  # fmt: skip
    text = json.loads(prompt_hook(cli).out)["hookSpecificOutput"]["additionalContext"]
    assert "no screenshot available" in text and "capture timed out" in text


def test_plg_05_delivered_once(cli, hub, known) -> None:  # noqa: ANN001
    hub.create_event(SESSION, "custom", value={"name": "n", "value": 1})
    assert prompt_hook(cli).out
    assert prompt_hook(cli).out == ""


def test_plg_05_no_events_prints_nothing(cli, hub, known) -> None:  # noqa: ANN001
    result = prompt_hook(cli)
    assert (result.code, result.out, result.err) == (0, "", "")


def test_plg_05_unknown_session_prints_nothing(cli, hub) -> None:  # noqa: ANN001
    result = prompt_hook(cli)
    assert (result.code, result.out, result.err) == (0, "", "")


def test_plg_05_hub_down_prints_nothing_and_never_starts_it(lone) -> None:  # noqa: ANN001
    started = time.monotonic()
    result = prompt_hook(lone.run)
    assert time.monotonic() - started < 1.0
    assert (result.code, result.out, result.err) == (0, "", "")
    assert lone.pids() == []


@pytest.mark.timing
def test_plg_05_with_the_hub_up_it_finishes_in_under_a_second(cli, hub, known) -> None:  # noqa: ANN001
    started = time.monotonic()
    prompt_hook(cli)
    assert time.monotonic() - started < 1.0


# ---- PLG-05 with LIFE-07 reminders ------------------------------------------

DAY = 24 * 3600
ENDING = (
    "Not needed any more: agent-canvas page archive NAME. "
    "Still needed: agent-canvas page extend NAME, "
    "or agent-canvas page kind NAME long-term."
)


def own_pages(cli, *pages: tuple[str, str | None]) -> dict[str, str]:  # noqa: ANN001
    """Show the (name, kind) pages in the known session; return its env."""
    env = {"AGENT_CANVAS_SESSION": SESSION, "AGENT_CANVAS_AGENT": "claude-code"}
    folder = Path(cli("session", "path", extra_env=env).json["folder"])
    for name, kind in pages:
        (folder / name).write_text(f"<p>{name}</p>")
        kind_flags = ["--kind", kind] if kind else []
        assert cli("show", name, "--no-audit", *kind_flags, extra_env=env).code == 0
    return env


def hub_clock_at(monkeypatch, seconds: float) -> dict[str, str]:  # noqa: ANN001
    """Shift the in-process hub; return the same shift for the hook process."""
    shift = {"AGENT_CANVAS_TEST_MODE": "1",
             "AGENT_CANVAS_TEST_CLOCK_OFFSET": str(seconds)}  # fmt: skip
    for name, value in shift.items():
        monkeypatch.setenv(name, value)
    return shift


def hook_text(cli, shift: dict[str, str]) -> str:  # noqa: ANN001
    prompt = stdin_for("UserPromptSubmit", cli.cwd)
    result = cli("hook", "user-prompt-submit", input=prompt, extra_env=shift)
    assert (result.code, result.err) == (0, "")
    if not result.out:
        return ""
    output = json.loads(result.out)["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    return output["additionalContext"]


def test_plg_05_a_reminder_alone_is_printed_when_no_event_is_queued(
    cli, hub, known, monkeypatch
) -> None:  # noqa: ANN001
    own_pages(cli, ("plot.html", "single-use"))
    shift = hub_clock_at(monkeypatch, 3 * DAY + 60)
    assert hook_text(cli, shift) == (
        "agent-canvas: 1 page past its lifetime: "
        f"plot.html (single-use, expired today). {ENDING}"
    )


def test_plg_05_two_pages_use_the_plural_and_say_how_long_ago_each_expired(
    cli, hub, known, monkeypatch
) -> None:  # noqa: ANN001
    env = own_pages(cli, ("plot.html", "single-use"), ("old.html", None))
    hub_clock_at(monkeypatch, 25 * DAY)
    assert cli("page", "extend", "plot.html", extra_env=env).code == 0
    shift = hub_clock_at(monkeypatch, 30 * DAY + 60)
    assert hook_text(cli, shift) == (
        "agent-canvas: 2 pages past their lifetime: "
        "plot.html (single-use, expired 2 days ago), "
        f"old.html (transitional, expired today). {ENDING}"
    )


def test_plg_05_the_reminder_follows_the_events_and_comes_once_a_day(
    cli, hub, known, monkeypatch
) -> None:  # noqa: ANN001
    own_pages(cli, ("plot.html", "single-use"))
    hub.create_event(SESSION, "custom", value={"name": "n", "value": 1})
    shift = hub_clock_at(monkeypatch, 3 * DAY + 60)
    lines = hook_text(cli, shift).split("\n")
    assert lines[0].startswith("Feedback from the owner")
    assert lines[-1].startswith("agent-canvas: 1 page past its lifetime: plot.html")
    assert hook_text(cli, shift) == ""


def test_plg_05_a_page_that_is_not_expired_adds_nothing(
    cli, hub, known, monkeypatch
) -> None:  # noqa: ANN001
    own_pages(cli, ("plot.html", "single-use"))
    shift = hub_clock_at(monkeypatch, 3 * DAY - 60)
    assert hook_text(cli, shift) == ""


# ---- PLG-06 ---------------------------------------------------------------


def test_plg_06_session_end_marks_the_session_ended(cli, hub, known) -> None:  # noqa: ANN001
    result = cli("hook", "session-end", input=stdin_for("SessionEnd", cli.cwd,
                                                         reason="other"))  # fmt: skip
    assert (result.code, result.out) == (0, "")
    [found] = [s for s in cli("session", "list", "--all").json["sessions"]
               if s["id"] == SESSION]  # fmt: skip
    assert found["state"] == "ended"


def test_plg_06_session_end_with_the_hub_down_is_silent(lone) -> None:  # noqa: ANN001
    result = lone.run(
        "hook", "session-end", input=stdin_for("SessionEnd", lone.run.cwd)
    )
    assert (result.code, result.out, result.err) == (0, "", "")
    assert lone.pids() == []


def test_plg_04_session_ids_that_are_not_valid_are_ignored(lone) -> None:  # noqa: ANN001
    bad = stdin_for("SessionEnd", lone.run.cwd, session_id="../../etc")
    assert lone.run("hook", "session-end", input=bad).code == 0
    assert uuid.UUID(SESSION)
