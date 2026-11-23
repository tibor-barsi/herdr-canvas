"""End-to-end: scenario 1 with the plugin loaded into a real Claude Code (M11).

A nested ``claude -p --model haiku --plugin-dir plugin/`` runs in the default
permission mode (no bypass). ``--settings`` grants only the page-write rule
``Edit(**/.agent-canvas/**)``, ``Bash(agent-canvas:*)`` and the plugin's MCP
tools. The hub, its state and config are temporary and use a free port;
Playwright is the owner and picks one of three options. Claude must continue
with that choice. Also checks PLG-02: the hooks ran and the tools are listed.
Run by hand: ``uv run pytest -m e2e -k plugin_claude -s``.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from harness import open_first_tab

from helpers import PLUGIN_DIR

pytestmark = pytest.mark.e2e

PROMPT = """I am choosing a design for a small phone stand. Use the agent-canvas \
canvas (the agent-canvas plugin is installed; follow its guideline): show me a \
page with three design options as a canvas-choices block with a submit button, \
then wait for my choice. When I have chosen, reply with exactly one line: \
`CHOSEN: <the id of the option I chose>`."""


def make_wrapper(directory: Path) -> Path:
    """Create an ``agent-canvas`` executable that runs this checkout's CLI."""
    directory.mkdir()
    wrapper = directory / "agent-canvas"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m agent_canvas.cli "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return directory


def events_of(stream: Path) -> list[dict]:
    found = []
    for line in stream.read_text().splitlines():
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def pick_second_option(
    owner, process, session_id: str, seconds: float = 240
) -> str | None:  # noqa: ANN001
    """
    Select the second of three options and submit; return its id, or None.

    Waits until the agent listens (CLI-06: an ``ask --block`` waits for the
    *next* event, so an earlier press would be missed).
    """
    deadline = time.monotonic() + seconds
    options = "canvas-choices .option"
    while time.monotonic() < deadline and process.poll() is None:
        try:
            open_first_tab(owner)  # a shown page never opens itself (SES-07)
            frame = owner.frame
            hub = owner.hub
            listening = hub.listening(session_id) or any(
                a["waiting"] for a in hub.open_asks(session_id)
            )
            if frame.locator(options).count() == 3 and listening:
                chosen = frame.locator(options).nth(1)
                option_id = chosen.get_attribute("data-id")
                chosen.click()
                frame.locator("canvas-choices .submit").click()
                return option_id
        except Exception:  # noqa: BLE001 - the frame may not exist yet or reloads
            pass
        owner.page.wait_for_timeout(200)
    return None


def test_e2e_plugin_claude_scenario_1_pick_one_of_three(owner, hub, tmp_path) -> None:  # noqa: ANN001
    claude = shutil.which("claude")
    if claude is None:
        pytest.skip("the claude command is not installed")
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Edit(**/.agent-canvas/**)",
                        "Bash(agent-canvas:*)",
                        "mcp__plugin_agent-canvas_agent-canvas__*",
                    ]
                }
            }
        )
    )
    environment = {
        **os.environ,
        "PATH": f"{make_wrapper(tmp_path / 'bin')}:{os.environ['PATH']}",
        "AGENT_CANVAS_PORT": str(hub.port),
        "AGENT_CANVAS_STATE_DIR": str(hub.state_dir),
        "AGENT_CANVAS_CONFIG_DIR": str(hub.config_dir),
        "AGENT_CANVAS_WINDOW_COMMAND": "true",
    }
    for name in ("AGENT_CANVAS_SESSION", "AGENT_CANVAS_PROJECT", "AGENT_CANVAS_AGENT"):
        environment.pop(name, None)  # the SessionStart hook must provide them
    session_id = str(uuid.uuid4())
    stream = tmp_path / "claude-stream.jsonl"
    command = [
        claude, "-p", PROMPT, "--model", "haiku",
        "--plugin-dir", str(PLUGIN_DIR), "--settings", str(settings),
        "--session-id", session_id, "--no-session-persistence",
        "--output-format", "stream-json", "--verbose", "--include-hook-events",
    ]  # fmt: skip
    with stream.open("w") as out, (tmp_path / "claude-stderr.txt").open("w") as err:
        process = subprocess.Popen(
            command, cwd=hub.project_dir, env=environment, stdin=subprocess.DEVNULL,
            stdout=out, stderr=err, text=True,
        )  # fmt: skip
        try:
            chosen = pick_second_option(owner, process, session_id)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and process.poll() is None:
                if chosen and any(e.get("type") == "result" for e in events_of(stream)):
                    break  # a Monitor watch could keep -p alive; the answer is in
                time.sleep(1)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
    events = events_of(stream)
    results = [e for e in events if e.get("type") == "result"]
    final = str(results[-1].get("result")) if results else "no result event"
    init = next((e for e in events if e.get("subtype") == "init"), {})
    tools = [t for t in init.get("tools", []) if "agent-canvas" in t]
    used = [
        block["name"]
        for e in events if e.get("type") == "assistant"
        for block in e.get("message", {}).get("content", [])
        if block.get("type") == "tool_use"
    ]  # fmt: skip
    denials = [d for r in results for d in r.get("permission_denials", [])]
    hooks = sorted(
        {e.get("hook_event") for e in events if e.get("subtype") == "hook_started"}
    )
    print(f"RESULT: {final}\nTOOLS LISTED: {tools}\nTOOLS USED: {used}")
    print(f"HOOKS: {hooks}\nDENIALS: {denials}\nCHOSEN BY OWNER: {chosen}")
    assert chosen, f"no three-option block appeared. Claude said: {final}"
    assert any(t.endswith("__show") for t in tools), tools  # PLG-02
    assert {"SessionStart", "UserPromptSubmit"} <= set(hooks), hooks  # PLG-02
    assert denials == [], denials  # default mode: the allow rules were enough
    log = hub.on_loop(lambda: hub.state.events.all(session_id))
    choices = [e for e in log if e["kind"] == "choice"]
    assert choices and choices[-1]["value"] == [chosen], log
    others = {"a", "b", "c", "1", "2", "3"} - {chosen}
    line = final.strip().splitlines()[-1]
    assert chosen in line and not any(f"CHOSEN: {o}" in line for o in others), final
