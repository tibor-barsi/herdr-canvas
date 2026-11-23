"""The ``answers --wait`` command: block until named items are answered (ANS-05).

The CLI opens a WebSocket, sends the ids and the timeout once and waits for the
hub's result. The open socket is the listener that lights the tab (FB-06); the
hub removes it when the socket closes, however the wait ends.
"""

from __future__ import annotations

import json
from typing import Any

from agent_canvas.client import HubClient
from agent_canvas.output import EXIT_OK, CliError
from agent_canvas.reconnect import final_error

EXIT_TIMEOUT = 6
HUB_MARGIN_SECONDS = 10.0  # the hub keeps the time; the CLI only guards against silence


def wait_answers(
    client: HubClient,
    session_id: str,
    ids: list[str],
    page: str | None,
    timeout: float,
) -> tuple[dict[str, Any], int]:
    """
    Wait for the named items (none named: those waiting now) and return them.

    Parameters
    ----------
    client : HubClient
        Hub client (opens the socket).
    session_id : str
        Session whose pages are searched.
    ids : list[str]
        ``data-canvas-id`` of the items; empty for every waiting item.
    page : str | None
        Limit the search to this page.
    timeout : float
        Seconds to wait.

    Returns
    -------
    tuple[dict[str, Any], int]
        The 5.7 result object and the exit code (0, or 6 at the timeout).

    Raises
    ------
    CliError
        When the hub refuses the request or goes away (exit 1, 3 or 5).
    """
    from websockets.exceptions import ConnectionClosed

    socket = client.open_answers_wait(session_id)
    try:
        socket.send(json.dumps({"ids": ids, "page": page, "timeout": timeout}))
        message = json.loads(socket.recv(timeout=timeout + HUB_MARGIN_SECONDS))
    except TimeoutError as error:
        raise CliError("hub-unreachable", "The hub did not answer the wait.") from error
    except ConnectionClosed as error:
        raise final_error(error) or CliError(
            "hub-unreachable", "Lost the hub connection while waiting."
        ) from error
    finally:
        socket.close()
    body = {"session": session_id, "items": message["items"]}
    if message["status"] == "timeout":
        return {"status": "timeout", **body}, EXIT_TIMEOUT
    return body, EXIT_OK
