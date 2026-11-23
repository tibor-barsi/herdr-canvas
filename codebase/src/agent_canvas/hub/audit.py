"""Fold the page-audit result into the answer of ``look`` and ``show`` (CHK-01).

The page checks run in the rendered frame (:file:`static/audit.js`) and return
findings. Here they are cleaned (the page is untrusted), merged with the page
and block errors of the render, sorted by severity and counted; the most severe
get a PNG crop next to the look picture.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from agent_canvas.hub.pngcrop import crop_png

SEVERITIES = ("error", "warn", "info")
RANK = {name: index for index, name in enumerate(SEVERITIES)}
MAX_FINDINGS = 100
MAX_CROPS = 5
CROP_PADDING = 12
MIN_VISIBLE_SHARE = 0.5
SOURCE_LABELS = {
    "script": "A script error occurred",
    "block": "A block shows an error",
    "helper": "The page helper failed",
}


def clean_findings(raw: Any) -> list[dict[str, Any]]:
    """
    Keep the well-formed findings of a page check result.

    Parameters
    ----------
    raw : Any
        The ``findings`` value from the page (untrusted).

    Returns
    -------
    list[dict[str, Any]]
        Findings with ``rule``, ``severity``, ``message``, ``where`` and
        ``bbox`` (a dict of whole numbers or None); unknown severities become
        ``info``, entries without rule or message are dropped.
    """
    if not isinstance(raw, list):
        return []
    kept = []
    for item in raw[: MAX_FINDINGS * 2]:
        if not isinstance(item, dict):
            continue
        rule, message = item.get("rule"), item.get("message")
        if not (isinstance(rule, str) and rule.strip()):
            continue
        if not (isinstance(message, str) and message.strip()):
            continue
        severity = item.get("severity")
        where = item.get("where")
        kept.append(
            {
                "rule": rule.strip()[:40],
                "severity": severity if severity in RANK else "info",
                "message": message.strip()[:400],
                "where": where.strip()[:200]
                if isinstance(where, str) and where.strip()
                else "page",
                "bbox": _clean_box(item.get("bbox")),
            }
        )
    return kept


def _clean_box(value: Any) -> dict[str, int] | None:
    """Return ``{x, y, w, h}`` as whole numbers, or None when not usable."""
    if not isinstance(value, dict):
        return None
    numbers = {}
    for key in ("x", "y", "w", "h"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, int | float):
            return None
        if not math.isfinite(number):
            return None
        numbers[key] = round(number)
    return numbers if numbers["w"] >= 0 and numbers["h"] >= 0 else None


def error_findings(errors: Any) -> list[dict[str, Any]]:
    """Turn page and block errors of a render into ``error`` findings (CHK-12)."""
    found: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for error in errors if isinstance(errors, list) else []:
        if not isinstance(error, dict):
            continue
        key = (
            error.get("source"),
            error.get("message"),
            error.get("line"),
            error.get("canvas_id"),
        )
        if key in seen:
            continue
        seen.add(key)
        found.append(_error_finding(error))
    return found


def _error_finding(error: dict[str, Any]) -> dict[str, Any]:
    """Describe one error record as a finding."""
    label = SOURCE_LABELS.get(str(error.get("source")), "The page reported an error")
    message = str(error.get("message") or "no message").strip()[:300]
    line = error.get("line")
    canvas_id = error.get("canvas_id")
    where = str(canvas_id) if canvas_id else "page"
    if isinstance(line, int):
        where += f" (line {line})"
    return {
        "rule": "errors",
        "severity": "error",
        "message": f"{label}: {message} - fix it before the owner sees the page.",
        "where": where,
        "bbox": None,
    }


def count_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    """Count findings per severity."""
    return {name: sum(f["severity"] == name for f in findings) for name in SEVERITIES}


def build_audit(raw: Any, errors: Any) -> dict[str, Any]:
    """
    Build the ``audit`` value of a look from the page result and the errors.

    Parameters
    ----------
    raw : Any
        What ``runPageAudit`` returned: ``{"findings": [...]}``, ``{"error":
        text}`` when the checks failed, or None/anything else when none ran.
    errors : Any
        The page and block errors seen while rendering.

    Returns
    -------
    dict[str, Any]
        ``{"findings": [...], "counts": {...}}``, most severe first.
    """
    findings: list[dict[str, Any]] = []
    if isinstance(raw, dict) and isinstance(raw.get("findings"), list):
        findings += clean_findings(raw["findings"])
    elif isinstance(raw, dict) and isinstance(raw.get("error"), str):
        findings.append(
            {
                "rule": "audit",
                "severity": "info",
                "message": f"The page checks could not run: {raw['error'][:200]}",
                "where": "page",
                "bbox": None,
            }
        )
    findings += error_findings(errors)
    findings.sort(key=lambda f: RANK[f["severity"]])
    findings = findings[:MAX_FINDINGS]
    return {"findings": findings, "counts": count_findings(findings)}


def summary_line(audit: dict[str, Any]) -> str:
    """Return the findings of an audit in one line, such as ``1 error, 2 warnings``."""
    counts = audit["counts"]
    if not sum(counts.values()):
        return "no problems found"

    def noun(number: int, word: str) -> str:
        return f"{number} {word}" + ("" if number == 1 else "s")

    return (
        f"{noun(counts['error'], 'error')}, {noun(counts['warn'], 'warning')}, "
        f"{counts['info']} info"
    )


def show_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Shrink an audit for ``show``: the summary and the errors and warnings."""
    return {
        "summary": summary_line(audit),
        "findings": [f for f in audit["findings"] if f["severity"] != "info"],
        "counts": audit["counts"],
    }


def attach_crops(
    audit: dict[str, Any], png: bytes, look_png: Path, page_width: int
) -> list[str]:
    """
    Save crops of the most severe findings next to the look picture (CHK-13).

    Parameters
    ----------
    audit : dict[str, Any]
        The audit; findings that get a crop gain a ``crop`` path.
    png : bytes
        The look picture; its top-left corner is the page origin.
    look_png : pathlib.Path
        Where the picture is stored; crops are ``NNNN-cropK.png`` beside it.
    page_width : int
        Width of the page in CSS pixels, to scale boxes to the picture.

    Returns
    -------
    list[str]
        Notes for the agent (a crop that could not be made, findings outside
        the picture).
    """
    from agent_canvas.hub.looks import png_size  # looks imports this module

    try:
        image_width, image_height = png_size(png)
    except ValueError:
        return []
    scale = image_width / page_width if page_width else 1.0
    made, outside = 0, 0
    notes: list[str] = []
    for finding in audit["findings"]:
        box = finding.get("bbox")
        if box is None:
            continue
        region = _crop_region(box, scale, image_width, image_height)
        if region is None:
            outside += 1
            continue
        if made >= MAX_CROPS:
            continue
        path = look_png.with_name(f"{look_png.stem}-crop{made + 1}.png")
        try:
            path.write_bytes(crop_png(png, *region))
        except (ValueError, OSError) as error:
            return [*notes, f"Crops could not be made: {error}."]
        finding["crop"] = str(path)
        made += 1
    if outside:
        notes.append(
            f"{outside} finding(s) lie outside the picture and have no crop; "
            "use --full to see the whole page."
        )
    return notes


def _crop_region(
    box: dict[str, int], scale: float, width: int, height: int
) -> tuple[int, int, int, int] | None:
    """Return the padded crop box in picture pixels, or None if out of it."""
    x, y = box["x"] * scale, box["y"] * scale
    w, h = max(box["w"], 1) * scale, max(box["h"], 1) * scale
    visible_w = min(x + w, width) - max(x, 0)
    visible_h = min(y + h, height) - max(y, 0)
    if visible_w <= 0 or visible_h <= 0:
        return None
    if visible_w * visible_h < MIN_VISIBLE_SHARE * w * h:
        return None
    pad = CROP_PADDING * scale
    left, top = max(0, math.floor(x - pad)), max(0, math.floor(y - pad))
    right = min(width, math.ceil(x + w + pad))
    bottom = min(height, math.ceil(y + h + pad))
    return left, top, right - left, bottom - top
