# ruff: noqa: E501
"""Feedback sent with no action of the owner reaches the agent marked (SEC-09).

Playwright's own scripted calls (evaluate, waiting for a selector) count as a user
gesture for about 5 s, so each test waits that out before the step it checks.
"""

from __future__ import annotations

import pytest

from agent_canvas.hooks import closing_lines, format_events

from .support import block, call

pytestmark = pytest.mark.browser

GESTURE_SECONDS = 6
MARK = "sent by the page's script without an action by the owner"
PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'></head><body>"
    + block("canvas-buttons", "b1", {"buttons": [{"id": "go", "label": "Go"}]})
    + block(
        "canvas-do",
        "w1",
        {
            "title": "Plug it in",
            "steps": [{"text": "plug"}, {"text": "switch on"}],
            "where": "bench",
        },
    )
    + "<button id='real'>Real</button>"
    + "<script>window.forge = () => {"
    " window.agentCanvas.emit('forged', {x: 1});"
    " window.agentCanvas.answer(document.querySelector('canvas-do'), {status: 'done', ticked: []});"
    "};"
    " window.forgeTick = () => document.querySelector('canvas-do').toggle(2, true);"
    " window.forgeAction = () => window.agentCanvas.blockAction('select', document.querySelector('canvas-do'), 'forged');"
    "</script></body></html>"
)


def wait_cards(owner) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "() => [...document.querySelectorAll('canvas-buttons, canvas-do')]"
        ".every((e) => e.renderIdle && e.shadowRoot.querySelector('button'))"
    )


def center(locator) -> tuple[float, float]:  # noqa: ANN001
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def delivered(owner, made) -> str:  # noqa: ANN001
    """The text the prompt hook hands to the agent."""
    answer = call(
        owner, "POST", f"/api/sessions/{made.sid}/pending", json={"via": "hook"}
    )
    events = answer["events"]
    return "\n".join([format_events(events), *closing_lines(events, 0)])


def test_sec_09_an_emit_and_an_answer_with_no_gesture_reach_the_agent_marked_not_from_the_owner(
    owner, make
) -> None:  # noqa: ANN001
    made = make(PAGE)
    wait_cards(owner)
    owner.frame.evaluate(f"setTimeout(window.forge, {(GESTURE_SECONDS + 1) * 1000})")
    owner.page.wait_for_timeout((GESTURE_SECONDS + 2) * 1000)
    events = made.wait_events(2)
    assert sorted(e["kind"] for e in events) == ["custom", "todo"]
    assert all(MARK in e["not_from_owner"] for e in events)
    rows = call(owner, "GET", f"/api/sessions/{made.sid}/answers")["items"]
    [row] = [r for r in rows if r["id"] == "w1"]
    assert MARK in row["not_from_owner"]
    text = delivered(owner, made)
    event_lines = [
        line for line in text.splitlines() if "forged" in line or "todo w1" in line
    ]
    assert len(event_lines) == 2
    assert all(MARK in line and "not owner feedback" in line for line in event_lines)
    assert "Act on the answers" not in text


def test_sec_09_a_real_click_reads_as_owner_feedback(owner, make) -> None:  # noqa: ANN001
    made = make(PAGE)
    wait_cards(owner)
    go = center(owner.frame.locator("canvas-buttons button"))
    done = center(owner.frame.locator("canvas-do button:text-is('Done')"))
    owner.page.wait_for_timeout(GESTURE_SECONDS * 1000)
    owner.page.mouse.click(*go)
    made.wait_events(1)
    owner.page.wait_for_timeout(GESTURE_SECONDS * 1000)
    owner.page.mouse.click(*done)
    events = made.wait_events(2)
    assert sorted(e["kind"] for e in events) == ["button", "todo"]
    assert not any("not_from_owner" in e for e in events)
    text = delivered(owner, made)
    assert "page's script" not in text
    assert "Act on the answers" in text


def wait_kind(owner, made, kind: str) -> dict:  # noqa: ANN001
    for _ in range(1500):
        found = [e for e in made.events if e["kind"] == kind]
        if found:
            return found[0]
        owner.page.wait_for_timeout(20)
    raise AssertionError(f"no {kind} event in {made.events}")


def test_sec_09_a_tick_with_no_gesture_stays_marked_inside_the_owners_done(
    owner, make
) -> None:  # noqa: ANN001
    made = make(PAGE)
    wait_cards(owner)
    step_one = center(owner.frame.locator("canvas-do .steps > li >> nth=0 >> input"))
    done = center(owner.frame.locator("canvas-do button:text-is('Done')"))
    owner.frame.evaluate(
        f"setTimeout(window.forgeTick, {(GESTURE_SECONDS + 1) * 1000})"
    )
    owner.page.wait_for_timeout((GESTURE_SECONDS + 2) * 1000)
    owner.page.mouse.click(*step_one)
    owner.page.mouse.click(*done)
    event = wait_kind(owner, made, "todo")
    assert event["value"]["ticked"] == [1, 2]
    assert "not_from_owner" not in event
    mark = event["value"]["ticks_not_from_owner"]
    assert "step 2 ticked by the page's script without an action by the owner" in mark
    assert "step 1" not in mark and "steps" not in mark
    [line] = [line for line in delivered(owner, made).splitlines() if "todo w1" in line]
    assert mark in line


def test_sec_09_a_draft_action_with_no_gesture_is_marked_in_the_send(
    owner, make
) -> None:  # noqa: ANN001
    made = make(PAGE)
    wait_cards(owner)
    real = center(owner.frame.locator("#real"))
    owner.frame.evaluate(
        f"setTimeout(window.forgeAction, {(GESTURE_SECONDS + 1) * 1000})"
    )
    owner.page.wait_for_timeout((GESTURE_SECONDS + 2) * 1000)
    owner.page.mouse.click(*real)
    owner.page.wait_for_function(f"window.__drafts['{made.sid}'].actions.length === 2")
    owner.page.click("#send-button")
    event = wait_kind(owner, made, "send")
    forged, clicked = event["actions"]
    assert forged["kind"] == "select" and MARK in forged["not_from_owner"]
    assert clicked["kind"] == "click" and "not_from_owner" not in clicked
    lines = [line for line in delivered(owner, made).splitlines() if "action:" in line]
    assert len(lines) == 2
    assert MARK in lines[0] and "forged" in lines[0]
    assert "page's script" not in lines[1]
