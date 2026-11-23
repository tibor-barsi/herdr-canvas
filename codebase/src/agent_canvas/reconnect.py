"""Reconnect rules shared by ``watch`` and ``ask`` (CLI-10).

A dropped hub connection is retried for 10 s and then ends the command with
exit 3. The retry only reconnects: it never starts a hub (CLI-12 is for the
first connection), so a hub that was stopped on purpose stays stopped.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from agent_canvas.output import CliError

CLOSE_BAD_REQUEST = 4400
CLOSE_UNAUTHORISED = 4401
CLOSE_NO_SESSION = 4404
RETRY_SECONDS = 10.0
RETRY_INTERVAL_SECONDS = 0.25


def final_error(error: Any) -> CliError | None:
    """
    Map a closed socket to the error it stands for, if the close is final.

    Parameters
    ----------
    error : websockets.exceptions.ConnectionClosed
        The exception raised when the hub closed the connection.

    Returns
    -------
    CliError | None
        An error for a close code the hub sends on purpose (refused key,
        unknown session, bad request); None when the connection merely
        dropped and a reconnect makes sense.
    """
    received = getattr(error, "rcvd", None)
    code = received.code if received else None
    if code == CLOSE_NO_SESSION:
        return CliError("no-session", "Unknown session.")
    if code == CLOSE_UNAUTHORISED:
        return CliError("unauthorised", "The hub rejected the access key.")
    if code == CLOSE_BAD_REQUEST:
        return CliError("failed", received.reason or "The hub refused the request.")
    return None


def reconnect(
    open_socket: Callable[[], Any],
    seconds: float = RETRY_SECONDS,
    pause: float = RETRY_INTERVAL_SECONDS,
) -> Any:
    """
    Open a new socket, retrying while the hub is unreachable.

    Parameters
    ----------
    open_socket : Callable[[], Any]
        Opens the socket once; raises ``hub-unreachable`` :class:`CliError`
        while the hub is down.
    seconds : float, optional
        How long to keep trying. Default is 10 s.
    pause : float, optional
        Time between attempts.

    Returns
    -------
    Any
        The new socket.

    Raises
    ------
    CliError
        ``hub-unreachable`` once ``seconds`` have passed; any other error
        from ``open_socket`` at once.
    """
    deadline = time.monotonic() + seconds
    while True:
        try:
            return open_socket()
        except CliError as error:
            if error.code != "hub-unreachable":
                raise
            if time.monotonic() + pause >= deadline:
                raise CliError(
                    "hub-unreachable",
                    f"Lost the hub connection and could not restore it within "
                    f"{seconds:.0f} s.",
                ) from error
        time.sleep(pause)
