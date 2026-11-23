"""Send records: validation, numbering and storage (DRAW-05, requirements 5.4).

A send is the owner's draft (message, actions) plus a screenshot; the hub adds
the comments of the store. The shell uploads it; this module checks it (the
shell is trusted but the content comes from an untrusted page), writes
``history/sends/NNNN.json`` and ``NNNN.png`` and describes the stored send for
the event. A send over several pages is one record per page (COM-10).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from agent_canvas.hub.comments import AGENT_HIDDEN, status
from agent_canvas.hub.events import NOT_FROM_OWNER
from agent_canvas.hub.registry import _write_json_atomic, now_iso
from agent_canvas.hub.viewers import viewer_type
from agent_canvas.hub.watcher import is_page_name
from agent_canvas.paths import make_private_dirs

SEND_SCHEMA = "agent-canvas/send@1"
SENDS_DIR = Path("history") / "sends"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
MAX_MESSAGE_CHARS = 100_000
MAX_ACTIONS = 50
MAX_MARKS = 500
MAX_PAGES = 200
NOT_SHOWN = "page not shown"
MAX_POINTS = 20_000
MARK_TYPES = ("pen", "arrow", "box", "text")
SEND_DELIVERIES = ("now", "next-message")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
NUMBERED = re.compile(r"^(\d{4,})\.json$")
TARGET_LIMITS = {"canvas_id": 200, "selector": 500, "text": 80}
WARNING_KEYS = ("canvas_id", "selector", "reason")


class SendError(ValueError):
    """A send payload that cannot be stored; the message names the problem."""


def _number(value: Any, name: str) -> int | float:
    """Return ``value`` if it is a finite number (not a bool), else raise."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SendError(f"{name} must be a number")
    if value != value or abs(value) > 1e7:
        raise SendError(f"{name} is out of range")
    return value


def _short(value: Any, limit: int) -> str | None:
    """Return a string cut to ``limit`` characters, or None for non-strings."""
    return value[:limit] if isinstance(value, str) else None


def _clean_target(value: Any) -> dict[str, Any] | None:
    """Keep the mark target fields of 5.4 (``canvas_id``, ``data_bbox``, ...)."""
    if not isinstance(value, dict):
        return None
    target: dict[str, Any] = {
        key: _short(value.get(key), limit) for key, limit in TARGET_LIMITS.items()
    }
    bbox = value.get("data_bbox")
    if isinstance(bbox, dict):
        target["data_bbox"] = {
            axis: [_number(v, "data_bbox") for v in bbox[axis][:2]]
            for axis in ("x", "y")
            if isinstance(bbox.get(axis), list) and len(bbox[axis]) == 2
        }
    else:
        target["data_bbox"] = None
    return target


def _clean_mark(mark: Any) -> dict[str, Any]:
    """Validate one mark (5.4) and return its stored form."""
    if not isinstance(mark, dict) or mark.get("type") not in MARK_TYPES:
        raise SendError(f"mark type must be one of {', '.join(MARK_TYPES)}")
    colour = mark.get("colour")
    if not isinstance(colour, str) or not COLOUR.match(colour):
        raise SendError("mark colour must look like #rrggbb")
    points = mark.get("points")
    expected = {"pen": None, "arrow": 2, "box": 2, "text": 1}[mark["type"]]
    if not isinstance(points, list) or not points or len(points) > MAX_POINTS:
        raise SendError("mark points must be a non-empty list")
    if expected is not None and len(points) != expected:
        raise SendError(f"a {mark['type']} mark needs {expected} points")
    clean_points = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise SendError("mark points must be [x, y] pairs")
        clean_points.append([_number(v, "mark points") for v in point])
    bbox = mark.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise SendError("mark bbox must be [x, y, width, height]")
    text = mark.get("text")
    if mark["type"] == "text" and not (isinstance(text, str) and text):
        raise SendError("a text mark needs its text")
    return {
        "id": int(_number(mark.get("id"), "mark id")),
        "type": mark["type"],
        "colour": colour,
        "points": clean_points,
        "bbox": [_number(v, "mark bbox") for v in bbox],
        "text": _short(text, 1000),
        "target": _clean_target(mark.get("target")),
    }


def _clean_viewport(value: Any) -> dict[str, int]:
    """Validate the viewport at send time."""
    if not isinstance(value, dict):
        raise SendError("viewport must be an object")
    viewport = {
        key: int(_number(value.get(key), f"viewport {key}"))
        for key in ("width", "height", "scroll_x", "scroll_y")
    }
    if viewport["width"] < 1 or viewport["height"] < 1:
        raise SendError("viewport size must be positive")
    return viewport


def _decode_screenshot(value: Any) -> bytes | None:
    """Decode the base64 PNG, or return None when there is none."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_SCREENSHOT_BYTES * 4 // 3 + 8:
        raise SendError("screenshot must be a base64 string within 10 MB")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise SendError("screenshot is not valid base64") from error
    if not data.startswith(PNG_SIGNATURE):
        raise SendError("screenshot is not a PNG")
    return data


def _is_shown_name(name: Any) -> bool:
    """Whether ``name`` is a page file or a PDF, Markdown file or picture."""
    return (
        isinstance(name, str)
        and "/" not in name
        and (is_page_name(name) or viewer_type(name) is not None)
    )


def clean_send(payload: Any) -> dict[str, Any]:
    """
    Validate an uploaded send and return its normalised form.

    Parameters
    ----------
    payload : Any
        The decoded JSON body of the upload.

    Returns
    -------
    dict[str, Any]
        Keys ``delivery``, ``message``, ``page``, ``pages`` (the tab's other
        pages), ``actions``, ``actions_dropped``, ``marks`` (validated, only
        so the route can drop and log them, COM-11), ``comments`` (always
        empty: the route fills it from the store, never from the request),
        ``viewport``,
        ``png`` (bytes or None),
        ``screenshot_error`` and ``screenshot_warnings``.

    Raises
    ------
    SendError
        If any field is missing or malformed; the message names the field.
    """
    if not isinstance(payload, dict):
        raise SendError("the send must be a JSON object")
    delivery = payload.get("delivery")
    if delivery not in SEND_DELIVERIES:
        raise SendError(f"delivery must be one of {', '.join(SEND_DELIVERIES)}")
    message = payload.get("message", "")
    if not isinstance(message, str) or len(message) > MAX_MESSAGE_CHARS:
        raise SendError("message must be a string")
    page = payload.get("page")
    if page is not None and not _is_shown_name(page):
        raise SendError("page must be the name of a page file")
    pages = payload.get("pages", [])
    if not isinstance(pages, list) or len(pages) > MAX_PAGES:
        raise SendError(f"pages must be a list of at most {MAX_PAGES}")
    if not all(_is_shown_name(p) for p in pages):
        raise SendError("pages must be names of page files")
    actions = payload.get("actions", [])
    marks = payload.get("marks", [])
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise SendError(f"actions must be a list of at most {MAX_ACTIONS}")
    if not isinstance(marks, list) or len(marks) > MAX_MARKS:
        raise SendError("marks must be a list")
    png = _decode_screenshot(payload.get("screenshot"))
    error = _short(payload.get("screenshot_error"), 500)
    if png is None and not error:
        raise SendError("screenshot_error is required without a screenshot")
    warnings = payload.get("screenshot_warnings", [])
    if not isinstance(warnings, list):
        raise SendError("screenshot_warnings must be a list")
    return {
        "delivery": delivery,
        "message": message,
        "page": page,
        "pages": [p for p in dict.fromkeys(pages) if p != page],
        "actions": [_clean_action(a) for a in actions],
        "actions_dropped": max(
            0, int(_number(payload.get("actions_dropped", 0), "actions_dropped"))
        ),
        "marks": [_clean_mark(m) for m in marks],
        "comments": [],
        "viewport": _clean_viewport(payload.get("viewport")),
        "png": png,
        "screenshot_error": None if png is not None else error,
        "screenshot_warnings": [
            {key: _short(w.get(key), 500) for key in WARNING_KEYS}
            for w in warnings[:50]
            if isinstance(w, dict)
        ],
    }


def _clean_action(action: Any) -> dict[str, Any]:
    """
    Keep the fields of an action (5.4); the value is passed on as sent.

    One the window recorded with no action of the owner (``no_gesture``) gets
    the ``not_from_owner`` mark (SEC-09).
    """
    if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
        raise SendError("every action needs a kind")
    if len(json.dumps(action)) > 100_000:
        raise SendError("an action is too large")
    event = action.get("event")
    return {
        "kind": action["kind"][:40],
        "time": _short(action.get("time"), 40) or "",
        "target": action.get("target")
        if isinstance(action.get("target"), dict)
        else None,
        "value": action.get("value"),
        "at": action.get("at") if isinstance(action.get("at"), list) else None,
        **({"event": event} if isinstance(event, str) else {}),
        **(
            {"not_from_owner": NOT_FROM_OWNER}
            if action.get("no_gesture") is True
            else {}
        ),
    }


def comments_for_send(
    folder: Path, records: list[dict[str, Any]], number: int
) -> list[dict[str, Any]]:
    """
    Describe comments handed over by send ``number`` for the event (COM-11).

    Each comment's picture is copied to ``history/sends/NNNN.c<n>.png`` so the
    send keeps it; the described comment has that copy's absolute path.

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    records : list[dict[str, Any]]
        Comment records of 5.13, already marked sent.
    number : int
        The send's number.

    Returns
    -------
    list[dict[str, Any]]
        The records with ``status`` and an absolute ``picture`` (None without
        one), without the fields the agent does not get.
    """
    directory = folder / SENDS_DIR
    described = []
    for record in records:
        shown = {k: v for k, v in record.items() if k not in AGENT_HIDDEN}
        source = folder / record["picture"] if record["picture"] else None
        shown["picture"] = None
        if source is not None and source.is_file():
            make_private_dirs(directory)
            copy = directory / f"{number:04d}.c{record['n']}.png"
            shutil.copyfile(source, copy)
            shown["picture"] = str(copy.resolve())
        elif source is not None and not shown["picture_error"]:
            shown["picture_error"] = "the picture file is missing"
        described.append({**shown, "status": status(record)})
    return described


def new_send_id() -> str:
    """Return a new random send id (``snd_`` and 16 hex digits)."""
    return f"snd_{secrets.token_hex(8)}"


def next_number(folder: Path) -> int:
    """Return the number of the next send of a session folder (from 1)."""
    directory = folder / SENDS_DIR
    if not directory.is_dir():
        return 1
    found = [
        int(m.group(1)) for p in directory.iterdir() if (m := NUMBERED.match(p.name))
    ]
    return max(found, default=0) + 1


def store_send(
    folder: Path,
    session_id: str,
    event_id: str,
    page_version: int | None,
    clean: dict[str, Any],
    send_id: str | None = None,
    part: list[int] | None = None,
) -> dict[str, Any]:
    """
    Write the PNG and the record of a send and return the record.

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    session_id, event_id : str
        Ids stored in the record; the event is created after this call.
    page_version : int | None
        Latest version of the page at send time.
    clean : dict[str, Any]
        Output of :func:`clean_send` (its marks are not stored, COM-11).
    send_id : str | None, optional
        Id shared by the records of one send; default a new one.
    part : list[int] | None, optional
        ``[k, n]``: this record's place among the send's records; default ``[1, 1]``.

    Returns
    -------
    dict[str, Any]
        The record as written to ``NNNN.json``.
    """
    number = next_number(folder)
    stem = f"{number:04d}"
    directory = folder / SENDS_DIR
    make_private_dirs(directory)
    screenshot = None
    if clean["png"] is not None:
        screenshot = f"{stem}.png"
        (directory / screenshot).write_bytes(clean["png"])
    record = {
        "schema": SEND_SCHEMA,
        "event": event_id,
        "session": session_id,
        "page": clean["page"],
        "page_version": page_version,
        "created": now_iso(),
        "send_id": send_id or new_send_id(),
        "part": part or [1, 1],
        "delivery": clean["delivery"],
        "message": clean["message"],
        "actions": clean["actions"],
        "actions_dropped": clean["actions_dropped"],
        "comments": clean["comments"],
        "viewport": clean["viewport"],
        "screenshot": screenshot,
        "screenshot_error": clean["screenshot_error"],
        "screenshot_warnings": clean["screenshot_warnings"],
    }
    _write_json_atomic(directory / f"{stem}.json", record)
    return record


def event_fields(folder: Path, record: dict[str, Any], number: int) -> dict[str, Any]:
    """
    Return the ``send`` event fields (5.3) describing a stored record.

    Paths are absolute.

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    record : dict[str, Any]
        The record returned by :func:`store_send`.
    number : int
        The send's number (the ``NNNN`` of its files).
    """
    directory = (folder / SENDS_DIR).resolve()
    return {
        "send_id": record["send_id"],
        "part": record["part"],
        "message": record["message"],
        "actions": record["actions"],
        "comments": record["comments"],
        "screenshot": str(directory / record["screenshot"])
        if record["screenshot"]
        else None,
        "screenshot_error": record["screenshot_error"],
        "send_file": str(directory / f"{number:04d}.json"),
    }


def list_sends(folder: Path) -> list[dict[str, Any]]:
    """Return all stored sends in number order; unreadable files are skipped."""
    directory = folder / SENDS_DIR
    if not directory.is_dir():
        return []
    found = []
    for path in directory.iterdir():
        if (match := NUMBERED.match(path.name)) is None:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(record, dict):
            found.append({"number": int(match.group(1)), **record})
    return sorted(found, key=lambda s: s["number"])


def read_screenshot(
    folder: Path, number: int, comment: str | None = None
) -> bytes | None:
    """Return the PNG of send ``number`` (or of its comment ``comment``), or None."""
    suffix = f".c{comment}" if comment else ""
    path = folder / SENDS_DIR / f"{number:04d}{suffix}.png"
    return path.read_bytes() if path.is_file() else None
