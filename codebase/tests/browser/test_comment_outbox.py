"""Offline outbox and unsaved state for comments (P23.3).

COM-16 is owned here; HUB-09 and SHELL-04 are the changed parts: comment changes
wait in the window's outbox while the hub is away, and the shell never reloads
over them or over text typed in a comment box or a reply field.
"""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE
from .test_comment_layer import comment_file, comment_mode, wait_saved, write_comment
from .test_comment_replies import entry, sent_comments, stored
from .test_shell_update import (
    BANNER,
    mark_document,
    same_document,
    update_hub,
    wait_for_reload,
)

pytestmark = pytest.mark.browser

COMMENT_ROUTE = "**/api/sessions/*/comments**"
TOO_MUCH = "Offline: too much waiting; wait for the canvas to reconnect"
FIRST = ((60, 60), (160, 160))
SECOND = ((200, 60), (300, 160))


def go_offline(studio) -> None:  # noqa: ANN001
    studio.owner.hub.stop()
    studio.page.wait_for_selector("#offline.visible")


def come_back(studio) -> None:  # noqa: ANN001
    studio.owner.hub.restart()
    studio.page.wait_for_selector("#offline.visible", state="hidden", timeout=15000)


def circles(studio) -> list[str]:  # noqa: ANN001
    return studio.page.locator("#comment-panel .ent .cn").all_inner_texts()


def waiting(studio):  # noqa: ANN001, ANN201
    return studio.page.locator("#comment-panel .ph .wait")


def texts(studio) -> list[str]:  # noqa: ANN001
    return [c["text"] for c in comment_file(studio)["comments"]]


def queued(studio) -> int:  # noqa: ANN001
    return studio.page.evaluate("window.__shell.outboxPending()")


def refusing(studio):  # noqa: ANN001, ANN201
    """Make the hub's comment routes answer 400 while ``state['on']`` is set."""
    state = {"on": False, "once": False}

    def handle(route) -> None:  # noqa: ANN001
        creates = route.request.url.endswith("/comments") or not state["once"]
        if state["on"] and route.request.method == "POST" and creates:
            state["on"] = not state["once"]
            route.fulfill(
                status=400, content_type="application/json",
                body='{"message": "The hub says no."}',
            )  # fmt: skip
        else:
            route.continue_()

    studio.page.route(COMMENT_ROUTE, handle)
    return state


def test_com_16_saves_wait_with_dots_and_get_the_next_numbers_in_order(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    go_offline(studio)
    write_comment(studio, *FIRST, "first offline")
    wait_saved(studio, 1)
    write_comment(studio, *SECOND, "second offline")
    wait_saved(studio, 2)
    assert circles(studio) == ["…", "…"]
    assert waiting(studio).inner_text() == "…"
    assert waiting(studio).get_attribute("title") == "Offline: 2 changes waiting"
    assert queued(studio) == 2  # HUB-09: the same outbox as button events
    assert texts(studio) == []
    come_back(studio)
    studio.page.wait_for_function(
        "[...document.querySelectorAll('#comment-panel .ent .cn')]"
        ".map((c) => c.textContent).join() === '1,2'"
    )
    assert [(c["n"], c["text"]) for c in comment_file(studio)["comments"]] == [
        (1, "first offline"), (2, "second offline"),
    ]  # fmt: skip
    assert waiting(studio).count() == 0 and queued(studio) == 0


def test_com_16_the_box_shows_dots_for_its_number_while_offline(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    go_offline(studio)
    from .test_comment_layer import drag

    drag(studio, *FIRST)
    studio.page.wait_for_selector(".cbox textarea")
    assert studio.page.locator(".cbox .h b").inner_text() == "#…"


def test_com_16_edits_replies_done_and_new_saves_are_applied_in_order(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    comment_mode(studio)
    go_offline(studio)
    entry(studio, 1).locator("button", has_text="Reply").click()
    studio.page.keyboard.type("r1")
    studio.page.keyboard.press("Enter")
    studio.page.wait_for_selector(".rform", state="detached")
    assert entry(studio, 1).locator(".rp.me .rt").inner_text() == "r1"
    entry(studio, 2).locator("button", has_text="Mark done").click()
    studio.page.wait_for_selector('#comment-panel .filters button:has-text("Done 1")')
    write_comment(studio, (400, 60), (500, 160), "third offline")
    wait_saved(studio, 2)
    entry(studio, 1).locator("button", has_text="Reply").click()
    studio.page.keyboard.type("r2")
    studio.page.keyboard.press("Enter")
    studio.page.wait_for_selector(".rform", state="detached")
    assert waiting(studio).get_attribute("title") == "Offline: 4 changes waiting"
    assert stored(studio, 2)["done"] is None
    come_back(studio)
    studio.page.wait_for_function("window.__shell.outboxPending() === 0")
    studio.page.wait_for_function(
        "document.querySelectorAll('#comment-panel .ent .cn').length === 2 "
        "&& !document.querySelector('#comment-panel .wait')"
    )
    assert [r["text"] for r in stored(studio, 1)["replies"]] == ["r1", "r2"]
    assert stored(studio, 2)["done"] is not None
    assert stored(studio, 3)["text"] == "third offline"


def test_com_16_a_save_past_the_cap_is_refused_with_the_notice(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    go_offline(studio)
    write_comment(studio, *FIRST, "fits")
    wait_saved(studio, 1)
    size = studio.page.evaluate("window.__shell.outboxBytes()")
    assert size > 0
    studio.page.evaluate(f"window.__outboxCapBytes = {size + size // 2}")
    write_comment(studio, *SECOND, "does not fit")
    studio.page.wait_for_function(
        "(t) => document.querySelector('.cbox .note')?.textContent === t", arg=TOO_MUCH
    )
    assert studio.page.input_value(".cbox textarea") == "does not fit"
    assert queued(studio) == 1
    studio.page.evaluate("window.__outboxCapBytes = undefined")
    come_back(studio)
    studio.page.wait_for_function("window.__shell.outboxPending() === 0")
    assert texts(studio) == ["fits"]


def test_com_16_a_queued_change_the_hub_refuses_is_dropped_with_a_notice(
    studio,
) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    refuse = refusing(studio)
    go_offline(studio)
    write_comment(studio, *FIRST, "will be refused")
    wait_saved(studio, 1)
    write_comment(studio, *SECOND, "will be kept")
    wait_saved(studio, 2)
    studio.page.evaluate(
        "window.__notes = []; const shown = showNotice;"
        " showNotice = (text) => { window.__notes.push(text); shown(text); }"
    )  # the frame's heartbeat hides the notice again, so record it
    refuse["on"] = refuse["once"] = True  # only the first request is refused
    studio.owner.hub.restart()
    studio.page.wait_for_function("window.__shell.outboxPending() === 0", timeout=20000)
    assert [n for n in studio.page.evaluate("window.__notes") if n] == [
        "The hub says no."
    ]
    assert texts(studio) == ["will be kept"]


def test_com_16_a_refused_save_keeps_the_typed_text_in_new_and_edit_boxes(
    studio,
) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    refuse = refusing(studio)
    refuse["on"] = True
    write_comment(studio, *FIRST, "typed with care")
    studio.page.wait_for_function(
        "document.querySelector('.cbox .note')?.textContent === 'The hub says no.'"
    )
    assert studio.page.input_value(".cbox textarea") == "typed with care"
    assert queued(studio) == 0 and waiting(studio).count() == 0
    refuse["on"] = False
    studio.page.press(".cbox textarea", "Enter")
    wait_saved(studio, 1)
    assert texts(studio) == ["typed with care"]
    entry(studio, 1).locator("button", has_text="Edit").click()
    refuse["on"] = True
    studio.page.fill(".cbox textarea", "edited with care")
    studio.page.press(".cbox textarea", "Enter")
    studio.page.wait_for_function(
        "document.querySelector('.cbox .note')?.textContent === 'The hub says no.'"
    )
    assert studio.page.input_value(".cbox textarea") == "edited with care"
    assert texts(studio) == ["typed with care"]


def test_com_16_a_refused_reply_keeps_the_typed_text(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    refuse = refusing(studio)
    entry(studio, 1).locator("button", has_text="Reply").click()
    refuse["on"] = True
    studio.page.keyboard.type("careful reply")
    studio.page.keyboard.press("Enter")
    studio.page.wait_for_function(
        "document.querySelector('.rform .note')?.textContent === 'The hub says no.'"
    )
    assert entry(studio, 1).locator(".rform textarea").input_value() == "careful reply"
    assert stored(studio, 1)["replies"] == []


def test_shell_04_a_update_while_changes_wait_does_not_reload_the_shell(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    go_offline(studio)
    write_comment(studio, *FIRST, "waiting")
    wait_saved(studio, 1)
    mark_document(studio.page)
    studio.page.evaluate("window.shellUpdate.onHello({build: 'build-after-update'})")
    studio.page.wait_for_selector(BANNER, state="visible")
    studio.page.wait_for_timeout(500)
    assert same_document(studio.page) and queued(studio) == 1


def test_shell_04_text_in_a_comment_box_keeps_the_shell(studio) -> None:  # noqa: ANN001
    from .test_comment_layer import drag

    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    drag(studio, *FIRST)
    studio.page.fill(".cbox textarea", "half a thought")
    mark_document(studio.page)
    update_hub(studio)
    studio.page.wait_for_selector(BANNER, state="visible", timeout=20000)
    studio.page.wait_for_timeout(1500)
    assert same_document(studio.page)
    assert studio.page.input_value(".cbox textarea") == "half a thought"


def test_shell_04_text_in_a_reply_field_keeps_the_shell(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    entry(studio, 1).locator("button", has_text="Reply").click()
    studio.page.keyboard.type("half a reply")
    mark_document(studio.page)
    update_hub(studio)
    studio.page.wait_for_selector(BANNER, state="visible", timeout=20000)
    studio.page.wait_for_timeout(1500)
    assert same_document(studio.page)
    assert entry(studio, 1).locator(".rform textarea").input_value() == "half a reply"


def test_shell_04_empty_comment_box_and_saved_comments_do_not_keep_the_shell(
    studio,
) -> None:  # noqa: ANN001
    from .test_comment_layer import drag

    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    write_comment(studio, *FIRST, "saved already")
    wait_saved(studio, 1)
    drag(studio, *SECOND)
    studio.page.wait_for_selector(".cbox textarea")
    mark_document(studio.page)
    update_hub(studio)
    wait_for_reload(studio)
    assert not same_document(studio.page)
    studio.page.wait_for_selector("#comment-panel .ent .tx")
    assert (
        studio.page.locator("#comment-panel .ent .tx").inner_text() == "saved already"
    )


def hold_edits(studio):  # noqa: ANN001, ANN201
    """Hold every edit request of the window; the test answers them one by one."""
    held, done = [], []

    def handle(route) -> None:  # noqa: ANN001
        if route.request.method != "POST" or not route.request.url.endswith("/edit"):
            return route.continue_()
        body = route.request.post_data_json
        if len(held) < state["hold"]:
            return held.append(route)
        done.append("reply" if "reply" in body else "done")
        route.continue_()

    state = {"hold": 0}
    studio.page.route("**/api/sessions/*/comments/edit", handle)
    return state, held, done


def lose_answer_once(studio) -> None:  # noqa: ANN001
    """The hub stores the first reply; the answer never reaches the window."""
    lost = []

    def handle(route) -> None:  # noqa: ANN001
        if route.request.method == "POST" and not lost:
            lost.append(1)
            route.fetch()
            return route.abort()
        route.continue_()

    studio.page.route("**/api/sessions/*/comments/edit", handle)
    return lost


def wait_until(studio, ready) -> None:  # noqa: ANN001
    for _ in range(100):
        if ready():
            return
        studio.page.wait_for_timeout(50)
    raise AssertionError("the window did not send the request")


def reply_in_window(studio, number: int, text: str) -> None:  # noqa: ANN001
    entry(studio, number).locator("button", has_text="Reply").click()
    studio.page.keyboard.type(text)
    studio.page.keyboard.press("Enter")


def test_com_16_a_reply_whose_answer_was_lost_is_applied_once_after_a_restart(
    studio,
) -> None:  # noqa: ANN001
    sent_comments(studio)
    lose_answer_once(studio)
    reply_in_window(studio, 1, "once")
    studio.page.wait_for_timeout(3500)
    studio.owner.hub.restart()
    studio.page.wait_for_function("window.__shell.outboxPending() === 0", timeout=20000)
    assert [r["text"] for r in stored(studio, 1)["replies"]] == ["once"]


def test_com_16_a_failed_request_is_retried_while_the_connection_stays_up(
    studio,
) -> None:  # noqa: ANN001
    sent_comments(studio)
    lost = lose_answer_once(studio)
    reply_in_window(studio, 1, "once")
    wait_until(studio, lambda: lost)
    studio.page.wait_for_timeout(300)  # the window has queued the reply by now
    studio.page.wait_for_function("window.__shell.outboxPending() === 0", timeout=8000)
    assert studio.page.locator("#offline.visible").count() == 0
    assert [r["text"] for r in stored(studio, 1)["replies"]] == ["once"]


def test_com_16_two_quick_changes_keep_their_order_when_the_first_fails(
    studio,
) -> None:  # noqa: ANN001
    sent_comments(studio)
    state, held, done = hold_edits(studio)
    state["hold"] = 1
    reply_in_window(studio, 1, "r1")
    wait_until(studio, lambda: held)
    entry(studio, 2).locator("button", has_text="Mark done").click()
    studio.page.wait_for_timeout(300)
    held[0].abort()
    studio.page.wait_for_function("window.__shell.outboxPending() === 0", timeout=8000)
    assert done == ["reply", "done"]


def test_com_16_send_stays_disabled_while_changes_wait_and_flush(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    write_comment(studio, *FIRST, "saved draft")
    wait_saved(studio, 1)
    assert not studio.page.is_disabled("#send-button")
    held = start_waiting_change(studio, SECOND, 2)
    assert len(held) == 1
    assert studio.page.is_disabled("#send-button")
    held[0].continue_()
    studio.page.wait_for_function("window.__shell.outboxPending() === 0")
    studio.page.wait_for_function("!document.querySelector('#send-button').disabled")


def start_waiting_change(studio, shape=FIRST, count: int = 1):  # noqa: ANN001, ANN201
    """One change waits in the outbox with the hub up (its request is held)."""
    comment_mode(studio)
    go_offline(studio)
    write_comment(studio, *shape, "waiting")
    wait_saved(studio, count)
    held = []

    def hold_creates(route) -> None:  # noqa: ANN001
        if route.request.method == "POST":
            held.append(route)
        else:
            route.continue_()

    studio.page.route("**/api/sessions/*/comments", hold_creates)
    come_back(studio)
    studio.page.wait_for_function("window.__shell.outboxPending() === 1")
    return held


def test_shell_04_reload_in_the_banner_asks_first_when_changes_wait(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    start_waiting_change(studio)
    dialogs = []
    studio.page.on("dialog", lambda dialog: (dialogs.append(dialog), dialog.dismiss()))
    mark_document(studio.page)
    studio.page.evaluate("window.shellUpdate.onHello({build: 'build-after-update'})")
    studio.page.wait_for_selector(BANNER, state="visible")
    studio.page.click("#update-reload")
    assert "1 change" in studio.page.inner_text(BANNER)
    studio.page.wait_for_timeout(500)
    assert same_document(studio.page) and queued(studio) == 1
    studio.page.click("#update-cancel")
    assert "agent-canvas was updated" in studio.page.inner_text(BANNER)
    studio.page.click("#update-reload")
    studio.page.click("#update-reload")  # "Reload anyway"
    studio.page.wait_for_function("window.__same_document !== true", timeout=20000)
    assert dialogs == []
