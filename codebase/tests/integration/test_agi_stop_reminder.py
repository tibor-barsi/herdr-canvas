"""Stop hook reminder and the title in the next line of `show` (AGI-20, AGI-22)."""
# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_agi_show_and_hook import ASK_PAGE, folder_of  # noqa: F401
from test_cli_watch import Watching, watching  # noqa: F401
from test_hooks import SESSION, known, stdin_for  # noqa: F401

pytestmark = pytest.mark.integration

ENV = {"AGENT_CANVAS_SESSION": SESSION, "AGENT_CANVAS_AGENT": "claude-code"}
ASK_WITH_DEFAULT = ASK_PAGE.replace('"options"', '"default": "gyroid", "options"')


def stop_hook(runner, prompt_id: str = "p1", active: bool = False):  # noqa: ANN001, ANN201
    stdin = stdin_for("Stop", runner.cwd, prompt_id=prompt_id, stop_hook_active=active)
    return runner("hook", "stop", input=stdin)


def reminder(result) -> str:  # noqa: ANN001
    assert (result.code, result.err) == (0, "")
    if not result.out:
        return ""
    output = json.loads(result.out)["hookSpecificOutput"]
    assert output["hookEventName"] == "Stop"
    return output["additionalContext"]


def show_page(cli, html: str) -> None:  # noqa: ANN001
    folder = Path(cli("session", "path", extra_env=ENV).json["folder"])
    (folder / "ask.html").write_text(html)
    assert cli("show", "ask", "--no-audit", extra_env=ENV).code == 0


def test_agi_20_an_open_ask_and_no_listener_gives_one_reminder(cli, hub, known) -> None:  # noqa: ANN001
    show_page(cli, ASK_PAGE)
    text = reminder(stop_hook(cli))
    assert "agent-canvas watch" in text and "Monitor" in text
    assert "terminal" in text


def test_agi_20_a_connected_listener_keeps_the_hook_silent(
    cli, hub, known, watching
) -> None:  # noqa: ANN001
    show_page(cli, ASK_PAGE)
    watching("--session", SESSION, "--timeout", "60")
    hub.wait_for(lambda: hub.listening(SESSION), timeout=15)
    assert reminder(stop_hook(cli)) == ""


def test_agi_20_an_ask_with_a_default_does_not_wait(cli, hub, known) -> None:  # noqa: ANN001
    show_page(cli, ASK_WITH_DEFAULT)
    assert reminder(stop_hook(cli)) == ""


def test_agi_20_no_ask_no_reminder(cli, hub, known) -> None:  # noqa: ANN001
    assert reminder(stop_hook(cli)) == ""


def test_agi_20_once_per_turn(cli, hub, known) -> None:  # noqa: ANN001
    show_page(cli, ASK_PAGE)
    assert reminder(stop_hook(cli, "p1")) != ""
    assert reminder(stop_hook(cli, "p1")) == ""
    assert reminder(stop_hook(cli, "p2")) != ""


def test_agi_20_a_stop_that_follows_the_reminder_is_silent(cli, hub, known) -> None:  # noqa: ANN001
    show_page(cli, ASK_PAGE)
    assert reminder(stop_hook(cli, "p9", active=True)) == ""


def test_agi_20_hub_down_prints_nothing_and_never_starts_it(lone) -> None:  # noqa: ANN001
    result = stop_hook(lone.run)
    assert (result.code, result.out, result.err) == (0, "", "")
    assert lone.pids() == []


def test_agi_22_next_line_names_the_title_given_to_show(cli) -> None:  # noqa: ANN001
    (folder_of(cli) / "p.html").write_text("<title>t</title><p>x</p>")
    data = cli("show", "p", "--title", "Test", "--session", "a").json
    assert '"Test"' in data["next"] and '"t"' not in data["next"]
