# ruff: noqa: F811, ANN001, E501
"""``ask --approval`` against a real hub (PLAN-01): details, answers, exit codes, MCP."""

from __future__ import annotations

import pytest
from test_ask_cards import asking, session  # noqa: F401

pytestmark = pytest.mark.integration


def test_plan_01_the_card_carries_the_details_and_an_approval_is_the_answer(
    hub,  # noqa: ANN001
    session,  # noqa: ANN001, F811
    asking,  # noqa: ANN001, F811
) -> None:
    ask = asking(
        "Use plan B?", "--approval", "--details", "- one\n- two", "--session", "a"
    )
    card = hub.wait_for_ask("a")
    assert card["approval"] is True and card["details"] == "- one\n- two"
    assert card["choices"] == [] and card["text"] is False
    assert hub.answer_ask("a", card["ask"], {"decision": "approved"}) is not None
    result = ask.result()
    assert result.code == 0
    assert result.json["event"]["value"] == {"decision": "approved"}
    assert result.json["event"]["delivery"] == "ask"


def test_plan_01_send_back_returns_the_reason(hub, session, asking) -> None:  # noqa: ANN001, F811
    ask = asking("Use plan B?", "--approval", "--session", "a")
    card = hub.wait_for_ask("a")
    assert card["details"] is None
    hub.answer_ask("a", card["ask"], {"decision": "sent-back", "reason": "too slow"})
    value = ask.result().json["event"]["value"]
    assert value == {"decision": "sent-back", "reason": "too slow"}


def test_plan_01_details_come_from_a_file(hub, session, asking, tmp_path) -> None:  # noqa: ANN001, F811
    path = tmp_path / "plan.txt"
    path.write_text("1. first\n2. second\n")
    ask = asking("Go?", "--approval", "--details-file", str(path), "--session", "a")
    card = hub.wait_for_ask("a")
    assert card["details"] == "1. first\n2. second"
    hub.dismiss_ask("a", card["ask"])
    assert ask.result().code == 7


def test_plan_01_the_timeout_and_dismissal_exit_codes_are_those_of_ask(
    hub,  # noqa: ANN001
    session,  # noqa: ANN001, F811
    asking,  # noqa: ANN001, F811
) -> None:
    assert (
        asking("Go?", "--approval", "--timeout", "1", "--session", "a").result().code
        == 6
    )
    assert hub.open_asks("a")  # the card stays for a late answer


@pytest.mark.parametrize(
    "args",
    [
        ["--choice", "A"],
        ["--text"],
        ["--multi"],
        ["--block", "d"],
        ["--details-file", "/no/such/file"],
    ],
)
def test_plan_01_approval_with_other_inputs_or_a_missing_file_exits_2(
    cli, session, args
) -> None:  # noqa: ANN001, F811
    result = cli("ask", "Q", "--approval", "--session", "a", *args)
    assert result.code == 2 and result.json["error"] == "usage"


def test_plan_01_details_without_approval_exit_2(cli, session) -> None:  # noqa: ANN001, F811
    result = cli("ask", "Q", "--details", "text", "--session", "a")
    assert result.code == 2 and result.json["error"] == "usage"
