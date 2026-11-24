# ruff: noqa: F811, ANN001, E501
"""The ``result`` command, its routes and the snapshot (RES-01, RES-02, RES-03).

The owner's part is played with the cookie through the answer route (the same call
the shell makes); the browser tests click the real card.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from test_ask_cards import session  # noqa: F401
from test_mcp_server import call, mcp_env, payload  # noqa: F401

pytestmark = pytest.mark.integration

DECISION = ["--decision", "Repeat run 15?", "--choice", "Keep", "--choice", "Drop"]


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    """An HTTP client logged in as the owner window (cookie only, no key)."""
    client = httpx.Client(
        base_url=hub.base_url,
        headers={"Origin": hub.base_url, "Content-Type": "application/json"},
    )
    client.get(hub.login_url(), follow_redirects=False)
    return client


def card_of(hub, sid: str = "a") -> dict | None:  # noqa: ANN001
    return hub.state.tab_provider(sid)["result"]


def answer(owner, sid: str, body: dict) -> httpx.Response:  # noqa: ANN001
    return owner.post(f"/api/sessions/{sid}/result/answer", content=json.dumps(body))


# ---- RES-01 ------------------------------------------------------------------------


def test_res_01_the_answer_names_the_card_and_the_window(cli, session, hub) -> None:  # noqa: ANN001, F811
    result = cli("result", "Fitted modes 1-4", "--session", "a")
    assert result.code == 0
    assert set(result.json) == {"result", "window"}
    assert result.json["result"].startswith("res_")
    assert card_of(hub)["id"] == result.json["result"]


def test_res_01_files_are_stored_as_absolute_paths(cli, session, hub, home) -> None:  # noqa: ANN001, F811
    cli(
        "result", "Done", "--session", "a", "--file", "fit.py", "--file", "/abs/out.csv"
    )
    stored = [f["path"] for f in card_of(hub)["files"]]
    assert stored == [str(home / "proj" / "fit.py"), "/abs/out.csv"]


def test_res_01_the_command_creates_an_unknown_session(cli, hub) -> None:  # noqa: ANN001
    result = cli("result", "Done", "--session", "fresh")
    assert result.code == 0 and card_of(hub, "fresh")["summary"] == "Done"


def test_res_01_a_second_result_replaces_the_first(cli, session, hub) -> None:  # noqa: ANN001, F811
    first = cli("result", "one", "--session", "a", *DECISION).json["result"]
    second = cli("result", "two", "--session", "a").json["result"]
    card = card_of(hub)
    assert card["id"] == second != first and card["summary"] == "two"
    assert card["decision"] is None


@pytest.mark.parametrize(
    "args",
    [
        ["x" * 2001],
        ["ok", *["--file=/f"] * 21],
        ["ok", "--choice", "Keep", "--choice", "Drop"],
        ["ok", "--decision", "Q?"],
        ["ok", "--decision", "Q?", "--choice", "Keep"],
        ["ok", "--decision", "Q?", *["--choice=c%d" % k for k in range(7)]],
        [" "],
    ],
    ids=[
        "summary",
        "files",
        "choice-alone",
        "no-choices",
        "one-choice",
        "7-choices",
        "blank",
    ],
)
def test_res_01_each_limit_exits_2(cli, session, args) -> None:  # noqa: ANN001, F811
    result = cli("result", "--session", "a", *args)
    assert result.code == 2 and result.json["error"] == "usage"


def test_res_01_the_limits_themselves_pass(cli, session, hub) -> None:  # noqa: ANN001, F811
    args = ["x" * 2000, *["--file=/f"] * 20, "--decision", "Q?"]
    args += [f"--choice=c{k}" for k in range(6)]
    assert cli("result", "--session", "a", *args).code == 0
    assert len(card_of(hub)["choices"]) == 6


def test_res_01_the_card_survives_a_hub_restart(cli, session, hub) -> None:  # noqa: ANN001, F811
    cli("result", "Kept", "--session", "a", *DECISION)
    before = card_of(hub)["id"]
    hub.restart()
    assert card_of(hub)["id"] == before


def test_res_01_a_cookie_cannot_store_and_a_key_cannot_answer(
    cli,
    session,  # noqa: F811
    hub,  # noqa: ANN001
    owner,  # noqa: ANN001
) -> None:
    stored = owner.post("/api/sessions/a/result", content=json.dumps({"summary": "x"}))
    assert stored.status_code == 403 and card_of(hub) is None
    card = cli("result", "x", "--session", "a", *DECISION).json["result"]
    forged = httpx.post(
        f"{hub.base_url}/api/sessions/a/result/answer",
        headers=hub.key_headers,
        json={"result": card, "choice": "Keep"},
    )
    assert forged.status_code == 403
    assert hub.state.events.all("a") == []


def test_res_01_the_mcp_tool_stores_a_card(hub, session) -> None:  # noqa: ANN001, F811
    data = payload(
        call("result", session=session, summary="Done", files=["/abs/a.csv"])
    )
    assert data["result"].startswith("res_")
    assert [f["path"] for f in card_of(hub)["files"]] == ["/abs/a.csv"]


def test_res_01_the_mcp_tool_refuses_one_choice_as_a_usage_error(hub, session) -> None:  # noqa: ANN001, F811
    result = call("result", session=session, summary="x", decision="Q?", choices=["a"])
    assert result.is_error is True and payload(result)["error"] == "usage"


# ---- RES-02 ------------------------------------------------------------------------


def test_res_02_a_choice_is_one_decision_event_and_watch_delivers_it(
    cli,
    session,  # noqa: F811
    hub,  # noqa: ANN001
    owner,  # noqa: ANN001
) -> None:
    card = cli("result", "x", "--session", "a", *DECISION).json["result"]
    done = answer(owner, "a", {"result": card, "choice": "Keep"})
    assert done.status_code == 200 and done.json()["state"] == "decided"
    watched = cli("watch", "--session", "a", "--count", "1", "--timeout", "5")
    event = json.loads(watched.out.splitlines()[0])
    assert event["type"] == "event"
    assert (event["kind"], event["value"], event["delivery"]) == (
        "decision",
        "Keep",
        "now",
    )
    assert event["target"] is None and event["result"] == card
    assert card_of(hub)["state"] == "decided"


def test_res_02_a_decision_is_taken_once(cli, session, hub, owner) -> None:  # noqa: ANN001, F811
    card = cli("result", "x", "--session", "a", *DECISION).json["result"]
    assert answer(owner, "a", {"result": card, "choice": "Keep"}).status_code == 200
    assert answer(owner, "a", {"result": card, "choice": "Drop"}).status_code == 409
    assert answer(owner, "a", {"result": card, "choice": "Maybe"}).status_code == 409
    assert [e["kind"] for e in hub.state.events.all("a")] == ["decision"]


def test_res_02_dismiss_creates_no_event_and_the_card_is_gone(
    cli,
    session,  # noqa: F811
    hub,  # noqa: ANN001
    owner,  # noqa: ANN001
) -> None:
    card = cli("result", "x", "--session", "a", *DECISION).json["result"]
    done = answer(owner, "a", {"result": card, "dismiss": True})
    assert done.status_code == 200 and done.json()["event"] is None
    assert hub.state.events.all("a") == []
    assert card_of(hub) is None


def test_res_02_an_old_card_cannot_be_answered(cli, session, hub, owner) -> None:  # noqa: ANN001, F811
    old = cli("result", "x", "--session", "a", *DECISION).json["result"]
    cli("result", "y", "--session", "a", *DECISION)
    assert answer(owner, "a", {"result": old, "choice": "Keep"}).status_code == 409
    assert hub.state.events.all("a") == []


def test_res_02_a_page_in_the_folder_is_a_page_chip(cli, session, hub) -> None:  # noqa: ANN001, F811
    folder = Path(cli("session", "path", "--session", "a").json["folder"])  # POOL-01
    (folder / "plan.html").write_text("<title>p</title>")
    cli("show", "plan.html", "--session", "a")
    other = Path("/abs/plan.html")
    cli(
        "result",
        "x",
        "--session",
        "a",
        "--file",
        str(folder / "plan.html"),
        "--file",
        str(other),
    )
    assert [f["page"] for f in card_of(hub)["files"]] == ["plan.html", None]


# ---- RES-03 ------------------------------------------------------------------------
