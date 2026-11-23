"""`look` and `show` of viewer pages in real browsers (VIEW-12, VIEW-14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.hub.headless import HeadlessRenderer
from helpers import decode_png

from .conftest import _launch_env
from .support import call
from .test_viewer_comments import BIG, RED, near

pytestmark = pytest.mark.browser

BROKEN_PDF = b"%PDF-1.4 this is not a document"


@pytest.fixture
def headless(owner) -> HeadlessRenderer:  # noqa: ANN001
    renderer = HeadlessRenderer(launch_env=_launch_env())
    owner.hub.app.state.looks.headless = renderer
    return renderer


def put(studio, name: str, data: bytes) -> str:  # noqa: ANN001
    """Write ``name`` into a new session and show it; return the session id."""
    sid = studio.make("<p>first</p>")
    (studio.folder / name).write_bytes(data)
    answer = call(
        studio.owner,
        "POST",
        f"/api/sessions/{sid}/show",
        json={"project": str(studio.tmp_path / "alpha"), "name": name, "audit": False},
    )
    assert answer["page"] == name, answer
    return sid


def look(studio, sid: str, **body) -> dict:  # noqa: ANN001, ANN003
    return call(studio.owner, "POST", f"/api/sessions/{sid}/look", json=body)


def pixels(result: dict) -> list:
    return [p for row in decode_png(Path(result["png"]).read_bytes())[2] for p in row]


def test_view_14_the_window_look_of_a_picture_that_cannot_be_decoded_names_the_reason(
    studio, headless
) -> None:  # noqa: ANN001
    sid = put(studio, "bad.png", b"not a picture")
    result = look(studio, sid, page="bad.png")
    assert result["source"] == "window", result
    assert result["viewer_error"] == "image-undecodable"
    assert result["audit"] is None


def test_view_14_the_headless_look_of_a_corrupt_pdf_names_the_reason(
    studio, headless
) -> None:  # noqa: ANN001
    sid = put(studio, "bad.pdf", BROKEN_PDF)
    result = look(studio, sid, page="bad.pdf", scheme="dark")
    assert result["source"] == "headless", result
    assert result["viewer_error"] == "pdf-corrupt"
    assert result["audit"] is None


def test_view_12_a_look_of_a_picture_shows_the_picture_and_no_error(
    studio, headless
) -> None:  # noqa: ANN001
    sid = put(studio, "pic.png", BIG)
    for options in ({}, {"scheme": "dark"}):
        result = look(studio, sid, page="pic.png", **options)
        assert result["viewer_error"] is None and result["audit"] is None, result
        assert result["errors"] == []
        assert any(near(p, RED) for p in pixels(result)), options


@pytest.mark.hub_config(show_audit=True)
def test_view_14_show_loads_the_page_headless_and_reports_the_reason_or_null(
    studio, headless
) -> None:  # noqa: ANN001
    sid = studio.make("<p>first</p>")
    answers = {}
    for name, data in (
        ("pic.png", BIG),
        ("bad.png", b"nope"),
        ("worse.pdf", BROKEN_PDF),
    ):
        (studio.folder / name).write_bytes(data)
        answers[name] = call(
            studio.owner,
            "POST",
            f"/api/sessions/{sid}/show",
            json={"project": str(studio.tmp_path / "alpha"), "name": name},
        )
    assert {n: a.get("viewer_error", a) for n, a in answers.items()} == {
        "pic.png": None,
        "bad.png": "image-undecodable",
        "worse.pdf": "pdf-corrupt",
    }
    assert all(a["audit"] is None for a in answers.values())
