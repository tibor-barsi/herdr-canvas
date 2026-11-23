"""The ? overview chooses the profile and rebinds keys from the keyboard (herdr-canvas keys)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

HELP = "#key-help"
CURRENT = "() => document.querySelector('#key-help-current')?.dataset.action"
STATUS = "() => document.querySelector('#key-help-status').textContent"
ACTIVE = "() => activeId"


def config() -> Path:
    return Path(os.environ["AGENT_CANVAS_CONFIG_DIR"])


def key(owner, name: str) -> None:  # noqa: ANN001
    owner.page.keyboard.press(name)
    owner.page.wait_for_timeout(150)


def two(make, owner) -> tuple:  # noqa: ANN001
    first = make("<p>one</p>", name="alpha")
    second = make("<p>two</p>", name="beta")
    owner.visit(first.sid)
    owner.page.wait_for_function("keyMap.current('tab.next').length > 0")
    return first, second


def open_help(owner) -> None:  # noqa: ANN001
    key(owner, "?")
    owner.page.wait_for_selector(HELP)


def select(owner, action: str) -> None:  # noqa: ANN001
    for _ in range(200):
        if owner.page.evaluate(CURRENT) == action:
            return
        key(owner, "ArrowDown")
    raise AssertionError(f"{action} is not in the overview")


def status(owner) -> str:  # noqa: ANN001
    return owner.page.evaluate(STATUS)


def reload(owner) -> None:  # noqa: ANN001
    owner.page.reload()
    owner.page.wait_for_function("keyMap.current('tab.next').length > 0")
    owner.page.wait_for_timeout(400)


def test_keys_10_the_overview_lists_every_action_with_its_keys(make, owner) -> None:  # noqa: ANN001
    two(make, owner)
    open_help(owner)
    rows = owner.page.evaluate(
        "() => [...document.querySelectorAll('#key-help dt[data-action]')].map((e) => e.dataset.action)"
    )
    actions = owner.page.evaluate(
        "() => keyMap.groups().flatMap(([, r]) => r).map((r) => r.id)"
    )
    assert rows == [a for a in actions if a] and len(rows) > 60
    text = owner.page.locator(HELP).inner_text()
    assert "Profile: [herdr]" in text and "vim" in text and "Ctrl+Alt+Down" in text
    key(owner, "Escape")
    assert owner.page.locator(HELP).count() == 0


def test_keys_11_a_profile_is_chosen_by_keyboard_and_remembered(make, owner) -> None:  # noqa: ANN001
    first, second = two(make, owner)
    (config() / "keys").mkdir()
    (config() / "keys" / "mine.toml").write_text(
        'description = "mine"\n[keys]\n"tab.next" = ["n"]\n'
    )
    reload(owner)
    key(owner, "n")
    assert owner.page.evaluate(ACTIVE) == first.sid  # not yet bound
    open_help(owner)
    key(owner, "ArrowRight")
    owner.page.wait_for_function(
        "document.querySelector('#key-help-profile').textContent.includes('[mine]')"
    )
    assert status(owner) == "Saved."
    key(owner, "Escape")
    key(owner, "n")
    owner.page.wait_for_function("(id) => activeId !== id", arg=first.sid)
    assert 'profile = "mine"' in (config() / "keys.toml").read_text()
    reload(owner)
    owner.visit(first.sid)
    key(owner, "n")
    owner.page.wait_for_function("(id) => activeId !== id", arg=first.sid)
    open_help(owner)
    key(owner, "ArrowRight")  # vim
    key(owner, "ArrowRight")  # wraps to herdr
    assert "[herdr]" in owner.page.locator("#key-help-profile").inner_text()


def test_keys_12_a_key_is_recorded_saved_and_survives_a_reload(make, owner) -> None:  # noqa: ANN001
    first, _ = two(make, owner)
    open_help(owner)
    select(owner, "tab.next")
    key(owner, "Enter")
    assert "press it now" in status(owner)
    key(owner, "n")
    assert status(owner) == "Saved."
    assert (
        "(changed)"
        in owner.page.locator("#key-help-current")
        .locator("xpath=following-sibling::dd[1]")
        .inner_text()
    )
    key(owner, "Escape")
    key(owner, "n")
    owner.page.wait_for_function("(id) => activeId !== id", arg=first.sid)
    assert '"tab.next" = ["n"]' in (config() / "keys.toml").read_text()
    reload(owner)
    owner.visit(first.sid)
    key(owner, "Control+PageDown")  # the replaced key does nothing
    assert owner.page.evaluate(ACTIVE) == first.sid
    key(owner, "n")
    owner.page.wait_for_function("(id) => activeId !== id", arg=first.sid)


def test_keys_13_a_key_can_be_added_and_a_reset_restores_the_profile(
    make, owner
) -> None:  # noqa: ANN001
    first, _ = two(make, owner)
    open_help(owner)
    select(owner, "tab.next")
    key(owner, "a")
    key(owner, "n")
    assert owner.page.evaluate("keyMap.current('tab.next')")[-1] == "n"
    assert len(owner.page.evaluate("keyMap.current('tab.next')")) == 5
    key(owner, "r")
    assert owner.page.evaluate("keyMap.current('tab.next')") == owner.page.evaluate(
        "keyMap.profileKeys('tab.next')"
    )
    assert "tab.next" not in (config() / "keys.toml").read_text().split("[keys]")[1]
    key(owner, "Escape")
    key(owner, "n")
    assert owner.page.evaluate(ACTIVE) == first.sid


def test_keys_14_a_clash_is_shown_and_must_be_confirmed(make, owner) -> None:  # noqa: ANN001
    first, _ = two(make, owner)
    open_help(owner)
    select(owner, "tab.next")
    key(owner, "Enter")
    key(owner, "c")
    assert "Already used" in status(owner) and "comment mode" in status(owner)
    key(owner, "Escape")  # cancel: nothing changed
    assert "Already used" not in status(owner)
    assert owner.page.evaluate("keyMap.current('tab.next')[0]") == "Ctrl+PageDown"
    assert not (config() / "keys.toml").exists()
    key(owner, "Enter")
    key(owner, "c")
    key(owner, "Enter")  # take it
    assert status(owner) == "Saved."
    assert owner.page.evaluate("keyMap.current('tab.next')") == ["c"]
    assert owner.page.evaluate("keyMap.current('comment.toggle')") == ["C"]
    key(owner, "Escape")
    key(owner, "c")
    owner.page.wait_for_function("(id) => activeId !== id", arg=first.sid)


def test_keys_15_escape_cancels_a_recording_and_reset_all_clears_every_change(
    make, owner
) -> None:  # noqa: ANN001
    two(make, owner)
    open_help(owner)
    select(owner, "tab.next")
    key(owner, "Enter")
    key(owner, "Escape")
    assert owner.page.locator(HELP).count() == 1
    assert owner.page.evaluate("keyMap.current('tab.next')[0]") == "Ctrl+PageDown"
    key(owner, "Enter")
    key(owner, "n")
    select(owner, "tab.prev")
    key(owner, "Enter")
    key(owner, "q")
    assert owner.page.evaluate("Object.keys(keyMap.ownerKeys()).length") == 2
    key(owner, "Shift+R")
    owner.page.wait_for_function("Object.keys(keyMap.ownerKeys()).length === 0")


def test_keys_16_a_bad_profile_file_is_reported_in_the_overview_and_the_rest_works(
    make, owner
) -> None:  # noqa: ANN001
    two(make, owner)
    (config() / "keys").mkdir()
    (config() / "keys" / "bad.toml").write_text("[keys\nbroken")
    reload(owner)
    open_help(owner)
    assert "bad.toml" in owner.page.locator(HELP).inner_text()
    assert "[herdr]" in owner.page.locator("#key-help-profile").inner_text()
