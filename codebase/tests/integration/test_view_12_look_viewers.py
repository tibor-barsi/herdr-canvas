"""`look` and `show` of viewer pages (VIEW-12, VIEW-14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shellfake import FakeHeadless, FakeShell, png_answer

pytestmark = pytest.mark.integration

WINDOW = {"width": 900, "height": 700, "scheme": "light"}
RAW_AUDIT = {
    "findings": [
        {
            "rule": "empty",
            "severity": "error",
            "message": "Empty.",
            "where": "#e",
            "bbox": {"x": 1, "y": 1, "w": 2, "h": 2},
        }
    ]
}
show_audit = pytest.mark.hub_config(show_audit=True)


@pytest.fixture
def session(cli, hub) -> dict:  # noqa: ANN001
    started = cli("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<p>published</p>")
    (folder / "report.pdf").write_bytes(b"%PDF-1.4 one")
    (folder / "notes.md").write_text("# Notes\n")
    headless = FakeHeadless()
    hub.app.state.looks.headless = headless
    return {"id": started["session"], "folder": folder, "headless": headless}


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


def look(cli, session: dict, name: str, *args: str):  # noqa: ANN001, ANN201
    return cli("look", name, *args, "--session", session["id"])


def test_view_12_a_look_loads_the_viewer_document_and_runs_no_page_checks(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    shell = shells(WINDOW, answer=lambda r: png_answer(r, audit=RAW_AUDIT))
    answer = look(cli, session, "report.pdf").json
    [request] = shell.requests
    assert (
        request["url"]
        == hub.state.frame_url(hub.pool_of(session["id"]), "report.pdf") + "?ac-view=1"
    )
    assert request["audit"] is False
    assert answer["audit"] is None and answer["viewer_error"] is None
    assert answer["page"] == "report.pdf"
    # the same answer from the window must not turn into findings for an HTML page
    html = look(cli, session, "page.html").json
    assert html["audit"]["counts"]["error"] == 1 and "viewer_error" not in html
    assert shell.requests[-1]["audit"] is True
    assert "ac-view" not in shell.requests[-1]["url"]


def test_view_12_the_headless_look_of_a_viewer_page_has_the_same_url_and_no_checks(
    cli, hub, session
) -> None:  # noqa: ANN001
    session["headless"].audit = RAW_AUDIT
    answer = look(cli, session, "notes.md").json
    [job] = session["headless"].jobs
    assert job.url.endswith("/notes.md?ac-view=1") and job.audit is False
    assert answer["audit"] is None and answer["source"] == "headless"


def test_view_14_a_look_names_the_reason_the_viewer_gave(cli, session, shells) -> None:  # noqa: ANN001
    shells(WINDOW, answer=lambda r: png_answer(r, viewer_error="pdf-password"))
    assert look(cli, session, "report.pdf").json["viewer_error"] == "pdf-password"


def test_view_14_a_headless_look_names_the_reason_too(cli, session) -> None:  # noqa: ANN001
    session["headless"].viewer_error = "image-too-large"
    assert look(cli, session, "report.pdf").json["viewer_error"] == "image-too-large"


@pytest.mark.parametrize("bad", ["it broke", 7, ["pdf-corrupt"], {"a": 1}])
def test_view_14_a_reason_outside_the_four_is_dropped(
    cli, session, shells, bad
) -> None:  # noqa: ANN001
    shells(WINDOW, answer=lambda r: png_answer(r, viewer_error=bad))
    assert look(cli, session, "report.pdf").json["viewer_error"] is None


@show_audit
def test_view_14_show_loads_a_viewer_page_once_headless_and_never_in_the_window(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    shell = shells(WINDOW)
    session["headless"].viewer_error = "pdf-corrupt"
    session["headless"].audit = RAW_AUDIT
    out = cli("show", "report.pdf", "--session", session["id"])
    assert out.code == 0, out.err
    assert out.json["viewer_error"] == "pdf-corrupt" and out.json["audit"] is None
    [job] = session["headless"].jobs
    assert job.url.endswith("/report.pdf?ac-view=1")
    assert job.audit is False and job.picture is False
    assert [r for r in shell.requests if r["type"] == "render"] == []
    assert not (session["folder"] / "history" / "looks").exists()


@show_audit
def test_view_14_show_of_a_file_that_shows_fine_says_null(cli, session) -> None:  # noqa: ANN001
    out = cli("show", "report.pdf", "--session", session["id"])
    assert out.json["viewer_error"] is None and len(session["headless"].jobs) == 1


@show_audit
def test_view_14_show_no_audit_loads_nothing(cli, session) -> None:  # noqa: ANN001
    out = cli("show", "report.pdf", "--session", session["id"], "--no-audit")
    assert out.json["viewer_error"] is None and session["headless"].jobs == []


@show_audit
def test_view_14_show_without_a_browser_still_succeeds_with_null(
    cli, hub, session
) -> None:  # noqa: ANN001
    hub.state.looks.headless = None
    out = cli("show", "report.pdf", "--session", session["id"])
    assert out.code == 0 and out.json["viewer_error"] is None


@show_audit
def test_view_12_show_of_an_html_page_has_no_viewer_error(cli, session) -> None:  # noqa: ANN001
    out = cli("show", "page.html", "--session", session["id"])
    assert "viewer_error" not in out.json and len(session["headless"].jobs) == 1
