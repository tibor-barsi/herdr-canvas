"""The hub's side of shell updates: build identity and clear look errors (SHELL-02+)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_canvas.hub.looks import NO_RENDERER
from shellfake import FakeHeadless, FakeShell

pytestmark = pytest.mark.integration

WINDOW = {"width": 900, "height": 700, "scheme": "light"}


@pytest.fixture
def session(cli, hub) -> dict:  # noqa: ANN001
    started = cli("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<p>published</p>")
    hub.app.state.looks.headless = None  # no fallback: the window is all there is
    return {"id": started["session"], "folder": folder}


@pytest.fixture
def shells(hub):  # noqa: ANN001, ANN201
    opened: list[FakeShell] = []

    def open_shell(*args, **kwargs) -> FakeShell:  # noqa: ANN002, ANN003
        opened.append(FakeShell(hub, *args, **kwargs))
        return opened[-1]

    yield open_shell
    for shell in opened:
        try:
            shell.close()
        except OSError:
            pass


def look(cli, session: dict):  # noqa: ANN001, ANN201
    return cli("look", "--session", session["id"])


def wait_for_message(hub, shell: FakeShell, kind: str) -> dict:  # noqa: ANN001
    hub.wait_for(lambda: kind in shell.types())
    return next(m for m in shell.messages if m.get("type") == kind)


def silent(request: dict) -> None:
    return None


# ---- SHELL-02: the identity is exposed ----------------------------------------


def test_shell_02_a_connecting_shell_is_told_the_build(hub, shells) -> None:  # noqa: ANN001
    shell = shells()
    hello = wait_for_message(hub, shell, "hello")
    assert hello["build"] == hub.state.build_id and hello["build"]
    wait_for_message(hub, shell, "tabs")
    assert shell.types().index("hello") < shell.types().index("tabs")


def test_shell_02_the_status_and_the_shell_page_carry_the_build(hub) -> None:  # noqa: ANN001
    status = httpx.get(hub.base_url + "/api/status", headers=hub.key_headers).json()
    assert status["build"] == hub.state.build_id
    answer = httpx.get(hub.login_url(), follow_redirects=False)
    with httpx.Client(base_url=hub.base_url, cookies=answer.cookies) as client:
        page = client.get("/").text
    assert f'content="{hub.state.build_id}"' in page


def test_shell_02_a_restarted_hub_has_the_identity_of_the_same_files(hub) -> None:  # noqa: ANN001
    before = hub.state.build_id
    hub.restart()
    assert hub.state.build_id == before


# ---- SHELL-05 and SHELL-06: look says what is wrong with a connected window --------


def test_shell_05_a_silent_window_is_named_and_a_reload_suggested(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    hub.state.looks.window_timeout = 0.4
    shells({**WINDOW, "build": hub.state.build_id}, answer=silent)
    result = look(cli, session)
    text = result.err + result.out
    assert result.code == 1 and "did not answer" in text and "reload" in text.lower()
    assert "No renderer is available" not in text


def test_shell_05_no_window_keeps_the_open_the_window_message(
    cli, hub, session
) -> None:  # noqa: ANN001
    result = look(cli, session)
    text = result.err + result.out
    assert result.code == 1 and NO_RENDERER.split(".")[0] in text
    assert "did not answer" not in text and "older version" not in text


def test_shell_06_a_window_of_another_build_is_called_older(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    hub.state.looks.window_timeout = 0.4
    shells({**WINDOW, "build": "old-build"}, answer=silent)
    result = look(cli, session)
    text = result.err + result.out
    assert "the canvas tab runs an older version" in text
    assert "reloads by itself, or reload it" in text


def test_shell_07_an_old_shell_without_build_and_hello_is_treated_sanely(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    # A 0.1.0 shell sends no window-info with a build and ignores render requests.
    hub.state.looks.window_timeout = 0.4
    shell = shells(WINDOW, answer=silent)
    shell.send({"type": "no-such-message-of-the-future", "x": 1})
    result = look(cli, session)
    text = result.err + result.out
    assert result.code == 1 and "older version" in text
    assert hub.on_loop(lambda: len(hub.state.shells)) == 1  # nothing crashed


def test_shell_07_a_shell_that_sends_a_junk_build_is_ignored(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    hub.state.looks.window_timeout = 0.4
    shells({**WINDOW, "build": 42}, answer=silent)
    result = look(cli, session)
    assert "older version" in result.err + result.out


def test_shell_06_a_window_that_answers_is_not_blamed(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    from shellfake import png_answer

    shells({**WINDOW, "build": "old-build"}, answer=png_answer)
    result = look(cli, session)
    assert result.code == 0 and result.json["source"] == "window"


# ---- SHELL-08: the show audit says why it is unavailable --------------------------


@pytest.mark.hub_config(show_audit=True)
def test_shell_08_show_names_a_silent_window_next_to_unavailable(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    hub.state.looks.window_timeout = 0.3
    hub.state.looks.show_audit_seconds = 5.0
    shells({**WINDOW, "build": "old-build"}, answer=silent)
    out = cli("show", "page.html", "--session", session["id"])
    assert out.code == 0 and out.json["audit"] == "unavailable", out.out
    assert "older version" in out.json["audit_note"]


@pytest.mark.hub_config(show_audit=True)
def test_shell_08_without_a_window_there_is_no_note(cli, hub, session) -> None:  # noqa: ANN001
    hub.state.looks.headless = FakeHeadless(error="no chromium")
    out = cli("show", "page.html", "--session", session["id"])
    assert out.json["audit"] == "unavailable" and out.json.get("audit_note") is None


def test_shell_02_static_files_are_revalidated_on_every_load(hub) -> None:  # noqa: ANN001
    # An updated hub must never run with a script the browser kept from before.
    for path in ("/static/shell.js", "/static/blocks/loader.js"):
        answer = httpx.get(hub.base_url + path, headers=hub.key_headers)
        assert answer.status_code == 200, path
        assert answer.headers.get("cache-control") == "no-cache", path
