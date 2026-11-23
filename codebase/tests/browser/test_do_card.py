# ruff: noqa: E501, F811
"""The Do card: steps, Copy through the shell, answers, secret steps (DO-01..DO-04).

Also the offline outbox for card answers (HUB-09).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from .support import block
from .test_look_window import headless, look  # noqa: F401

pytestmark = pytest.mark.browser

LONG_SECRET = "a" * 40
DO = {
    "title": "Re-seat the plug",
    "why": "The heater drops out.",
    "where": "work, ~/project",
    "time": "5 min",
    "risk": ["Mains voltage"],
    "steps": [
        {"text": "Switch off", "expect": "LED dark"},
        {"text": "Run the check", "run": "uv run check\n--port 1", "if_not": "Tell me"},
        {"text": "Enter the password", "secret": True},
    ],
}
RUN_LINE = "uv run check\n--port 1"


def page(config: dict = DO) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        + block("canvas-do", "w1", config)
        + "</body></html>"
    )


def wait_card(owner) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "(() => { const e = document.querySelector('canvas-do');"
        " return e && e.renderIdle && e.shadowRoot.querySelector('.k, .block-error'); })()"
    )


def card(owner, selector: str):  # noqa: ANN001, ANN201
    return owner.frame.locator(f"canvas-do {selector}")


def words(owner) -> str:  # noqa: ANN001
    return card(owner, ".kt").inner_text()


def wait_words(owner, start: str) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "(s) => document.querySelector('canvas-do').shadowRoot"
        ".querySelector('.kt').textContent.startsWith(s)",
        arg=start,
    )


def todo_events(made) -> list[dict]:  # noqa: ANN001
    return [e for e in made.events if e["kind"] == "todo"]


@pytest.fixture
def made(owner, make):  # noqa: ANN001, ANN201
    owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    shown = make(page())
    wait_card(owner)
    return shown


def clipboard(owner) -> str:  # noqa: ANN001
    return owner.page.evaluate("navigator.clipboard.readText()")


def copy_requests(owner) -> list[str]:  # noqa: ANN001
    return owner.page.evaluate(
        "performance.getEntriesByType('resource').map((r) => r.name)"
        ".filter((n) => n.includes('/answers/copy'))"
    )


# ---- DO-01: what the card shows -------------------------------------------------------


def test_do_01_the_card_shows_numbered_steps_run_boxes_and_notes(owner, made) -> None:  # noqa: ANN001
    assert card(owner, ".steps > li").count() == 3
    text = card(owner, ".kb").inner_text()
    for part in ("Re-seat the plug", "Where: work, ~/project", "Time: 5 min", "Mains voltage",
                 "Expect: LED dark", "If not: Tell me"):  # fmt: skip
        assert part in text
    assert card(owner, ".cmd code").inner_text() == RUN_LINE
    assert card(owner, ".cmd button").count() == 1
    assert words(owner) == "waits for you"


def test_do_01_there_is_no_run_button_anywhere(owner, made) -> None:  # noqa: ANN001
    labels = card(owner, "button").all_inner_texts()
    assert sorted(labels) == ["Copy", "Done", "Later", "Problem…"]
    assert not [label for label in labels if "run" in label.lower()]


def test_do_01_a_run_without_where_shows_the_error_box(owner, make) -> None:  # noqa: ANN001
    make(page({k: v for k, v in DO.items() if k != "where"}))
    wait_card(owner)
    assert "needs `where`" in card(owner, ".block-error").inner_text()


def test_do_01_one_run_without_steps_is_one_step(owner, make) -> None:  # noqa: ANN001
    make(page({"title": "T", "where": "here", "run": "ls -l"}))
    wait_card(owner)
    assert card(owner, ".steps > li").count() == 1
    assert card(owner, ".cmd code").inner_text() == "ls -l"


def test_do_01_ticks_send_no_event_and_are_stored_and_shown_after_a_reload(
    owner, made
) -> None:  # noqa: ANN001
    card(owner, ".steps > li >> nth=0 >> input").check()
    card(owner, ".steps > li >> nth=1 >> input").check()
    stored = made.folder / ".answers" / "page.html.json"
    owner.page.wait_for_function("true")
    for _ in range(100):
        if stored.exists() and json.loads(stored.read_text())["items"]["w1"][
            "ticked"
        ] == [1, 2]:
            break
        owner.page.wait_for_timeout(50)
    assert json.loads(stored.read_text())["items"]["w1"]["ticked"] == [1, 2]
    assert made.events == []
    owner.page.reload()
    owner.visit(made.sid)
    wait_card(owner)
    owner.frame.wait_for_function(
        "document.querySelector('canvas-do').shadowRoot.querySelectorAll('input:checked').length === 2"
    )


# ---- DO-02: Copy ----------------------------------------------------------------------


def test_do_02_copy_puts_exactly_the_run_text_on_the_clipboard_and_notes_it(
    owner, made
) -> None:  # noqa: ANN001
    card(owner, ".cmd button").click()
    owner.page.wait_for_selector("#copied.visible")
    assert clipboard(owner) == RUN_LINE
    assert owner.page.inner_text("#copied") == "Copied: uv run check…"
    owner.page.wait_for_selector("#copied.visible", state="hidden", timeout=4000)


def test_do_02_without_clipboard_permission_the_text_is_offered_to_select(
    owner, make
) -> None:  # noqa: ANN001
    make(page())
    wait_card(owner)
    card(owner, ".cmd button").click()
    field = owner.page.locator("#copied textarea")
    field.wait_for()
    assert field.input_value() == RUN_LINE
    assert "Copied" not in owner.page.inner_text("#copied")


@pytest.mark.parametrize(
    "forged",
    [
        {"type": "copy", "id": "w1", "step": 1},  # a step with no run
        {"type": "copy", "id": "w1", "step": 99},
        {"type": "copy", "id": "w1", "step": "2"},
        {"type": "copy", "id": "nope", "step": 2},
        {"type": "copy", "id": "w1", "step": 2, "text": "rm -rf /"},
        {"type": "copy", "text": "rm -rf /"},
    ],
)
def test_do_02_a_forged_copy_message_copies_nothing_of_the_frames_choosing(
    owner,
    made,
    forged,  # noqa: ANN001
) -> None:
    owner.page.evaluate("navigator.clipboard.writeText('before')")
    owner.page.evaluate("(m) => privateMessage(m)", forged)
    owner.page.wait_for_timeout(800)
    # Playwright's evaluate counts as a click, so a real step 2 still copies here.
    expected = (
        RUN_LINE if forged.get("step") == 2 and forged.get("id") == "w1" else "before"
    )
    assert clipboard(owner) == expected
    assert "rm -rf" not in clipboard(owner)


def test_do_02_a_copy_of_a_real_step_long_after_the_last_click_copies_nothing(
    owner, made
) -> None:  # noqa: ANN001
    owner.page.evaluate("navigator.clipboard.writeText('before')")
    owner.page.evaluate(
        "setTimeout(() => privateMessage({type: 'copy', id: 'w1', step: 2}), 6000)"
    )
    owner.page.wait_for_timeout(6800)  # the click-like evaluate wears off after 5 s
    assert clipboard(owner) == "before"
    assert copy_requests(owner) == []


def test_do_02_the_text_comes_from_the_file_not_the_pages_dom(owner, made) -> None:  # noqa: ANN001
    owner.frame.evaluate(
        "document.querySelector('canvas-do').shadowRoot.querySelector('.cmd code')"
        ".textContent = 'rm -rf /'"
    )
    card(owner, ".cmd button").click()
    owner.page.wait_for_selector("#copied.visible")
    assert clipboard(owner) == RUN_LINE


def test_do_02_two_copies_within_a_second_make_one_request(owner, made) -> None:  # noqa: ANN001
    button = card(owner, ".cmd button")
    button.click()
    button.click()
    owner.page.wait_for_selector("#copied.visible")
    owner.page.wait_for_timeout(300)
    assert len(copy_requests(owner)) == 1
    owner.page.wait_for_timeout(1000)
    button.click()
    owner.page.wait_for_function(
        "performance.getEntriesByType('resource').filter((r) => r.name.includes('/answers/copy')).length === 2"
    )


# ---- DO-03: Done, Problem, Later ------------------------------------------------------


def test_do_03_done_sends_a_todo_event_with_the_ticked_steps_and_shows_the_receipt(
    owner, made
) -> None:  # noqa: ANN001
    card(owner, ".steps > li >> nth=0 >> input").check()
    card(owner, "button:text-is('Done')").click()
    [event] = made.wait_events(1)
    assert event["kind"] == "todo"
    assert event["value"]["status"] == "done" and event["value"]["ticked"] == [1]
    wait_words(owner, "done ")
    assert "not read by the agent yet" in card(owner, ".answer").inner_text()
    assert card(owner, "button:text-is('Reopen')").count() == 1
    assert card(owner, ".k.pulse").count() == 0
    card(owner, "button:text-is('Reopen')").click()
    card(owner, "button:text-is('Done')").wait_for()


def test_do_03_problem_needs_a_note_and_sends_it(owner, made) -> None:  # noqa: ANN001
    card(owner, "button:text-is('Problem…')").click()
    card(owner, "button:text-is('Send')").click()
    assert "Say what went wrong" in card(owner, ".problem").inner_text()
    assert todo_events(made) == []
    card(owner, "textarea").fill("The plug is loose")
    card(owner, "button:text-is('Send')").click()
    [event] = made.wait_events(1)
    assert event["value"]["status"] == "problem"
    assert event["value"]["note"] == "The plug is loose"
    wait_words(owner, "problem reported ")
    assert card(owner, "button:text-is('Reopen')").count() == 0


def test_do_03_later_stops_the_pulse_and_sends_later(owner, made) -> None:  # noqa: ANN001
    assert card(owner, ".k.pulse").count() == 1
    card(owner, "button:text-is('Later')").click()
    [event] = made.wait_events(1)
    assert event["value"]["status"] == "later"
    wait_words(owner, "later")
    assert card(owner, ".k.pulse").count() == 0


# ---- DO-04: secret steps ---------------------------------------------------------------


def test_do_04_a_secret_step_says_to_type_it_yourself(owner, made) -> None:  # noqa: ANN001
    hints = card(owner, ".hint").all_inner_texts()
    assert hints == [
        "Type this in your terminal yourself; do not paste the output here."
    ]


@pytest.mark.parametrize(
    "secret",
    [
        "-----BEGIN PRIVATE KEY-----",
        "key sk-abc123",
        "ghp_abc",
        "AKIAIOSFODNN7",
        LONG_SECRET,
    ],
)
def test_do_04_key_like_text_in_a_problem_asks_before_it_is_sent(
    owner, made, secret: str
) -> None:  # noqa: ANN001
    card(owner, "button:text-is('Problem…')").click()
    card(owner, "textarea").fill(f"it failed with {secret}")
    card(owner, "button:text-is('Send')").click()
    card(owner, "button:text-is('Send anyway')").wait_for()
    assert "looks like a secret" in card(owner, ".problem").inner_text()
    owner.page.wait_for_timeout(300)
    assert todo_events(made) == []
    card(owner, "button:text-is('Send anyway')").click()
    [event] = made.wait_events(1)
    assert secret in event["value"]["note"]


def test_do_04_ordinary_text_is_sent_without_a_warning(owner, made) -> None:  # noqa: ANN001
    card(owner, "button:text-is('Problem…')").click()
    card(owner, "textarea").fill("a task-force of 31 letters and digits: " + "ab " * 20)
    card(owner, "button:text-is('Send')").click()
    made.wait_events(1)


# ---- HUB-09: card answers wait in the outbox ----------------------------------------------


def test_hub_09_a_done_given_while_the_hub_is_away_is_sent_once_when_it_is_back(
    owner, made
) -> None:  # noqa: ANN001
    owner.hub.stop()
    owner.page.wait_for_selector("#offline.visible")
    card(owner, ".steps > li >> nth=0 >> input").check()
    card(owner, "button:text-is('Done')").click()
    owner.page.wait_for_function("window.__shell.outboxPending() === 2")
    assert words(owner) == "waits for you"
    owner.hub.restart()
    owner.page.wait_for_selector("#offline.visible", state="hidden", timeout=15000)
    owner.page.wait_for_function("window.__shell.outboxPending() === 0", timeout=20000)
    [event] = [e for e in made.wait_events(1) if e["kind"] == "todo"]
    assert event["value"]["status"] == "done" and event["value"]["ticked"] == [1]
    wait_words(owner, "done ")
    assert len(todo_events(made)) == 1


def test_hub_09_at_most_a_hundred_answers_wait(owner, made) -> None:  # noqa: ANN001
    owner.hub.stop()
    owner.page.wait_for_selector("#offline.visible")
    for _ in range(3):  # the shell takes at most 100 frame messages a second
        owner.frame.evaluate(
            "for (let i = 0; i < 35; i++)"
            " window.agentCanvas.tick(document.querySelector('canvas-do'), [1 + (i % 2)])"
        )
        owner.page.wait_for_timeout(1100)
    owner.page.wait_for_timeout(500)
    assert owner.page.evaluate("window.__shell.outboxPending()") == 100


# ---- the look ---------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_do_01_the_contrast_check_finds_nothing_in_either_mode(
    owner,
    make,
    headless,
    scheme: str,  # noqa: ANN001, F811
) -> None:
    made = make(page())
    wait_card(owner)
    result = look(owner, made.sid, width=900, height=900, scheme=scheme, full=True)
    assert result["scheme"] == scheme, result
    findings = result["audit"]["findings"]
    assert [f for f in findings if f["rule"] == "contrast"] == [], findings
    if os.environ.get("DO_LOOK_DIR"):
        target = Path(os.environ["DO_LOOK_DIR"])
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(result["png"], target / f"do-open-{scheme}.png")
