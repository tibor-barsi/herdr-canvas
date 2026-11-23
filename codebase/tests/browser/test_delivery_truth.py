# ruff: noqa: E501
"""What the owner sees of delivery: the floating delivery messages, an ended session, card answers
that need no send, and the question badge of a waiting page card (FB-05, FB-10, ANS-08,
SES-16).

Real hub, real owner window (headless). The agent side is played through the hub's API.
"""

from __future__ import annotations

import json

import pytest
from websockets.sync.client import connect

from .support import SCROLL_PAGE, block, call
from .test_ask_point_fields import click_data
from .test_com_10_multi_page import go_to, open_other_page
from .test_comment_layer import comment_mode, wait_saved, write_comment
from .test_heavy_blocks import plot_config, wait_plot

pytestmark = pytest.mark.browser

TOAST = "#send-toast"
SENT = "Sent \u2014 agent will read it next turn"
READ = "Read by the agent"
SENT_ENDED = "Sent \u2014 but the session has ended"
TABLE = {"columns": ["name"], "rows": [["a"], ["b"]], "key": "name", "select": "single"}
ENDED = "This session has ended: answers are kept, but no agent will read them"
ASK = {"question": "Keep layout A?", "form": "one", "options": ["keep", "change"]}
CHOICES = {
    "mode": "single",
    "options": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
    "submit": "Use",
}


def wait_toast(page, text: str) -> None:  # noqa: ANN001
    page.wait_for_function(
        "(t) => { const e = document.querySelector('#send-toast');"
        " return e.classList.contains('visible') && e.textContent === t; }",
        arg=text,
    )


def toast_text(page) -> str:  # noqa: ANN001
    return page.inner_text(TOAST).strip()


def send_now(studio) -> None:  # noqa: ANN001
    studio.queue_action()
    studio.page.click("#send-button")
    studio.page.wait_for_function(
        "window.__shell.draftOf(window.__shell.activeTab().id).actions.length === 0"
    )


def cards_page(extra: str = "") -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        "<button id='b'>plain</button>"
        + block("canvas-ask", "q1", ASK)
        + extra
        + "</body></html>"
    )


def wait_card(owner, card_id: str = "q1") -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "(id) => { const e = document.querySelector(`[data-canvas-id=${id}]`);"
        " return e && e.renderIdle && e.shadowRoot && e.shadowRoot.querySelector('.k, .options, .line'); }",
        arg=card_id,
    )


def answer_card(owner) -> None:  # noqa: ANN001
    owner.frame.locator("[data-canvas-id=q1] .opt[data-id=keep]").click()
    owner.frame.locator("[data-canvas-id=q1] button.submit").click()
    owner.frame.wait_for_function(
        "() => document.querySelector('[data-canvas-id=q1]').shadowRoot.querySelector('.said')"
    )


# ---- FB-10: the floating delivery messages --------------------------------------------


def test_fb_10_a_send_says_sent_then_read_and_a_reload_does_not_repeat_the_read(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    send_now(studio)
    wait_toast(studio.page, SENT)
    call(studio.owner, "POST", f"/api/sessions/{sid}/pending", json={})
    wait_toast(studio.page, READ)
    studio.page.reload()
    studio.owner.visit(sid)
    studio.page.wait_for_timeout(700)
    assert studio.page.evaluate("document.querySelector('#send-toast').textContent") != READ
    send_now(studio)
    wait_toast(studio.page, SENT)


def test_fb_10_delivery_by_a_watch_and_by_the_prompt_hook_reads_the_send(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    hub = studio.owner.hub
    url = f"ws://127.0.0.1:{hub.port}/api/sessions/{sid}/watch"
    with connect(url, additional_headers={"X-Agent-Canvas-Key": hub.key}) as watch:
        studio.page.wait_for_function("activeTab()?.listening === true")
        send_now(studio)
        wait_toast(studio.page, SENT)
        event = json.loads(watch.recv(timeout=10))
        watch.send(json.dumps({"type": "ack", "id": event["id"]}))
        wait_toast(studio.page, READ)
    studio.page.wait_for_function("activeTab()?.listening === false")
    send_now(studio)
    wait_toast(studio.page, SENT)
    call(studio.owner, "POST", f"/api/sessions/{sid}/pending", json={"via": "hook"})
    wait_toast(studio.page, READ)


def test_fb_10_a_send_over_two_pages_is_read_only_when_both_parts_are_read(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    open_other_page(studio, sid)
    go_to(studio, "other.html")
    comment_mode(studio)
    write_comment(studio, (60, 60), (200, 160), "on the other page")
    wait_saved(studio, 1)
    go_to(studio, "page.html")
    studio.queue_action()
    studio.page.click("#send-button")
    first, second = studio.wait_events(sid, 2)
    wait_toast(studio.page, SENT)
    hub = studio.owner.hub
    hub.on_loop(lambda: hub.state.events.ack(sid, first["id"]))
    studio.page.wait_for_timeout(500)
    assert toast_text(studio.page) != READ  # one part read is not the send read
    hub.on_loop(lambda: hub.state.events.ack(sid, second["id"]))
    wait_toast(studio.page, READ)


def test_fb_10_a_send_to_an_ended_session_says_so(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    call(studio.owner, "POST", f"/api/sessions/{sid}/end", json={})
    studio.page.wait_for_function("activeTab()?.state === 'ended'")
    send_now(studio)
    wait_toast(studio.page, SENT_ENDED)


# ---- ANS-08: an ended session ------------------------------------------------------------


def test_ans_08_an_ended_session_says_so_in_the_bar_and_on_the_cards_and_still_keeps_answers(
    owner, make
) -> None:  # noqa: ANN001
    made = make(cards_page(block("canvas-choices", "c1", CHOICES)))
    wait_card(owner)
    assert (
        owner.frame.evaluate(
            "() => document.querySelector('[data-canvas-id=q1]').shadowRoot.querySelector('.ended')"
        )
        is None
    )
    call(owner, "POST", f"/api/sessions/{made.sid}/end", json={})
    for card_id in ("q1", "c1"):
        owner.frame.wait_for_function(
            "([id, t]) => document.querySelector(`[data-canvas-id=${id}]`).shadowRoot"
            ".querySelector('.ended')?.textContent === t",
            arg=[card_id, ENDED],
        )
    answer_card(owner)
    rows = call(owner, "GET", f"/api/sessions/{made.sid}/answers")["items"]
    assert [r["state"] for r in rows if r["id"] == "q1"] == ["answered"]


# ---- FB-05: answering a card needs no send -----------------------------------------------


def test_fb_05_answering_a_card_counts_no_action_and_leaves_send_off_but_a_page_click_does(
    owner, make
) -> None:  # noqa: ANN001
    made = make(cards_page(block("canvas-choices", "c1", CHOICES)))
    wait_card(owner)
    wait_card(owner, "c1")
    answer_card(owner)
    owner.frame.locator("[data-canvas-id=c1] .option[data-id=a]").click()
    owner.frame.locator("[data-canvas-id=c1] button.submit").click()
    made.wait_events(2)
    made.wait_action("click", 3)  # the clicks are kept as context for a send
    assert counted(owner, made.sid) == 0
    assert owner.page.is_hidden("#send-button")
    owner.frame.locator("#b").click()
    owner.page.wait_for_function("!document.getElementById('send-button').hidden")
    assert counted(owner, made.sid) == 1
    assert owner.page.is_enabled("#send-button")


def counted(owner, sid: str) -> int:  # noqa: ANN001
    """How many draft actions a send would count (not events, not card answers)."""
    return owner.page.evaluate(
        f"window.__drafts['{sid}'].actions.filter((a) => !a.event && !a.card).length"
    )


def all_counted(owner, made, kind: str) -> int:  # noqa: ANN001
    """Wait for the block's ``kind`` action; every action of the click counts."""
    made.wait_action(kind)
    owner.page.wait_for_timeout(300)  # the plain click of the same press, if any
    total = len(owner.page.evaluate(f"window.__drafts['{made.sid}'].actions"))
    assert counted(owner, made.sid) == total
    assert owner.page.is_enabled("#send-button")
    return total


def test_fb_05_a_plot_click_inside_an_ask_counts_and_answering_that_ask_does_not(
    owner, make
) -> None:  # noqa: ANN001
    made = make(
        "<!doctype html><body>"
        + block(
            "canvas-ask",
            "q1",
            ASK,
            extra=block("canvas-plot", "spectrum", plot_config()),
        )
        + "</body>"
    )
    wait_card(owner)
    wait_plot(owner)
    click_data(owner, 3, 35)
    total = all_counted(owner, made, "plot-click")
    answer_card(owner)
    owner.page.wait_for_timeout(300)
    assert counted(owner, made.sid) == total


def test_fb_05_a_table_selection_inside_an_ask_counts(owner, make) -> None:  # noqa: ANN001
    made = make(
        "<!doctype html><body>"
        + block("canvas-ask", "q1", ASK, extra=block("canvas-table", "t", TABLE))
        + "</body>"
    )
    wait_card(owner)
    owner.frame.locator("canvas-table tbody tr").nth(1).click()
    all_counted(owner, made, "select")


# ---- SES-16: a waiting page card badges its tab ----------------------------------------
