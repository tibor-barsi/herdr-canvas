"""Page checks in ``look`` and ``show``: output shape, switches, time budget (CHK-*)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from agent_canvas.hub.looks import LookRequest
from helpers import decode_png
from shellfake import FakeHeadless, FakeShell, png_answer

pytestmark = pytest.mark.integration

WINDOW = {"width": 900, "height": 700, "scheme": "dark"}


def raw_finding(severity: str, rule: str = "overflow", where: str = "#a") -> dict:
    return {
        "rule": rule,
        "severity": severity,
        "message": f"A {severity} thing.",
        "where": where,
        "bbox": {"x": 50, "y": 50, "w": 40, "h": 20},
    }


RAW = {
    "findings": [
        raw_finding("info", "plot", "#i"),
        raw_finding("warn", "overlap", "#w"),
        raw_finding("error", "empty", "#e"),
    ]
}


@pytest.fixture
def session(cli, hub) -> dict:  # noqa: ANN001
    started = cli("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<p>published</p>")
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


def window_with_audit(shells, raw=RAW, errors=None):  # noqa: ANN001, ANN201
    def answer(request: dict) -> dict:
        return png_answer(request, audit=raw, errors=errors or [])

    return shells(WINDOW, answer=answer)


# ---- look -------------------------------------------------------------------------


def test_chk_14_look_returns_findings_and_counts_most_severe_first(
    cli, session, shells
) -> None:  # noqa: ANN001
    window_with_audit(shells)
    out = cli("look", "--session", session["id"])
    assert out.code == 0, out.err
    audit = out.json["audit"]
    assert [f["severity"] for f in audit["findings"]] == ["error", "warn", "info"]
    assert audit["counts"] == {"error": 1, "warn": 1, "info": 1}
    assert set(audit) == {"findings", "counts"}


def test_chk_12_errors_of_the_render_are_folded_in_as_error_findings(
    cli, session, shells
) -> None:  # noqa: ANN001
    errors = [{"source": "script", "message": "boom", "line": 2, "canvas_id": None}]
    window_with_audit(shells, {"findings": []}, errors)
    audit = cli("look", "--session", session["id"]).json["audit"]
    assert audit["counts"]["error"] == 1
    assert audit["findings"][0]["rule"] == "errors"
    assert "boom" in audit["findings"][0]["message"]


def test_chk_14_no_audit_skips_the_checks_and_tells_the_renderer(
    cli, session, shells
) -> None:  # noqa: ANN001
    shell = window_with_audit(shells)
    out = cli("look", "--no-audit", "--session", session["id"])
    assert out.json["audit"] is None
    [request] = shell.requests
    assert request["audit"] is False and request["picture"] is True
    cli("look", "--session", session["id"])
    assert shell.requests[-1]["audit"] is True


def test_chk_14_the_headless_job_carries_the_audit_switch(cli, session) -> None:  # noqa: ANN001
    cli("look", "--no-audit", "--session", session["id"])
    cli("look", "--session", session["id"])
    jobs = session["headless"].jobs
    assert [j.audit for j in jobs] == [False, True]
    assert all(j.picture for j in jobs)


def test_chk_13_crops_sit_next_to_the_look_png(cli, session, shells) -> None:  # noqa: ANN001
    window_with_audit(shells)
    out = cli("look", "--session", session["id"]).json
    crops = [f["crop"] for f in out["audit"]["findings"] if "crop" in f]
    assert len(crops) == 3
    for crop in crops:
        assert Path(crop).parent == Path(out["png"]).parent
        width, height, _ = decode_png(Path(crop).read_bytes())
        assert (width, height) == (64, 44)  # 40 x 20 plus 12 px on every side


def test_chk_13_a_section_look_makes_no_crops(cli, session, shells) -> None:  # noqa: ANN001
    session["folder"].joinpath("page.html").write_text('<p id="x">hi</p>')
    window_with_audit(shells)
    out = cli("look", "--section", "x", "--session", session["id"]).json
    assert all("crop" not in f for f in out["audit"]["findings"])


def test_chk_14_a_page_hook_returning_other_json_is_not_passed_through(
    cli, session, shells
) -> None:  # noqa: ANN001
    window_with_audit(shells, {"checks": ["x"]})
    audit = cli("look", "--session", session["id"]).json["audit"]
    assert audit["findings"] == [] and audit["counts"]["error"] == 0


# ---- the API body -------------------------------------------------------------------


def test_chk_14_audit_must_be_true_or_false() -> None:
    from agent_canvas.hub.looks import LookError

    assert LookRequest.from_body({}).audit is True
    assert LookRequest.from_body({"audit": False}).audit is False
    with pytest.raises(LookError):
        LookRequest.from_body({"audit": "no"})


# ---- show ---------------------------------------------------------------------------

show_audit = pytest.mark.hub_config(show_audit=True)


def run_show(cli, session: dict, *args: str):  # noqa: ANN001, ANN201
    return cli("show", "page.html", "--session", session["id"], *args)


@show_audit
def test_chk_15_show_adds_a_summary_and_only_errors_and_warnings(
    cli, session, shells
) -> None:  # noqa: ANN001
    shell = window_with_audit(shells)
    out = run_show(cli, session)
    assert out.code == 0, out.err
    audit = out.json["audit"]
    assert audit["summary"] == "1 error, 1 warning, 1 info"
    assert [f["severity"] for f in audit["findings"]] == ["error", "warn"]
    assert audit["counts"] == {"error": 1, "warn": 1, "info": 1}
    [request] = [r for r in shell.requests]
    assert (request["width"], request["height"]) == (900, 700)
    assert request["picture"] is False and request["audit"] is True
    assert not (session["folder"] / "history" / "looks").exists()


@show_audit
def test_chk_15_show_no_audit_skips_it(cli, session, shells) -> None:  # noqa: ANN001
    shell = window_with_audit(shells)
    out = run_show(cli, session, "--no-audit")
    assert out.json["audit"] is None and shell.requests == []


@show_audit
def test_chk_15_show_uses_the_headless_browser_without_a_window(cli, session) -> None:  # noqa: ANN001
    session["headless"].audit = RAW
    out = run_show(cli, session)
    assert out.json["audit"]["counts"]["error"] == 1
    [job] = session["headless"].jobs
    assert job.picture is False and (job.width, job.height) == (1280, 800)


@show_audit
def test_chk_15_a_slow_audit_is_pending_after_the_budget(hub, session, shells) -> None:  # noqa: ANN001
    shells(WINDOW, answer=lambda request: None)  # a window that never answers
    looks = hub.state.looks
    looks.show_audit_seconds = 0.4
    loop = hub.state.loop
    started = time.monotonic()
    audit = asyncio.run_coroutine_threadsafe(
        looks.audit_for_show(hub.state.session_of(session["id"]), "page.html"), loop
    ).result(10)
    elapsed = time.monotonic() - started
    assert audit == "pending"
    assert 0.35 <= elapsed < 1.5


@show_audit
def test_chk_15_the_cli_reports_pending_in_the_show_json(
    cli, hub, session, shells
) -> None:  # noqa: ANN001
    shells(WINDOW, answer=lambda request: None)
    hub.state.looks.show_audit_seconds = 0.3
    out = run_show(cli, session)
    assert out.code == 0 and out.json["audit"] == "pending"
    assert out.json["page"] == "page.html"


@show_audit
def test_chk_15_without_any_renderer_the_audit_is_unavailable(
    cli, hub, session
) -> None:  # noqa: ANN001
    hub.state.looks.headless = None
    out = run_show(cli, session)
    assert out.code == 0 and out.json["audit"] == "unavailable"


def test_chk_15_show_audit_is_off_in_the_default_test_hub(cli, session) -> None:  # noqa: ANN001
    out = run_show(cli, session)
    assert out.json["audit"] is None and session["headless"].jobs == []
