"""A shell tab that outlives a hub update reloads or offers a reload (SHELL-03/04).

A build change is simulated by giving the running test hub another build
identity and making the shell reconnect, as it does after a hub restart.
"""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE, call
from .test_ask_cards import Asking

pytestmark = pytest.mark.browser

NEW_BUILD = "build-after-update"
BANNER = "#update-bar"


def loaded_build(page) -> str:  # noqa: ANN001
    return page.evaluate(
        "document.querySelector('meta[name=agent-canvas-build]').content"
    )


def mark_document(page) -> None:  # noqa: ANN001
    """Tag the shell document: the tag is gone after a reload."""
    page.evaluate("window.__same_document = true")


def same_document(page) -> bool:  # noqa: ANN001
    return page.evaluate("window.__same_document === true")


def update_hub(studio, build: str = NEW_BUILD) -> None:  # noqa: ANN001
    """Give the hub a new build identity and make the shell reconnect."""
    studio.owner.hub.state.build_id = build
    studio.page.evaluate("socket.close()")


def wait_for_reload(studio, build: str = NEW_BUILD) -> None:  # noqa: ANN001
    studio.page.wait_for_function(
        "(b) => document.querySelector('meta[name=agent-canvas-build]')"
        ".content === b && window.__same_document !== true",
        arg=build,
        timeout=20000,
    )
    studio.page.wait_for_function(
        "typeof socket !== 'undefined' && socket && socket.readyState === 1"
    )


def test_shell_03_an_idle_shell_reloads_and_keeps_tab_and_page(studio) -> None:  # noqa: ANN001
    first = studio.make(SCROLL_PAGE, "alpha")
    second = studio.make(SCROLL_PAGE, "beta")
    folder = studio.folder
    (folder / "notes.html").write_text("<p id=n>notes</p>")
    call(
        studio.owner, "POST", f"/api/sessions/{second}/show",
        json={"project": str(studio.tmp_path / "beta"), "name": "notes.html"},
    )  # fmt: skip
    studio.frame.wait_for_selector("#n")
    old_build = loaded_build(studio.page)
    mark_document(studio.page)
    update_hub(studio)
    wait_for_reload(studio)
    assert old_build != NEW_BUILD and loaded_build(studio.page) == NEW_BUILD
    studio.page.wait_for_selector(f'.hv-card.focus[data-session="{second}"]')
    assert studio.page.locator(f'.hv-card.focus[data-session="{first}"]').count() == 0
    studio.owner.frame.wait_for_selector("#n")
    assert studio.owner.frame.url.endswith("/notes.html")
    assert not studio.page.is_visible(BANNER)


def test_shell_04_an_unsent_action_alone_keeps_the_shell(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    studio.frame.click("#b")
    studio.page.wait_for_function(f"window.__drafts['{sid}'].actions.length === 1")
    mark_document(studio.page)
    update_hub(studio)
    studio.page.wait_for_selector(BANNER, state="visible", timeout=20000)
    assert same_document(studio.page)


def test_shell_04_an_answer_being_typed_keeps_the_shell(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    ask = Asking(studio.owner, studio.tmp_path, "Why?", "--text", "--session", sid)
    try:
        field = studio.page.locator("#ask-bar .ask-text")
        field.wait_for()
        field.fill("because")
        mark_document(studio.page)
        update_hub(studio)
        studio.page.wait_for_selector(BANNER, state="visible", timeout=20000)
        assert same_document(studio.page)
        assert field.input_value() == "because"
    finally:
        ask.process.kill()
        ask.process.wait()
        ask.process.stdout.close()
        ask.process.stderr.close()


def test_shell_03_an_unchanged_build_does_nothing(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    mark_document(studio.page)
    studio.page.evaluate("socket.close()")
    studio.page.wait_for_function(
        "typeof socket !== 'undefined' && socket && socket.readyState === 1"
    )
    studio.page.wait_for_timeout(1200)
    assert same_document(studio.page) and not studio.page.is_visible(BANNER)


def test_shell_03_a_shell_does_not_reload_twice_for_one_build(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    # The page was served with a build the hub then no longer reports at all
    # times (a broken install): after one reload it shows the banner instead.
    studio.page.evaluate(
        "sessionStorage.setItem('agent-canvas-reloaded-for', 'build-after-update')"
    )
    mark_document(studio.page)
    update_hub(studio)
    studio.page.wait_for_selector(BANNER, state="visible", timeout=20000)
    assert same_document(studio.page)


# ---- SHELL-06 with a real window: look names an old shell ---------------------------


def test_shell_06_look_with_a_stale_window_says_it_is_older(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    hub = studio.owner.hub
    hub.state.looks.headless = None
    hub.state.looks.window_timeout = 1.0
    # A shell of an older build: it neither reloads (unsaved text) nor answers.
    studio.queue_action()
    studio.page.evaluate("handleRender = async () => {}")
    update_hub(studio)
    studio.page.wait_for_selector(BANNER, state="visible", timeout=20000)
    result = call(studio.owner, "POST", f"/api/sessions/{sid}/look", json={})
    assert "older version" in str(result), result
