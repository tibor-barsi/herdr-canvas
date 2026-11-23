"""Replies, done and reopen in the window; live pushes; the hub's unsent count (P23.2).

RPL-04 and RPL-05 are owned here; R-16 is the hub-side unsent count.
"""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE, call
from .test_com_10_multi_page import go_to, open_other_page
from .test_comment_layer import comment_file, comment_mode, wait_saved, write_comment
from .test_comment_panel import filter_button

pytestmark = pytest.mark.browser


def sent_comments(studio, texts=("first", "second")) -> str:  # noqa: ANN001
    """A session with sent comments on page.html, comment mode on."""
    sid = studio.make(SCROLL_PAGE)
    comment_mode(studio)
    for index, text in enumerate(texts):
        left = 60 + 140 * index
        write_comment(studio, (left, 60), (left + 100, 160), text)
        wait_saved(studio, index + 1)
    studio.page.keyboard.press("Control+Enter")
    studio.wait_events(sid, 1)
    studio.page.wait_for_function(
        "[...document.querySelectorAll('#comment-panel .chip')]"
        ".every((c) => c.textContent !== 'draft')"
    )
    return sid


def agent(studio, sid: str, tail: str, **body) -> None:  # noqa: ANN001, ANN003
    call(
        studio.owner,
        "POST",
        f"/api/sessions/{sid}/comments/{tail}",
        json={"page": "page.html", **body},
    )


def stored(studio, number: int) -> dict:  # noqa: ANN001
    return next(c for c in comment_file(studio)["comments"] if c["n"] == number)


def entry(studio, number: int):  # noqa: ANN001, ANN201
    return studio.page.locator(f'#comment-panel .ent[data-n="{number}"]')


def test_rpl_05_reply_opens_a_field_enter_saves_an_unsent_owner_reply(studio) -> None:  # noqa: ANN001
    sid = sent_comments(studio)
    entry(studio, 1).locator("button", has_text="Reply").click()
    field = entry(studio, 1).locator(".rform textarea")
    assert field.evaluate("e => e === document.activeElement")
    field.type("line one")
    studio.page.keyboard.press("Shift+Enter")
    field.type("line two")
    assert stored(studio, 1)["replies"] == []  # Shift+Enter saved nothing
    studio.page.keyboard.press("Enter")
    studio.page.wait_for_selector(".rform", state="detached")
    [reply] = stored(studio, 1)["replies"]
    assert reply["text"] == "line one\nline two" and reply["from"] is None
    assert reply["sent"] is None  # a draft until the next send (COM-10)
    assert entry(studio, 1).locator(".rp.me .rt").inner_text() == "line one\nline two"
    assert entry(studio, 1).locator(".chip").inner_text() == "draft"
    studio.page.wait_for_function(
        "window.__shell.unsentComments().comments === 1"
    )
    studio.page.keyboard.press("Control+Enter")
    [_, second] = studio.wait_events(sid, 2)
    [carried] = second["comments"]
    assert [r["text"] for r in carried["replies"]] == ["line one\nline two"]
    assert carried["replies"][0]["sent"] == second["time"]


def test_rpl_05_escape_cancels_the_reply_and_keeps_comment_mode(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    entry(studio, 2).locator("button", has_text="Reply").click()
    entry(studio, 2).locator(".rform textarea").type("never mind")
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_selector(".rform", state="detached")
    assert stored(studio, 2)["replies"] == []
    assert studio.page.evaluate("document.body.classList.contains('commenting')")


def test_rpl_05_mark_done_and_reopen_buttons_change_the_comment(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    entry(studio, 1).locator("button", has_text="Mark done").click()
    studio.page.wait_for_selector('#comment-panel .ent[data-n="1"]', state="detached")
    assert stored(studio, 1)["done"]["by"] == "owner"
    assert filter_button(studio, "open").inner_text() == "Open 1"
    filter_button(studio, "done").click()
    assert entry(studio, 1).locator(".chip").inner_text() == "✓ done"
    assert entry(studio, 1).locator("button").all_inner_texts() == ["Reopen"]
    entry(studio, 1).locator("button", has_text="Reopen").click()
    studio.page.wait_for_selector('#comment-panel .ent[data-n="1"]', state="detached")
    after = stored(studio, 1)
    assert after["done"] is None and after["last_done"] is not None


def test_rpl_05_x_marks_the_selected_comment_done_and_x_again_reopens(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    studio.page.keyboard.press("x")  # nothing selected: nothing changes
    studio.page.wait_for_timeout(200)
    assert stored(studio, 1)["done"] is None and stored(studio, 2)["done"] is None
    filter_button(studio, "all").click()
    entry(studio, 2).click()
    studio.page.keyboard.press("x")
    studio.page.wait_for_function(
        "document.querySelector('#comment-panel .ent[data-n=\"2\"] .chip')"
        ".textContent === '✓ done'"
    )
    assert (
        stored(studio, 2)["done"]["by"] == "owner" and stored(studio, 1)["done"] is None
    )
    studio.page.keyboard.press("X")
    studio.page.wait_for_function(
        "document.querySelector('#comment-panel .ent[data-n=\"2\"] .chip')"
        ".textContent !== '✓ done'"
    )
    # A press during the first request is queued and shown at once.
    studio.page.wait_for_function("!commentOutbox.busy()")
    assert stored(studio, 2)["done"] is None


def test_rpl_05_x_with_focus_in_the_page_frame_marks_done_and_reopens(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    filter_button(studio, "all").click()
    entry(studio, 1).click()
    studio.frame.locator("#plain").focus()
    studio.page.keyboard.press("x")
    studio.page.wait_for_function(
        "document.querySelector('#comment-panel .ent[data-n=\"1\"] .chip')"
        ".textContent === '✓ done'"
    )
    assert stored(studio, 1)["done"]["by"] == "owner"
    studio.frame.locator("#plain").focus()
    studio.page.keyboard.press("x")
    studio.page.wait_for_function(
        "document.querySelector('#comment-panel .ent[data-n=\"1\"] .chip')"
        ".textContent !== '✓ done'"
    )
    assert stored(studio, 1)["done"] is None


def test_rpl_05_x_outside_comment_mode_marks_the_selected_comment_done(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    entry(studio, 1).click()
    comment_mode(studio, False)
    studio.frame.evaluate(
        "window.keysSeen = []; document.addEventListener('keydown', "
        "(e) => window.keysSeen.push(e.key))"
    )
    studio.frame.locator("#plain").focus()
    studio.page.keyboard.press("x")
    for _ in range(50):
        if stored(studio, 1)["done"] is not None:
            break
        studio.page.wait_for_timeout(100)
    assert studio.frame.evaluate("window.keysSeen") == ["x"]  # the page got its key
    assert stored(studio, 1)["done"] is not None


@pytest.mark.timing
def test_rpl_04_an_agent_reply_shows_within_a_second_unread_until_selected(
    studio,
) -> None:  # noqa: ANN001
    sid = sent_comments(studio)
    filter_button(studio, "all").click()
    agent(studio, sid, "reply", n=1, text="Fixed the unit.", **{"from": "claude-code"})
    entry(studio, 1).locator(".rp .rt", has_text="Fixed the unit.").wait_for(
        timeout=1000
    )
    chip = entry(studio, 1).locator(".chip")
    assert chip.inner_text() == "answered" and "unread" in chip.get_attribute("class")
    entry(studio, 1).click()
    studio.page.wait_for_function(
        "!document.querySelector('#comment-panel .ent[data-n=\"1\"] .chip')"
        ".classList.contains('unread')"
    )
    assert stored(studio, 1)["read"] is not None


def test_rpl_04_an_agent_done_shows_in_the_panel_without_a_reload(studio) -> None:  # noqa: ANN001
    sid = sent_comments(studio)
    agent(studio, sid, "done", n=[2])
    studio.page.wait_for_selector(
        '#comment-panel .ent[data-n="2"]', state="detached", timeout=1000
    )
    assert filter_button(studio, "done").inner_text() == "Done 1"


def test_rpl_04_typing_in_a_reply_field_survives_a_push(studio) -> None:  # noqa: ANN001
    sid = sent_comments(studio)
    entry(studio, 2).locator("button", has_text="Reply").click()
    field = entry(studio, 2).locator(".rform textarea")
    field.type("hello world")
    for _ in range(6):
        studio.page.keyboard.press("ArrowLeft")  # the caret stands after "hello"
    # A redraw that handed back a fresh field would put the caret at the end.
    studio.page.evaluate(
        "HTMLTextAreaElement.prototype.focus = function () {"
        " const v = this.value; this.value = ''; this.value = v;"
        " HTMLElement.prototype.focus.call(this); }; 0"
    )
    for target in (1, 2):  # a reply to another comment, then to the one being typed in
        agent(
            studio,
            sid,
            "reply",
            n=target,
            text=f"push {target}",
            **{"from": "claude-code"},
        )
        entry(studio, target).locator(".rp .rt", has_text=f"push {target}").wait_for(
            timeout=1000
        )
        state = studio.page.evaluate(
            "(() => { const f = document.activeElement;"
            " return [f.getAttribute('aria-label'), f.value,"
            " f.selectionStart, f.selectionEnd]; })()"
        )
        assert state == ["Reply to comment 2", "hello world", 5, 5]
    studio.page.keyboard.type("!")
    assert field.input_value() == "hello! world"


def test_rpl_04_an_agent_done_on_the_comment_being_typed_in_keeps_the_field(
    studio,
) -> None:  # noqa: ANN001
    sid = sent_comments(studio)
    entry(studio, 1).locator("button", has_text="Reply").click()
    studio.page.keyboard.type("half a reply")
    agent(
        studio, sid, "reply", n=1, text="closing", done=True, **{"from": "claude-code"}
    )
    entry(studio, 1).locator(".rp .rt", has_text="closing").wait_for(timeout=1000)
    state = studio.page.evaluate(
        "({active: document.activeElement.tagName,"
        " value: document.activeElement.value,"
        " n: document.querySelectorAll('#comment-panel .rform').length})"
    )
    assert state == {"active": "TEXTAREA", "value": "half a reply", "n": 1}
    filter_button(studio, "done").click()
    assert entry(studio, 1).locator(".rform textarea").input_value() == "half a reply"


def test_r_16_drafts_on_a_page_the_window_has_not_loaded_count_after_a_reload(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    open_other_page(studio, sid)
    go_to(studio, "other.html")
    comment_mode(studio)
    write_comment(studio, (60, 60), (200, 160), "on the other page")
    wait_saved(studio, 1)
    go_to(studio, "page.html")
    shown = {"project": str(studio.tmp_path / "alpha"), "name": "page.html"}
    call(studio.owner, "POST", f"/api/sessions/{sid}/show", json=shown)

    # After the reload the window never asks for other.html's comments (the file
    # list would), so only the hub's count can show its draft.
    def hold_other_page(ws) -> None:  # noqa: ANN001
        server = ws.connect_to_server()

        def forward(message) -> None:  # noqa: ANN001
            if '"comments-get"' in message and "other.html" in message:
                return
            server.send(message)

        ws.on_message(forward)

    studio.page.route_web_socket("**/ws/shell", hold_other_page)
    studio.page.reload()
    studio.page.wait_for_selector(f'.hv-pill[data-session="{sid}"]')
    studio.owner.visit(sid)
    studio.page.wait_for_function(
        "window.__shell.unsentComments().comments === 1"
    )
    unsent = studio.page.evaluate("window.__shell.unsentComments()")
    assert unsent == {"comments": 1, "files": 1}
    assert not studio.page.is_disabled("#send-button")
