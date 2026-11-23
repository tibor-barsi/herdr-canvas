"""One key map, the owner's key file and the vim profile (KMAP-01 to KMAP-04, D-64, D-65)."""

# ruff: noqa: E501

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .test_key_keyboard_control import (
    DIALOG,
    active,
    press,
)

pytestmark = pytest.mark.browser


def write_keys(owner, text: str) -> None:  # noqa: ANN001
    (Path(os.environ["AGENT_CANVAS_CONFIG_DIR"]) / "keys.toml").write_text(text)
    owner.page.reload()
    owner.page.wait_for_function("typeof keyMap !== 'undefined'")
    owner.page.wait_for_timeout(300)


def two_tabs(make, owner) -> tuple:  # noqa: ANN001
    first = make("<p>one</p>", name="alpha")
    second = make("<p>two</p>", name="beta")
    owner.visit(first.sid)
    return first, second


def help_text(owner) -> str:  # noqa: ANN001
    press(owner, "?")
    owner.page.locator(DIALOG).wait_for()
    text = owner.page.locator(DIALOG).inner_text()
    press(owner, "Escape")
    return text


def test_kmap_02_a_user_key_replaces_the_default_and_the_overview_shows_it(
    make, owner
) -> None:  # noqa: ANN001
    first, second = two_tabs(make, owner)
    write_keys(owner, '[keys]\n"tab.next" = "n"\n')
    owner.visit(first.sid)
    press(owner, "n")
    owner.page.wait_for_function("(id) => activeId !== id", arg=first.sid)
    assert active(owner) != first.sid
    owner.visit(first.sid)
    press(owner, "]")
    owner.page.wait_for_timeout(300)
    assert active(owner) == first.sid
    text = help_text(owner)
    assert "next tab" in text and "\nn" in text.replace("\t", "\n")


def test_kmap_03_a_rebound_key_is_forwarded_from_inside_the_frame(make, owner) -> None:  # noqa: ANN001
    first, second = two_tabs(make, owner)
    write_keys(owner, '[keys]\n"tab.next" = "n"\n')
    owner.visit(first.sid)
    owner.page.wait_for_timeout(500)
    owner.frame.locator("body").click()
    owner.frame.page.keyboard.press("]")
    owner.page.wait_for_timeout(300)
    assert active(owner) == first.sid
    owner.frame.page.keyboard.press("n")
    owner.page.wait_for_function("(id) => activeId !== id", arg=first.sid)


def test_kmap_04_in_comment_mode_the_vim_l_is_the_lasso(make, owner) -> None:  # noqa: ANN001
    first, second = two_tabs(make, owner)
    write_keys(owner, 'profile = "vim"\n')
    owner.visit(first.sid)
    owner.frame.wait_for_function("window.agentCanvas !== undefined")
    press(owner, "c")
    press(owner, "L")
    owner.frame.wait_for_function(
        "document.documentElement.getAttribute('data-ac-commenting') === 'lasso'"
    )
    assert active(owner) == first.sid
