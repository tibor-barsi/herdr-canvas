"""End-to-end run of the agent table with a real subagent (PLG-10).

A nested ``claude -p --model haiku --plugin-dir plugin/`` launches one
``general-purpose`` subagent with the task "count files". Its hooks call this
checkout's ``agent-canvas hook forward`` and post to the temporary hub only.
Polling ``GET /api/home`` every 200 ms must see the session and the subagent
while it runs, and the session ``ended`` in the lane after the process exits.
Run by hand: ``uv run pytest -m e2e -k plg_10``.
"""

from __future__ import annotations

import shutil
import time
import uuid

import httpx
import pytest
from harness import ClaudeRun

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.retry_once,
    pytest.mark.fixed_model("haiku"),
]

PROMPT = (
    "Use the Agent tool exactly once, with subagent_type general-purpose and "
    "description 'count files'. Its prompt: count the files in the current "
    "folder with one `ls` and reply with the number. Then reply with one line: "
    "DONE <number>."
)


def observe(hub, session_id: str) -> tuple | None:  # noqa: ANN001
    """Return (session state, place, ((type, task, state), ...)) or None."""
    snapshot = httpx.get(f"{hub.base_url}/api/home", headers=hub.key_headers).json()
    for session in snapshot["sessions"]:
        if session["id"] == session_id:
            subagents = tuple(
                (s["type"], s["task"], s["state"]) for s in session["subagents"]
            )
            return session["state"], session["place"], subagents
    return None


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed")
def test_e2e_plg_10_a_real_subagent_is_listed_while_it_runs_and_ended_after(
    hub,  # noqa: ANN001
    tmp_path,  # noqa: ANN001
) -> None:
    run = ClaudeRun(hub, tmp_path, "haiku", extra_allow=["Bash(ls:*)"])
    session_id = str(uuid.uuid4())
    sequence: list[tuple] = []
    started = time.monotonic()

    def poll() -> None:
        seen = observe(hub, session_id)
        if seen is not None and (not sequence or sequence[-1][1] != seen):
            sequence.append((round(time.monotonic() - started, 1), seen))
        time.sleep(0.2)

    run.start(PROMPT, session_id=session_id)
    try:
        while run.running and time.monotonic() - started < 160:
            poll()
        for _ in range(25):  # SessionEnd may follow the exit by a moment
            poll()
            if sequence and sequence[-1][1][0] == "ended":
                break
        print(f"STATE SEQUENCE (s, state, place, subagents): {sequence}")
        print(run.report())
        states = [entry[1] for entry in sequence]
        running = [
            s for s in states
            if ("general-purpose", "count files", "working") in s[2]
        ]  # fmt: skip
        assert running, "no snapshot showed the working general-purpose subagent"
        assert any(s[0] == "working" for s in states)
        assert states[-1][0] == "ended" and states[-1][1] == "lane"
        assert states[-1][2] == ()
    finally:
        run.stop()
