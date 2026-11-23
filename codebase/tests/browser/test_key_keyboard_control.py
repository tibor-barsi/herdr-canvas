"""Keyboard control of the window and the home view (KEY-01 to KEY-04, D-60)."""

# ruff: noqa: E501  (long page-side scripts)

from __future__ import annotations

import pytest

from .support import owner_field

pytestmark = pytest.mark.browser

ON_HOME = "document.body.classList.contains('home')"
DIALOG = "#key-help"


def press(owner, *keys: str) -> None:  # noqa: ANN001
    for key in keys:
        owner.page.keyboard.press(key)


def active(owner) -> str | None:  # noqa: ANN001
    return owner.page.evaluate("activeId")


# ---- KEY-01: H, [ and ] --------------------------------------------------------------


def test_key_01_keys_are_ignored_in_a_text_field_and_with_ctrl(make, owner) -> None:  # noqa: ANN001
    made = make("<input id=t><textarea id=a></textarea>")
    owner.visit(made.sid)
    owner.frame.wait_for_function("document.readyState === 'complete'")
    owner.frame.locator("#t").click()
    press(owner, "h", "[", "]", "?")
    assert owner.frame.evaluate("document.getElementById('t').value") == "h[]?"
    owner_field(owner.page)
    owner.page.locator("#owner-field").click()
    press(owner, "h", "[", "]", "?")
    assert owner.page.locator("#owner-field").input_value() == "h[]?"
    assert active(owner) == made.sid
    assert owner.page.locator(DIALOG).count() == 0
    owner.page.locator("#owner-field").blur()
    press(owner, "Control+h")
    assert active(owner) == made.sid


# ---- KEY-03: ? ---------------------------------------------------------------------------


def test_key_03_question_mark_closes_the_dialog_and_other_keys_wait(
    make, owner
) -> None:  # noqa: ANN001
    made = make("<p>x</p>")
    owner.visit(made.sid)
    owner_field(owner.page)
    owner.page.locator("#owner-field").click()
    owner.page.locator("#owner-field").blur()
    press(owner, "?")
    owner.page.locator(DIALOG).wait_for()
    press(owner, "h")
    assert active(owner) == made.sid
    press(owner, "?")
    assert owner.page.locator(DIALOG).count() == 0
    assert active(owner) == made.sid


def test_key_03_it_opens_from_inside_the_frame_and_gives_the_focus_back(
    make, owner
) -> None:  # noqa: ANN001
    made = make("<p>x</p>")
    owner.visit(made.sid)
    owner.frame.wait_for_function("document.readyState === 'complete'")
    owner.frame.locator("body").click()
    press(owner, "?")
    owner.page.locator(DIALOG).wait_for()
    press(owner, "Escape")
    assert owner.page.locator(DIALOG).count() == 0
    assert owner.page.evaluate("document.activeElement.id") == "frame"


# ---- no clash with the comment keys ---------------------------------------------------------
