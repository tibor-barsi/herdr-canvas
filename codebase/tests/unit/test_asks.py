"""Ask specs, persistence and answer validation (CLI-04, CLI-05, CLI-06, CLI-14)."""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_canvas.hub.asks import AskError, AskService, clean_spec
from agent_canvas.hub.events import EventService
from agent_canvas.hub.registry import SessionRegistry
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit


def run(coroutine):  # noqa: ANN001, ANN201
    """Run a coroutine in a fresh thread (browser tests leave a loop running)."""
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


class Setup:
    """Registry, events and ask service over a temporary state dir."""

    def __init__(self, tmp_path: Path) -> None:
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir()
        self.project = tmp_path / "project"
        self.project.mkdir()
        self.state = HubState(1, "key", time.monotonic)
        self.registry = SessionRegistry(self.state_dir, self.state)
        self.events = EventService(self.state)
        self.changes: list[tuple[str, str]] = []
        self.asks = AskService(
            self.registry,
            self.events,
            lambda kind, session_id: self.changes.append((kind, session_id)),
        )
        self.meta = self.registry.create("s1", str(self.project), "agent", None)

    def session_file(self) -> dict:
        path = self.registry.folder_of(self.meta) / "session.json"
        return json.loads(path.read_text())

    def events_file(self) -> list[dict]:
        path = self.registry.folder_of(self.meta) / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


SPEC = {"question": "Which layout?", "choices": ["A", "B"], "multi": False}


# ---- clean_spec ---------------------------------------------------------------


def test_cli_04_a_card_without_choices_has_a_text_field() -> None:
    spec = clean_spec({"question": "Name?"})
    assert spec == {
        "question": "Name?", "choices": [], "multi": False, "text": True, "block": None,
    }  # fmt: skip


def test_cli_04_choices_with_text_keep_both_inputs() -> None:
    spec = clean_spec({"question": "Q", "choices": ["A"], "text": True})
    assert spec["choices"] == ["A"] and spec["text"] is True


def test_cli_04_choices_alone_have_no_text_field() -> None:
    assert clean_spec({"question": "Q", "choices": ["A"]})["text"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {"question": ""},
        {"question": "   "},
        {"question": 3},
        {"question": "Q", "choices": "A"},
        {"question": "Q", "choices": [""]},
        {"question": "Q", "choices": [1]},
        {"question": "Q", "choices": ["A", "A"]},
        {"question": "Q", "choices": [f"c{i}" for i in range(21)]},
        {"question": "Q", "multi": True},
        {"question": "Q", "block": ""},
        {"question": "Q", "block": "x" * 201},
        {"question": "Q", "block": "d", "choices": ["A"]},
        {"question": "Q", "block": "d", "text": True},
        {"question": "x" * 2001},
    ],
)
def test_cli_04_invalid_specs_are_refused(bad) -> None:  # noqa: ANN001
    with pytest.raises(AskError):
        clean_spec(bad)


def test_cli_06_a_block_spec_has_no_inputs() -> None:
    spec = clean_spec({"question": "Pick", "block": "design"})
    assert spec["block"] == "design" and spec["choices"] == [] and not spec["text"]


# ---- registration and persistence ----------------------------------------------


def test_cli_04_register_persists_the_open_ask_in_session_json(setup) -> None:  # noqa: ANN001
    async def scenario() -> None:
        entry, waiter = setup.asks.register("s1", SPEC)
        [stored] = setup.session_file()["open_asks"]
        assert stored == entry
        assert set(stored) == {
            "ask", "question", "choices", "multi", "text", "block", "created",
        }  # fmt: skip
        assert stored["ask"].startswith("ask_") and stored["choices"] == ["A", "B"]
        assert setup.changes[-1] == ("opened", "s1")
        assert waiter.ask_id == stored["ask"]

    run(scenario())


def test_cli_05_a_detached_card_ask_stays_but_a_block_ask_goes(setup) -> None:  # noqa: ANN001
    async def scenario() -> None:
        _, card = setup.asks.register("s1", SPEC)
        _, block = setup.asks.register("s1", {"question": "P", "block": "d"})
        assert [a["waiting"] for a in setup.asks.public("s1")] == [True, True]
        setup.asks.detach(card)
        setup.asks.detach(block)
        [left] = setup.asks.public("s1")
        assert left["ask"] == card.ask_id and left["waiting"] is False
        assert [a["ask"] for a in setup.session_file()["open_asks"]] == [card.ask_id]

    run(scenario())


def test_cli_10_register_under_a_known_id_reattaches_to_the_stored_card(
    setup,  # noqa: ANN001
) -> None:
    async def scenario() -> None:
        entry, first = setup.asks.register("s1", SPEC)
        setup.asks.detach(first)
        again, second = setup.asks.register("s1", {**SPEC, "ask": entry["ask"]})
        assert again == entry and second.ask_id == entry["ask"]
        assert len(setup.asks.public("s1")) == 1
        with pytest.raises(AskError):  # a second CLI for the same ask
            setup.asks.register("s1", {**SPEC, "ask": entry["ask"]})

    run(scenario())


def test_cli_10_an_unknown_but_well_formed_id_is_recreated(setup) -> None:  # noqa: ANN001
    async def scenario() -> None:
        wanted = "ask_0123456789abcdef"
        entry, _ = setup.asks.register("s1", {**SPEC, "ask": wanted})
        assert entry["ask"] == wanted
        with pytest.raises(AskError):
            setup.asks.register("s1", {**SPEC, "ask": "../evil"})

    run(scenario())


def test_cli_10_restore_drops_block_asks_and_keeps_cards(tmp_path: Path) -> None:
    first = Setup(tmp_path)

    async def prepare() -> None:
        _, card = first.asks.register("s1", SPEC)
        first.asks.register("s1", {"question": "P", "block": "d"})
        first.asks.detach(card)

    run(prepare())
    # a new hub process reads the same state dir
    state = HubState(1, "key", time.monotonic)
    registry = SessionRegistry(first.state_dir, state)
    registry.load()
    asks = AskService(registry, EventService(state), lambda kind, session_id: None)
    asks.restore()
    [kept] = asks.public("s1")
    assert kept["question"] == "Which layout?" and kept["waiting"] is False
    meta = registry.get("s1")
    assert [a["block"] for a in meta.open_asks] == [None]


# ---- answers --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "value"),
    [
        (SPEC, ["Z"]),  # not an offered choice
        (SPEC, []),
        (SPEC, ["A", "B"]),  # single choice only
        (SPEC, "free text"),  # no text field
        (SPEC, 3),
        ({"question": "Q"}, ["A"]),  # text card, no choices
        ({"question": "Q"}, ""),
        ({"question": "Q"}, "x" * 10_001),
        ({"question": "Q", "choices": ["A"], "multi": True}, ["A", "A"]),
        ({"question": "P", "block": "d"}, "hello"),  # block asks have no card
    ],
)
def test_cli_04_invalid_answers_are_ignored_and_the_card_stays(
    setup,  # noqa: ANN001
    spec,  # noqa: ANN001
    value,  # noqa: ANN001
) -> None:
    async def scenario() -> None:
        entry, waiter = setup.asks.register("s1", spec)
        assert setup.asks.answer("s1", entry["ask"], value) is None
        assert not waiter.future.done()
        assert len(setup.asks.public("s1")) == 1
        assert setup.events.all("s1") == []

    run(scenario())


def test_cli_04_a_valid_answer_reaches_the_waiter_and_is_delivered_via_ask(
    setup,  # noqa: ANN001
) -> None:
    async def scenario() -> None:
        entry, waiter = setup.asks.register("s1", SPEC)
        event = setup.asks.answer("s1", entry["ask"], ["B"])
        assert event["kind"] == "answer" and event["value"] == ["B"]
        assert event["delivery"] == "ask" and event["state"] == "delivered"
        assert event["target"] is None
        result = waiter.future.result()
        assert result == {"status": "answered", "ask": entry["ask"], "event": event}
        assert setup.asks.public("s1") == []
        assert setup.session_file()["open_asks"] == []
        records = setup.events_file()
        assert [r["record"] for r in records] == ["event", "delivered"]
        assert records[1]["via"] == "ask"
        # a second answer finds no card
        assert setup.asks.answer("s1", entry["ask"], ["A"]) is None

    run(scenario())


def test_cli_04_multi_and_text_answers(setup) -> None:  # noqa: ANN001
    async def scenario() -> None:
        multi, _ = setup.asks.register(
            "s1", {"question": "Q", "choices": ["A", "B", "C"], "multi": True}
        )
        event = setup.asks.answer("s1", multi["ask"], ["A", "C"])
        assert event["value"] == ["A", "C"]
        both, _ = setup.asks.register(
            "s1", {"question": "Q", "choices": ["A"], "text": True}
        )
        assert setup.asks.answer("s1", both["ask"], "my own")["value"] == "my own"

    run(scenario())


def test_cli_05_a_late_answer_is_a_queued_now_event(setup) -> None:  # noqa: ANN001
    async def scenario() -> None:
        entry, waiter = setup.asks.register("s1", SPEC)
        setup.asks.detach(waiter)
        event = setup.asks.answer("s1", entry["ask"], ["A"])
        assert event["delivery"] == "now" and event["state"] == "queued"
        assert [e["id"] for e in setup.events.log("s1").queued()] == [event["id"]]
        assert setup.asks.public("s1") == []

    run(scenario())


# ---- dismissal and block routing ----------------------------------------------------


def test_cli_05_dismiss_resolves_the_waiter_with_the_reason(setup) -> None:  # noqa: ANN001
    async def scenario() -> None:
        entry, waiter = setup.asks.register("s1", SPEC)
        assert setup.asks.dismiss("s1", entry["ask"]) is True
        assert waiter.future.result() == {
            "status": "dismissed", "ask": entry["ask"],
            "event": None, "reason": "owner",
        }  # fmt: skip
        assert setup.asks.dismiss("s1", entry["ask"]) is False
        assert setup.session_file()["open_asks"] == []

    run(scenario())


def test_cli_14_dismiss_all_ends_every_waiter_with_session_ended(setup) -> None:  # noqa: ANN001
    async def scenario() -> None:
        _, one = setup.asks.register("s1", SPEC)
        _, two = setup.asks.register("s1", {"question": "P", "block": "d"})
        _, gone = setup.asks.register("s1", SPEC)
        setup.asks.detach(gone)
        setup.asks.dismiss_all("s1", "session-ended")
        for waiter in (one, two):
            assert waiter.future.result()["reason"] == "session-ended"
        assert setup.asks.public("s1") == []

    run(scenario())


def test_cli_06_only_an_attached_block_ask_intercepts_matching_events(
    setup,  # noqa: ANN001
) -> None:
    async def scenario() -> None:
        entry, waiter = setup.asks.register("s1", {"question": "P", "block": "d"})
        assert setup.asks.intercept("s1", "choice", "d") == entry["ask"]
        assert setup.asks.intercept("s1", "text", "d") == entry["ask"]
        assert setup.asks.intercept("s1", "button", "d") == entry["ask"]
        assert setup.asks.intercept("s1", "custom", "d") == entry["ask"]
        assert setup.asks.intercept("s1", "choice", "other") is None
        assert setup.asks.intercept("s1", "choice", None) is None
        assert setup.asks.intercept("s1", "send", "d") is None
        setup.asks.detach(waiter)
        assert setup.asks.intercept("s1", "choice", "d") is None

    run(scenario())
