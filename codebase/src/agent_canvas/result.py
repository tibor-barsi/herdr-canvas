"""The ``result`` command: leave a result card for the owner (RES-01)."""

from __future__ import annotations

import os
from typing import Any

from agent_canvas.client import HubClient


def send_result(
    client: HubClient,
    session_id: str,
    creation: dict[str, Any],
    summary: str,
    files: list[str],
    decision: str | None,
    choices: list[str],
) -> dict[str, Any]:
    """
    Store the session's result card and return the hub's answer.

    Parameters
    ----------
    client : HubClient
        The hub client.
    session_id : str
        The session; an unknown id creates it, as ``ask`` does (SES-03).
    creation : dict[str, Any]
        Project and agent fields for the session creation.
    summary : str
        What was done.
    files : list[str]
        Paths of the files to offer; relative ones are taken from the current
        directory.
    decision : str | None
        The question of the one decision left, or None.
    choices : list[str]
        The decision's answer buttons.

    Returns
    -------
    dict[str, Any]
        ``result`` (the card id) and ``window``.

    Raises
    ------
    CliError
        ``usage`` when the hub refuses the card (RES-01's limits).
    """
    client.request("POST", f"/api/sessions/{session_id}/path", creation)
    body = {
        "summary": summary,
        "files": [os.path.abspath(path) for path in files],
        "decision": decision,
        "choices": choices,
    }
    return client.request("POST", f"/api/sessions/{session_id}/result", body)
