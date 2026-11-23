"""Final acceptance (TST-04): scenarios 1 and 2 with opencode.

``opencode run --model opencode/big-pickle`` is set up exactly as
``docs/opencode.md`` says (MCP server in ``opencode.json``, instructions in
``AGENTS.md``) inside the temporary project, with temporary XDG directories.
A model or network failure is a test failure with its reason in the message;
like every scenario it may be retried once (same model), and the retry is
recorded (TST-03).
Run by hand: ``uv run pytest -m e2e -k acceptance_opencode -s``.
"""

from __future__ import annotations

import shutil

import pytest
from harness import (
    OPENCODE_MODEL,
    OpencodeRun,
    comment_lasso_around,
    frame_has,
    open_first_tab,
    pump,
    session_events,
    wait_listening,
)
from test_acceptance_claude import PROMPT_2, assert_lasso_on_peak, plot_ready

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.retry_once,
    pytest.mark.fixed_model(OPENCODE_MODEL),  # recorded under this name, not haiku
]

PROMPT_1 = (
    "I am choosing a design for a small phone stand. Use the agent-canvas "
    "canvas as your instructions say: show me a page with three design options "
    "as a canvas-choices block (data-canvas-id `design`) with a submit button, "
    "then wait for my choice with the `ask` tool for that block. When I have "
    "chosen, reply with exactly one line: `CHOSEN: <the id of the option I "
    "chose>`."
)


@pytest.fixture(autouse=True)
def opencode_installed() -> None:
    """Fail (not skip) when the opencode command is missing."""
    assert shutil.which("opencode"), "the opencode command is not installed"


def first_session(owner, run: OpencodeRun) -> str | None:  # noqa: ANN001
    """Session id of the first tab the agent created, or None."""
    tab = owner.page.locator(".tab[data-session]")
    return tab.first.get_attribute("data-session") if tab.count() else None


def wait_for(run: OpencodeRun, owner, condition, seconds: float) -> bool:  # noqa: ANN001
    """Wait for ``condition`` while the owner's browser keeps running."""
    return run.wait(condition, seconds, tick=lambda: pump(owner))


def test_e2e_scenario_1_opencode_pick_one_of_three(owner, hub, tmp_path) -> None:  # noqa: ANN001
    run = OpencodeRun(hub, tmp_path)
    run.start(PROMPT_1)
    options = "canvas-choices .option"
    try:
        shown = wait_for(
            run,
            owner,
            lambda: open_first_tab(owner) and frame_has(owner, options, 3),
            240,
        )
        assert shown, f"no three-option block. {run.failure()} said: {run.final()}"
        session = first_session(owner, run)
        # CLI-06: an ask waits for the *next* event, so choose once it waits.
        assert wait_listening(owner, run, session, 120), run.failure() or run.final()
        pick = owner.frame.locator(options).nth(1)
        chosen = pick.get_attribute("data-id")
        others = [
            o.get_attribute("data-id")
            for i, o in enumerate(owner.frame.locator(options).all())
            if i != 1
        ]
        pick.click()
        owner.frame.locator("canvas-choices .submit").click()
        wait_for(run, owner, lambda: not run.running, 180)
    finally:
        run.stop()
    final = run.final()
    print(f"CHOSEN BY OWNER: {chosen}\nTOOLS: {run.tools_used()}\nFINAL: {final}")
    assert not run.failure(), run.failure()
    choices = [e for e in session_events(hub, session) if e["kind"] == "choice"]
    assert choices and choices[-1]["value"] == [chosen], choices
    line = [ln for ln in final.splitlines() if "CHOSEN:" in ln][-1].lower()
    assert f"chosen: {chosen}".lower() in line.replace("`", ""), final
    assert not any(f"chosen: {o}".lower() in line for o in others), final


def test_e2e_scenario_2_opencode_circle_a_peak(owner, hub, tmp_path) -> None:  # noqa: ANN001
    run = OpencodeRun(hub, tmp_path)
    run.start(PROMPT_2)
    try:
        shown = wait_for(
            run, owner, lambda: open_first_tab(owner) and plot_ready(owner), 240
        )
        assert shown, f"no plot appeared. {run.failure()} said: {run.final()}"
        session = first_session(owner, run)
        wait_for(run, owner, lambda: hub.listening(session), 90)
        comment_lasso_around(owner, 120)
        owner.page.fill("#draft-message", "why this peak?")
        owner.page.click("#send-button")
        wait_for(run, owner, lambda: not run.running, 180)
    finally:
        run.stop()
    final = run.final()
    print(f"TOOLS: {run.tools_used()}\nFINAL: {final}")
    assert not run.failure(), run.failure()
    [event] = [e for e in session_events(hub, session) if e["kind"] == "send"]
    assert_lasso_on_peak(event)
    text = final.lower()
    assert "120" in text or "alpha" in text, final
    assert "480" not in text and "beta" not in text, final
