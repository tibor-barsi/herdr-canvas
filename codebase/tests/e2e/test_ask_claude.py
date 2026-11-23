"""End-to-end smoke run of ``ask`` with a real Claude Code (M7, CLI-04).

A nested ``claude -p --model haiku`` writes a page, shows it and runs
``agent-canvas ask`` through its Bash tool. Playwright is the owner who answers
the question card. The hub, its state and its config are temporary and use a
free port; nothing touches the real user directories or the default port.
Run by hand: ``uv run pytest -m e2e -k ask_claude``.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from harness import open_first_tab

pytestmark = pytest.mark.e2e

SESSION = "e2e-ask"
PAGE = '<h1 id="t">Layout smoke</h1><p>Two candidate layouts.</p>'
ASK_COMMAND = (
    'agent-canvas ask "Which layout do you prefer?" '
    "--choice Ribbed --choice Lattice --timeout 150"
)
PROMPT = f"""You are testing a command line tool called `agent-canvas`. It is on
your PATH and already configured through environment variables. Use the Bash
tool for every step and do not use any other command line tool.

1. Run `agent-canvas session path` and read the folder it prints.
2. Write this exact HTML to `page.html` inside that folder:
   {PAGE}
3. Run `agent-canvas show` (no arguments).
4. Run `{ASK_COMMAND}` in the foreground and wait for it to finish. It
   prints one JSON object.
5. Reply with exactly one line: `ANSWER: <label>` where <label> is the chosen
   label from the event value in that JSON.
"""


def make_wrapper(directory: Path) -> Path:
    """Create an ``agent-canvas`` executable that runs this checkout's CLI."""
    directory.mkdir()
    wrapper = directory / "agent-canvas"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m agent_canvas.cli "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return directory


def test_e2e_claude_haiku_asks_and_the_owner_answers(owner, hub, tmp_path) -> None:  # noqa: ANN001
    claude = shutil.which("claude")
    if claude is None:
        pytest.skip("the claude command is not installed")
    project = hub.project_dir
    environment = {
        **os.environ,
        "PATH": f"{make_wrapper(tmp_path / 'bin')}:{os.environ['PATH']}",
        "AGENT_CANVAS_PORT": str(hub.port),
        "AGENT_CANVAS_STATE_DIR": str(hub.state_dir),
        "AGENT_CANVAS_CONFIG_DIR": str(hub.config_dir),
        "AGENT_CANVAS_WINDOW_COMMAND": "true",
        "AGENT_CANVAS_SESSION": SESSION,
        "AGENT_CANVAS_PROJECT": str(project),
        "AGENT_CANVAS_AGENT": "claude-code",
    }
    stream = tmp_path / "claude-stream.jsonl"
    with stream.open("w") as out, (tmp_path / "claude-stderr.txt").open("w") as err:
        process = subprocess.Popen(
            [claude, "-p", PROMPT, "--model", "haiku",
             "--output-format", "stream-json", "--verbose",
             "--allowedTools", "Bash,Write", "--permission-mode", "bypassPermissions",
             "--no-session-persistence"],
            cwd=project, env=environment, stdin=subprocess.DEVNULL,
            stdout=out, stderr=err, text=True,
        )  # fmt: skip
        try:
            answered = answer_the_card(owner, process, "Lattice")
            process.wait(timeout=120)
        finally:
            if process.poll() is None:
                process.kill()
    report = summarise(stream)
    print(report)  # shown with -s; the acceptance report quotes it
    assert answered, f"no question card appeared. Claude said: {report}"
    # The owner's installed plugin, if any, replaces AGENT_CANVAS_SESSION with
    # Claude's own session id (PLG-04), so take the events of every session.
    events = hub.on_loop(
        lambda: [
            e for s in hub.state.sessions() for e in hub.state.events.all(s.session_id)
        ]
    )
    [answer] = [e for e in events if e["kind"] == "answer"]
    assert answer["value"] == ["Lattice"] and answer["delivery"] == "ask"
    assert answer["state"] == "delivered"
    assert "Lattice" in report, report


def answer_the_card(owner, process, label: str, seconds: float = 180) -> bool:  # noqa: ANN001
    """Click ``label`` on the question card once it shows; False if it never does."""
    deadline = time.monotonic() + seconds
    card = owner.page.locator("#ask-bar .ask-card")
    while time.monotonic() < deadline and process.poll() is None:
        open_first_tab(owner)  # the card shows in the session's tab (SES-07)
        if card.count() and card.get_by_role("button", name=label).count():
            assert owner.frame.locator("#t").inner_text() == "Layout smoke"
            card.get_by_role("button", name=label).click()
            return True
        owner.page.wait_for_timeout(100)
    return False


def summarise(stream: Path) -> str:
    """Return Claude's final result text (or its error) from the stream."""
    final = "no result event"
    for line in stream.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            final = str(event.get("result"))
    return final
