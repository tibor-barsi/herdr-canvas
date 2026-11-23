# ruff: noqa: E501
"""The Options box with a submit button answers like a card (BLK-24, ANS-01 to ANS-03, #19).

Real hub, real owner window (headless). The agent side is played through the hub's API.
"""

from __future__ import annotations

import pytest

from .support import block, call
from .test_look_window import headless, look  # noqa: F401

pytestmark = pytest.mark.browser

OPTIONS = [
    {"id": "a", "title": "Group by part"},
    {"id": "b", "title": "Group by material"},
    {"id": "c", "title": "Group by date"},
]
SUBMIT = {"mode": "multi", "options": OPTIONS, "submit": "Use this grouping"}
LIVE = {"mode": "single", "options": OPTIONS}


def wait_ready(owner) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "() => { const e = document.querySelector('canvas-choices');"
        " return e && e.renderIdle && e.shadowRoot && e.shadowRoot.querySelector('.options, .line'); }"
    )


def inside(owner, selector: str) -> str:  # noqa: ANN001
    return owner.frame.evaluate(
        "(s) => { const n = document.querySelector('[data-canvas-id=c1]').shadowRoot.querySelector(s);"
        " return n ? n.textContent : null; }",
        selector,
    )


def pick(owner, option_id: str) -> None:  # noqa: ANN001
    owner.frame.locator("[data-canvas-id=c1]").locator(
        f".option[data-id={option_id}]"
    ).click()


def submit(owner) -> None:  # noqa: ANN001
    owner.frame.locator("[data-canvas-id=c1]").locator("button.submit").click()


def wait_line(owner) -> str:  # noqa: ANN001
    owner.frame.wait_for_function(
        "() => { const n = document.querySelector('[data-canvas-id=c1]').shadowRoot.querySelector('.said');"
        " return n && n.textContent.startsWith('Sent'); }"
    )
    return inside(owner, ".said")


@pytest.fixture
def chosen(owner, make):  # noqa: ANN001, ANN201
    made = make(block("canvas-choices", "c1", SUBMIT))
    wait_ready(owner)
    pick(owner, "a")
    pick(owner, "c")
    submit(owner)
    return made


def test_ans_07_submit_shows_the_sent_line_and_the_unread_receipt(
    owner, chosen
) -> None:  # noqa: ANN001
    said = wait_line(owner)
    assert said.startswith("Sent ") and said.endswith(": Group by part, Group by date")
    assert inside(owner, ".receipt") == "not read by the agent yet"
    assert inside(owner, ".link") == "Change"
    assert inside(owner, ".options") is None
    [event] = chosen.wait_events(1)
    assert event["kind"] == "choice" and event["value"] == ["a", "c"]


def test_ans_07_the_receipt_turns_to_read_once_the_event_is_delivered(
    owner, chosen
) -> None:  # noqa: ANN001
    wait_line(owner)
    call(owner, "POST", f"/api/sessions/{chosen.sid}/pending", json={})
    owner.frame.wait_for_function(
        "() => document.querySelector('[data-canvas-id=c1]').shadowRoot"
        ".querySelector('.receipt').textContent.startsWith('read by the agent')"
    )


def test_ans_07_after_a_reload_the_sent_line_is_still_shown(owner, chosen) -> None:  # noqa: ANN001
    said = wait_line(owner)
    owner.page.reload()
    owner.visit(chosen.sid)
    wait_ready(owner)
    assert wait_line(owner) == said
    assert inside(owner, ".receipt") == "not read by the agent yet"


def test_ans_07_change_reopens_the_choice_with_the_pick_kept_and_a_new_send_replaces_it(
    owner,
    chosen,  # noqa: ANN001
) -> None:
    wait_line(owner)
    owner.frame.locator("[data-canvas-id=c1]").locator("button.link").click()
    owner.frame.locator("[data-canvas-id=c1]").locator(
        ".option[aria-checked=true]"
    ).nth(1).wait_for()
    assert inside(owner, ".submit") == "Use this grouping"
    pick(owner, "c")
    submit(owner)
    owner.frame.wait_for_function(
        "() => document.querySelector('[data-canvas-id=c1]').shadowRoot"
        ".querySelector('.said')?.textContent.endsWith(': Group by part')"
    )
    assert len(chosen.wait_events(2)) == 2
    assert inside(owner, ".receipt") == "not read by the agent yet"


def test_ans_07_the_agent_listing_shows_the_answered_options_box(owner, chosen) -> None:  # noqa: ANN001
    wait_line(owner)
    rows = call(owner, "GET", f"/api/sessions/{chosen.sid}/answers")["items"]
    [row] = [r for r in rows if r["id"] == "c1"]
    assert (
        row["kind"] == "choices"
        and row["state"] == "answered"
        and row["answer"] == ["a", "c"]
    )
    assert (
        call(owner, "GET", f"/api/sessions/{chosen.sid}/answers?open=1")["items"] == []
    )


def test_ans_07_an_options_box_without_submit_stays_as_it_was(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-choices", "c1", LIVE))
    wait_ready(owner)
    pick(owner, "b")
    made.wait_action("select")
    assert inside(owner, ".said") is None and inside(owner, ".submit") is None
    assert call(owner, "GET", f"/api/sessions/{made.sid}/answers")["items"] == []
    assert made.events == []
