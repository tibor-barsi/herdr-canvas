"""End-to-end run of the agent table with a real question (PLG-11).

An interactive ``claude --model haiku --dangerously-skip-permissions
--plugin-dir plugin/`` runs in a detached tmux (``claude -p`` offers no
``AskUserQuestion``, early check 8), in a fresh folder, on a private tmux
socket so the owner's tmux is never touched. It is asked to call
``AskUserQuestion`` once. Polling ``GET /api/home`` every 200 ms must see the
session ``needs-you`` of kind ``question`` with the question text while it
waits, and not ``needs-you`` after the test answers with Enter (option A).
Run by hand: ``uv run pytest -m e2e -k plg_11``.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid

import httpx
import pytest
from harness import hub_environment, make_bin

from helpers import PLUGIN_DIR

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.retry_once,
    pytest.mark.fixed_model("haiku"),
]

QUESTION = "Which layout?"
PROMPT = (
    f"Call the AskUserQuestion tool exactly once with the question '{QUESTION}' "
    "and the options 'A' and 'B'. After the answer, reply with the chosen letter only."
)


PROMPT_START = PROMPT[:30]


class Tmux:
    """A detached tmux on a private socket; ``kill`` ends its server and clients."""

    def __init__(self, socket: str, environment: dict[str, str]) -> None:
        self.socket, self.environment = socket, environment

    def run(self, *args: str) -> str:
        """Run one tmux command on the private socket and return its output."""
        done = subprocess.run(
            ["tmux", "-L", self.socket, *args], env=self.environment,
            capture_output=True, text=True, timeout=20,
        )  # fmt: skip
        return done.stdout

    def screen(self) -> str:
        """Return the visible text of the session."""
        return self.run("capture-pane", "-t", "s", "-p")

    def kill(self) -> None:
        """End the private tmux server (and so the claude it holds)."""
        self.run("kill-server")


@pytest.fixture
def tmux(hub, tmp_path):  # noqa: ANN001, ANN201
    """A private tmux whose server is killed at the end, also after a failure."""
    environment = hub_environment(hub, make_bin(tmp_path / "bin-claude"))
    handle = Tmux(f"ac-plg11-{uuid.uuid4().hex[:8]}", environment)
    yield handle
    handle.kill()


def snapshot_entry(hub, session_id: str) -> tuple | None:  # noqa: ANN001
    """Return (state, need kind, need text) of the session, or None."""
    data = httpx.get(f"{hub.base_url}/api/home", headers=hub.key_headers).json()
    for session in data["sessions"]:
        if session["id"] == session_id:
            need = session["need"] or {}
            return session["state"], need.get("kind"), need.get("text")
    return None


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed")
@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_e2e_plg_11_a_real_question_is_needs_you_until_it_is_answered(
    hub,  # noqa: ANN001
    tmux,  # noqa: ANN001
    claude_model,  # noqa: ANN001
    tmp_path,  # noqa: ANN001
) -> None:
    folder = tmp_path / "fresh"
    folder.mkdir()
    session_id = str(uuid.uuid4())
    sequence: list[tuple] = []
    started = time.monotonic()

    def poll() -> tuple | None:
        seen = snapshot_entry(hub, session_id)
        if seen is not None and (not sequence or sequence[-1][1] != seen):
            sequence.append((round(time.monotonic() - started, 1), seen))
        time.sleep(0.2)
        return seen

    def until(condition, seconds: float, what: str) -> None:  # noqa: ANN001
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return
        raise AssertionError(f"{what}; sequence {sequence}; screen:\n{tmux.screen()}")

    def seen_within(seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if poll() is not None:
                return True
        return False

    tmux.run(
        "new-session", "-d", "-s", "s", "-x", "200", "-y", "50", "-c", str(folder),
        "claude", "--model", claude_model, "--dangerously-skip-permissions",
        "--plugin-dir", str(PLUGIN_DIR), "--session-id", session_id,
    )  # fmt: skip

    def ready() -> bool:
        screen = tmux.screen()
        if "Yes, I trust this folder" in screen:
            tmux.run("send-keys", "-t", "s", "Down", "Enter")
        time.sleep(0.2)
        return "bypass permissions on" in screen

    until(ready, 60, "claude did not reach its prompt")
    tmux.run("send-keys", "-t", "s", "-l", PROMPT)
    until(lambda: PROMPT_START in tmux.screen(), 15, "the prompt was not typed")
    tmux.run("send-keys", "-t", "s", "Enter")
    if not seen_within(10):  # an Enter lost before the box took the text
        tmux.run("send-keys", "-t", "s", "Enter")

    def asking() -> bool:
        seen = poll()
        return seen is not None and seen[0] == "needs-you"

    until(asking, 90, "the session never became needs-you")
    assert snapshot_entry(hub, session_id) == ("needs-you", "question", QUESTION)
    for _ in range(5):  # the PermissionRequest must not turn it into a permission
        assert poll() == ("needs-you", "question", QUESTION)

    tmux.run("send-keys", "-t", "s", "Enter")
    answered_at = time.monotonic()
    until(lambda: poll()[0] != "needs-you", 10, "needs-you did not end")
    left_after = time.monotonic() - answered_at
    until(lambda: poll()[0] == "turn-done", 60, "the turn did not finish")
    for _ in range(10):
        poll()
    tmux.run("send-keys", "-t", "s", "-l", "/exit")
    tmux.run("send-keys", "-t", "s", "Enter")
    until(lambda: poll()[0] == "ended", 20, "the session did not end")

    print(f"STATE SEQUENCE (s, (state, kind, text)): {sequence}")
    print(f"LEFT needs-you {left_after:.1f} s after the answer")
    states = [entry[1][0] for entry in sequence]
    assert states.count("needs-you") == 1, sequence
