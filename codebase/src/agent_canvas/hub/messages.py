"""The messages the hub sends a window (P33.2, ARC-04): type -> field names.

The window's copy, with its handlers, is ``HUB_MESSAGES`` in ``static/shell.js``; a
test compares the two. What a window sends the hub is ``SHELL_MESSAGES`` in
``hub/routes/sockets.py``. A type or field no row knows is logged, not passed over in
silence (``note_unknown``).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)
NOTE = "unknown message"
MAX_NOTES = 20
_noted: set[str] = set()

WINDOW_MESSAGES: dict[str, tuple[str, ...]] = {
    "hello": ("build", "version"),
    "tabs": ("sessions", "closed", "show"),
    "herdr": ("available", "focus", "spaces", "other"),
    "show": ("session", "page", "url", "tab"),
    "ask-opened": ("session", "tab"),
    "listening": ("session", "listening", "watching"),
    "send-state": ("session", "send"),
    "event-created": ("ref", "event"),
    "file-changed": ("session", "path"),
    "comments": ("session", "page", "next", "comments", "unsent"),
    "answers": ("session", "page", "items", "folder"),
    "render": (
        "id",
        "url",
        "width",
        "height",
        "scheme",
        "section",
        "full",
        "settle_ms",
        "audit",
        "picture",
        "answers",
    ),
    "update": ("url", "version", "html", "viewer", "digest"),
}


def note_unknown(
    where: str, message: dict[str, Any], fields: Sequence[str] | None
) -> None:
    """
    Log a message whose type has no row, or the fields its row does not name.

    Only the type and field names are logged, never values; each name once and at
    most ``MAX_NOTES`` of them, so that a window cannot flood the log.

    Parameters
    ----------
    where : str
        The direction, e.g. ``"from a window"``.
    message : dict
        The message.
    fields : Sequence[str] | None
        The field names of its row; None when its type has no row.
    """
    kind = message.get("type")
    name = repr(kind[:40]) if isinstance(kind, str) else "(not a string)"
    if fields is None:
        _note(f"{NOTE} {where}: type {name}")
        return
    for field in message:
        if field != "type" and field not in fields:
            _note(f"{NOTE} field {where}: {name} has {str(field)[:40]!r}")


def _note(text: str) -> None:
    if text in _noted or len(_noted) >= MAX_NOTES:
        return
    _noted.add(text)
    logger.warning("%s", text)
