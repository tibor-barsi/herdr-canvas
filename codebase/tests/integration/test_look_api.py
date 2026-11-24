"""``look``: routing between window and headless renderer, CLI and API (LOOK-*)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub.auth import cookie_name
from agent_canvas.hub.looks import png_size
from helpers import own_draft
from shellfake import FakeHeadless, FakeShell, png_answer

pytestmark = pytest.mark.integration


@pytest.fixture
def session(cli, hub) -> dict:  # noqa: ANN001
    """A session with a page and a draft; returns id, folder and the headless fake."""
    started = cli("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<p>published</p>")
    (folder / "report.html").write_text("<p>report</p>")
    (folder / own_draft(started["session"], "report")).write_text("<p>draft</p>")
    headless = FakeHeadless()
    hub.app.state.looks.headless = headless
    return {"id": started["session"], "folder": folder, "headless": headless}


def look(cli, session: dict, *args: str):  # noqa: ANN001, ANN201
    return cli("look", *args, "--session", session["id"])


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


WINDOW = {"width": 900, "height": 700, "scheme": "dark"}


def test_look_02_window_size_and_scheme_are_the_defaults(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    result = look(cli, session)
    assert result.code == 0, result.err
    answer = result.json
    [request] = shell.requests
    assert (request["width"], request["height"], request["scheme"]) == (
        900,
        700,
        "dark",
    )
    assert request["url"] == hub.state.frame_url(
        hub.pool_of(session["id"]), "page.html"
    )
    assert request["full"] is False and request["section"] is None
    assert answer["source"] == "window" and answer["scheme"] == "dark"
    assert (answer["width"], answer["height"]) == (900, 700)
    assert answer["page"] == "page.html" and answer["draft"] is False
    assert answer["errors"] == []
    assert answer["audit"] == {
        "findings": [],
        "counts": {"error": 0, "warn": 0, "info": 0},
    }
    assert session["headless"].jobs == []


def test_look_01_the_png_is_stored_as_history_look_and_numbered(
    cli, session, shells
) -> None:  # noqa: ANN001
    shells(WINDOW)
    first = look(cli, session).json
    second = look(cli, session).json
    folder = session["folder"]
    assert first["png"] == str(folder.resolve() / "history/looks/0001.png")
    assert second["png"].endswith("history/looks/0002.png")
    assert png_size(Path(first["png"]).read_bytes()) == (900, 700)


def test_look_01_a_look_leaves_no_version_event_or_page_change(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    pages = session["folder"] / "history" / "pages"
    time.sleep(0.5)  # the watcher saves the first versions of the two pages
    before = sorted(p.name for p in pages.glob("*")) if pages.exists() else []
    shell.messages.clear()
    look(cli, session, "report", "--draft")
    time.sleep(0.5)
    after = sorted(p.name for p in pages.glob("*")) if pages.exists() else []
    assert after == before and not any("draft" in name for name in after)
    assert hub.on_loop(lambda: hub.state.events.all(session["id"])) == []
    # no update, show or tabs message
    assert set(shell.types()) - {"herdr"} == {"render"}


def test_look_02_no_window_means_headless_1280_by_800_light(cli, hub, session) -> None:  # noqa: ANN001
    result = look(cli, session)
    assert result.code == 0, result.err
    assert result.json["source"] == "headless" and result.json["scheme"] == "light"
    assert (result.json["width"], result.json["height"]) == (1280, 800)
    [job] = session["headless"].jobs
    assert (job.width, job.height, job.scheme) == (1280, 800, "light")
    access = session["headless"].access[0]
    assert access.cookie_name == cookie_name(hub.port)
    assert access.cookie_value not in result.out + result.err


def test_look_02_options_override_the_window(cli, session, shells) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    result = look(
        cli, session, "--width", "500", "--height", "300", "--scheme", "dark",
        "--full", "--section", "spectrum",
    )  # fmt: skip
    assert result.code == 0, result.err
    [request] = shell.requests
    assert (request["width"], request["height"]) == (500, 300)
    assert request["full"] is True and request["section"] == "spectrum"
    assert (result.json["width"], result.json["height"]) == (500, 300)


def test_look_02_the_window_report_is_clamped_and_the_newest_wins(hub, shells) -> None:  # noqa: ANN001
    shell = shells({"width": 90000, "height": 5, "scheme": "light"})
    info = hub.on_loop(hub.state.looks.window_info)
    assert (info.width, info.height, info.scheme) == (8000, 100, "light")
    shell.send({"type": "window-info", "width": 640, "height": 480, "scheme": "dark"})
    hub.wait_for(lambda: hub.on_loop(hub.state.looks.window_info).width == 640)
    assert hub.on_loop(hub.state.looks.window_info).scheme == "dark"
    shell.send({"type": "window-info", "width": "wide", "height": 1, "scheme": "x"})
    shell.send({"type": "window-info", "width": 700, "height": 500, "scheme": "light"})
    hub.wait_for(lambda: hub.on_loop(hub.state.looks.window_info).width == 700)


def test_look_02_a_closed_window_is_forgotten(hub, shells) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    shell.close()
    hub.wait_for(lambda: hub.on_loop(hub.state.looks.window_info) is None)


def test_look_07_a_window_that_closes_during_the_look_falls_back_at_once(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    hub.state.looks.window_timeout = 20.0
    holder: list[FakeShell] = []

    def hang_up(request: dict) -> None:
        holder[0].close()

    holder.append(shells(WINDOW, answer=hang_up))
    started = time.monotonic()
    result = look(cli, session)
    assert result.code == 0, result.err
    assert result.json["source"] == "headless"
    assert time.monotonic() - started < 10
    assert (result.json["width"], result.json["height"]) == (900, 700)


def test_look_03_a_silent_window_times_out_and_falls_back(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    hub.state.looks.window_timeout = 0.4
    shell = shells(WINDOW, answer=lambda request: None)
    result = look(cli, session)
    assert result.json["source"] == "headless" and len(shell.requests) == 1


def test_look_07_a_failed_window_render_falls_back(cli, session, shells) -> None:  # noqa: ANN001
    def broken(request: dict) -> dict:
        return {
            "type": "render-result", "id": request["id"], "ok": False,
            "error": "capture exploded",
        }  # fmt: skip

    shells(WINDOW, answer=broken)
    result = look(cli, session)
    assert result.json["source"] == "headless"


def test_look_07_answers_nobody_asked_for_are_ignored(cli, session, shells) -> None:  # noqa: ANN001
    def answer(request: dict) -> dict | None:
        shell.send(png_answer({**request, "id": "someone-else"}, errors=[]))
        shell.send({"type": "render-result", "id": 7, "ok": True})
        return png_answer(request)

    shell = shells(WINDOW, answer=answer)
    result = look(cli, session)
    assert result.code == 0 and result.json["source"] == "window"


def test_look_07_page_errors_of_the_render_are_returned(cli, session, shells) -> None:  # noqa: ANN001
    err = [{"source": "script", "message": "boom", "line": 3, "canvas_id": None},
           {"source": "block", "message": "canvas-plot: bad", "line": None,
            "canvas_id": "p1"}]  # fmt: skip
    shells(WINDOW, answer=lambda r: png_answer(r, errors=err, notes=["slow"]))
    answer = look(cli, session).json
    assert answer["errors"] == err and answer["notes"] == ["slow"]


def test_look_07_audit_output_of_the_page_is_returned(cli, session, shells) -> None:  # noqa: ANN001
    finding = {
        "rule": "overflow", "severity": "warn", "message": "Too wide.",
        "where": "#a", "bbox": None,
    }  # fmt: skip
    shells(WINDOW, answer=lambda r: png_answer(r, audit={"findings": [finding]}))
    audit = look(cli, session).json["audit"]
    assert audit["findings"] == [finding]
    assert audit["counts"] == {"error": 0, "warn": 1, "info": 0}


def test_look_06_a_different_scheme_goes_to_headless_even_with_a_window(
    cli, session, shells
) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    result = look(cli, session, "--scheme", "light")
    assert result.json["source"] == "headless" and result.json["scheme"] == "light"
    assert shell.requests == []
    assert (result.json["width"], result.json["height"]) == (900, 700)


def test_look_06_a_different_scheme_uses_the_window_when_headless_fails(
    cli, session, shells
) -> None:  # noqa: ANN001
    session["headless"].error = "no browser"
    shell = shells(WINDOW)
    result = look(cli, session, "--scheme", "light")
    assert result.code == 0, result.err
    assert result.json["source"] == "window" and result.json["scheme"] == "dark"
    assert any("light" in note for note in result.json["notes"])
    assert len(shell.requests) == 1


def test_look_06_no_window_and_no_browser_says_to_open_the_window(cli, session) -> None:  # noqa: ANN001
    session["headless"].error = "Chromium is not installed"
    result = look(cli, session)
    assert result.code == 1 and result.out == ""
    error = result.json
    assert error["error"] == "failed"
    assert "agent-canvas open" in error["message"]
    assert "Chromium is not installed" in error["message"]
    assert not (session["folder"] / "history" / "looks").exists()


def test_look_01_a_draft_is_rendered_from_its_own_file(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    answer = look(cli, session, "report", "--draft").json
    assert shell.requests[0]["url"] == hub.state.frame_url(
        hub.pool_of(session["id"]), own_draft(session["id"], "report")
    )
    assert answer["draft"] is True and answer["page"] == "report.html"
    again = look(cli, session, "report.draft.html").json
    assert again["draft"] is True


def test_look_01_the_default_page_is_the_active_one(cli, hub, session, shells) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    assert cli("show", "report.html", "--session", session["id"]).code == 0
    look(cli, session)
    assert shell.requests[0]["url"].endswith("/report.html")


def test_look_01_missing_files_are_refused_with_their_names(
    cli, session, shells
) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    (session["folder"] / own_draft(session["id"], "report")).unlink()
    no_draft = look(cli, session, "report", "--draft")
    assert (
        no_draft.code == 1
        and own_draft(session["id"], "report") in no_draft.json["message"]
    )
    no_page = look(cli, session, "ghost")
    assert no_page.code == 1 and "ghost.html" in no_page.json["message"]
    assert shell.requests == []


@pytest.mark.parametrize(
    "args",
    [["--width", "0"], ["--width", "abc"], ["--height", "99999"], ["--scheme", "blue"],
     ["--section", ""]],
)  # fmt: skip
def test_look_01_bad_options_exit_2(cli, session, args: list[str]) -> None:  # noqa: ANN001
    result = look(cli, session, *args)
    assert result.code == 2 and result.json["error"] == "usage"


def test_look_05_an_unknown_section_is_a_page_problem_not_a_renderer_failure(
    cli, session, shells
) -> None:  # noqa: ANN001
    shell = shells(
        WINDOW,
        answer=lambda r: {"type": "render-result", "id": r["id"], "ok": False,
                          "code": "section", "error": "no element with id 'nope'"},
    )  # fmt: skip
    result = look(cli, session, "--section", "nope")
    assert result.code == 1 and "nope" in result.json["message"]
    assert session["headless"].jobs == [] and len(shell.requests) == 1


def test_look_01_an_oversized_or_invalid_png_from_the_window_falls_back(
    cli, session, shells
) -> None:  # noqa: ANN001
    shells(WINDOW, answer=lambda r: {"type": "render-result", "id": r["id"], "ok": True,
                                      "png": "bm90IGEgcG5n"})  # fmt: skip
    assert look(cli, session).json["source"] == "headless"


def test_look_07_the_hub_answers_for_unknown_sessions_with_no_session(cli) -> None:  # noqa: ANN001
    result = cli("look", "--session", "00000000-0000-4000-8000-000000000000")
    assert result.code == 5 and result.json["error"] == "no-session"


def test_look_07_the_api_needs_the_key(hub, session) -> None:  # noqa: ANN001
    url = f"{hub.base_url}/api/sessions/{session['id']}/look"
    assert httpx.post(url, json={}).status_code == 401
    ok = httpx.post(url, json={}, headers=hub.key_headers, timeout=30)
    assert ok.status_code == 200 and ok.json()["source"] == "headless"


def test_look_06_the_render_host_page_is_for_the_owner_cookie_only(hub) -> None:  # noqa: ANN001
    url = f"{hub.base_url}/render"
    assert httpx.get(url).status_code == 401
    assert httpx.get(url, headers=hub.key_headers).status_code == 401
    cookie = {cookie_name(hub.port): hub.state.credentials.cookie_value}
    page = httpx.get(url, cookies=cookie)
    assert page.status_code == 200 and "/static/render.js" in page.text


def test_look_01_cleanup_removes_looks_like_sends(cli, session, shells) -> None:  # noqa: ANN001
    shells(WINDOW)
    png = Path(look(cli, session).json["png"])
    old = time.time() - 40 * 86400
    os.utime(png, (old, old))
    dry = cli("cleanup", "--older-than", "30d").json
    assert str(png) in dry["deleted"] and png.exists()
    cli("cleanup", "--older-than", "30d", "--yes")
    assert not png.exists()
    assert (session["folder"] / "page.html").exists()
