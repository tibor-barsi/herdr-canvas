"""End-to-end smoke run of the home view with a real Claude Code (P14.4).

A nested ``claude -p --model haiku --plugin-dir plugin/`` answers one line. Its
hooks call ``agent-canvas hook forward`` from PATH: ``harness.make_bin`` puts a
wrapper of this checkout first, and the environment points the CLI at the
temporary hub (own state folder, own port), never at the owner's hub. The
owner's window (headless Chromium) must show a lane with one row that is
``working`` and then ``turn-done``.
Run by hand: ``uv run pytest -m e2e -k home_claude``.
"""

from __future__ import annotations

import shutil
import uuid

import httpx
import pytest
from harness import ClaudeRun, pump

pytestmark = pytest.mark.e2e

ROW = "#home .home-row"


def home_states(hub, session_id: str) -> list[str]:  # noqa: ANN001
    """Return the state of the session in the hub's home snapshot, or []."""
    snapshot = httpx.get(f"{hub.base_url}/api/home", headers=hub.key_headers).json()
    return [s["state"] for s in snapshot["sessions"] if s["id"] == session_id]


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed")
def test_e2e_home_claude_a_real_session_shows_working_then_turn_done(
    owner,  # noqa: ANN001
    hub,  # noqa: ANN001
    tmp_path,  # noqa: ANN001
) -> None:
    run = ClaudeRun(hub, tmp_path, "haiku")
    path = run.environment["PATH"]
    assert shutil.which("agent-canvas", path=path) == str(
        tmp_path / "bin-claude" / "agent-canvas"
    )  # the hooks find this checkout's CLI first, not the installed copy
    session_id = str(uuid.uuid4())
    owner.page.evaluate(
        """(id) => {
          window.__seen = [];
          new MutationObserver(() => {
            const row = document.querySelector(`#home .home-row[data-session='${id}']`);
            const state = row && row.dataset.state;
            if (state && window.__seen.at(-1) !== state) window.__seen.push(state);
          }).observe(document.getElementById("home"), {subtree: true, childList: true});
        }""",
        session_id,
    )

    def finished() -> bool:
        seen = owner.page.evaluate("__seen")
        return "working" in seen and seen[-1] == "turn-done"

    run.start("Reply with exactly one line: PONG", session_id=session_id)
    try:
        run.wait(finished, 120, lambda: pump(owner))
        seen = owner.page.evaluate("__seen")
        print(
            f"STATES IN THE VIEW: {seen}\nHUB SNAPSHOT: {home_states(hub, session_id)}"
        )
        print(run.report())
        assert "working" in seen and seen[-1] == "turn-done", seen
        # Once `claude -p` has exited, the 10 s process check (AGT-09) may already
        # have marked the session ended.
        assert home_states(hub, session_id) in (["turn-done"], ["ended"])
        assert owner.page.locator("#home .home-lane").count() == 1
        assert owner.page.evaluate("document.body.classList.contains('home')")
    finally:
        run.stop()
