"""Question cards: ``ask`` and ``ask --block`` (CLI-04, CLI-05, CLI-06, FB-08).

An open ask is stored in the session's ``session.json`` as ``open_asks`` (5.2),
so that its card comes back after a hub restart. Whether a CLI is attached to
it (``waiting``) lives only in memory: a card whose CLI went away (timeout,
crash) stays until the owner answers or dismisses it, and its answer becomes a
queued ``now`` event.

Everything here runs on the hub's event loop without awaiting, so an answer is
taken by exactly one path.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_canvas.hub.events import EventService
from agent_canvas.hub.registry import SessionRegistry, now_iso

ASK_ID = re.compile(r"^ask_[0-9a-f]{16}$")
BLOCK_KINDS = ("choice", "text", "button", "custom", "answer", "todo", "change")
MAX_QUESTION_CHARS = 2000
MAX_CHOICES = 20
MAX_CHOICE_CHARS = 200
MAX_BLOCK_CHARS = 200
MAX_ANSWER_CHARS = 10_000
MAX_DETAILS_CHARS = 4000
MAX_REASON_CHARS = 300


class AskError(ValueError):
    """An ask request is malformed or its ask id is already in use."""


@dataclass
class Waiter:
    """
    A CLI attached to an ask.

    Attributes
    ----------
    ask_id : str
        Id of the ask the CLI waits for.
    session_id : str
        Session of the ask.
    future : asyncio.Future[dict[str, Any]]
        Resolved with the result message (``answered`` or ``dismissed``).
    """

    ask_id: str
    session_id: str
    future: asyncio.Future[dict[str, Any]]


def clean_spec(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Validate an ask request and return the stored fields of 5.2.

    Parameters
    ----------
    raw : dict[str, Any]
        Request with ``question`` and optionally ``choices``, ``multi``,
        ``text``, ``block``, ``approval`` and ``details`` (PLAN-01).

    Returns
    -------
    dict[str, Any]
        ``question``, ``choices``, ``multi``, ``text`` and ``block``; an
        approval adds ``approval`` (True) and ``details``. A card without
        choices always has a text field, except an approval.

    Raises
    ------
    AskError
        If a field is missing, of the wrong type or out of range.
    """
    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        raise AskError("The question must be a non-empty string.")
    if len(question) > MAX_QUESTION_CHARS:
        raise AskError(f"The question is longer than {MAX_QUESTION_CHARS} characters.")
    choices = _clean_choices(raw.get("choices", []))
    multi, text = bool(raw.get("multi")), bool(raw.get("text"))
    block = _clean_block(raw.get("block"))
    if multi and not choices:
        raise AskError("--multi needs at least one choice.")
    if block is not None and (choices or text or multi):
        raise AskError("A block ask takes no choices, text field or multi.")
    spec = {
        "question": question.strip(),
        "choices": choices,
        "multi": multi,
        "text": False if block is not None else (text or not choices),
        "block": block,
    }
    approval = raw.get("approval")
    details = raw.get("details")
    if not approval:
        if details is not None:
            raise AskError("details belong to an approval.")
        return spec
    if choices or text or multi or block is not None:
        raise AskError("An approval takes no choices, text field, multi or block.")
    if details is not None and not isinstance(details, str):
        raise AskError("details must be a string.")
    if details is not None and len(details) > MAX_DETAILS_CHARS:
        raise AskError(f"The details are longer than {MAX_DETAILS_CHARS} characters.")
    return {
        **spec,
        "text": False,
        "approval": True,
        "details": details.strip() if details else None,
    }


def _clean_choices(value: Any) -> list[str]:
    """Return the choice labels or raise :class:`AskError`."""
    if not isinstance(value, list):
        raise AskError("choices must be a list of labels.")
    if len(value) > MAX_CHOICES:
        raise AskError(f"At most {MAX_CHOICES} choices are allowed.")
    for label in value:
        if not isinstance(label, str) or not label.strip():
            raise AskError("Every choice must be a non-empty string.")
        if len(label) > MAX_CHOICE_CHARS:
            raise AskError(f"A choice is longer than {MAX_CHOICE_CHARS} characters.")
    if len(set(value)) != len(value):
        raise AskError("Choices must be distinct.")
    return list(value)


def _clean_block(value: Any) -> str | None:
    """Return the block id or None; raise :class:`AskError` for a bad one."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_BLOCK_CHARS:
        raise AskError(
            f"block must be a canvas id of 1 to {MAX_BLOCK_CHARS} characters."
        )
    return value


def _valid_answer(entry: dict[str, Any], value: Any) -> bool:
    """Check an owner's answer against the card it answers."""
    if entry["block"] is not None:
        return False  # a block ask is answered inside the page
    if entry.get("approval"):
        return _valid_decision(value)
    if isinstance(value, str):
        return (
            entry["text"]
            and 0 < len(value.strip())
            and (len(value) <= MAX_ANSWER_CHARS)
        )
    if not isinstance(value, list) or not entry["choices"]:
        return False
    picked_ok = all(isinstance(v, str) and v in entry["choices"] for v in value)
    distinct = len(set(map(str, value))) == len(value)
    right_count = len(value) >= 1 and (entry["multi"] or len(value) == 1)
    return picked_ok and distinct and right_count


def _valid_decision(value: Any) -> bool:
    """Check PLAN-01's answer: approved, or sent back with a reason."""
    if value == {"decision": "approved"}:
        return True
    if not isinstance(value, dict) or set(value) != {"decision", "reason"}:
        return False
    reason = value["reason"]
    return (
        value["decision"] == "sent-back"
        and isinstance(reason, str)
        and 0 < len(reason.strip())
        and len(reason) <= MAX_REASON_CHARS
    )


class AskService:
    """
    Open asks of all sessions and the CLIs waiting for them.

    Parameters
    ----------
    registry : SessionRegistry
        Holds ``open_asks`` in each ``session.json``.
    events : EventService
        Creates the ``answer`` events.
    notify : Callable[[str, str], None]
        Called with ``("opened", session_id)`` for a new ask and
        ``("changed", session_id)`` for any other change, so that the hub can
        tell the shells.
    """

    def __init__(
        self,
        registry: SessionRegistry,
        events: EventService,
        notify: Callable[[str, str], None],
    ) -> None:
        self._registry = registry
        self._events = events
        self._notify = notify
        self._waiters: dict[str, Waiter] = {}

    def restore(self) -> None:
        """
        Tidy ``open_asks`` after a hub start (CLI-10).

        Question cards stay and come back in the shell. Block asks are dropped
        (the CLI registers them again, which restores the highlight), and so
        is everything of an ended session.
        """
        for meta in self._registry.list(True, None):
            stored = meta.get("open_asks", [])
            ended = meta["state"] == "ended"
            kept = [] if ended else [a for a in stored if a.get("block") is None]
            if kept != stored:
                self._registry.set_open_asks(meta["id"], kept)

    def open_asks(self, session_id: str) -> list[dict[str, Any]]:
        """Return the stored open asks of a session, oldest first."""
        meta = self._registry.get(session_id)
        return [] if meta is None else list(meta.open_asks)

    def public(self, session_id: str) -> list[dict[str, Any]]:
        """Return the open asks, each with ``waiting`` (a CLI is attached)."""
        return [
            {**entry, "waiting": entry["ask"] in self._waiters}
            for entry in self.open_asks(session_id)
        ]

    def register(
        self, session_id: str, raw: dict[str, Any]
    ) -> tuple[dict[str, Any], Waiter]:
        """
        Attach a CLI to an ask, creating the ask unless it is already stored.

        Parameters
        ----------
        session_id : str
            Known session.
        raw : dict[str, Any]
            Request as for :func:`clean_spec`, plus ``ask`` (the id of an ask
            to re-attach to after a reconnect or a hub restart).

        Returns
        -------
        tuple[dict[str, Any], Waiter]
            The stored ask and the waiter; must run inside the event loop.

        Raises
        ------
        AskError
            If the request is invalid or another CLI already waits for the id.
        """
        requested = raw.get("ask")
        if requested is not None and not (
            isinstance(requested, str) and ASK_ID.match(requested)
        ):
            raise AskError("Malformed ask id.")
        ask_id = requested or f"ask_{secrets.token_hex(8)}"
        if ask_id in self._waiters:
            raise AskError(f"Another command already waits for {ask_id}.")
        stored = self.open_asks(session_id)
        entry = next((a for a in stored if a["ask"] == ask_id), None)
        created = entry is None
        if entry is None:
            entry = {"ask": ask_id, **clean_spec(raw), "created": now_iso()}
            self._registry.set_open_asks(session_id, [*stored, entry])
        future = asyncio.get_running_loop().create_future()
        waiter = Waiter(ask_id, session_id, future)
        self._waiters[ask_id] = waiter
        self._notify("opened" if created else "changed", session_id)
        return dict(entry), waiter

    def detach(self, waiter: Waiter) -> None:
        """
        Detach a CLI (timeout, disconnect, or after its result).

        A question card stays for a late answer; a block ask has nothing left
        to answer and goes, which removes the highlight.
        """
        if self._waiters.get(waiter.ask_id) is not waiter:
            return
        del self._waiters[waiter.ask_id]
        entry = self._entry(waiter.session_id, waiter.ask_id)
        if entry is not None and entry["block"] is not None:
            self._remove(waiter.session_id, waiter.ask_id)
        self._notify("changed", waiter.session_id)

    def answer(self, session_id: str, ask_id: str, value: Any) -> dict[str, Any] | None:
        """
        Record the owner's answer on a card (CLI-04, CLI-05).

        Returns
        -------
        dict[str, Any] | None
            The ``answer`` event: delivery ``ask`` and ``delivered`` when a CLI
            was waiting, else delivery ``now`` and ``queued``. None when there
            is no such card or the value does not fit it (nothing changes).
        """
        entry = self._entry(session_id, ask_id)
        if entry is None or not _valid_answer(entry, value):
            return None
        waiter = self._live_waiter(ask_id)
        event = self._events.create(
            session_id, "answer", delivery="ask" if waiter else "now", value=value
        )
        self._remove(session_id, ask_id)
        if waiter is not None:
            event = self._deliver(session_id, event["id"])
            waiter.future.set_result(
                {"status": "answered", "ask": ask_id, "event": event}
            )
        self._notify("changed", session_id)
        return event

    def dismiss(self, session_id: str, ask_id: str, reason: str = "owner") -> bool:
        """
        Dismiss an ask; a waiting CLI ends with ``dismissed`` (CLI-05).

        Parameters
        ----------
        session_id, ask_id : str
            The ask.
        reason : str, optional
            ``owner`` (default) or ``session-ended``.

        Returns
        -------
        bool
            False if the ask was not open.
        """
        if self._entry(session_id, ask_id) is None:
            return False
        self._remove(session_id, ask_id)
        if (waiter := self._live_waiter(ask_id)) is not None:
            waiter.future.set_result(
                {"status": "dismissed", "ask": ask_id, "event": None, "reason": reason}
            )
        self._notify("changed", session_id)
        return True

    def dismiss_all(self, session_id: str, reason: str) -> None:
        """Dismiss every open ask of a session (``session end``, CLI-14)."""
        for entry in self.open_asks(session_id):
            self.dismiss(session_id, entry["ask"], reason)

    def intercept(
        self, session_id: str, kind: str, canvas_id: str | None
    ) -> str | None:
        """
        Return the ask that an event from a page element would answer (FB-08).

        Parameters
        ----------
        session_id : str
            Session of the event.
        kind : str
            Event kind.
        canvas_id : str | None
            ``data-canvas-id`` of the element the event came from.

        Returns
        -------
        str | None
            The id of an ``ask --block`` that waits on that element with a CLI
            attached, else None.
        """
        if kind not in BLOCK_KINDS or not canvas_id:
            return None
        for entry in self.open_asks(session_id):
            if entry["block"] == canvas_id and self._live_waiter(entry["ask"]):
                return entry["ask"]
        return None

    def complete_block(self, session_id: str, ask_id: str, event_id: str) -> None:
        """Hand an event created for an awaited block to its waiting CLI."""
        waiter = self._live_waiter(ask_id)
        self._remove(session_id, ask_id)
        event = self._deliver(session_id, event_id)
        if waiter is not None:
            waiter.future.set_result(
                {"status": "answered", "ask": ask_id, "event": event}
            )
        self._notify("changed", session_id)

    # ---- internals ---------------------------------------------------------

    def _entry(self, session_id: str, ask_id: str) -> dict[str, Any] | None:
        return next((a for a in self.open_asks(session_id) if a["ask"] == ask_id), None)

    def _live_waiter(self, ask_id: str) -> Waiter | None:
        waiter = self._waiters.get(ask_id)
        return waiter if waiter is not None and not waiter.future.done() else None

    def _remove(self, session_id: str, ask_id: str) -> None:
        kept = [a for a in self.open_asks(session_id) if a["ask"] != ask_id]
        self._registry.set_open_asks(session_id, kept)

    def _deliver(self, session_id: str, event_id: str) -> dict[str, Any]:
        """Mark an event delivered via ``ask`` and return its current state."""
        self._events.log(session_id).mark_delivered(event_id, "ask")
        event = self._events.get(session_id, event_id)
        assert event is not None
        return event
