"""The result card: one per session, stored in ``session.json`` (RES-01 to RES-03).

A result is not an ask: no command waits for it and it never makes its session
``needs-you``. The owner's choice becomes a ``decision`` event; Dismiss makes
none.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any

from agent_canvas.hub.events import EventService
from agent_canvas.hub.registry import SessionMeta, SessionRegistry, now_iso

MAX_SUMMARY_CHARS = 2000
MAX_FILES = 20
MAX_PATH_CHARS = 1000
MIN_CHOICES, MAX_CHOICES = 2, 6
MAX_DECISION_CHARS = 300
MAX_CHOICE_CHARS = 80
LINE_CHARS = 80


class ResultError(ValueError):
    """A result request is malformed, or its card does not allow the change."""


def clean_result(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a ``result`` request and return the stored card without its state.

    Parameters
    ----------
    raw : dict[str, Any]
        ``summary`` and optionally ``files`` (absolute paths), ``decision`` and
        ``choices``.

    Returns
    -------
    dict[str, Any]
        ``summary``, ``files``, ``decision`` and ``choices``.

    Raises
    ------
    ResultError
        If a field is missing, of the wrong type or beyond a limit.
    """
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ResultError("The summary must be a non-empty string.")
    if len(summary) > MAX_SUMMARY_CHARS:
        raise ResultError(f"The summary is longer than {MAX_SUMMARY_CHARS} characters.")
    decision, choices = raw.get("decision"), raw.get("choices") or []
    if decision is None:
        if choices:
            raise ResultError("--choice needs --decision.")
    else:
        _check_decision(decision, choices)
    return {
        "summary": summary.strip(),
        "files": _clean_files(raw.get("files") or []),
        "decision": decision.strip() if decision else None,
        "choices": list(choices),
    }


def _check_decision(decision: Any, choices: Any) -> None:
    if not isinstance(decision, str) or not decision.strip():
        raise ResultError("The decision must be a non-empty string.")
    if len(decision) > MAX_DECISION_CHARS:
        raise ResultError(
            f"The decision is longer than {MAX_DECISION_CHARS} characters."
        )
    if not isinstance(choices, list) or not MIN_CHOICES <= len(choices) <= MAX_CHOICES:
        raise ResultError(f"A decision needs {MIN_CHOICES} to {MAX_CHOICES} choices.")
    for label in choices:
        if not isinstance(label, str) or not label.strip():
            raise ResultError("Every choice must be a non-empty string.")
        if len(label) > MAX_CHOICE_CHARS:
            raise ResultError(f"A choice is longer than {MAX_CHOICE_CHARS} characters.")
    if len(set(choices)) != len(choices):
        raise ResultError("Choices must be distinct.")


def _clean_files(files: Any) -> list[str]:
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ResultError(f"files must be a list of at most {MAX_FILES} paths.")
    for path in files:
        if not isinstance(path, str) or not PurePath(path).is_absolute():
            raise ResultError("Every file must be an absolute path.")
        if len(path) > MAX_PATH_CHARS:
            raise ResultError(f"A path is longer than {MAX_PATH_CHARS} characters.")
    return list(files)


def summary_line(summary: str) -> str:
    """Return the first non-blank line of ``summary``, cut to 80 characters (RES-03)."""
    line = next((s.strip() for s in summary.splitlines() if s.strip()), "")
    return line if len(line) <= LINE_CHARS else line[: LINE_CHARS - 1] + "…"


class ResultService:
    """
    The result cards of all sessions.

    Parameters
    ----------
    registry : SessionRegistry
        Holds ``result`` in each ``session.json`` (5.2).
    events : EventService
        Creates the ``decision`` events.
    notify : Callable[[str], None]
        Called with the session id after every change, so that the hub can tell
        the windows.
    """

    def __init__(
        self,
        registry: SessionRegistry,
        events: EventService,
        notify: Callable[[str], None],
    ) -> None:
        self._registry = registry
        self._events = events
        self._notify = notify

    def store(self, session_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        """Store the session's result card, replacing an earlier one (RES-01)."""
        card = {
            "id": f"res_{secrets.token_hex(8)}",
            **clean_result(raw),
            "created": now_iso(),
            "state": "open",
        }
        self._registry.set_result(session_id, card)
        self._notify(session_id)
        return card

    def choose(self, session_id: str, result_id: str, label: str) -> dict[str, Any]:
        """
        Take the owner's choice: a ``decision`` event, the card decided (RES-02).

        Raises
        ------
        ResultError
            If the card is not the open one of the session, has no decision or
            does not offer ``label``.
        """
        card = self._open_card(session_id, result_id)
        if card["decision"] is None or label not in card["choices"]:
            raise ResultError("That is not a choice of this card.")
        event = self._events.create(
            session_id,
            "decision",
            delivery="now",
            value=label,
            fields={"result": result_id},
        )
        self._registry.set_result(
            session_id, {**card, "state": "decided", "decided": label}
        )
        self._notify(session_id)
        return event

    def dismiss(self, session_id: str, result_id: str) -> None:
        """Close the card without an event (RES-02)."""
        card = self._card(session_id, result_id)
        self._registry.set_result(session_id, {**card, "state": "dismissed"})
        self._notify(session_id)

    def public(self, session_id: str) -> dict[str, Any] | None:
        """
        Return the card the tab shows, or None.

        Files carry ``name`` (the base name) and ``page`` (the page name when the
        file is a page of the session's folder, else None).
        """
        meta = self._registry.get(session_id)
        card = meta.result if meta else None
        if card is None or card["state"] == "dismissed":
            return None
        folder = self._registry.folder_of(meta)
        files = [
            {"path": p, "name": Path(p).name, "page": _page_of(meta, folder, p)}
            for p in card["files"]
        ]
        return {**card, "files": files}

    def _card(self, session_id: str, result_id: str) -> dict[str, Any]:
        meta = self._registry.get(session_id)
        card = meta.result if meta else None
        if card is None or card["id"] != result_id:
            raise ResultError("That result card is no longer there.")
        return card

    def _open_card(self, session_id: str, result_id: str) -> dict[str, Any]:
        card = self._card(session_id, result_id)
        if card["state"] != "open":
            raise ResultError("That result card has been answered or closed.")
        return card


def _page_of(meta: SessionMeta, folder: Path, path: str) -> str | None:
    where = Path(path)
    if where.parent == folder and where.name in meta.pages:
        return where.name
    return None
