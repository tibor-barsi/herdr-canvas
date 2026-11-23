"""Checks of the E-test helpers on synthetic streams (no agent, in the gate)."""

from __future__ import annotations

import json

from harness import wait_command_items

ITEMS = {"items": [{"id": "q-layout", "state": "answered", "answer": "wide"}]}


def call(use_id: str, name: str, command: str) -> dict:
    block = {
        "type": "tool_use",
        "id": use_id,
        "name": name,
        "input": {"command": command},
    }
    return {"type": "assistant", "message": {"content": [block]}}


def result(use_id: str, text: str) -> dict:
    block = {"type": "tool_result", "tool_use_id": use_id, "content": text}
    return {"type": "user", "message": {"content": [block]}}


def test_the_output_of_the_wait_call_is_parsed() -> None:
    events = [
        call("a", "Bash", "agent-canvas answers --wait q-layout --timeout 300"),
        result("a", json.dumps(ITEMS)),
    ]
    assert wait_command_items(events, "answers --wait")["q-layout"]["answer"] == "wide"


def test_another_tool_result_holding_the_ids_does_not_count() -> None:
    events = [
        call("r", "Read", "page.html"),
        result("r", json.dumps(ITEMS)),
        call("b", "Bash", "cat page.html"),
        result("b", json.dumps(ITEMS)),
    ]
    assert wait_command_items(events, "answers --wait") == {}
