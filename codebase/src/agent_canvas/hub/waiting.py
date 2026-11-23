"""What waits in a session, and for whom (P33.3).

For the owner: the questions the agent put with the ``ask`` command (CLI-05)
and the open Ask and Do boxes of its pages. Whether one box waits (an Ask
without ``default`` or a Do, while open; A-85) is decided where a page is
scanned (``answers.py``). For the agent: the owner's queued feedback (CLI-09)
and the page reminders due now (LIFE-07). :class:`Waiting` holds this for one
session; the functions below are the views of it, and each says where it
differs from the others.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from agent_canvas.hub.watcher import is_page_name


@dataclass(frozen=True)
class Waiting:
    """
    What waits in one session, and for whom.

    Attributes
    ----------
    asks : list[dict[str, Any]]
        For the owner: open questions put with ``ask``, oldest first: ``id``,
        ``approval``, ``question`` and ``created``.
    boxes : list[dict[str, Any]]
        For the owner: the open Ask and Do boxes in page order, waiting or
        not: ``page``, ``id``, ``kind`` (``ask`` or ``do``), ``text``,
        ``waits`` and ``default``.
    feedback : list[dict[str, Any]]
        For the agent: the queued events ``pending`` hands over (CLI-09).
    reminders : list[dict[str, str]]
        For the agent: the page reminders due now (LIFE-07).
    """

    asks: list[dict[str, Any]] = field(default_factory=list)
    boxes: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    reminders: list[dict[str, str]] = field(default_factory=list)

    def count(self, kind: str) -> int:
        """Return the number of boxes of ``kind`` (``ask`` or ``do``) that wait."""
        return sum(1 for b in self.boxes if b["waits"] and b["kind"] == kind)


def agent_pages(pages: Iterable[str]) -> list[str]:
    """
    Return the pages whose boxes the agent is told about (AGI-08, ANS-04).

    Every page of the session that is not a draft, archived pages and pages
    whose file is gone included (their saved versions are read).
    """
    return [p for p in pages if is_page_name(p)]


def for_agent(summary: Waiting) -> dict[str, Any]:
    """
    Return what ``pending`` tells the agent (CLI-09, LIFE-07, AGI-08).

    ``waiting`` counts the waiting Ask boxes and ``waiting_todos`` the
    waiting Do boxes (D-65), each left out at zero. It counts no question
    put with ``ask`` (the agent gets that answer through the command or as an
    event); its boxes come from :func:`agent_pages` (A-742).

    Returns
    -------
    dict[str, Any]
        ``events`` and ``reminders``, and ``waiting`` and ``waiting_todos``
        when above zero.
    """
    told = {"events": summary.feedback, "reminders": summary.reminders}
    counts = {"waiting": summary.count("ask"), "waiting_todos": summary.count("do")}
    return told | {k: n for k, n in counts.items() if n}
