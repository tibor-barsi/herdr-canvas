"""The ``ask`` command against a real hub (M7).

Covers CLI-04, CLI-05, CLI-06, CLI-10, CLI-14, FB-06 and FB-08. The owner's part
is played through the hub's ask service (the same calls the shell's messages
make); the browser tests click the real card.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time

import pytest
from websockets.sync.client import connect

pytestmark = pytest.mark.integration


class CliResult:
    """Exit code and output of a finished ``ask``."""

    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err

    @property
    def json(self) -> dict:
        """Parsed stdout (exit 0, 6, 7) or stderr (exit 1-5)."""
        return json.loads(self.out if self.out else self.err)


class Asking:
    """A running ``agent-canvas ask`` whose result is collected in a thread."""

    def __init__(self, cli, *args: str) -> None:  # noqa: ANN001
        self.started = time.monotonic()
        self.process = subprocess.Popen(
            [sys.executable, "-m", "agent_canvas.cli", "ask", *args],
            cwd=cli.cwd,
            env=cli.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._result: CliResult | None = None
        self.elapsed = 0.0
        self._thread = threading.Thread(target=self._collect, daemon=True)
        self._thread.start()

    def _collect(self) -> None:
        out, err = self.process.communicate()
        self.elapsed = time.monotonic() - self.started
        self._result = CliResult(self.process.returncode, out, err)

    def result(self, timeout: float = 20) -> CliResult:
        """Wait for the process to end and return its exit code and output."""
        self._thread.join(timeout)
        assert self._result is not None, "ask did not end in time"
        return self._result


@pytest.fixture
def asking(cli, hub):  # noqa: ANN001, ANN201
    started: list[Asking] = []

    def start(*args: str) -> Asking:
        ask = Asking(cli, *args)
        started.append(ask)
        return ask

    yield start
    for ask in started:
        if ask.process.poll() is None:
            ask.process.kill()
        ask._thread.join(5)


@pytest.fixture
def session(cli, hub) -> str:  # noqa: ANN001
    assert cli("session", "path", "--session", "a").code == 0
    hub.sessions["a"] = hub.state.session_of("a")
    return "a"


def events_file(hub, sid: str = "a") -> list[dict]:  # noqa: ANN001
    folder = hub.state.session_of(sid).folder
    lines = (folder / "events.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


# ---- CLI-04 -----------------------------------------------------------------------


def test_cli_04_a_choice_answer_is_printed_as_the_answer_event(
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Which layout?", "--choice", "A", "--choice", "B", "--session", "a")
    card = hub.wait_for_ask("a")
    assert card["question"] == "Which layout?" and card["choices"] == ["A", "B"]
    assert card["multi"] is False and card["text"] is False and card["block"] is None
    assert hub.answer_ask("a", card["ask"], ["B"]) is not None
    result = ask.result()
    assert result.code == 0 and result.err == ""
    body = result.json
    assert body["status"] == "answered" and body["ask"] == card["ask"]
    event = body["event"]
    assert event["type"] == "event" and event["kind"] == "answer"
    assert event["value"] == ["B"] and event["delivery"] == "ask"
    assert event["state"] == "delivered" and event["target"] is None
    delivered = [r for r in events_file(hub) if r["record"] == "delivered"]
    assert [(r["id"], r["via"]) for r in delivered] == [(event["id"], "ask")]
    assert hub.open_asks("a") == []


def test_cli_04_without_choices_the_card_takes_text(hub, session, asking) -> None:  # noqa: ANN001
    ask = asking("Part name?", "--session", "a")
    card = hub.wait_for_ask("a")
    assert card["text"] is True and card["choices"] == []
    hub.answer_ask("a", card["ask"], "bracket-7")
    event = ask.result().json["event"]
    assert event["value"] == "bracket-7" and event["delivery"] == "ask"


def test_cli_04_multi_returns_the_label_list(hub, session, asking) -> None:  # noqa: ANN001
    ask = asking("Pick", "--choice", "A", "--choice", "B", "--multi", "--session", "a")
    card = hub.wait_for_ask("a")
    assert card["multi"] is True
    hub.answer_ask("a", card["ask"], ["A", "B"])
    assert ask.result().json["event"]["value"] == ["A", "B"]


def test_cli_04_ask_creates_an_unknown_session(cli, hub, asking) -> None:  # noqa: ANN001
    ask = asking("Hello?", "--session", "fresh", "--timeout", "1")
    hub.wait_for(lambda: bool(hub.state.sessions()))
    assert ask.result().code == 6
    folder = hub.state.session_of("fresh").folder
    assert folder.is_dir() and (folder / "session.json").is_file()


def test_cli_04_ask_without_a_session_exits_5(cli) -> None:  # noqa: ANN001
    result = cli("ask", "Hello?")
    assert result.code == 5 and result.out == ""


@pytest.mark.parametrize(
    "args",
    [
        [],
        [""],
        ["Q", "--multi"],
        ["Q", "--timeout", "0"],
        ["Q", "--timeout", "-3"],
        ["Q", "--timeout", "soon"],
        ["Q", "--block", "d", "--choice", "A"],
        ["Q", "--block", "d", "--text"],
        ["Q", "--choice", "A", "--choice", "A"],
    ],
)
def test_cli_04_bad_arguments_are_usage_errors(cli, session, args) -> None:  # noqa: ANN001
    result = cli("ask", "--session", "a", *args)
    assert result.code == 2 and result.out == ""
    assert result.json["error"] == "usage"


@pytest.mark.hub_config(open_window=True)
def test_cli_04_ask_launches_the_window_when_none_is_connected(
    cli,
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Hello?", "--session", "a", "--timeout", "1")
    hub.wait_for(lambda: len(hub.launches) == 1)
    assert ask.result().code == 6


# ---- CLI-05 -----------------------------------------------------------------------


def test_cli_05_timeout_exits_6_and_the_card_stays(hub, session, asking) -> None:  # noqa: ANN001
    ask = asking("Still there?", "--choice", "yes", "--timeout", "1", "--session", "a")
    card = hub.wait_for_ask("a")
    result = ask.result()
    assert result.code == 6 and result.err == ""
    assert result.json == {"status": "timeout", "ask": card["ask"], "event": None}
    assert ask.elapsed >= 1
    hub.wait_for(lambda: hub.open_asks("a") and not hub.open_asks("a")[0]["waiting"])
    [left] = hub.open_asks("a")
    assert left["ask"] == card["ask"]


def test_cli_05_a_late_answer_is_queued_as_now_and_visible_in_pending(
    cli,
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Late?", "--choice", "yes", "--choice", "no", "--timeout", "1",
                 "--session", "a")  # fmt: skip
    card = hub.wait_for_ask("a")
    assert ask.result().code == 6
    hub.wait_for(lambda: not hub.open_asks("a")[0]["waiting"])
    event = hub.answer_ask("a", card["ask"], ["no"])
    assert event["delivery"] == "now" and event["state"] == "queued"
    assert hub.open_asks("a") == []
    [found] = cli("pending", "--session", "a").json["events"]
    assert found["id"] == event["id"] and found["kind"] == "answer"
    assert found["value"] == ["no"] and found["delivery"] == "now"


def test_cli_05_dismissal_exits_7_with_reason_owner(hub, session, asking) -> None:  # noqa: ANN001
    ask = asking("Dismiss me", "--choice", "x", "--session", "a")
    card = hub.wait_for_ask("a")
    assert hub.dismiss_ask("a", card["ask"]) is True
    result = ask.result()
    assert result.code == 7 and result.err == ""
    assert result.json == {
        "status": "dismissed", "ask": card["ask"], "event": None, "reason": "owner",
    }  # fmt: skip
    assert hub.open_asks("a") == []


def test_cli_05_dismissing_a_timed_out_card_removes_it(hub, session, asking) -> None:  # noqa: ANN001
    ask = asking("Q", "--choice", "x", "--timeout", "1", "--session", "a")
    card = hub.wait_for_ask("a")
    assert ask.result().code == 6
    hub.wait_for(lambda: not hub.open_asks("a")[0]["waiting"])
    assert hub.dismiss_ask("a", card["ask"]) is True
    assert hub.open_asks("a") == []


# ---- FB-06 and CLI-14 ---------------------------------------------------------------


def test_fb_06_the_light_is_green_while_an_ask_waits(hub, session, asking) -> None:  # noqa: ANN001
    assert not hub.listening("a")
    ask = asking("Light?", "--choice", "x", "--timeout", "2", "--session", "a")
    hub.wait_for(lambda: hub.listening("a"), timeout=15)
    assert ask.result().code == 6
    hub.wait_for(lambda: not hub.listening("a"), timeout=5)


def test_cli_14_session_end_makes_a_waiting_ask_exit_7_session_ended(
    cli,
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Anyone?", "--choice", "x", "--session", "a")
    card = hub.wait_for_ask("a")
    ended = cli("session", "end", "--session", "a")
    assert ended.code == 0 and ended.json == {"session": "a", "state": "ended"}
    result = ask.result()
    assert result.code == 7
    assert result.json == {
        "status": "dismissed", "ask": card["ask"], "event": None,
        "reason": "session-ended",
    }  # fmt: skip
    assert hub.open_asks("a") == []
    meta = json.loads((hub.state.session_of("a").folder / "session.json").read_text())
    assert meta["state"] == "ended" and meta["open_asks"] == []


def test_cli_14_the_light_of_an_ended_session_is_grey_even_with_a_listener(
    cli,
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Anyone?", "--choice", "x", "--session", "a")
    hub.wait_for_ask("a")
    assert hub.on_loop(lambda: hub.state.tab_provider("a")["listening"]) is True
    cli("session", "end", "--session", "a")
    ask.result()
    watch = connect(
        f"ws://127.0.0.1:{hub.port}/api/sessions/a/watch",
        additional_headers=hub.key_headers,
    )
    try:
        hub.wait_for(lambda: hub.listening("a"))
        assert hub.on_loop(lambda: hub.state.tab_provider("a")["listening"]) is False
        listed = cli("session", "list", "--all").json["sessions"]
        assert [s["listening"] for s in listed if s["id"] == "a"] == [False]
    finally:
        watch.close()


# ---- CLI-06 and FB-08 ------------------------------------------------------------


def test_cli_06_a_block_ask_returns_the_next_choice_event_with_delivery_ask(
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Which design?", "--block", "design", "--session", "a")
    card = hub.wait_for_ask("a")
    assert card["block"] == "design" and card["choices"] == [] and not card["text"]
    event = hub.shell_event("a", "choice", "design", ["b"])
    assert event["delivery"] == "ask"
    result = ask.result()
    assert result.code == 0
    body = result.json
    assert body["status"] == "answered" and body["ask"] == card["ask"]
    assert body["event"]["id"] == event["id"] and body["event"]["value"] == ["b"]
    assert body["event"]["kind"] == "choice" and body["event"]["delivery"] == "ask"
    assert body["event"]["target"]["canvas_id"] == "design"
    assert body["event"]["state"] == "delivered"
    assert hub.open_asks("a") == []  # the highlight goes with the entry


@pytest.mark.parametrize(
    ("kind", "value"),
    [("text", "hello"), ("button", "stop"), ("custom", {"name": "n", "value": 1})],
)
def test_cli_06_text_button_and_custom_events_also_answer_a_block_ask(
    hub,
    session,
    asking,
    kind,
    value,  # noqa: ANN001
) -> None:
    ask = asking("Go?", "--block", "b1", "--session", "a")
    hub.wait_for_ask("a")
    hub.shell_event("a", kind, "b1", value)
    event = ask.result().json["event"]
    assert event["kind"] == kind and event["value"] == value
    assert event["delivery"] == "ask"


def test_cli_06_events_from_other_elements_do_not_answer_the_ask(
    cli,
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking(
        "Which design?", "--block", "design", "--timeout", "3", "--session", "a"
    )
    hub.wait_for_ask("a")
    other = hub.shell_event("a", "choice", "elsewhere", ["a"])
    assert other["delivery"] == "now"
    assert ask.result().code == 6
    [found] = cli("pending", "--session", "a").json["events"]
    assert found["id"] == other["id"]


def test_cli_06_a_timed_out_block_ask_removes_its_entry(hub, session, asking) -> None:  # noqa: ANN001
    ask = asking("Which?", "--block", "design", "--timeout", "1", "--session", "a")
    hub.wait_for_ask("a")
    assert ask.result().code == 6
    hub.wait_for(lambda: hub.open_asks("a") == [])
    assert hub.shell_event("a", "choice", "design", ["a"])["delivery"] == "now"


def test_fb_08_the_block_event_reaches_only_the_ask_not_a_running_watch(
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    watch = connect(
        f"ws://127.0.0.1:{hub.port}/api/sessions/a/watch",
        additional_headers=hub.key_headers,
    )
    try:
        hub.wait_for(lambda: hub.listening("a"))
        ask = asking("Which?", "--block", "design", "--session", "a")
        hub.wait_for_ask("a")
        event = hub.shell_event("a", "choice", "design", ["a"])
        assert ask.result().json["event"]["id"] == event["id"]
        with pytest.raises(TimeoutError):
            watch.recv(timeout=1)  # the watch never saw it
        via = [r["via"] for r in events_file(hub) if r["record"] == "delivered"]
        assert via == ["ask"]
        # the watch still works for the next event
        follow = hub.create_event("a", "custom", value={"name": "n", "value": 1})
        assert json.loads(watch.recv(timeout=5))["id"] == follow["id"]
    finally:
        watch.close()


# ---- CLI-10 ----------------------------------------------------------------------


def test_cli_10_a_hub_restart_keeps_the_ask_and_the_answer_arrives(
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Survive?", "--choice", "yes", "--choice", "no", "--session", "a")
    card = hub.wait_for_ask("a")
    hub.restart()
    # the card is restored from session.json, then the CLI re-registers under its id
    restored = hub.wait_for_ask("a", waiting=True)
    assert restored["ask"] == card["ask"] and restored["choices"] == ["yes", "no"]
    hub.answer_ask("a", card["ask"], ["yes"])
    result = ask.result()
    assert result.code == 0 and result.json["ask"] == card["ask"]
    assert result.json["event"]["value"] == ["yes"]


def test_cli_10_a_restored_card_without_a_cli_gives_a_late_answer(hub, session) -> None:  # noqa: ANN001
    def register_and_detach() -> dict:
        entry, waiter = hub.state.asks.register(
            "a", {"question": "Q", "choices": ["x"]}
        )
        hub.state.asks.detach(waiter)
        return entry

    entry = hub.on_loop(register_and_detach)
    hub.restart()
    [card] = hub.open_asks("a")
    assert card["ask"] == entry["ask"] and card["waiting"] is False
    event = hub.answer_ask("a", entry["ask"], ["x"])
    assert event["delivery"] == "now" and event["state"] == "queued"


def test_cli_10_a_block_ask_is_registered_again_after_a_restart(
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    ask = asking("Which?", "--block", "design", "--session", "a")
    card = hub.wait_for_ask("a")
    hub.restart()
    again = hub.wait_for_ask("a")
    assert again["ask"] == card["ask"] and again["block"] == "design"
    hub.shell_event("a", "choice", "design", ["a"])
    assert ask.result().json["event"]["delivery"] == "ask"


def test_cli_10_a_watch_continues_after_a_restart_within_5_seconds(
    cli,
    hub,
    session,  # noqa: ANN001
) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", "watch", "--session", "a",
         "--timeout", "60"],
        cwd=cli.cwd, env=cli.environment, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        hub.wait_for(lambda: hub.listening("a"), timeout=15)
        hub.restart()
        hub.wait_for(lambda: hub.listening("a"), timeout=15)  # reconnected
        hub.sessions["a"] = hub.state.session_of("a")
        event = hub.create_event("a", "custom", value={"name": "n", "value": 2})
        line = json.loads(process.stdout.readline())
        assert line["id"] == event["id"]
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


def test_cli_10_a_stopped_hub_ends_watch_and_ask_with_exit_3_within_15_seconds(
    cli,
    hub,
    session,
    asking,  # noqa: ANN001
) -> None:
    watch = subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", "watch", "--session", "a",
         "--timeout", "120"],
        cwd=cli.cwd, env=cli.environment, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    ask = asking("Anyone?", "--choice", "x", "--session", "a", "--timeout", "120")
    try:
        # the ask is a listener too: wait for the watch itself, or a slow
        # watch would start a hub of its own after the stop
        hub.wait_for(lambda: "watch" in hub.listener_kinds("a"), timeout=15)
        hub.wait_for_ask("a")
        stopped = time.monotonic()
        hub.stop()
        result = ask.result(timeout=15)
        out, err = watch.communicate(timeout=15)
        assert time.monotonic() - stopped < 15
        assert result.code == 3 and result.out == ""
        assert result.json["error"] == "hub-unreachable"
        assert watch.returncode == 3 and out == ""
        assert json.loads(err)["error"] == "hub-unreachable"
        # it retried for about 10 s and did not start a hub of its own
        assert time.monotonic() - stopped >= 8
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", hub.port)) != 0
    finally:
        watch.kill()
        watch.wait()
        watch.stdout.close()
        watch.stderr.close()


def test_cli_10_a_hub_started_during_a_test_is_killed_by_kill_hubs(
    cli,  # noqa: ANN001
    hub,
) -> None:
    """The hub fixture's teardown helper finds and kills a detached hub."""
    from tests.conftest import hub_pids, kill_hubs

    hub.stop()
    spawned = subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", "hub"],
        cwd=cli.cwd, env=cli.environment, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        hub.wait_for(lambda: hub_pids(hub.state_dir) != [], timeout=15)
        kill_hubs(hub.state_dir)
        assert spawned.wait(timeout=15) != 0
        assert hub_pids(hub.state_dir) == []
    finally:
        spawned.kill()
        spawned.wait()
