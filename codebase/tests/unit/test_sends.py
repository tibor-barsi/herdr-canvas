"""Send validation, numbering and storage (DRAW-05, 5.4)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from agent_canvas.hub.sends import (
    SendError,
    clean_send,
    list_sends,
    next_number,
    read_screenshot,
    store_send,
)

pytestmark = pytest.mark.unit

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def payload(**changes) -> dict:  # noqa: ANN003
    base = {
        "delivery": "now",
        "message": "why this peak?",
        "page": "page.html",
        "actions": [],
        "actions_dropped": 0,
        "marks": [],
        "viewport": {"width": 800, "height": 600, "scroll_x": 0, "scroll_y": 340},
        "screenshot": base64.b64encode(PNG).decode(),
        "screenshot_error": None,
        "screenshot_warnings": [],
    }
    base.update(changes)
    return base


def box_mark(**changes) -> dict:  # noqa: ANN003
    mark = {
        "id": 1, "type": "box", "colour": "#e5484d", "points": [[10, 20], [50, 80]],
        "bbox": [10, 20, 40, 60], "text": None,
        "target": {"canvas_id": "a", "data_bbox": None},
    }  # fmt: skip
    mark.update(changes)
    return mark


def test_draw_05_clean_send_decodes_the_screenshot() -> None:
    clean = clean_send(payload())
    assert clean["png"] == PNG
    assert clean["delivery"] == "now" and clean["message"] == "why this peak?"


def test_draw_05_failed_capture_needs_an_error_text() -> None:
    clean = clean_send(payload(screenshot=None, screenshot_error="timeout"))
    assert clean["png"] is None and clean["screenshot_error"] == "timeout"
    with pytest.raises(SendError, match="screenshot_error"):
        clean_send(payload(screenshot=None))


@pytest.mark.parametrize(
    ("changes", "word"),
    [
        ({"delivery": "ask"}, "delivery"),
        ({"message": 3}, "message"),
        ({"page": "../x.html"}, "page"),
        ({"marks": [box_mark(type="circle")]}, "type"),
        ({"marks": [box_mark(colour="red")]}, "colour"),
        ({"marks": [box_mark(points=[[1, 2]])]}, "points"),
        ({"marks": [box_mark(points=[[1, "a"], [2, 3]])]}, "points"),
        (
            {"viewport": {"width": 0, "height": 5, "scroll_x": 0, "scroll_y": 0}},
            "viewport",
        ),
        ({"screenshot": "!!notbase64!!"}, "screenshot"),
        ({"screenshot": base64.b64encode(b"GIF89a").decode()}, "PNG"),
        ({"actions": "x"}, "actions"),
    ],
)
def test_draw_05_invalid_payload_is_refused_with_a_reason(changes, word) -> None:
    with pytest.raises(SendError, match=word):
        clean_send(payload(**changes))


def test_com_10_a_send_may_name_a_pdf_markdown_or_picture_page() -> None:
    clean = clean_send(payload(page="spec.pdf", pages=["notes.md", "pic.png"]))
    assert clean["page"] == "spec.pdf" and clean["pages"] == ["notes.md", "pic.png"]
    with pytest.raises(SendError, match="page"):
        clean_send(payload(page="spec.txt"))


def test_draw_05_text_mark_needs_one_point_and_text() -> None:
    note = box_mark(type="text", points=[[5, 5]], bbox=[5, 5, 30, 16], text="peak")
    assert clean_send(payload(marks=[note]))["marks"][0]["text"] == "peak"
    with pytest.raises(SendError, match="points"):
        clean_send(payload(marks=[{**note, "points": [[5, 5], [6, 6]]}]))


def test_draw_05_numbers_start_at_one_and_follow_the_files(tmp_path: Path) -> None:
    assert next_number(tmp_path) == 1
    store_send(tmp_path, "s1", "evt_1", 3, clean_send(payload()))
    store_send(tmp_path, "s1", "evt_2", 3, clean_send(payload()))
    assert sorted(p.name for p in (tmp_path / "history/sends").iterdir()) == [
        "0001.json", "0001.png", "0002.json", "0002.png",
    ]  # fmt: skip
    assert next_number(tmp_path) == 3


def test_draw_05_record_follows_the_5_4_shape(tmp_path: Path) -> None:
    clean = clean_send(payload(marks=[box_mark()]))
    record = store_send(tmp_path, "s1", "evt_9", 7, clean)
    stored = json.loads((tmp_path / "history/sends/0001.json").read_text())
    assert stored == record
    assert stored["schema"] == "agent-canvas/send@1"
    assert stored["event"] == "evt_9" and stored["session"] == "s1"
    assert stored["page"] == "page.html" and stored["page_version"] == 7
    assert stored["screenshot"] == "0001.png" and stored["screenshot_error"] is None
    assert stored["viewport"]["scroll_y"] == 340 and stored["actions_dropped"] == 0
    assert "marks" not in stored
    assert read_screenshot(tmp_path, 1) == PNG


def test_draw_05_no_png_file_without_screenshot(tmp_path: Path) -> None:
    clean = clean_send(payload(screenshot=None, screenshot_error="boom"))
    record = store_send(tmp_path, "s1", "evt_1", None, clean)
    assert record["screenshot"] is None and record["screenshot_error"] == "boom"
    assert not (tmp_path / "history/sends/0001.png").exists()
    assert read_screenshot(tmp_path, 1) is None


def test_hist_03_listing_is_ordered_and_skips_broken_files(tmp_path: Path) -> None:
    store_send(tmp_path, "s1", "evt_1", 1, clean_send(payload(message="one")))
    store_send(tmp_path, "s1", "evt_2", 1, clean_send(payload(message="two")))
    (tmp_path / "history/sends/0003.json").write_text("{broken")
    listing = list_sends(tmp_path)
    assert [(s["number"], s["message"]) for s in listing] == [(1, "one"), (2, "two")]
