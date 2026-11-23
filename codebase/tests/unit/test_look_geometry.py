"""Crop maths, PNG sizes, look requests, browser lookup, guideline (LOOK-*)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.guide_text import guide_text
from agent_canvas.hub.headless import BROWSER_NAMES, find_browser
from agent_canvas.hub.looks import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    LookError,
    LookRequest,
    crop_region,
    next_look_number,
    png_size,
    store_look,
)
from helpers import solid_png

pytestmark = pytest.mark.unit


def box(x, y, width, height):  # noqa: ANN001, ANN201
    return {"x": x, "y": y, "width": width, "height": height}


def test_look_05_crop_pads_the_element_by_8_px_on_every_side() -> None:
    assert crop_region(box(100, 400, 200, 120), 8, 1280, 2000) == box(92, 392, 216, 136)


def test_look_05_crop_is_clamped_to_the_image() -> None:
    assert crop_region(box(0, 0, 50, 50), 8, 1280, 800) == box(0, 0, 58, 58)
    assert crop_region(box(1200, 760, 100, 100), 8, 1280, 800) == box(1192, 752, 88, 48)


def test_look_05_fractional_boxes_round_outwards() -> None:
    assert crop_region(box(10.4, 20.6, 30.2, 10.1), 0, 500, 500) == box(10, 20, 31, 11)


def test_look_05_an_empty_or_outside_element_cannot_be_cropped() -> None:
    for bad in (box(10, 10, 0, 50), box(10, 10, 50, 0), box(2000, 10, 50, 50)):
        with pytest.raises(ValueError, match="no visible area"):
            crop_region(bad, 8, 1280, 800)


def test_look_01_png_size_is_read_from_the_header() -> None:
    assert png_size(solid_png(30, 20)) == (30, 20)
    for bad in (b"", b"not a png at all, really not a png", solid_png(3, 3)[:20]):
        with pytest.raises(ValueError, match="PNG"):
            png_size(bad)


def test_look_01_looks_are_numbered_in_history_looks(tmp_path: Path) -> None:
    assert next_look_number(tmp_path) == 1
    first = store_look(tmp_path, solid_png(2, 2))
    second = store_look(tmp_path, solid_png(2, 2))
    assert first == tmp_path / "history" / "looks" / "0001.png"
    assert second.name == "0002.png" and next_look_number(tmp_path) == 3
    assert png_size(second.read_bytes()) == (2, 2)


def test_look_01_a_request_has_defaults_from_the_body() -> None:
    request = LookRequest.from_body({})
    assert request == LookRequest(None, False, None, False, None, None, None)
    assert (DEFAULT_WIDTH, DEFAULT_HEIGHT) == (1280, 800)


def test_look_01_a_draft_file_name_means_draft() -> None:
    request = LookRequest.from_body({"page": "r.draft.html"})
    assert request.draft and request.page == "r.html"
    assert LookRequest.from_body({"page": "r", "draft": True}).page == "r.html"


@pytest.mark.parametrize(
    "body",
    [
        {"width": 0},
        {"width": 99},
        {"width": 9000},
        {"height": "tall"},
        {"height": True},
        {"scheme": "blue"},
        {"section": ""},
        {"section": 3},
        {"page": "../x"},
        {"full": "yes"},
    ],
)
def test_look_01_bad_values_are_usage_errors(body: dict) -> None:
    with pytest.raises(LookError) as error:
        LookRequest.from_body(body)
    assert error.value.code == "usage"


def test_look_06_the_environment_names_the_browser_first(tmp_path: Path) -> None:
    mine = tmp_path / "my-chrome"
    mine.write_text("")
    found = find_browser({"AGENT_CANVAS_BROWSER": str(mine)}, lambda n: f"/usr/bin/{n}")
    assert found == str(mine)


def test_look_06_a_broken_environment_value_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="AGENT_CANVAS_BROWSER"):
        find_browser({"AGENT_CANVAS_BROWSER": str(tmp_path / "nope")}, lambda n: None)


def test_look_06_system_browsers_are_tried_in_order() -> None:
    assert BROWSER_NAMES[:3] == ("chromium", "chromium-browser", "google-chrome")
    present = {"google-chrome": "/opt/g", "chromium-browser": "/opt/cb"}
    assert find_browser({}, present.get) == "/opt/cb"
    assert find_browser({}, {"chromium": "/opt/c", **present}.get) == "/opt/c"


def test_look_06_without_any_system_browser_playwrights_own_is_used() -> None:
    assert find_browser({}, lambda n: None) is None


def test_look_10_the_guideline_describes_the_private_workflow() -> None:
    raw = guide_text()
    text = " ".join(raw.split())
    for phrase in (
        ".draft.html",
        "look NAME --draft",
        "show NAME --publish",
        "--section",
        "--full",
        "agent-canvas new",
    ):
        assert phrase in text, phrase
    section = raw.split("## The loop, worked through", 1)[1].split("\n## ", 1)[0]
    assert len(section.split()) < 300  # one worked example, no design advice
