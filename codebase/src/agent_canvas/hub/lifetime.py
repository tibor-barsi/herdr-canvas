"""Page kinds and when a page expires (LIFE-01, LIFE-02, D-38)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent_canvas.hub.clock import iso, seconds_of

KINDS = ("single-use", "transitional", "long-term")
DEFAULT_KIND = "transitional"
DAY_SECONDS = 24 * 3600
ARCHIVE_DAYS = 30
VERSION_DAYS = 30  # saved page versions older than this are deleted (HIST-86)
REMIND_SECONDS = DAY_SECONDS
LIFETIME_SECONDS = {
    "single-use": 3 * DAY_SECONDS,
    "transitional": 30 * DAY_SECONDS,
    "long-term": None,
}


def expiry(entry: dict[str, Any], changed: float) -> float | None:
    """
    Return the POSIX time a page expires, None when it never does (LIFE-02, STAR-03).

    The clock starts at the latest of ``counted_from``, the newest version,
    ``extended`` and, for a single-use page only, ``answered``. The kind never
    moves the start, so a change of kind does not restart the clock.

    Parameters
    ----------
    entry : dict[str, Any]
        The page's ``page_meta`` entry (5.2).
    changed : float
        POSIX time of the page's newest version.

    Returns
    -------
    float | None
        Expiry time, or None for a long-term or starred page.
    """
    lifetime = LIFETIME_SECONDS[entry["kind"]]
    if lifetime is None or entry.get("starred"):
        return None
    stamps = [entry["counted_from"], entry["extended"]]
    if entry["kind"] == "single-use":
        stamps.append(entry["answered"])
    start = max([changed, *(seconds_of(s) for s in stamps if s)])
    return start + lifetime


def is_expired(entry: dict[str, Any], changed: float, now: float) -> bool:
    """Return True for a page that is not archived and is at or past its expiry."""
    when = expiry(entry, changed)
    return entry["archived"] is None and when is not None and now >= when


def due_reminders(
    pages: Iterable[tuple[str, dict[str, Any], float]], now: float
) -> list[dict[str, str]]:
    """
    Return the expired pages a reminder names now (LIFE-07).

    Parameters
    ----------
    pages : Iterable[tuple[str, dict[str, Any], float]]
        Each page's name, ``page_meta`` entry and newest-version time.
    now : float
        POSIX time.

    Returns
    -------
    list[dict[str, str]]
        ``{"page", "kind", "expired"}`` of each expired, not archived page that
        no reminder named in the last 24 h; the expiry is an ``iso`` stamp.
    """
    due = []
    for name, entry, changed in pages:
        reminded = entry["reminded"]
        if not is_expired(entry, changed, now):
            continue
        if reminded and now - seconds_of(reminded) < REMIND_SECONDS:
            continue
        when = iso(expiry(entry, changed))
        due.append({"page": name, "kind": entry["kind"], "expired": when})
    return due
