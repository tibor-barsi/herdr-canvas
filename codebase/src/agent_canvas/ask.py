"""The ``ask`` command: put a question to the owner and wait (CLI-04 to CLI-06).

The CLI opens a WebSocket, sends the question once, and then waits for the
hub's ``result`` message. The timeout is kept here, across reconnects (CLI-10):
on a timeout the CLI just disconnects and the hub keeps the card for a late
answer. After a drop the CLI registers again under the ask id the hub gave it.
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent_canvas.client import HubClient
from agent_canvas.output import EXIT_OK, CliError, emit_result
from agent_canvas.reconnect import final_error, reconnect

EXIT_TIMEOUT = 6
EXIT_DISMISSED = 7


MAX_DETAILS_CHARS = 4000


def build_ask_spec(
    question: str,
    choices: list[str],
    multi: bool,
    text: bool,
    block: str | None,
    approval: bool = False,
    details: str | None = None,
) -> dict[str, Any]:
    """
    Check the ask arguments and build the request body.

    Parameters
    ----------
    question : str
        The question shown on the card.
    choices : list[str]
        Answer buttons.
    multi : bool
        Allow several choices.
    text : bool
        Add a text field.
    block : str | None
        ``data-canvas-id`` to wait on instead of a card.
    approval : bool, optional
        Show an approval card with Approve and "Send back..." (PLAN-01).
    details : str | None, optional
        Text of the approval card, at most 4000 characters.

    Returns
    -------
    dict[str, Any]
        ``question``, ``choices``, ``multi``, ``text`` and ``block``; an
        approval adds ``approval`` and ``details``.

    Raises
    ------
    CliError
        ``usage`` for an empty question or a bad combination of options.
    """
    if not question.strip():
        raise CliError("usage", "The question must not be empty.")
    if multi and not choices:
        raise CliError("usage", "--multi needs at least one --choice.")
    if len(set(choices)) != len(choices):
        raise CliError("usage", "Each --choice must be different.")
    if block and (choices or text or multi):
        raise CliError(
            "usage", "--block cannot be combined with --choice/--text/--multi."
        )
    spec = {
        "question": question,
        "choices": choices,
        "multi": multi,
        "text": text,
        "block": block,
    }
    if details is not None and not approval:
        raise CliError("usage", "--details needs --approval.")
    if not approval:
        return spec
    if choices or text or multi or block:
        raise CliError(
            "usage",
            "--approval cannot be combined with --choice/--text/--multi/--block.",
        )
    if details is not None and len(details) > MAX_DETAILS_CHARS:
        raise CliError(
            "usage", f"The details are longer than {MAX_DETAILS_CHARS} characters."
        )
    return {**spec, "approval": True, "details": details}


def run_ask(
    client: HubClient, session_id: str, spec: dict[str, Any], timeout: float
) -> int:
    """
    Show the question, wait for the outcome and print the result object.

    Parameters
    ----------
    client : HubClient
        Hub client (opens the sockets).
    session_id : str
        Session whose tab shows the card.
    spec : dict[str, Any]
        ``question``, ``choices``, ``multi``, ``text`` and ``block``.
    timeout : float
        Seconds to wait, counted across reconnects.

    Returns
    -------
    int
        0 when answered, 6 on timeout, 7 when dismissed or the session ended.

    Raises
    ------
    CliError
        When the hub refuses the request or does not come back (exit 3).
    """
    result, exit_code = ask_once(client, session_id, spec, timeout)
    return emit_result(result, exit_code)


def ask_once(
    client: HubClient, session_id: str, spec: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], int]:
    """
    Show the question and wait for the outcome, without printing (MCP-02).

    Parameters
    ----------
    client : HubClient
        Hub client (opens the sockets).
    session_id : str
        Session whose tab shows the card.
    spec : dict[str, Any]
        ``question``, ``choices``, ``multi``, ``text`` and ``block``.
    timeout : float
        Seconds to wait, counted across reconnects.

    Returns
    -------
    tuple[dict[str, Any], int]
        The 5.7 result object and the exit code (0, 6 or 7).

    Raises
    ------
    CliError
        When the hub refuses the request or does not come back (exit 3).
    """
    from websockets.exceptions import ConnectionClosed

    deadline = time.monotonic() + timeout
    ask_id: str | None = None
    socket = client.open_ask(session_id)
    try:
        while True:
            try:
                socket.send(json.dumps({"type": "ask", **spec, "ask": ask_id}))
                while (message := _next(socket, deadline)) is not None:
                    if message["type"] == "registered":
                        ask_id = message["ask"]
                    elif message["type"] == "result":
                        return _result(message)
                body = {"status": "timeout", "ask": ask_id, "event": None}
                return body, EXIT_TIMEOUT
            except ConnectionClosed as error:
                if (refused := final_error(error)) is not None:
                    raise refused from error
                socket.close()
                socket = reconnect(lambda: client.open_ask(session_id, start=False))
    finally:
        socket.close()


def _next(socket: Any, deadline: float) -> dict[str, Any] | None:
    """Return the next hub message, or None when the deadline has passed."""
    left = deadline - time.monotonic()
    if left <= 0:
        return None
    try:
        return json.loads(socket.recv(timeout=left))
    except TimeoutError:
        return None


def _result(message: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Return the hub's result as the 5.7 object and its exit code."""
    status = message["status"]
    if status == "answered":
        body = {"status": status, "ask": message["ask"], "event": message["event"]}
        return body, EXIT_OK
    if status == "dismissed":
        body = {
            "status": status,
            "ask": message["ask"],
            "event": None,
            "reason": message.get("reason", "owner"),
        }
        return body, EXIT_DISMISSED
    raise CliError("failed", f"Unexpected ask result: {status!r}")
