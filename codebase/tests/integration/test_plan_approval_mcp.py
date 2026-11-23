# ruff: noqa: F811, ANN001, E501
"""The MCP ``ask`` tool takes ``approval`` and ``details`` (PLAN-01, MCP-02)."""

from __future__ import annotations

import threading

import pytest
from test_mcp_server import call, mcp_env, payload, session  # noqa: F401

pytestmark = pytest.mark.integration


def test_plan_01_mcp_ask_takes_approval_and_details(hub, session) -> None:  # noqa: ANN001, F811
    def answer() -> None:
        card = hub.wait_for_ask(session)
        assert card["approval"] is True and card["details"] == "all of it"
        hub.answer_ask(session, card["ask"], {"decision": "approved"})

    threading.Thread(target=answer, daemon=True).start()
    result = call(
        "ask",
        session=session,
        question="Go?",
        approval=True,
        details="all of it",
        timeout_s=20,
    )
    data = payload(result)
    assert data["status"] == "answered"
    assert data["event"]["value"] == {"decision": "approved"}


def test_plan_01_mcp_approval_with_choices_is_a_usage_error(hub, session) -> None:  # noqa: ANN001, F811
    result = call("ask", session=session, question="Go?", approval=True, choices=["A"])
    assert result.is_error is True and payload(result)["error"] == "usage"
