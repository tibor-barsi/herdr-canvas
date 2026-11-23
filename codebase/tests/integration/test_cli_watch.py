"""The ``watch`` and ``pending`` commands (CLI-07, CLI-09, FB-03, SES-03)."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.integration


class Watching:
    """A running ``agent-canvas watch`` whose stdout is read line by line."""

    def __init__(self, cli, *args: str) -> None:  # noqa: ANN001
        self.process = subprocess.Popen(
            [sys.executable, "-m", "agent_canvas.cli", "watch", *args],
            cwd=cli.cwd,
            env=cli.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.process.stdout:  # type: ignore[union-attr]
            self.lines.put(line)

    def line(self, timeout: float = 10) -> dict:
        """Next stdout line as JSON (fails the test on timeout)."""
        return json.loads(self.lines.get(timeout=timeout))

    def rest(self, timeout: float = 10) -> list[dict]:
        """Wait for exit and return all remaining lines."""
        self.process.wait(timeout=timeout)
        found = []
        while not self.lines.empty():
            found.append(json.loads(self.lines.get()))
        return found


@pytest.fixture
def watching(cli, hub):  # noqa: ANN001, ANN201
    started: list[Watching] = []

    def start(*args: str) -> Watching:
        watch = Watching(cli, *args)
        started.append(watch)
        return watch

    yield start
    for watch in started:
        if watch.process.poll() is None:
            watch.process.kill()
        watch.process.wait()
        watch.process.stdout.close()
        watch.process.stderr.close()


@pytest.fixture
def session(cli, hub) -> str:  # noqa: ANN001
    assert cli("session", "path", "--session", "a").code == 0
    hub.sessions["a"] = hub.state.session_of("a")
    return "a"


def wait_listening(hub, session_id: str = "a") -> None:  # noqa: ANN001
    hub.wait_for(lambda: hub.listening(session_id), timeout=15)


# ---- CLI-07 -------------------------------------------------------------------


def test_cli_07_queued_now_events_are_printed_first_then_count_ends_the_watch(
    cli, hub, session, watching
) -> None:
    first = hub.create_event("a", "send", message="one")
    hub.create_event("a", "send", message="later", delivery="next-message")
    second = hub.create_event("a", "custom", value={"name": "n", "value": 2})
    watch = watching("--session", "a", "--count", "2")
    assert watch.line()["id"] == first["id"]  # flushed on connect, in seq order
    assert watch.line()["id"] == second["id"]
    assert watch.line() == {"type": "watch-ended", "reason": "count", "renew": False}
    assert watch.process.wait(10) == 0
    hub.wait_for(lambda: hub.event_state("a", second["id"]) == "delivered")
    # the next-message event was never printed and is still there for pending
    [left] = cli("pending", "--session", "a").json["events"]
    assert left["delivery"] == "next-message"


def test_cli_07_a_live_event_is_flushed_as_one_line_while_the_watch_runs(
    cli, hub, session, watching
) -> None:
    watch = watching("--session", "a", "--timeout", "60")
    wait_listening(hub)
    event = hub.create_event("a", "send", message="live")
    line = watch.line(timeout=5)  # the process is still running: it flushed
    assert watch.process.poll() is None
    assert line["id"] == event["id"]
    assert line["type"] == "event" and line["message"] == "live"
    hub.wait_for(lambda: hub.event_state("a", event["id"]) == "delivered")
    watch.process.terminate()


def test_cli_07_count_one_ends_after_the_first_event(
    cli, hub, session, watching
) -> None:
    watch = watching("--session", "a", "--count", "1")
    wait_listening(hub)
    event = hub.create_event("a", "custom")
    assert watch.line()["id"] == event["id"]
    assert watch.line() == {"type": "watch-ended", "reason": "count", "renew": False}
    assert watch.process.wait(10) == 0
    assert watch.process.stderr.read() == ""
    hub.wait_for(lambda: not hub.listening("a"))


def test_cli_07_timeout_2_ends_cleanly_with_the_specified_last_line(
    cli, hub, session, watching
) -> None:
    started = time.monotonic()
    watch = watching("--session", "a", "--timeout", "2")
    wait_listening(hub)
    lines = watch.rest(timeout=15)
    assert lines == [{"type": "watch-ended", "reason": "timeout", "renew": True}]
    assert watch.process.returncode == 0
    assert time.monotonic() - started >= 2
    assert watch.process.stderr.read() == ""
    hub.wait_for(lambda: not hub.listening("a"))


BAD_ARGS = [["--timeout", "0"], ["--count", "0"], ["--timeout", "soon"]]


@pytest.mark.parametrize("args", BAD_ARGS)
def test_cli_07_out_of_range_arguments_are_usage_errors(cli, session, args) -> None:
    assert cli("watch", "--session", "a", *args).code == 2


def test_cli_07_unknown_session_exits_5_without_creating_it(cli, hub) -> None:
    result = cli("watch", "--session", "ghost", "--timeout", "2")
    assert result.code == 5 and result.out == ""
    assert result.json["error"] == "no-session"


def test_cli_07_no_session_id_exits_5(cli) -> None:
    assert cli("watch").code == 5


# ---- FB-03 --------------------------------------------------------------------


def test_fb_03_watch_never_prints_next_message_events(
    cli, hub, session, watching
) -> None:
    hub.create_event("a", "send", delivery="next-message", message="queued before")
    watch = watching("--session", "a", "--timeout", "2")
    wait_listening(hub)
    hub.create_event("a", "send", delivery="next-message", message="live")
    assert watch.rest(timeout=15) == [
        {"type": "watch-ended", "reason": "timeout", "renew": True}
    ]
    events = cli("pending", "--session", "a").json["events"]
    assert [e["message"] for e in events] == ["queued before", "live"]


# ---- CLI-09 -------------------------------------------------------------------


def test_cli_09_two_pending_calls_return_the_events_once_and_peek_twice(
    cli, hub, session
) -> None:
    first = hub.create_event("a", "send", message="one")
    second = hub.create_event("a", "send", delivery="next-message", message="two")
    ids = [first["id"], second["id"]]
    peek = [cli("pending", "--session", "a", "--peek").json for _ in range(2)]
    assert [[e["id"] for e in p["events"]] for p in peek] == [ids, ids]
    assert peek[0]["session"] == "a"
    taken = cli("pending", "--session", "a")
    assert taken.code == 0 and [e["id"] for e in taken.json["events"]] == ids
    assert cli("pending", "--session", "a").json == {
        "session": "a",
        "events": [],
        "reminders": [],
    }


def test_cli_09_unknown_id_exits_5(cli) -> None:
    result = cli("pending", "--session", "ghost")
    assert result.code == 5 and result.json["error"] == "no-session"


def test_cli_09_pending_events_use_the_event_object_shape(cli, hub, session) -> None:
    hub.create_event("a", "send", message="m", page="page.html")
    [event] = cli("pending", "--session", "a").json["events"]
    assert event["type"] == "event" and event["session"] == "a"
    assert event["kind"] == "send" and event["message"] == "m"
    assert event["state"] == "delivered"  # taken by this call


# ---- FB-07 --------------------------------------------------------------------


def test_fb_07_pending_after_a_hub_restart_returns_the_queued_event(
    cli, hub, session
) -> None:
    event = hub.create_event("a", "send", message="survives")
    hub.restart()
    [again] = cli("pending", "--session", "a").json["events"]
    assert again["id"] == event["id"] and again["message"] == "survives"
