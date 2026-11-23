"""The ``watch`` command: stream events as JSON Lines (CLI-07, CLI-08, CLI-10).

Claude's Monitor tool reads the output line by line, so every line is flushed
at once. An event is acknowledged only after its line was written and flushed.
A dropped hub connection is retried for 10 s (CLI-10); the hub then flushes the
events still queued, so nothing is lost across a restart.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from typing import Any

from agent_canvas.output import CliError
from agent_canvas.reconnect import final_error


def _write_line(payload: dict[str, Any]) -> None:
    """Write one JSON line and flush it."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def run_watch(
    socket: Any, timeout: float, count: int | None, reopen: Callable[[], Any]
) -> int:
    """
    Print events from ``socket`` until the timeout or the count is reached.

    Parameters
    ----------
    socket : websockets.sync.client.ClientConnection
        Connected watch socket.
    timeout : float
        Seconds to watch, counted across reconnects.
    count : int | None
        Stop after this many events; None means only the timeout ends it.
    reopen : Callable[[], Any]
        Returns a new connected socket after a drop, or raises a
        ``hub-unreachable`` :class:`CliError` once the retry window is over.

    Returns
    -------
    int
        Exit code 0; the last line is the ``watch-ended`` object.

    Raises
    ------
    CliError
        When the hub refuses the connection or does not come back.
    """
    from websockets.exceptions import ConnectionClosed

    deadline = time.monotonic() + timeout
    seen = 0
    try:
        while count is None or seen < count:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                event = json.loads(socket.recv(timeout=left))
                _write_line(event)
                seen += 1
                socket.send(json.dumps({"type": "ack", "id": event["id"]}))
            except TimeoutError:
                break
            except ConnectionClosed as error:
                if (refused := final_error(error)) is not None:
                    raise refused from error
                socket.close()
                socket = reopen()
    finally:
        socket.close()
    reason = "count" if count is not None and seen >= count else "timeout"
    _write_line({"type": "watch-ended", "reason": reason, "renew": reason == "timeout"})
    return 0


def collect_events(
    socket: Any, timeout: float, max_events: int, window: float = 0.2
) -> list[dict[str, Any]]:
    """
    Wait for events and return them as a batch, for ``wait_for_feedback``.

    Returns as soon as one event has arrived and no further one follows within
    ``window`` seconds (MCP-04), or when ``max_events`` are collected, or at
    the timeout. Each event is acknowledged as delivered via ``mcp``.

    Parameters
    ----------
    socket : websockets.sync.client.ClientConnection
        Connected watch socket (counts as a listener while open).
    timeout : float
        Seconds to wait for the first event.
    max_events : int
        Most events to return.
    window : float, optional
        Seconds to wait for more events after the first. Default is 0.2.

    Returns
    -------
    list[dict[str, Any]]
        The events in arrival order; empty on timeout.

    Raises
    ------
    CliError
        When the hub refuses the connection or goes away.
    """
    from websockets.exceptions import ConnectionClosed

    found: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    try:
        while len(found) < max_events:
            left = deadline - time.monotonic()
            if found:
                left = min(left, window)
            if left <= 0:
                break
            try:
                event = json.loads(socket.recv(timeout=left))
            except TimeoutError:
                break
            found.append(event)
            socket.send(json.dumps({"type": "ack", "id": event["id"], "via": "mcp"}))
    except ConnectionClosed as error:
        refused = final_error(error)
        raise refused or CliError(
            "hub-unreachable", "Lost the hub connection while waiting."
        ) from error
    finally:
        socket.close()
    return found
