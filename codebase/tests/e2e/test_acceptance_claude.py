"""Final acceptance (TST-03): the five scenarios with a real Claude Code.

Each test runs a nested ``claude -p --plugin-dir plugin/`` in the default
permission mode: ``--settings`` allows only ``Edit(**/.agent-canvas/**)``,
``Bash(agent-canvas:*)`` and the plugin's MCP tools, plus the one fixture
command (``longrun`` and a few read-only helpers) in the scenarios that run a
long job. Playwright is the owner. The first attempt uses ``haiku``; one retry
with ``sonnet`` is allowed and recorded (see ``conftest.py``).
Run by hand: ``uv run pytest -m e2e -k acceptance_claude -s``.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from harness import (
    FIXTURE_ALLOW,
    MCP_PREFIX,
    ClaudeRun,
    comment_lasso_around,
    delivery_routes,
    frame_has,
    open_first_tab,
    pump,
    result_with,
    send_note,
    session_events,
    wait_listening,
    wait_reply,
)

pytestmark = [pytest.mark.e2e, pytest.mark.retry_once]

GUIDE = "Use the agent-canvas canvas (the plugin is installed; follow its guideline)."


@pytest.fixture(autouse=True)
def claude_installed() -> None:
    """Fail (not skip) when the claude command is missing."""
    assert shutil.which("claude"), "the claude command is not installed"


def alive(pid_file: Path) -> bool:
    """Whether the process whose pid is in ``pid_file`` is still running."""
    try:
        os.kill(int(pid_file.read_text()), 0)
    except (OSError, ValueError):
        return False
    return True


def wait_for(run: ClaudeRun, owner, condition, seconds: float) -> bool:  # noqa: ANN001
    """Wait for ``condition`` while the owner's browser keeps running."""
    return run.wait(condition, seconds, tick=lambda: pump(owner))


def is_plain_canvas_command(command: str) -> bool:
    """Whether ``command`` is one ``agent-canvas`` call, which the rule covers."""
    return command.startswith("agent-canvas") and not any(
        mark in command for mark in (";", "&", "|", "\n", "`", "$(", ">")
    )


def assert_no_denials(run: ClaudeRun) -> None:
    """
    The documented allow rules must have been enough for agent-canvas itself.

    A denied command unrelated to agent-canvas (the model tried to compute data
    with a script, or chained `agent-canvas` with `find` in one command, which
    the rule does not cover) is printed and tolerated: default mode refuses it,
    and the model has to find another way.
    """
    canvas = [
        d
        for d in run.denials()
        if d["tool_name"].startswith("mcp__")
        or ".agent-canvas" in str(d["tool_input"].get("file_path", ""))
        or is_plain_canvas_command(str(d["tool_input"].get("command", "")))
    ]
    print("OTHER DENIALS:", [d for d in run.denials() if d not in canvas])
    assert canvas == [], canvas


# ---- Scenario 1 -----------------------------------------------------------------

PROMPT_1 = f"""I am choosing a design for a small phone stand. {GUIDE} Show me a \
page with three design options as a canvas-choices block with a submit button, \
then wait for my choice. When I have chosen, reply with exactly one line: \
`CHOSEN: <the id of the option I chose>`."""


def test_e2e_scenario_1_claude_pick_one_of_three(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    run = ClaudeRun(hub, tmp_path, claude_model)
    session = str(uuid.uuid4())
    run.start(PROMPT_1, session)
    chosen = None
    try:
        options = "canvas-choices .option"
        assert wait_for(
            run,
            owner,
            lambda: open_first_tab(owner) and frame_has(owner, options, 3),
            200,
        ), f"no three-option block appeared\n{run.report()}"
        assert wait_listening(owner, run, session, 150), run.report()
        pick = owner.frame.locator(options).nth(1)
        chosen = pick.get_attribute("data-id")
        others = [
            o.get_attribute("data-id")
            for i, o in enumerate(owner.frame.locator(options).all())
            if i != 1
        ]
        pick.click()
        owner.frame.locator("canvas-choices .submit").click()
        wait_for(run, owner, lambda: result_with(run, "CHOSEN:") is not None, 120)
        final = result_with(run, "CHOSEN:") or run.final()
    finally:
        run.finish(5)
    print(run.report())
    assert_no_denials(run)
    assert any(t.endswith("__show") for t in run.init_tools() if MCP_PREFIX in t)
    log = session_events(hub, session)
    choices = [e for e in log if e["kind"] == "choice"]
    assert choices and choices[-1]["value"] == [chosen], log
    line = [ln for ln in final.splitlines() if "CHOSEN:" in ln][-1]
    assert f"CHOSEN: {chosen}".lower() in line.lower().replace("`", ""), final
    assert not any(f"CHOSEN: {o}".lower() in line.lower() for o in others), final


# ---- Scenario 2 -----------------------------------------------------------------

PROMPT_2 = f"""I am looking at the spectrum of a vibrating bracket. {GUIDE} Show me a \
canvas-plot (data-canvas-id "spectrum") with frequency in Hz on the x axis from \
0 to 600 and amplitude on the y axis: one smooth line with two clearly separated \
peaks, a tall one labelled "Alpha" at exactly 120 Hz (amplitude 10) and a lower \
one labelled "Beta" at exactly 480 Hz (amplitude 6), both labels written next to \
the peaks. Then wait for my feedback. I will draw a lasso comment around one \
peak and ask a question. When it arrives, look at what I marked (the \
comment line with its picture, and the screenshot) and answer in one or two \
sentences about the peak \
I circled only: name its label and frequency, and do not mention the other peak."""


def plot_ready(owner) -> bool:  # noqa: ANN001
    """Whether the first plot has drawn its curve."""
    try:
        return owner.frame.evaluate(
            "() => { const e = document.querySelector('canvas-plot');"
            " return !!(e && e.shadowRoot"
            ".querySelector('.plot .scatterlayer .trace')); }"
        )
    except Exception:  # noqa: BLE001 - frame not there yet
        return False


def assert_lasso_on_peak(event: dict) -> None:
    """The send event has one lasso on the plot, a picture and the peak's x range."""
    record = json.loads(Path(event["send_file"]).read_text())
    [comment] = record["comments"]
    assert comment["kind"] == "lasso", comment
    assert comment["target"]["canvas_id"] == "spectrum", comment
    picture = Path(comment["picture"])
    if not picture.is_absolute():
        picture = Path(event["send_file"]).parent / picture
    assert picture.is_file(), comment
    data = comment["data"]
    assert data and data["canvas_id"] == "spectrum", comment
    low, high = data["x"]
    assert low <= 120 <= high and not low <= 480 <= high, (low, high)


def test_e2e_scenario_2_claude_circle_a_peak(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    run = ClaudeRun(hub, tmp_path, claude_model)
    session = str(uuid.uuid4())
    run.start(PROMPT_2, session)
    try:
        assert wait_for(
            run, owner, lambda: open_first_tab(owner) and plot_ready(owner), 200
        ), run.report()
        listening = wait_listening(owner, run, session, 120)
        comment_lasso_around(owner, 120)
        send_note(owner, "why this peak?")
        final = ""
        if wait_for(run, owner, lambda: session_events(hub, session), 20):
            final = wait_reply(
                owner, run, session, ("120", "alpha", "480", "beta"), 150, settle=25
            )
    finally:
        run.finish(5)
    print(run.report(), f"\nLISTENING BEFORE SEND: {listening}")
    assert_no_denials(run)
    [event] = [e for e in session_events(hub, session) if e["kind"] == "send"]
    assert_lasso_on_peak(event)
    text = final.lower()
    assert "120" in text or "alpha" in text, final
    assert "480" not in text and "beta" not in text, final


# ---- Scenario 3 -----------------------------------------------------------------


def prompt_3(run_dir: Path) -> str:
    """Prompt of scenario 3 for a run directory."""
    return f"""{GUIDE} Run `longrun --dir {run_dir} --seconds 75 --steps 10` in \
the background (a Bash background task). It writes its process id to \
{run_dir}/pid and appends a line `PROGRESS n/10` to {run_dir}/progress.log \
about every 8 seconds. Show me a page with a canvas-progress block (data-canvas-id \
"job", label "Long run", max 10, value 0) and a canvas-buttons block with one \
danger button labelled "Stop" (id "stop"). Keep the bar current: whenever a new \
PROGRESS line appears, rewrite page.html with the new value. Follow the progress \
log with Monitor (`tail -n +1 -f {run_dir}/progress.log`) and listen for my \
feedback with `agent-canvas watch` under Monitor too. If I press Stop, kill the \
process (its pid is in {run_dir}/pid), set the progress status to "failed", and \
reply with one line starting `STOPPED:`. If the run finishes first, reply \
`FINISHED`."""


def bar_value(owner) -> str | None:  # noqa: ANN001
    """The progress bar's current value as the owner sees it."""
    try:
        bar = owner.frame.locator("canvas-progress [role=progressbar]")
        return bar.first.get_attribute("aria-valuenow", timeout=500)
    except Exception:  # noqa: BLE001 - not rendered yet
        return None


def test_e2e_scenario_3_claude_live_progress_and_stop(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    run_dir = hub.project_dir / "longrun"
    run = ClaudeRun(hub, tmp_path, claude_model, extra_allow=FIXTURE_ALLOW)
    session = str(uuid.uuid4())
    run.start(prompt_3(run_dir), session)
    values: list[str] = []
    green = None
    try:
        assert wait_for(
            run, owner,
            lambda: open_first_tab(owner)
            and frame_has(owner, "canvas-progress")
            and frame_has(owner, "canvas-buttons"),
            200,
        ), run.report()  # fmt: skip
        owner.frame.evaluate("window.__acProbe = 'same frame'")

        def enough_changes() -> bool:
            value = bar_value(owner)
            if value is not None and (not values or values[-1] != value):
                values.append(value)
            return len(values) >= 4  # three changes

        assert wait_for(run, owner, enough_changes, 150), (values, run.report())
        assert wait_for(run, owner, lambda: hub.listening(session), 60), run.report()
        tab = owner.page.locator(f'.tab[data-session="{session}"]')
        green = tab.locator('[data-listening="true"]').count() == 1
        probe_kept = owner.frame.evaluate("window.__acProbe") == "same frame"
        pressed_at = time.monotonic()
        owner.frame.locator("canvas-buttons button").first.click()
        pid_file = run_dir / "pid"
        assert wait_for(run, owner, lambda: not alive(pid_file), 60), "run not stopped"
        stopped_after = time.monotonic() - pressed_at
        final = wait_reply(owner, run, session, ("STOPPED:",), 90)
    finally:
        run.finish(5)
    print(
        run.report(),
        f"\nVALUES: {values}\nGREEN: {green}\nSTOP TOOK: {stopped_after:.1f}s",
    )
    assert_no_denials(run)
    assert probe_kept, "the frame was reloaded while progress changed"
    assert green, "the tab light was not green at the press"
    assert not (run_dir / "finished").exists(), "the run finished by itself"
    assert "STOPPED:" in final, final


# ---- Scenario 4 -----------------------------------------------------------------


def prompt_4a(run_dir: Path) -> str:
    """Prompt of scenario 4a (no listener) for a run directory."""
    return f"""{GUIDE} Show me a page with a canvas-markdown block saying \
"Benchmark running". Then run `longrun --dir {run_dir} --seconds 40 --steps 4` \
in the foreground with Bash (timeout 120000 ms) and wait for it to end. Do not \
listen for feedback and do not use Monitor. When it ends, reply with exactly \
`DONE`."""


def prompt_4b(run_dir: Path) -> str:
    """Prompt of scenario 4b (listening under Monitor) for a run directory."""
    return f"""{GUIDE} Show me a page with a canvas-markdown block saying \
"Benchmark running". Start `agent-canvas watch` under Monitor so that I can reach \
you while you work. Then run `longrun --dir {run_dir} --seconds 45 --steps 3` in \
the foreground with Bash (timeout 120000 ms). When it ends, reply `READY` and \
wait. When a note from me arrives, reply with one line `NOTE: <what it says>`."""


def start_when_busy(run: ClaudeRun, owner, run_dir: Path, ready) -> bool:  # noqa: ANN001
    """Wait until the long command runs and the page is shown."""
    return wait_for(
        run,
        owner,
        lambda: open_first_tab(owner) and alive(run_dir / "pid") and ready(),
        200,
    )


def test_e2e_scenario_4a_claude_note_while_busy_without_listener(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    run_dir = hub.project_dir / "busy-a"
    run = ClaudeRun(hub, tmp_path, claude_model, extra_allow=FIXTURE_ALLOW)
    session = str(uuid.uuid4())
    run.start(prompt_4a(run_dir), session)
    try:
        busy = start_when_busy(
            run, owner, run_dir, lambda: frame_has(owner, "canvas-markdown")
        )
        assert busy, run.report()
        was_listening = hub.listening(session)
        send_note(owner, "Please use the code word MARMOT-4417 in your next answer.")
        [event] = wait_events(owner, hub, session, 1)
        run.finish(150)
        queued_after_run = hub.event_state(session, event["id"])
        first_report = run.report()
        run.start(
            "What code word did I send you in my note? Reply with only the word.",
            resume=session,
        )
        run.finish(150)
    finally:
        run.stop()
    print(first_report, "\n", run.report())
    assert_no_denials(run)
    assert not was_listening and queued_after_run == "queued"
    assert "MARMOT-4417" in run.final(), run.final()
    routes = delivery_routes(hub, session)
    assert routes.get(event["id"]) == "hook", routes


def wait_events(owner, hub, session: str, count: int) -> list[dict]:  # noqa: ANN001
    """Wait for ``count`` events in a session while the browser runs."""
    for _ in range(100):
        found = session_events(hub, session)
        if len(found) >= count:
            return found
        pump(owner, 50)
    raise AssertionError(f"expected {count} events, got {session_events(hub, session)}")


def event_times(hub, session: str, event_id: str) -> tuple[datetime, datetime]:  # noqa: ANN001
    """Return (created, delivered) times of an event from ``events.jsonl``."""
    log = hub.project_dir / hub.project_dir_name / session / "events.jsonl"
    created = delivered = None
    for line in log.read_text().splitlines():
        record = json.loads(line)
        if record.get("id") != event_id:
            continue
        when = datetime.fromisoformat(record["time"])
        if record.get("record") == "delivered":
            delivered = when
        elif record.get("record") == "event":
            created = when
    assert created and delivered, (created, delivered)
    return created, delivered


def test_e2e_scenario_4b_claude_note_while_busy_with_listener(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    run_dir = hub.project_dir / "busy-b"
    run = ClaudeRun(hub, tmp_path, claude_model, extra_allow=FIXTURE_ALLOW)
    session = str(uuid.uuid4())
    run.start(prompt_4b(run_dir), session)
    try:
        busy = start_when_busy(
            run, owner, run_dir,
            lambda: frame_has(owner, "canvas-markdown") and hub.listening(session),
        )  # fmt: skip
        assert busy, run.report()
        send_note(owner, "Code word is HERON-2093, please say it back.")
        [event] = wait_events(owner, hub, session, 1)
        still_busy = alive(run_dir / "pid")
        final = wait_reply(owner, run, session, ("HERON-2093",), 120)
    finally:
        run.finish(5)
    print(run.report(), f"\nSTILL BUSY AT DELIVERY: {still_busy}")
    assert_no_denials(run)
    created, delivered = event_times(hub, session, event["id"])
    assert delivery_routes(hub, session).get(event["id"]) == "watch"
    assert (delivered - created).total_seconds() <= 1.0, (created, delivered)
    assert "HERON-2093" in final, final


# ---- Scenario 5 -----------------------------------------------------------------


def prompt_5(label: str, button: str) -> str:
    """Prompt of scenario 5 for one of the two sessions."""
    return f"""{GUIDE} Show me a page with a canvas-markdown block with the heading \
"{label}" and a canvas-buttons block (data-canvas-id "pick") with one button \
labelled "{label} button" and id "{button}". Wait for my button press (with ask \
--block pick, or watch), then reply with exactly one line: `GOT: <button id>`."""


def test_e2e_scenario_5_claude_two_sessions_one_project(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    specs = [("Cedar", "cedar"), ("Maple", "maple")]
    runs, sessions = [], []
    for label, button in specs:
        run = ClaudeRun(hub, tmp_path, claude_model, name=f"s5-{button}")
        sessions.append(str(uuid.uuid4()))
        run.start(prompt_5(label, button), sessions[-1])
        runs.append(run)
    try:
        for run, sid in zip(runs, sessions):
            tab = owner.page.locator(f'.tab[data-session="{sid}"]')
            assert wait_for(run, owner, lambda tab=tab: tab.count() == 1, 200), (
                run.report()
            )
        groups = owner.page.locator(".group").count()
        in_one_group = owner.page.locator(
            f'.group:has(.tab[data-session="{sessions[0]}"]):'
            f'has(.tab[data-session="{sessions[1]}"])'
        ).count()
        for (label, button), run, sid in zip(specs, runs, sessions):
            owner.page.locator(f'.tab[data-session="{sid}"] .tab-main').click()
            ready = lambda label=label: frame_has(owner, f"text={label}")  # noqa: E731
            assert wait_for(run, owner, ready, 150), run.report()
            assert frame_has(owner, "canvas-buttons button")
            # CLI-06: an ask waits for the *next* event, so press once it waits.
            assert wait_listening(owner, run, sid, 150), run.report()
            owner.frame.locator("canvas-buttons button").first.click()
        finals = [
            wait_reply(owner, run, sid, ("GOT:",), 120)
            for run, sid in zip(runs, sessions)
        ]
    finally:
        for run in runs:
            run.finish(5)
    for run in runs:
        print(run.report())
    for run in runs:
        assert_no_denials(run)
    assert (groups, in_one_group) == (1, 1), (groups, in_one_group)
    for (label, button), other, sid, final in zip(
        specs, reversed(specs), sessions, finals
    ):
        events = [e for e in session_events(hub, sid) if e["kind"] == "button"]
        assert [e["value"] for e in events] == [button], events
        page = (hub.project_dir / hub.project_dir_name / sid / "page.html").read_text()
        assert label in page and other[0] not in page, sid
        assert f"GOT: {button}" in final and other[1] not in final, final
