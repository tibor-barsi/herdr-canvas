"""Every mouse action of the comment panel and the comment gestures has a key (herdr-canvas keys)."""

# ruff: noqa: E501

from __future__ import annotations

import json

import pytest

from .test_comment_panel import record, show_comments

pytestmark = pytest.mark.browser

TEXT_PAGE = (
    "<!doctype html><html><body style='margin:0;font:30px/40px monospace;white-space:pre'>"
    + "".join("lorem ipsum dolor sit amet consectetur\n" for _ in range(40))
    + "</body></html>"
)
SELECTED = "() => document.querySelector('#comment-panel .ent.sel')?.dataset.n"


def press(owner, key: str) -> None:  # noqa: ANN001
    owner.page.keyboard.press(key)
    owner.page.wait_for_timeout(150)


@pytest.fixture
def panel(make, owner):  # noqa: ANN001, ANN201
    made = make("<p>page</p>")
    owner.page.wait_for_function("keyMap.current('comment.next').length > 0")
    tab = owner.page.evaluate("window.__shell.activeTab()")
    records = [record(1), record(2), record(3), record(4, "draft", sent=None)]
    show_comments(owner, tab["id"], records, tab["page"])
    owner.page.wait_for_selector("#comment-panel .ent")
    owner.edits = []

    def catch(route) -> None:  # noqa: ANN001
        owner.edits.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body="{}")

    owner.page.route("**/comments/edit", catch)
    return made


def test_keys_20_next_and_previous_comment_select_it_and_wrap(panel, owner) -> None:  # noqa: ANN001
    for key, expected in [("j", "1"), ("j", "2"), ("k", "1"), ("k", "4"), ("j", "1")]:
        press(owner, key)
        assert owner.page.evaluate(SELECTED) == expected, key


def test_keys_21_fold_fold_all_filter_and_collapse_have_keys(panel, owner) -> None:  # noqa: ANN001
    press(owner, "j")
    press(owner, "f")
    assert owner.page.locator("#comment-panel .ent.folded").count() == 1
    press(owner, "f")
    assert owner.page.locator("#comment-panel .ent.folded").count() == 0
    press(owner, "F")
    assert owner.page.locator("#comment-panel .ent.folded").count() == 4
    assert owner.page.locator("#comment-panel .foldall").inner_text() == "Unfold all"
    press(owner, "F")
    assert owner.page.locator("#comment-panel .ent.folded").count() == 0
    pressed = "() => document.querySelector('#comment-panel .filters [aria-pressed=true]').dataset.filter"
    seen = []
    for _ in range(3):
        press(owner, "v")
        seen.append(owner.page.evaluate(pressed))
    assert seen == ["done", "all", "open"]
    press(owner, "m")
    assert owner.page.evaluate(
        "document.getElementById('comment-panel').classList.contains('strip')"
    )
    press(owner, "m")
    assert not owner.page.evaluate(
        "document.getElementById('comment-panel').classList.contains('strip')"
    )


def test_keys_22_done_reopen_reply_edit_and_delete_have_keys(panel, owner) -> None:  # noqa: ANN001
    press(owner, "j")
    press(owner, "x")
    assert {"n": 1, "done": True}.items() <= owner.edits[-1].items()
    press(owner, "a")
    assert owner.page.locator("#comment-panel .rform textarea").count() == 1
    press(owner, "Escape")
    press(owner, "k")  # the draft, number 4
    assert owner.page.evaluate(SELECTED) == "4"
    press(owner, "e")
    assert owner.page.locator(".cbox textarea").count() == 1
    press(owner, "Escape")
    owner.page.locator("body").focus()
    press(owner, "Delete")
    assert {"n": 4, "delete": True}.items() <= owner.edits[-1].items()


def test_keys_23_the_panel_keys_work_from_inside_the_page_frame(panel, owner) -> None:  # noqa: ANN001
    owner.page.wait_for_timeout(500)
    owner.page.evaluate("document.getElementById('frame').focus()")
    press(owner, "j")
    assert owner.page.evaluate(SELECTED) == "1"
    press(owner, "j")
    assert owner.page.evaluate(SELECTED) == "2"


def test_keys_24_banner_buttons_and_the_file_chooser_have_keys(make, owner) -> None:  # noqa: ANN001
    make("<p>page</p>")
    owner.page.wait_for_function("keyMap.current('notice.reload').length > 0")
    owner.page.evaluate(
        "document.getElementById('changes-bar').classList.add('visible')"
    )
    owner.page.evaluate(
        "window.__dismissed = 0; document.getElementById('changes-dismiss').addEventListener('click', () => window.__dismissed++)"
    )
    press(owner, "Alt+d")
    assert owner.page.evaluate("window.__dismissed") == 1
    with owner.page.expect_file_chooser():
        press(owner, "Alt+o")
    owner.page.evaluate("document.getElementById('notice').classList.add('visible')")
    owner.page.evaluate(
        "window.__reloads = 0; document.getElementById('notice-reload').addEventListener('click', () => window.__reloads++)"
    )
    press(owner, "Alt+r")
    assert owner.page.evaluate("window.__reloads") == 1


def comment_mode_with(owner, kind: str) -> None:  # noqa: ANN001
    owner.page.wait_for_function("keyMap.current('comment.cursor').length > 0")
    owner.page.wait_for_timeout(400)
    press(owner, "c")
    owner.frame.wait_for_function(
        "document.documentElement.hasAttribute('data-ac-commenting')"
    )
    press(owner, kind)


def box_kind(owner) -> str:  # noqa: ANN001
    owner.page.wait_for_selector(".cbox textarea")
    return owner.page.locator(".cbox").inner_text()


@pytest.mark.parametrize(
    ("kind", "steps", "word"),
    [
        ("p", ["Enter", "Enter"], "Point"),
        (
            "r",
            ["Enter", "Enter", "Shift+ArrowRight", "Shift+ArrowDown", "Enter"],
            "Rectangle",
        ),
        (
            "l",
            [
                "Enter",
                "Enter",
                "Shift+ArrowRight",
                "Enter",
                "Shift+ArrowDown",
                "Enter",
                "Shift+Enter",
            ],
            "Lasso",
        ),
        (
            "t",
            [
                "Enter",
                "Enter",
                "ArrowRight",
                "ArrowRight",
                "ArrowRight",
                "ArrowRight",
                "ArrowRight",
                "Enter",
            ],
            "Text",
        ),
    ],
)
def test_keys_25_each_comment_kind_can_be_placed_with_the_keyboard(
    make, owner, kind, steps, word
) -> None:  # noqa: ANN001
    make(TEXT_PAGE)
    comment_mode_with(owner, kind)
    for step in steps:
        press(owner, step)
    assert word in box_kind(owner)
    press(owner, "Escape")  # closes the box
    owner.page.wait_for_selector(".cbox", state="detached")
    press(owner, "Escape")  # leaves comment mode
    owner.page.wait_for_function("!document.body.classList.contains('commenting')")


def test_keys_26_the_cursor_works_with_the_focus_in_the_page_frame_and_escape_cancels_it(
    make, owner
) -> None:  # noqa: ANN001
    make(TEXT_PAGE)
    comment_mode_with(owner, "r")
    owner.page.evaluate("document.getElementById('frame').focus()")
    for step in ["Enter", "Enter", "Shift+ArrowRight", "Shift+ArrowDown"]:
        press(owner, step)
    press(owner, "Escape")  # cancels the cursor, comment mode stays
    assert owner.page.evaluate("document.body.classList.contains('commenting')")
    press(owner, "Enter")  # a fresh cursor, not the old corner
    press(owner, "Enter")
    press(owner, "Shift+ArrowRight")
    press(owner, "Enter")
    assert (
        owner.page.locator(".cbox").count() == 0
    )  # a corner 50 px away only, so no square yet
    press(owner, "Shift+ArrowDown")
    press(owner, "Enter")
    assert "Rectangle" in box_kind(owner)
