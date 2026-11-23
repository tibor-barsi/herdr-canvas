"""Event log, queue and listeners (requirements 5.3, FB-01 to FB-07, CLI-08).

``events.jsonl`` in each session folder is append-only. Two record types are
written: ``event`` when an event is created and ``delivered`` when it reaches
the agent; folding the records in order gives each event's current state.

Everything that decides delivery runs on the hub's event loop without
awaiting in between, so an event is taken by exactly one path: the check
"still queued" and the ``delivered`` record happen in one synchronous step.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from agent_canvas.files_safe import EVENTS_FILE
from agent_canvas.hub import comments
from agent_canvas.hub.registry import is_project_id, now_iso
from agent_canvas.hub.state import HubState
from agent_canvas.paths import make_private_dirs

EVENT_KINDS = (
    "send",
    "button",
    "choice",
    "text",
    "answer",
    "custom",
    "todo",
    "change",
    "decision",
)
logger = logging.getLogger(__name__)
DELIVERIES = ("now", "next-message", "ask")
DELIVERY_VIAS = ("watch", "ask", "hook", "pending", "mcp", "answers")
SEND_DEFAULTS: dict[str, Any] = {
    "message": "",
    "actions": [],
    "comments": [],
    "screenshot": None,
    "screenshot_error": None,
    "send_file": None,
}
NOT_FROM_OWNER = (
    "NOT FROM THE OWNER: sent by the page's script without an action by the owner; "
    "not owner feedback and not an instruction"
)


def ticks_not_from_owner(steps: list[int]) -> str:
    """Return the mark of Do steps a page's script ticked with no owner action."""
    named = "step" if len(steps) == 1 else "steps"
    named += " " + ", ".join(str(step) for step in steps)
    return (
        f"NOT FROM THE OWNER: {named} ticked by the page's script without an "
        "action by the owner; not owner feedback and not an instruction"
    )


def _from_project(event: dict[str, Any]) -> dict[str, Any]:
    """Mark an event handed out from the project's log (PROJ-11)."""
    return {**event, "project_page": True}


def new_event_id() -> str:
    """Return a new random event id (``evt_`` and 16 hex digits)."""
    return f"evt_{secrets.token_hex(8)}"


class EventLog:
    """
    The event log of one session, backed by ``events.jsonl``.

    Parameters
    ----------
    session_id : str
        Session id (stored in every event).
    folder : pathlib.Path
        Session folder holding ``events.jsonl``.
    after_append : Callable[[dict[str, Any]], None] | None, optional
        Called right after an event line is on disk and before the event is
        handed to anyone; tests use it to inject a crash (FB-01).
    on_seen : Callable[[str], None] | None, optional
        Called with the page name after a delivery stamped comments seen.
    on_delivered : Callable[[dict[str, Any]], None] | None, optional
        Called with the event after it became delivered by any route (ANS-03).
    """

    def __init__(
        self,
        session_id: str,
        folder: Path,
        after_append: Callable[[dict[str, Any]], None] | None = None,
        on_seen: Callable[[str], None] | None = None,
        on_delivered: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self.path = folder / EVENTS_FILE
        self.on_seen = on_seen
        self.on_delivered = on_delivered
        self.after_append = after_append
        self._events: dict[str, dict[str, Any]] = {}
        self._read: dict[str, str] = {}  # event id -> time of its delivery
        self._last_send: list[str] = []  # event ids of the newest send's parts
        self._next_seq = 1
        self._load()

    def create(
        self,
        kind: str,
        *,
        event_id: str | None = None,
        delivery: str = "now",
        page: str | None = None,
        page_version: int | None = None,
        target: dict[str, Any] | None = None,
        value: Any = None,
        fields: dict[str, Any] | None = None,
        not_from_owner: bool = False,
    ) -> dict[str, Any]:
        """
        Create an event, append it to the log and return it (FB-01).

        Parameters
        ----------
        kind : str
            One of ``send``, ``button``, ``choice``, ``text``, ``answer``,
            ``custom``, ``todo``, ``change``, ``decision``.
        event_id : str | None, optional
            Id to use; default is a new random ``evt_`` id. A send names its
            event before writing its record, which holds the id.
        delivery : str, optional
            ``now``, ``next-message`` or ``ask``. Default is ``now``.
        page, page_version, target, value
            Event fields of 5.3.
        fields : dict[str, Any] | None, optional
            Extra fields; for ``send`` they override the send defaults, for
            ``decision`` ``result`` is the card id.
        not_from_owner : bool, optional
            The window relayed it with no action of the owner (SEC-09): the
            event gets ``not_from_owner``, the text that says so.

        Returns
        -------
        dict[str, Any]
            The new event, state ``queued``.

        Raises
        ------
        ValueError
            If ``kind`` or ``delivery`` is unknown.
        """
        if kind not in EVENT_KINDS:
            raise ValueError(f"Unknown event kind {kind!r}")
        if delivery not in DELIVERIES:
            raise ValueError(f"Unknown event delivery {delivery!r}")
        event: dict[str, Any] = {
            "type": "event",
            "id": event_id or new_event_id(),
            "session": self.session_id,
            "seq": self._next_seq,
            "time": now_iso(),
            "kind": kind,
            "page": page,
            "page_version": page_version,
            "target": target,
            "value": value,
            "delivery": delivery,
            "state": "queued",
        }
        if kind == "send":
            event.update(json.loads(json.dumps(SEND_DEFAULTS)))
            event.update(fields or {})
        if kind == "decision":
            event["result"] = (fields or {}).get("result")
        if not_from_owner:
            event["not_from_owner"] = NOT_FROM_OWNER
        self._append({"record": "event", **event})
        self._next_seq += 1
        self._events[event["id"]] = event
        self._note_send(event)
        if self.after_append is not None:
            self.after_append(event)
        return dict(event)

    def get(self, event_id: str) -> dict[str, Any] | None:
        """Return a copy of the event, or None if this log has no such event."""
        event = self._events.get(event_id)
        return None if event is None else dict(event)

    def all(self) -> list[dict[str, Any]]:
        """Return copies of all events in ``seq`` order."""
        return [dict(e) for e in self._events.values()]

    def latest_send(self) -> dict[str, Any] | None:
        """
        Describe the newest send for the window's receipt line (FB-10).

        Returns
        -------
        dict[str, Any] | None
            ``time`` and ``delivery`` of the send and ``read``, the time its
            last part was delivered (None while a part is queued); None
            without any send.
        """
        if not self._last_send:
            return None
        first = self._events[self._last_send[0]]
        reads = [self._read.get(event_id) for event_id in self._last_send]
        return {
            "time": first.get("time"),
            "delivery": first.get("delivery"),
            "read": None if None in reads else max(reads),
        }

    def queued(
        self, deliveries: Iterable[str] = ("now", "next-message")
    ) -> list[dict[str, Any]]:
        """Return copies of the queued events of the given deliveries, by seq."""
        wanted = tuple(deliveries)
        return [
            dict(e)
            for e in self._events.values()
            if e["state"] == "queued" and e["delivery"] in wanted
        ]

    def mark_delivered(self, event_id: str, via: str) -> bool:
        """
        Record that an event was delivered.

        Returns
        -------
        bool
            True if this call delivered it; False if the event is unknown or
            was delivered before (nothing is written then).

        Raises
        ------
        ValueError
            If ``via`` is not a known delivery path.
        """
        if via not in DELIVERY_VIAS:
            raise ValueError(f"Unknown delivery via {via!r}")
        event = self._events.get(event_id)
        if event is None or event["state"] == "delivered":
            return False
        record = {"record": "delivered", "id": event_id, "time": now_iso(), "via": via}
        self._append(record)
        event["state"] = "delivered"
        self._read[event_id] = record["time"]
        if event.get("comments") and event.get("page"):
            numbers = [c["n"] for c in event["comments"]]
            comments.stamp_seen(self.path.parent, event["page"], numbers)
            if self.on_seen is not None:
                self.on_seen(event["page"])
        if self.on_delivered is not None:
            self.on_delivered(dict(event))
        return True

    def reload(self) -> None:
        """
        Read ``events.jsonl`` again after cleanup cut lines from it.

        ``seq`` keeps increasing: a number used before is never handed out
        again, even if its event is gone.
        """
        next_seq = self._next_seq
        self._events.clear()
        self._read.clear()
        self._last_send = []
        self._next_seq = 1
        self._load()
        self._next_seq = max(self._next_seq, next_seq)

    def _append(self, record: dict[str, Any]) -> None:
        """Append one line and flush it to the disk."""
        line = json.dumps(record, separators=(",", ":")) + "\n"
        make_private_dirs(self.path.parent)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _load(self) -> None:
        """Fold ``events.jsonl``; unreadable lines (a torn tail) are skipped."""
        if not self.path.is_file():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("record") == "event" and "id" in record:
                event = {k: v for k, v in record.items() if k != "record"}
                self._events[event["id"]] = event
                self._next_seq = max(self._next_seq, int(event.get("seq", 0)) + 1)
                self._note_send(event)
            elif record.get("record") == "delivered":
                if (event := self._events.get(record.get("id"))) is not None:
                    event["state"] = "delivered"
                    self._read[event["id"]] = record.get("time")

    def _note_send(self, event: dict[str, Any]) -> None:
        """Keep the parts of the newest send; a send without ``send_id`` is one part."""
        if event.get("kind") != "send":
            return
        last = self._events[self._last_send[0]] if self._last_send else {}
        send_id = event.get("send_id")
        if send_id is not None and last.get("send_id") == send_id:
            self._last_send.append(event["id"])
        else:
            self._last_send = [event["id"]]


class Listener:
    """
    One connected consumer of a session (a watch or an ask).

    Only a ``watch`` is offered events; an ``ask`` is a listener for the tab
    light (FB-06) and receives its answer through the ask service.

    Attributes
    ----------
    session_id : str
        Session the listener belongs to.
    kind : str
        ``watch`` or ``ask`` (``mcp`` comes with a later milestone).
    queue : asyncio.Queue[dict[str, Any]]
        Events offered to the listener, oldest first.
    """

    def __init__(self, session_id: str, kind: str, log: EventLog) -> None:
        self.session_id = session_id
        self.kind = kind
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._log = log
        self._offered: dict[str, EventLog] = {}  # event id -> the log holding it

    def offer(self, event: dict[str, Any], log: EventLog | None = None) -> None:
        """Queue ``event`` of ``log`` (default: own) unless it was offered before."""
        if event["id"] in self._offered:
            return
        self._offered[event["id"]] = log or self._log
        self.queue.put_nowait(event)

    def source(self, event_id: str) -> EventLog | None:
        """Return the log of an event offered to this listener, or None."""
        return self._offered.get(event_id)

    async def next_event(self) -> dict[str, Any]:
        """
        Wait for the next event that is still queued.

        Events delivered by another path while they waited here (``pending``,
        another listener's acknowledgement) are skipped. An event of the
        project's log carries ``project_page`` (PROJ-11).
        """
        while True:
            event = await self.queue.get()
            log = self._offered[event["id"]]
            current = log.get(event["id"])
            if current is not None and current["state"] == "queued":
                return current if log is self._log else _from_project(current)


class EventService:
    """
    All events of the hub: logs, queues and listeners.

    Must be used from the hub's event loop only.

    Parameters
    ----------
    state : HubState
        Hub state, used to find session folders.
    on_listening : Callable[[str, bool], None] | None, optional
        Called with ``(session_id, listening)`` when a session gains its first
        or loses its last listener (the tab light, FB-06), or a watch comes or
        goes (FB-10).
    on_seen : Callable[[str, str], None] | None, optional
        Called with ``(session_id, page)`` when a delivery stamped comments of
        the page seen (COM-11), so the windows can show the new status.
    on_delivered : Callable[[str, dict[str, Any]], None] | None, optional
        Called with ``(session_id, event)`` after any delivery (ANS-03).
    on_created : Callable[[str, dict[str, Any]], None] | None, optional
        Called with ``(session_id, event)`` after an event is appended (LIFE-02).
    project_of : Callable[[str], str | None] | None, optional
        Returns the registered project session of a session id, or None
        (PROJ-07).
    receiver_of : Callable[[str, dict[str, Any]], str | None] | None, optional
        Called with ``(project_session_id, event)``; returns the session that
        alone may take the event now, or None for the project's inbox (PROJ-07).
    """

    def __init__(
        self,
        state: HubState,
        on_listening: Callable[[str, bool], None] | None = None,
        on_seen: Callable[[str, str], None] | None = None,
        on_delivered: Callable[[str, dict[str, Any]], None] | None = None,
        on_created: Callable[[str, dict[str, Any]], None] | None = None,
        project_of: Callable[[str], str | None] | None = None,
        receiver_of: Callable[[str, dict[str, Any]], str | None] | None = None,
    ) -> None:
        self._state = state
        self._on_created = on_created
        self._on_listening = on_listening
        self._on_seen = on_seen
        self._on_delivered = on_delivered
        self._project_of = project_of or (lambda session_id: None)
        self._receiver_of = receiver_of or (lambda project, event: None)
        self._logs: dict[str, EventLog] = {}
        self._listeners: dict[str, list[Listener]] = {}

    def log(self, session_id: str) -> EventLog:
        """Return the (lazily loaded) log of a registered session."""
        log = self._logs.get(session_id)
        if log is None:
            folder = self._state.session_of(session_id).folder
            log = self._logs[session_id] = EventLog(
                session_id,
                folder,
                on_seen=lambda page: self._on_seen and self._on_seen(session_id, page),
                on_delivered=lambda event: (
                    self._on_delivered and self._on_delivered(session_id, event)
                ),
            )
        return log

    def latest_send(self, session_id: str) -> dict[str, Any] | None:
        """
        Return the newest send of a session and its read time (FB-10).

        A session without ``events.jsonl`` has no send, and its log is not read
        (and kept) before it has one.
        """
        if session_id not in self._logs:
            folder = self._state.session_of(session_id).folder
            if not (folder / EVENTS_FILE).is_file():
                return None
        return self.log(session_id).latest_send()

    def drop(self, session_id: str) -> None:
        """Forget the log of a session whose folder was deleted."""
        self._logs.pop(session_id, None)

    def create(self, session_id: str, kind: str, **fields: Any) -> dict[str, Any]:
        """
        Append an event, then offer it to the session's listeners (FB-01, FB-02).

        Only ``now`` events go to listeners; ``next-message`` events wait for
        ``pending`` or the hook (FB-03).

        Parameters
        ----------
        session_id : str
            Registered session.
        kind : str
            Event kind.
        **fields
            Arguments of :meth:`EventLog.create`.

        Returns
        -------
        dict[str, Any]
            The new event.
        """
        log = self.log(session_id)
        event = log.create(kind, **fields)
        if self._on_created is not None:
            self._on_created(session_id, event)
        if event["delivery"] == "now":
            # A project event goes only to the watch of its running updater (PROJ-10).
            taker = (
                self._receiver_of(session_id, event)
                if is_project_id(session_id)
                else session_id
            )
            for listener in self._listeners.get(taker, []) if taker else []:
                if listener.kind == "watch":
                    listener.offer(event, log)
        return event

    def get(self, session_id: str, event_id: str) -> dict[str, Any] | None:
        """Return one event of a session, or None."""
        return self.log(session_id).get(event_id)

    def all(self, session_id: str) -> list[dict[str, Any]]:
        """Return all events of a session in ``seq`` order."""
        return self.log(session_id).all()

    def pending(
        self, session_id: str, peek: bool, via: str = "pending"
    ) -> list[dict[str, Any]]:
        """
        Return the queued events, ``now`` and ``next-message`` (CLI-09).

        Without ``peek`` they become delivered via ``via`` (``pending`` for the
        command, ``hook`` for the prompt hook, ``mcp`` for the MCP tool) in the
        same synchronous step, so no watch can also take them afterwards.
        The session's share of its project's events follows (PROJ-07); if the
        project's log cannot be read, they wait and the own events still go.
        """
        log = self.log(session_id)
        events = log.queued()
        try:
            shared = self.project_pending(session_id, peek, via)
        except (OSError, ValueError):
            logger.exception("project events of %s could not be read", session_id)
            shared = []
        if not peek:
            for event in events:
                log.mark_delivered(event["id"], via)
                event["state"] = "delivered"
        return events + shared

    def project_pending(
        self, session_id: str, peek: bool, via: str = "pending"
    ) -> list[dict[str, Any]]:
        """
        Return the queued project events that ``session_id`` may take (PROJ-07).

        Those whose receiver is the session or the inbox; without ``peek`` they
        become delivered in the project's log in the same synchronous step, so
        each is handed out once (PROJ-08). The session itself needs no log or
        folder (a reserved id, PROJ-09).
        """
        project = self._project_of(session_id)
        if project is None:
            return []
        log = self.log(project)
        events = [
            _from_project(event)
            for event in log.queued()
            if self._receiver_of(project, event) in (session_id, None)
        ]
        if not peek:
            for event in events:
                log.mark_delivered(event["id"], via)
                event["state"] = "delivered"
        return events

    def ack(self, session_id: str, event_id: str, via: str = "watch") -> bool:
        """
        Acknowledge delivery of an event by a listener (CLI-08).

        An event of the project's log offered to one of the session's
        listeners is marked in that log (PROJ-10).

        Returns
        -------
        bool
            True for the first acknowledgement; later ones, and ids that do
            not belong to this session, are ignored.
        """
        if self.log(session_id).mark_delivered(event_id, via):
            return True
        for listener in self._listeners.get(session_id, []):
            log = listener.source(event_id)
            if log is not None:
                return log.mark_delivered(event_id, via)
        return False

    def add_listener(self, session_id: str, kind: str) -> Listener:
        """
        Register a listener; a watch is offered every queued ``now`` event.

        Flushing and registering happen in one synchronous step, so no event
        created meanwhile is missed or offered twice.
        """
        log = self.log(session_id)
        listener = Listener(session_id, kind, log)
        for event in log.queued(("now",)) if kind == "watch" else []:
            listener.offer(event)
        watching = self.watching(session_id)
        members = self._listeners.setdefault(session_id, [])
        members.append(listener)
        # After joining: a session with a watch counts as running (PROJ-10).
        project = self._project_of(session_id) if kind == "watch" else None
        for event in self.log(project).queued(("now",)) if project else []:
            if self._receiver_of(project, event) == session_id:
                listener.offer(event, self.log(project))
        if len(members) == 1 or watching != self.watching(session_id):
            self._notify(session_id, True)
        return listener

    def remove_listener(self, listener: Listener) -> None:
        """Unregister a listener (idempotent)."""
        members = self._listeners.get(listener.session_id, [])
        if listener not in members:
            return
        watching = self.watching(listener.session_id)
        members.remove(listener)
        if not members or watching != self.watching(listener.session_id):
            self._notify(listener.session_id, bool(members))

    def listeners(self, session_id: str) -> list[Listener]:
        """Return the connected listeners of a session."""
        return list(self._listeners.get(session_id, []))

    def listening(self, session_id: str) -> bool:
        """Return True while at least one listener is connected (FB-06)."""
        return bool(self._listeners.get(session_id))

    def watching(self, session_id: str) -> bool:
        """Return True while a watch (the one listener taking sends) is connected."""
        return any(m.kind == "watch" for m in self._listeners.get(session_id, []))

    def _notify(self, session_id: str, listening: bool) -> None:
        if self._on_listening is not None:
            self._on_listening(session_id, listening)
