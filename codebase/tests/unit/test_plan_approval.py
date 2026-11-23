"""Approval asks: spec, answer check, command line (PLAN-01)."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_canvas.ask import build_ask_spec
from agent_canvas.cli import build_parser
from agent_canvas.hub.asks import AskError, AskService, clean_spec
from agent_canvas.hub.events import EventService
from agent_canvas.hub.registry import SessionRegistry
from agent_canvas.hub.state import HubState
from agent_canvas.output import CliError

pytestmark = pytest.mark.unit

SPEC = {"question": "Use plan B?", "approval": True, "details": "- one\n- two"}


def test_plan_01_an_approval_spec_has_details_and_no_inputs() -> None:
    spec = clean_spec(SPEC)
    assert spec["approval"] is True and spec["details"] == "- one\n- two"
    assert spec["choices"] == [] and spec["text"] is False and spec["block"] is None


def test_plan_01_details_are_optional() -> None:
    assert clean_spec({"question": "Q", "approval": True})["details"] is None


def test_plan_01_a_plain_question_spec_is_unchanged() -> None:
    assert "approval" not in clean_spec({"question": "Q", "choices": ["A"]})


@pytest.mark.parametrize(
    "extra",
    [
        {"choices": ["A"]},
        {"multi": True},
        {"text": True},
        {"block": "d"},
        {"details": 5},
        {"details": "x" * 4001},
    ],
)
def test_plan_01_an_approval_with_other_inputs_or_bad_details_is_refused(extra) -> None:  # noqa: ANN001
    with pytest.raises(AskError):
        clean_spec({"question": "Q", "approval": True, **extra})


def test_plan_01_details_of_4000_characters_pass_and_details_alone_are_refused() -> (
    None
):
    assert clean_spec({"question": "Q", "approval": True, "details": "x" * 4000})
    with pytest.raises(AskError):
        clean_spec({"question": "Q", "details": "text"})


def test_plan_01_the_command_line_refuses_mixed_options() -> None:
    assert build_ask_spec("Q", [], False, False, None, True, "d")["approval"] is True
    bad = [
        ("Q", ["A"], False, False, None, True, None),
        ("Q", [], True, False, None, True, None),
        ("Q", [], False, True, None, True, None),
        ("Q", [], False, False, "d", True, None),
        ("Q", [], False, False, None, False, "text"),
        ("Q", [], False, False, None, True, "x" * 4001),
    ]
    for args in bad:
        with pytest.raises(CliError) as error:
            build_ask_spec(*args)
        assert error.value.code == "usage"


def test_plan_01_details_and_details_file_exclude_each_other() -> None:
    parser = build_parser()
    with pytest.raises(CliError):
        parser.parse_args(
            ["ask", "Q", "--approval", "--details", "a", "--details-file", "b"]
        )


# ---- answers ------------------------------------------------------------------------


def run(coroutine):  # noqa: ANN001, ANN201
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


@pytest.fixture
def service(tmp_path: Path) -> AskService:
    (tmp_path / "state").mkdir()
    state = HubState(1, "key", time.monotonic)
    registry = SessionRegistry(tmp_path / "state", state)
    registry.create("s1", str(tmp_path), "agent", None)
    return AskService(registry, EventService(state), lambda kind, session_id: None)


@pytest.mark.parametrize(
    "value",
    [
        ["approved"],
        "approved",
        {"decision": "approved", "reason": "x"},
        {"decision": "maybe"},
        {"decision": "sent-back"},
        {"decision": "sent-back", "reason": ""},
        {"decision": "sent-back", "reason": "   "},
        {"decision": "sent-back", "reason": "x" * 301},
        {"decision": "sent-back", "reason": 3},
        {"decision": "sent-back", "reason": "ok", "always": True},
        {"decision": "always-approve"},
    ],
)
def test_plan_01_an_answer_that_is_not_a_decision_is_ignored(service, value) -> None:  # noqa: ANN001
    async def scenario() -> None:
        entry, waiter = service.register("s1", SPEC)
        assert service.answer("s1", entry["ask"], value) is None
        assert not waiter.future.done()

    run(scenario())


@pytest.mark.parametrize(
    "value",
    [{"decision": "approved"}, {"decision": "sent-back", "reason": "x" * 300}],
)
def test_plan_01_a_decision_reaches_the_waiting_command(service, value) -> None:  # noqa: ANN001
    async def scenario() -> None:
        entry, waiter = service.register("s1", SPEC)
        event = service.answer("s1", entry["ask"], value)
        assert event["value"] == value and event["delivery"] == "ask"
        assert waiter.future.result()["event"]["value"] == value

    run(scenario())


def test_plan_01_a_decision_does_not_answer_a_question_card(service) -> None:  # noqa: ANN001
    async def scenario() -> None:
        entry, _ = service.register("s1", {"question": "Q", "choices": ["A"]})
        assert service.answer("s1", entry["ask"], {"decision": "approved"}) is None

    run(scenario())
