"""Final acceptance (TST-03), scenario 8: a page past its lifetime.

A real nested ``claude -p --plugin-dir plugin/`` works against a temporary hub
whose clock is shifted by ``AGENT_CANVAS_TEST_CLOCK_OFFSET`` (LIFE-14), for the
hub (this process) and for the agent's hook and commands (its environment).
No browser: the owner only sends prompts.
First attempt ``haiku``, one retry with ``sonnet`` (see ``conftest.py``).
Run by hand: ``uv run pytest -m e2e -k scenario_8 -s``.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import httpx
import pytest
from harness import ClaudeRun
from test_acceptance_claude import GUIDE, assert_no_denials
from test_acceptance_comments_cards import ONE_COMMAND, canvas, session_folder

from agent_canvas.hub import clock, events

pytestmark = [pytest.mark.e2e, pytest.mark.retry_once]

DAY = 24 * 3600
SINGLE, TRANSITIONAL = "result.html", "notes.html"
REMINDER = "past their lifetime"

PROMPT_8A = f"""{GUIDE} {ONE_COMMAND} Deal with everything the canvas told you with \
this message, then reply with one line `READY` and stop."""
PROMPT_8B = f"{GUIDE} {ONE_COMMAND} Reply with one line `AGAIN` and stop."


@pytest.fixture(autouse=True)
def claude_installed() -> None:
    """Fail (not skip) when the claude command is missing."""
    assert shutil.which("claude"), "the claude command is not installed"


def hook_outputs(run: ClaudeRun) -> list[str]:
    """What the UserPromptSubmit hooks of the run's current stream printed."""
    return [
        event["output"]
        for event in run.events()
        if event.get("subtype") == "hook_response"
        and event.get("hook_event") == "UserPromptSubmit"
    ]


def pages_of(run: ClaudeRun, session: str, *flags: str) -> dict[str, dict]:
    """``page list`` of the session by page name."""
    out = json.loads(canvas(run, "page", "list", "--session", session, *flags))
    return {page["name"]: page for page in out["pages"]}


def test_e2e_scenario_8_claude_pages_past_their_lifetime(
    hub, tmp_path, claude_model, monkeypatch
) -> None:  # noqa: ANN001
    run = ClaudeRun(hub, tmp_path, claude_model)
    session = str(uuid.uuid4())
    base = f"{hub.base_url}/api/sessions/{session}"

    def at(days: float) -> None:
        """Shift the hub (this process) and the agent's environment."""
        for name, value in (
            ("AGENT_CANVAS_TEST_MODE", "1"),
            ("AGENT_CANVAS_TEST_CLOCK_OFFSET", str(days * DAY)),
        ):
            monkeypatch.setenv(name, value)
            run.environment[name] = value

    def put(name: str, kind: str) -> None:
        httpx.post(
            f"{base}/show", json={"name": name, "audit": False},
            headers=hub.key_headers, timeout=30,
        ).raise_for_status()  # fmt: skip
        httpx.post(
            f"{base}/pages", json={"action": "kind", "name": name, "kind": kind},
            headers=hub.key_headers,
        ).raise_for_status()  # fmt: skip

    answer = httpx.post(
        f"{base}/path", json={"project": str(hub.project_dir), "agent": "claude-code"},
        headers=hub.key_headers,
    )  # fmt: skip
    folder = Path(answer.json()["folder"])
    assert folder == session_folder(hub, session)
    at(0)
    (folder / TRANSITIONAL).write_text(
        "<p>working notes</p><p>In use: I will update these notes.</p>"
    )
    put(TRANSITIONAL, "transitional")
    (folder / SINGLE).write_text("<p>one result</p>")
    put(SINGLE, "single-use")
    # The hub stamps events with the real time; the answer must be dated day 27.
    at(27)
    with monkeypatch.context() as patch:
        patch.setattr(events, "now_iso", lambda: clock.iso(clock.now()))
        hub.create_event(session, "button", page=SINGLE)
    at(31)  # the result was answered 4 days ago, the notes changed 31 days ago
    before = pages_of(run, session)
    assert before[SINGLE]["expired"] and before[TRANSITIONAL]["expired"], before

    run.start(PROMPT_8A, session)
    run.finish(240)
    first_hook = hook_outputs(run)
    first_final = run.final()
    after = pages_of(run, session)
    archived = pages_of(run, session, "--archived")

    run.start(PROMPT_8B, resume=session)
    run.finish(240)
    second_hook = hook_outputs(run)
    print(
        run.report(),
        f"\nFIRST HOOK: {first_hook}\nSECOND HOOK: {second_hook}\nFINAL: {first_final}"
        f"\nLIVE AFTER: {after}\nARCHIVED LIST: {archived}",
    )
    assert_no_denials(run)

    [line] = [text for text in first_hook if text]
    assert line.count(REMINDER) == 1 and SINGLE in line and TRANSITIONAL in line, line
    assert archived[SINGLE]["archived"], archived
    assert SINGLE not in after, after
    assert after[TRANSITIONAL]["expired"] is False, after
    assert second_hook, "the hook did not run on the second prompt"
    assert not any(REMINDER in text for text in second_hook), second_hook
