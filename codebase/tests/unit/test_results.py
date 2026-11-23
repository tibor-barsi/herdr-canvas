"""The stored result card: limits, state changes, the event (RES-01 to RES-03)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent_canvas.hub.events import EventService
from agent_canvas.hub.registry import SessionRegistry
from agent_canvas.hub.results import (
    ResultError,
    ResultService,
    clean_result,
    summary_line,
)
from agent_canvas.hub.state import HubState

pytestmark = pytest.mark.unit

GOOD = {"summary": "Fitted modes 1-4."}
DECISION = {**GOOD, "decision": "Repeat run 15?", "choices": ["Keep", "Drop"]}


class Setup:
    """Registry, events and result service over a temporary state dir."""

    def __init__(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        self.state = HubState(1, "key", time.monotonic)
        self.registry = SessionRegistry(state_dir, self.state)
        self.events = EventService(self.state)
        self.changes: list[str] = []
        self.results = ResultService(self.registry, self.events, self.changes.append)
        self.meta = self.registry.create("s1", str(project), "agent", None)

    def stored(self) -> dict | None:
        path = self.registry.folder_of(self.meta) / "session.json"
        return json.loads(path.read_text()).get("result")


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


# ---- RES-01: limits ---------------------------------------------------------------


def test_res_01_a_summary_alone_is_a_card_without_files_or_decision() -> None:
    card = clean_result(GOOD)
    assert card["summary"] == "Fitted modes 1-4."
    assert card["files"] == [] and card["decision"] is None and card["choices"] == []


@pytest.mark.parametrize(
    "raw",
    [
        {"summary": ""},
        {"summary": "  "},
        {"summary": 3},
        {"summary": "x" * 2001},
        {**GOOD, "files": ["/a"] * 21},
        {**GOOD, "files": ["relative.txt"]},
        {**GOOD, "files": "/a"},
        {**GOOD, "choices": ["Keep", "Drop"]},
        {**GOOD, "decision": "Q?", "choices": ["Keep"]},
        {**GOOD, "decision": "Q?"},
        {**GOOD, "decision": "Q?", "choices": ["a", "b", "c", "d", "e", "f", "g"]},
        {**GOOD, "decision": "Q?", "choices": ["a", "a"]},
        {**GOOD, "decision": "Q?", "choices": ["a", ""]},
        {**GOOD, "decision": " ", "choices": ["a", "b"]},
    ],
)
def test_res_01_every_limit_is_refused(raw: dict) -> None:
    with pytest.raises(ResultError):
        clean_result(raw)


def test_res_01_the_limits_themselves_are_accepted() -> None:
    card = clean_result(
        {
            "summary": "x" * 2000,
            "files": [f"/f{k}" for k in range(20)],
            "decision": "Q?",
            "choices": list("abcdef"),
        }
    )
    assert len(card["files"]) == 20 and len(card["choices"]) == 6


def test_res_01_a_stored_card_has_the_5_2_shape(setup: Setup) -> None:
    card = setup.results.store("s1", DECISION)
    assert setup.stored() == card
    assert card["id"].startswith("res_") and card["state"] == "open"
    assert set(card) >= {"id", "summary", "files", "decision", "choices", "created"}


def test_res_01_a_second_result_replaces_the_first(setup: Setup) -> None:
    first = setup.results.store("s1", DECISION)
    second = setup.results.store("s1", GOOD)
    assert setup.stored()["id"] == second["id"] != first["id"]
    assert setup.results.public("s1")["decision"] is None


def test_res_01_the_card_is_read_again_from_session_json(setup: Setup) -> None:
    card = setup.results.store("s1", DECISION)
    again = ResultService(setup.registry, setup.events, lambda sid: None)
    assert again.public("s1")["id"] == card["id"]


# ---- RES-02: choice and dismiss ----------------------------------------------


def test_res_02_a_choice_creates_one_decision_event_and_the_card_is_decided(
    setup: Setup,
) -> None:
    card = setup.results.store("s1", DECISION)
    event = setup.results.choose("s1", card["id"], "Keep")
    assert (event["kind"], event["value"], event["delivery"]) == (
        "decision", "Keep", "now",
    )  # fmt: skip
    assert event["target"] is None and event["result"] == card["id"]
    assert setup.stored()["state"] == "decided" and setup.stored()["decided"] == "Keep"
    assert [e["kind"] for e in setup.events.all("s1")] == ["decision"]


def test_res_02_a_decision_is_taken_once_and_only_with_a_listed_choice(
    setup: Setup,
) -> None:
    card = setup.results.store("s1", DECISION)
    with pytest.raises(ResultError):
        setup.results.choose("s1", card["id"], "Maybe")
    setup.results.choose("s1", card["id"], "Drop")
    with pytest.raises(ResultError):
        setup.results.choose("s1", card["id"], "Keep")
    assert len(setup.events.all("s1")) == 1


def test_res_02_a_card_without_decision_takes_no_choice(setup: Setup) -> None:
    card = setup.results.store("s1", GOOD)
    with pytest.raises(ResultError):
        setup.results.choose("s1", card["id"], "Keep")


def test_res_02_a_choice_for_a_replaced_card_is_refused(setup: Setup) -> None:
    old = setup.results.store("s1", DECISION)
    setup.results.store("s1", DECISION)
    with pytest.raises(ResultError):
        setup.results.choose("s1", old["id"], "Keep")
    assert setup.events.all("s1") == []


def test_res_02_dismiss_creates_no_event_and_hides_the_card(setup: Setup) -> None:
    card = setup.results.store("s1", DECISION)
    setup.results.dismiss("s1", card["id"])
    assert setup.events.all("s1") == []
    assert setup.stored()["state"] == "dismissed"
    assert setup.results.public("s1") is None


def test_res_02_the_tab_card_names_page_files_and_leaves_other_files_as_paths(
    setup: Setup,
) -> None:
    folder = setup.registry.folder_of(setup.meta)
    (folder / "page.html").write_text("<title>t</title>")
    setup.registry.show("s1", "page.html", None, None)
    other = str(folder / "other.csv")
    page = str(folder / "page.html")
    setup.results.store("s1", {**GOOD, "files": [page, other, "/elsewhere/page.html"]})
    files = setup.results.public("s1")["files"]
    assert [f["path"] for f in files] == [page, other, "/elsewhere/page.html"]
    assert [f["page"] for f in files] == ["page.html", None, None]
    assert files[1]["name"] == "other.csv"


def test_res_03_the_line_is_the_first_line_cut_at_80_characters() -> None:
    assert summary_line("first\nsecond") == "first"
    assert summary_line("\n\n  first\nsecond") == "first"
    assert len(summary_line("a" * 200)) == 80
    assert summary_line("a" * 80) == "a" * 80
    assert summary_line("a" * 81).endswith("…")


def test_res_03_every_change_tells_the_windows(setup: Setup) -> None:
    card = setup.results.store("s1", DECISION)
    setup.results.choose("s1", card["id"], "Keep")
    setup.results.dismiss("s1", card["id"])
    assert setup.changes == ["s1", "s1", "s1"]
