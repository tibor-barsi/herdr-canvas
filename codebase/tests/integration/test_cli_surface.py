"""Every command's help, the 5.7 output shapes and the speed rules (CLI-01, NFR-04)."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

COMMANDS = [
    ["hub"], ["status"], ["open"], ["session", "start"], ["session", "path"],
    ["session", "set"], ["session", "end"], ["session", "list"], ["show"], ["new"],
    ["ask"], ["result"], ["watch"], ["pending"], ["guide"], ["mcp"], ["hook"],
    ["cleanup"], ["install-service"], ["install-tunnel"], ["uninstall-tunnel"],
    ["stop"], ["page", "kind"], ["page", "archive"], ["page", "restore"],
    ["page", "extend"], ["page", "list"], ["look"], ["answers"],
    ["comment", "list"], ["comment", "reply"], ["comment", "done"],
]  # fmt: skip


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_cli_01_every_command_has_help(command, cli) -> None:  # noqa: ANN001
    result = cli(*command, "--help")
    assert result.code == 0 and result.err == ""
    assert f"usage: agent-canvas {' '.join(command)}" in result.out


def test_cli_01_hook_names_its_three_hooks(cli) -> None:  # noqa: ANN001
    out = cli("hook", "--help").out
    for name in ("session-start", "user-prompt-submit", "session-end"):
        assert name in out
    assert cli("hook", "nonsense").code == 2


# ---- shapes: field -> type, tuple of types, set of allowed values, or dict ----

STR, INT, BOOL = str, int, bool
NULL_STR = (str, type(None))
EVENT = {
    "type": {"event"}, "id": STR, "session": STR, "seq": INT, "time": STR,
    "kind": {"send", "button", "choice", "text", "answer", "custom"},
    "page": NULL_STR, "page_version": (int, type(None)), "target": (dict, type(None)),
    "delivery": {"now", "next-message", "ask"}, "state": {"queued", "delivered"},
}  # fmt: skip


def check(shape: dict, value: object, path: str = "$") -> None:
    """Assert that ``value`` has exactly the fields of ``shape`` with right types."""
    assert isinstance(value, dict), path
    missing = set(shape) - set(value)
    assert not missing, f"{path}: missing {missing}"
    for name, rule in shape.items():
        item = value[name]
        where = f"{path}.{name}"
        if isinstance(rule, dict):
            check(rule, item, where)
        elif isinstance(rule, set):
            assert item in rule, (where, item)
        elif isinstance(rule, list):  # list of items of one shape
            assert isinstance(item, list), where
            for number, element in enumerate(item):
                check(rule[0], element, f"{where}[{number}]")
        else:
            kinds = rule if isinstance(rule, tuple) else (rule,)
            assert isinstance(item, kinds), (where, item)
            assert not (isinstance(item, bool) and bool not in kinds), where


SHAPES = {
    "status": {"hub": {"running"}, "version": STR, "port": INT,
               "window_connected": BOOL, "sessions": INT},
    "open": {"window": {"connected", "launched", "launch-failed", "disabled"}},
    "session start": {"session": STR, "folder": STR},
    "session path": {"session": STR, "folder": STR},
    "session set": {"session": STR, "title": STR},
    "session end": {"session": STR, "state": {"ended"}},
    "session list": {"sessions": [{"id": STR, "project": STR, "agent": STR,
                                   "title": NULL_STR, "state": {"active", "ended"},
                                   "listening": BOOL}]},
    "show": {"session": STR, "page": STR, "path": STR, "url": STR, "version": INT,
             "window": {"connected", "launched", "launch-failed", "disabled"},
             "rendered": (bool, str),
             "errors": [{"source": STR, "message": STR, "line": (int, type(None)),
                         "canvas_id": NULL_STR}]},
    "pending": {"session": STR, "events": [EVENT]},
}  # fmt: skip


def test_cli_01_output_shapes_of_the_session_commands(cli, hub) -> None:  # noqa: ANN001
    started = cli("session", "start", "--title", "T").json
    sid = started["session"]
    s = ["--session", sid]
    (Path(started["folder"]) / "page.html").write_text("<p>x</p>")  # the pool's
    results = {
        "status": cli("status"),
        "open": cli("open"),
        "session start": cli("session", "start"),
        "session path": cli("session", "path", *s),
        "session set": cli("session", "set", "--title", "N", *s),
        "session list": cli("session", "list"),
        "show": cli("show", *s),
        "pending": cli("pending", *s),
        "session end": cli("session", "end", *s),
    }
    for name, result in results.items():
        assert result.code == 0 and result.err == "", (name, result.err)
        check(SHAPES[name], result.json, name)


def test_cli_01_pending_event_items_have_the_event_shape(cli, hub) -> None:  # noqa: ANN001
    sid = cli("session", "start").json["session"]
    hub.create_event(sid, "send", message="m", screenshot=None,
                     screenshot_error="x")  # fmt: skip
    events = cli("pending", "--session", sid).json["events"]
    assert len(events) == 1
    check(EVENT, events[0])


def test_cli_01_error_shape_on_stderr(cli, hub) -> None:  # noqa: ANN001
    result = cli("pending", "--session", "nobody")
    assert (result.code, result.out) == (5, "")
    check({"error": {"no-session"}, "message": STR}, result.json)


def run_in_thread(cli, *args: str):  # noqa: ANN001, ANN201
    box: dict = {}

    def target() -> None:
        box["result"] = cli(*args, timeout=30)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


ASK = {"status": {"answered"}, "ask": STR, "event": EVENT}


def test_cli_01_ask_answered_timeout_dismissed_shapes(cli, hub) -> None:  # noqa: ANN001
    sid = cli("session", "start").json["session"]
    timeout = cli("ask", "Q?", "--choice", "A", "--timeout", "1", "--session", sid)
    assert timeout.code == 6
    check({"status": {"timeout"}, "ask": STR, "event": (type(None),)}, timeout.json)

    for outcome in ("answered", "dismissed"):
        thread, box = run_in_thread(cli, "ask", "Q?", "--choice", "A",
                                    "--timeout", "20", "--session", sid)  # fmt: skip
        ask = hub.wait_for_ask(sid)
        if outcome == "answered":
            hub.answer_ask(sid, ask["ask"], ["A"])
        else:
            hub.dismiss_ask(sid, ask["ask"])
        thread.join(30)
        result = box["result"]
        if outcome == "answered":
            assert result.code == 0
            check(ASK, result.json)
        else:
            assert result.code == 7
            check(
                {
                    "status": {"dismissed"},
                    "ask": STR,
                    "event": (type(None),),
                    "reason": {"owner", "session-ended"},
                },
                result.json,
            )


def test_cli_01_watch_prints_events_then_the_ended_line(cli, hub) -> None:  # noqa: ANN001
    sid = cli("session", "start").json["session"]
    hub.create_event(sid, "custom", value={"name": "n", "value": 1})
    result = cli("watch", "--count", "1", "--timeout", "10", "--session", sid)
    lines = [json.loads(line) for line in result.out.splitlines()]
    check(EVENT, lines[0])
    check({"type": {"watch-ended"}, "reason": {"count", "timeout"}, "renew": BOOL},
          lines[-1])  # fmt: skip
    assert lines[-1] == {"type": "watch-ended", "reason": "count", "renew": False}


# ---- NFR-04 -------------------------------------------------------------

PROBE = """
import json, sys
from agent_canvas.cli import main
code = main(sys.argv[1:])
heavy = [m for m in ("mcp", "starlette", "uvicorn") if m in sys.modules]
sys.stderr.write("HEAVY=" + json.dumps(heavy))
sys.exit(code)
"""


def probe(cli, *args: str, input: str | None = None):  # noqa: ANN001, ANN201
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-c", PROBE, *args],
        cwd=cli.cwd, env=cli.environment, capture_output=True, text=True,
        input=input, stdin=None if input is not None else subprocess.DEVNULL,
        timeout=30,
    )  # fmt: skip
    elapsed = time.monotonic() - started
    heavy = json.loads(done.stderr.rsplit("HEAVY=", 1)[1])
    assert done.returncode == 0, done.stderr  # a failing command is not a fast one
    return elapsed, heavy


def hook_input(cli, event: str, session: str) -> str:  # noqa: ANN001
    return json.dumps({"session_id": session, "cwd": str(cli.cwd),
                       "hook_event_name": event, "prompt": "x"})  # fmt: skip


@pytest.mark.timing
def test_nfr_04_short_commands_are_fast_and_light(cli, hub) -> None:  # noqa: ANN001
    sid = cli("session", "start").json["session"]
    cases = {
        "status": (["status"], None),
        "pending": (["pending", "--session", sid], None),
        "session-start": (
            ["hook", "session-start"], hook_input(cli, "SessionStart", sid)),
        "user-prompt-submit": (
            ["hook", "user-prompt-submit"], hook_input(cli, "UserPromptSubmit", sid)),
        "session-end": (["hook", "session-end"], hook_input(cli, "SessionEnd", sid)),
    }  # fmt: skip
    for name, (args, data) in cases.items():
        runs = [probe(cli, *args, input=data) for _ in range(5)]
        median = statistics.median(elapsed for elapsed, _ in runs)
        assert median < 1.0, (name, median)
        assert all(heavy == [] for _, heavy in runs), (name, runs[0][1])
