"""Folding page-audit results in the hub: findings, counts, crops (CHK-01, 12, 13)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from agent_canvas.hub.audit import (
    attach_crops,
    build_audit,
    clean_findings,
    show_audit,
    summary_line,
)
from agent_canvas.hub.pngcrop import crop_png
from helpers import decode_png, solid_png

pytestmark = pytest.mark.unit


def finding(severity: str = "warn", rule: str = "overflow", **extra) -> dict:  # noqa: ANN003
    return {
        "rule": rule,
        "severity": severity,
        "message": "Something is wrong.",
        "where": "#box",
        "bbox": {"x": 10, "y": 20, "w": 30, "h": 40},
        **extra,
    }


def gradient_png(width: int, height: int, filter_type: int = 0) -> bytes:
    """An RGB PNG whose pixel (x, y) is (x, y, 7); optional Sub/Up filtering."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    previous = bytes(width * 3)
    raw = b""
    for y in range(height):
        line = b"".join(bytes((x, y, 7)) for x in range(width))
        if filter_type == 1:  # Sub
            data = bytes(
                (line[i] - (line[i - 3] if i >= 3 else 0)) & 255
                for i in range(len(line))
            )
        elif filter_type == 2:  # Up
            data = bytes((line[i] - previous[i]) & 255 for i in range(len(line)))
        else:
            data = line
        raw += bytes([filter_type]) + data
        previous = line
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_chk_01_clean_findings_keeps_good_ones_and_repairs_the_rest() -> None:
    raw = [
        finding(),
        {"rule": "x", "severity": "loud", "message": "m", "where": "w"},
        "junk",
        finding(bbox={"x": "a"}),
        finding(message=""),
    ]
    kept = clean_findings(raw)
    assert [f["severity"] for f in kept] == ["warn", "info", "warn"]
    assert kept[0]["bbox"] == {"x": 10, "y": 20, "w": 30, "h": 40}
    assert kept[1]["bbox"] is None and kept[2]["bbox"] is None


def test_chk_01_build_audit_sorts_by_severity_and_counts() -> None:
    raw = {"findings": [finding("info"), finding("error"), finding("warn")]}
    audit = build_audit(raw, [])
    assert [f["severity"] for f in audit["findings"]] == ["error", "warn", "info"]
    assert audit["counts"] == {"error": 1, "warn": 1, "info": 1}


def test_chk_12_page_and_block_errors_become_error_findings() -> None:
    errors = [
        {"source": "script", "message": "boom", "line": 3, "canvas_id": None},
        {"source": "block", "message": "bad config", "line": None, "canvas_id": "t1"},
    ]
    audit = build_audit({"findings": []}, errors)
    assert audit["counts"]["error"] == 2
    first, second = audit["findings"]
    assert first["rule"] == "errors" and "boom" in first["message"]
    assert "line 3" in first["where"]
    assert second["where"].startswith("t1")


def test_chk_01_a_hook_without_result_or_failing_still_gives_an_audit() -> None:
    assert build_audit(None, [])["findings"] == []
    failed = build_audit({"error": "audit failed: nope"}, [])
    assert failed["counts"] == {"error": 0, "warn": 0, "info": 1}
    assert "nope" in failed["findings"][0]["message"]


def test_chk_01_summary_line() -> None:
    assert summary_line(build_audit({"findings": []}, [])) == "no problems found"
    audit = build_audit({"findings": [finding("error")] * 2 + [finding("warn")]}, [])
    assert summary_line(audit) == "2 errors, 1 warning, 0 info"


def test_chk_15_show_audit_carries_the_summary_and_only_errors_and_warnings() -> None:
    audit = build_audit({"findings": [finding("info"), finding("warn")]}, [])
    shown = show_audit(audit)
    assert shown["summary"] == "0 errors, 1 warning, 1 info"
    assert [f["severity"] for f in shown["findings"]] == ["warn"]
    assert shown["counts"] == audit["counts"]


@pytest.mark.parametrize("filter_type", [0, 1, 2])
def test_chk_13_crop_png_cuts_the_right_pixels(filter_type: int) -> None:
    png = gradient_png(20, 10, filter_type)
    width, height, rows = decode_png(crop_png(png, 5, 2, 6, 4))
    assert (width, height) == (6, 4)
    assert rows[0][0][:3] == (5, 2, 7) and rows[3][5][:3] == (10, 5, 7)


def test_chk_13_crop_png_reads_the_png_the_tests_use_and_clamps() -> None:
    cropped = crop_png(solid_png(50, 40, (9, 8, 7)), 40, 30, 100, 100)
    width, height, rows = decode_png(cropped)
    assert (width, height) == (10, 10) and rows[0][0][:3] == (9, 8, 7)


def test_chk_13_crop_png_refuses_what_it_cannot_read() -> None:
    with pytest.raises(ValueError):
        crop_png(b"not a png at all, really not", 0, 0, 5, 5)
    with pytest.raises(ValueError):
        crop_png(solid_png(10, 10), 20, 20, 5, 5)


def test_chk_13_attach_crops_takes_the_five_most_severe_that_are_in_the_picture(
    tmp_path: Path,
) -> None:
    png = solid_png(200, 100)
    inside = {"x": 10, "y": 10, "w": 20, "h": 20}
    outside = {"x": 10, "y": 500, "w": 20, "h": 20}
    found = [finding("info", bbox=inside)] * 3
    found += [finding("error", bbox=inside), finding("error", bbox=outside)]
    found += [finding("warn", bbox=inside)] * 4
    audit = build_audit({"findings": found}, [])
    look_png = tmp_path / "0007.png"
    notes = attach_crops(audit, png, look_png, 200)
    with_crop = [f for f in audit["findings"] if "crop" in f]
    assert len(with_crop) == 5
    assert [f["severity"] for f in with_crop] == ["error"] + ["warn"] * 4
    assert (tmp_path / "0007-crop1.png").read_bytes()[:4] == b"\x89PNG"
    assert not (tmp_path / "0007-crop6.png").exists()
    assert any("outside the picture" in n for n in notes)


def test_chk_13_crop_boxes_are_padded_and_scaled_to_the_picture(
    tmp_path: Path,
) -> None:
    png = solid_png(400, 200)  # picture is twice the page width of 200
    audit = build_audit({"findings": [finding("error")]}, [])
    attach_crops(audit, png, tmp_path / "0001.png", 200)
    width, height, _ = decode_png((tmp_path / "0001-crop1.png").read_bytes())
    # bbox (10,20,30,40) padded by 12 and doubled: x 0..104, y 16..144
    assert (width, height) == (104, 128)
