"""Claude Code hooks (``agent-canvas hook <name>``).

Hooks run on the owner's prompt path, so they follow three rules: they are
fast (standard library only, lazy imports, a short timeout), they never start
the hub, and they never fail: every problem ends in exit 0 with no output, so
a dead hub or a bad input cannot block or break a prompt (PLG-04 to PLG-06).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

HOOK_TIMEOUT_SECONDS = 2.0
AGENT_NAME = "claude-code"
HOOK_NAMES = ("session-start", "user-prompt-submit", "session-end", "stop")
STOP_REMINDER = (
    "agent-canvas: a question you put on the canvas is still open and nothing is "
    "listening for the answer. Start `agent-canvas watch --timeout 540` under "
    "Monitor, or tell the owner to reply in the terminal when they have answered."
)
STOP_REMINDER_COUNTED = (  # a Do box waits too (D-65)
    "agent-canvas: {} on the canvas and nothing is listening. Start "
    "`agent-canvas watch --timeout 540` under Monitor, or tell the owner to reply "
    "in the terminal when they have answered."
)
ITEM_EVENTS = ("answer", "todo", "change")  # one line each when they name a card
NOTE_CHARS = 200


def run_hook(
    name: str, stdin: TextIO, stdout: TextIO, environ: Mapping[str, str]
) -> int:
    """
    Run one hook and write its JSON output, if any.

    Parameters
    ----------
    name : str
        One of ``session-start``, ``user-prompt-submit``, ``session-end``, ``stop``.
    stdin : TextIO
        Hook input as Claude Code sends it (a JSON object).
    stdout : TextIO
        Where the hook's JSON object goes.
    environ : Mapping[str, str]
        Environment (``CLAUDE_ENV_FILE`` and the hub settings).

    Returns
    -------
    int
        Always 0: a hook must never block or break the owner's prompt.
    """
    try:
        data = _read_input(stdin)
        session_id = _session_id(data)
        if session_id is None:
            return 0
        handler = {
            "session-start": _session_start,
            "user-prompt-submit": _user_prompt_submit,
            "session-end": _session_end,
            "stop": _stop,
        }[name]
        context = handler(session_id, data, environ)
        if context:
            event = _EVENT_NAMES[name]
            output = {"hookSpecificOutput": {"hookEventName": event}}
            output["hookSpecificOutput"]["additionalContext"] = context
            stdout.write(json.dumps(output) + "\n")
            stdout.flush()
    except Exception:  # noqa: BLE001 - a hook must never fail the prompt
        return 0
    return 0


_EVENT_NAMES = {
    "session-start": "SessionStart",
    "user-prompt-submit": "UserPromptSubmit",
    "session-end": "SessionEnd",
    "stop": "Stop",
}


def main(name: str) -> int:
    """
    Run a hook with the process's standard streams and environment.

    Parameters
    ----------
    name : str
        Hook name, see :func:`run_hook`.

    Returns
    -------
    int
        Always 0.
    """
    return run_hook(name, sys.stdin, sys.stdout, os.environ)


def format_events(events: list[dict[str, Any]]) -> str:
    """
    Render queued events as compact text for the model (PLG-05).

    Parameters
    ----------
    events : list[dict[str, Any]]
        Event objects of requirements 5.3.

    Returns
    -------
    str
        Text with the message, actions, mark summaries and screenshot path of
        each event, or the reason there is no screenshot.
    """
    lines = ["Feedback from the owner in the agent-canvas window:"]
    for number, event in enumerate(events, 1):
        lines.extend(_event_lines(number, event))
    return "\n".join(lines)


def closing_lines(
    events: list[dict[str, Any]], waiting: int, todos: int = 0
) -> list[str]:
    """
    Return the lines that say what to do about the delivered events (AGI-07, AGI-08).

    Parameters
    ----------
    events : list[dict[str, Any]]
        The events delivered with this prompt.
    waiting : int
        Number of Asks on shown pages that still wait for an answer.
    todos : int, optional
        Number of Do boxes on shown pages that still wait (D-65).

    Returns
    -------
    list[str]
        The "act on it" line when an answer, todo or change of the owner was
        delivered (not one marked ``not_from_owner``, SEC-09), and the
        "questions wait" line when ``waiting`` or ``todos`` is above zero.
    """
    lines = []
    owned = [e for e in events if not e.get("not_from_owner")]
    if any(e.get("kind") in ITEM_EVENTS for e in owned):
        lines.append(
            "Act on the answers, todos and changes above, say so in your reply, "
            "and record decisions in the project's decision log."
        )
    if waiting or todos:
        lines.append(f"agent-canvas: {_what_waits(waiting, todos)} on the canvas.")
    return lines


def _what_waits(questions: int, todos: int) -> str:
    """Return e.g. ``1 question waits`` or ``2 questions and 1 to-do wait``."""
    parts = [
        f"{n} {word if n == 1 else word + 's'}"
        for n, word in ((questions, "question"), (todos, "to-do"))
        if n
    ]
    verb = "waits" if questions + todos == 1 else "wait"
    return f"{' and '.join(parts)} {verb}"


def format_reminders(reminders: list[dict[str, str]]) -> str:
    """
    Render the reminder line for expired pages (LIFE-07).

    Parameters
    ----------
    reminders : list[dict[str, str]]
        ``{"page", "kind", "expired"}`` as ``pending`` returns them.

    Returns
    -------
    str
        One line naming each page with its kind and how long ago it expired.
    """
    from agent_canvas.hub import clock
    from agent_canvas.hub.lifetime import DAY_SECONDS

    now = clock.now()
    named = []
    for reminder in reminders:
        days = int((now - clock.seconds_of(reminder["expired"])) // DAY_SECONDS)
        ago = "today" if days < 1 else f"{days} day{'s' * (days > 1)} ago"
        named.append(f"{reminder['page']} ({reminder['kind']}, expired {ago})")
    count = len(named)
    head = (
        "1 page past its lifetime"
        if count == 1
        else f"{count} pages past their lifetime"
    )
    return (
        f"agent-canvas: {head}: {', '.join(named)}. "
        "Not needed any more: agent-canvas page archive NAME. "
        "Still needed: agent-canvas page extend NAME, "
        "or agent-canvas page kind NAME long-term."
    )


# ---- handlers -------------------------------------------------------------


def _read_input(stdin: TextIO) -> dict[str, Any]:
    """Parse the hook input; anything but a JSON object gives an empty dict."""
    if stdin.isatty():
        return {}
    try:
        data = json.load(stdin)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _session_id(data: dict[str, Any]) -> str | None:
    """Return the valid session id of the hook input, or None."""
    from agent_canvas.paths_safe import InvalidSessionId, validate_session_id

    try:
        return validate_session_id(str(data.get("session_id", "")))
    except InvalidSessionId:
        return None


def _hub_request(
    path: str, body: dict[str, Any], timeout: float = HOOK_TIMEOUT_SECONDS
) -> Any:
    """POST to the hub if it is running; None when it is not (never starts it)."""
    from agent_canvas.client import HubClient
    from agent_canvas.config import ConfigError, load_config
    from agent_canvas.output import CliError
    from agent_canvas.paths import state_dir

    try:
        client = HubClient(load_config(), state_dir())
        return client.request("POST", path, body, start=False, timeout=timeout)
    except (CliError, ConfigError):
        return None


def _session_start(
    session_id: str, data: dict[str, Any], environ: Mapping[str, str]
) -> str:
    """Export the session to Bash, reserve its id if the hub is up, give id and core."""
    from agent_canvas.guide_text import core_text

    cwd = str(data.get("cwd") or os.getcwd())
    _append_env_file(environ.get("CLAUDE_ENV_FILE"), session_id, cwd)
    # Only a reservation: the folder, tab and watcher appear on first use (SES-10).
    _hub_request(
        f"/api/sessions/{session_id}/reserve", {"project": cwd, "agent": AGENT_NAME}
    )
    return (
        f"Your agent-canvas session id is {session_id}; pass it as `session` to "
        "agent-canvas MCP tools. AGENT_CANVAS_SESSION is set for Bash.\n\n"
        + core_text()  # every source, so it comes back after compaction (AGI-10)
    )


def _append_env_file(path: str | None, session_id: str, cwd: str) -> None:
    """Append the three ``export`` lines to ``CLAUDE_ENV_FILE`` (PLG-04)."""
    if not path:
        return
    values = {
        "AGENT_CANVAS_SESSION": session_id,
        "AGENT_CANVAS_AGENT": AGENT_NAME,
        "AGENT_CANVAS_PROJECT": cwd,
    }
    text = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in values.items())
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(text)


def _user_prompt_submit(
    session_id: str, data: dict[str, Any], environ: Mapping[str, str]
) -> str:
    """Hand the queued events to the model as context (PLG-05)."""
    answer = _hub_request(f"/api/sessions/{session_id}/pending", {"via": "hook"})
    if not isinstance(answer, dict):
        return ""
    parts = []
    if answer.get("events"):
        parts.append(format_events(answer["events"]))
    parts.extend(
        closing_lines(
            answer.get("events") or [],
            answer.get("waiting", 0),
            answer.get("waiting_todos", 0),
        )
    )
    if answer.get("reminders"):
        parts.append(format_reminders(answer["reminders"]))
    return "\n".join(parts)


def _session_end(
    session_id: str, data: dict[str, Any], environ: Mapping[str, str]
) -> str:
    """Mark the session ended if the hub is up (PLG-06); no output."""
    _hub_request(f"/api/sessions/{session_id}/end", {})
    return ""


def _stop(session_id: str, data: dict[str, Any], environ: Mapping[str, str]) -> str:
    """Remind once per turn that an open Ask or Do has no listener (AGI-20)."""
    if data.get("stop_hook_active"):
        return ""
    answer = _hub_request(
        f"/api/sessions/{session_id}/pending", {"via": "hook", "peek": True}
    )
    if not isinstance(answer, dict):
        return ""
    waiting, todos = answer.get("waiting", 0), answer.get("waiting_todos", 0)
    if not (waiting or todos) or answer.get("listening") is not False:
        return ""
    if not _first_stop_of_turn(session_id, str(data.get("prompt_id", ""))):
        return ""
    if not todos:
        return STOP_REMINDER
    return STOP_REMINDER_COUNTED.format(_what_waits(waiting, todos))


def _first_stop_of_turn(session_id: str, turn: str) -> bool:
    """Record ``turn`` (the prompt id) for the session; False if already recorded."""
    from agent_canvas.paths import state_dir

    stamp = state_dir() / "stop-reminded" / session_id
    if stamp.is_file() and stamp.read_text(encoding="utf-8") == turn:
        return False
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(turn, encoding="utf-8")
    return True


# ---- text -----------------------------------------------------------------


def _event_lines(number: int, event: dict[str, Any]) -> list[str]:
    """Lines describing one event; a mark the hub gave it comes first (SEC-09)."""
    lines = _event_text(number, event)
    if event.get("not_from_owner"):
        lines[0] = f"[{event['not_from_owner']}] {lines[0]}"
    return lines


def _event_text(number: int, event: dict[str, Any]) -> list[str]:
    """Lines describing one event."""
    kind = event.get("kind", "event")
    if (
        kind in ITEM_EVENTS
        and event.get("page")
        and (event.get("target") or {}).get("canvas_id")
    ):
        return [_item_line(event)]
    head = f"{number}. {kind}"
    if event.get("target"):
        head += f" on {_target_text(event['target'])}"
    if event.get("page"):
        word = "project page" if event.get("project_page") else "page"
        head += f" ({word} {event['page']}, version {event.get('page_version')})"
    if kind != "send":
        return [f"{head}: {json.dumps(event.get('value'))}"]
    lines = [f"{head}: {json.dumps(event.get('message', ''), ensure_ascii=False)}"]
    lines.append("   " + _screenshot_text(event))
    for action in event.get("actions") or []:
        lines.append("   action: " + _action_text(action))
    for mark in event.get("marks") or []:
        lines.append("   mark: " + _mark_text(mark))
    comments = event.get("comments") or []
    for comment in comments:
        lines.extend(_comment_lines(comment, event.get("time")))
    if comments:
        flag = " --project-page" if event.get("project_page") else ""
        lines.append(
            f"Answer each: agent-canvas comment reply{flag} {event.get('page')} "
            'N "text" [--done]'
        )
    return lines


def _item_line(event: dict[str, Any]) -> str:
    """One line for the answer to a card (ANS-06)."""
    value = event.get("value") or {}
    page = (
        f"project page {event['page']}" if event.get("project_page") else event["page"]
    )
    head = f"{event['kind']} {event['target']['canvas_id']} ({page}): "
    if event["kind"] == "change":
        return head + _one_line(value.get("reason"))
    if event["kind"] == "todo":
        parts = [str(value.get("status"))]
        if value.get("note"):
            parts.append(_one_line(value["note"])[:NOTE_CHARS])
        if value.get("ticks_not_from_owner"):
            parts.append(f"[{value['ticks_not_from_owner']}]")
        return head + " · ".join(parts)
    parts = [_one_line(_answer_text(value.get("answer")))]
    if value.get("other"):
        parts.append(f"other: {_one_line(value['other'])}")
    if value.get("note"):
        parts.append(f"note: {_one_line(value['note'])[:NOTE_CHARS]}")
    return head + " · ".join(parts)


def _one_line(text: Any) -> str:
    """Replace line breaks and runs of spaces in typed text by single spaces."""
    return " ".join(str(text).split())


def _answer_text(answer: Any) -> str:
    """Write an answer value of an Ask: ids joined, a decision or change spelled out."""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, list) and all(isinstance(a, str) for a in answer):
        return ", ".join(answer)
    if isinstance(answer, dict) and "change" in answer:
        return f"change: {answer['change']}"
    if isinstance(answer, dict) and "decision" in answer:
        reason = f": {answer['reason']}" if answer.get("reason") else ""
        return f"{answer['decision']}{reason}"
    return json.dumps(answer, ensure_ascii=False)


def _comment_lines(comment: dict[str, Any], sent: str | None) -> list[str]:
    """One comment (RPL-07): its line, its picture line and the replies sent with it."""
    anchor = comment.get("anchor") or {}
    where = [_target_text(comment.get("target"))]
    if comment.get("kind") == "text" and anchor.get("quote"):
        where.append(f"«{anchor['quote'][:120]}»")
    if anchor.get("space") == "pdf-pt":
        page = anchor.get("p") or next(
            (r["p"] for r in anchor.get("rects") or []), None
        )
        where.append(f"p. {page}")
    if comment.get("source_line"):
        where.append(f"line {comment['source_line']}")
    if comment.get("data"):
        where.append(_data_text(comment["data"]))
    if comment.get("text_inside"):
        where.append(f"text inside «{comment['text_inside'][:120]}»")
    if comment.get("lost"):
        where.append("(lost: no longer found on the page)")
    lines = [
        f"comment #{comment.get('n')} {comment.get('kind')} on {' '.join(where)}: "
        f"{json.dumps(comment.get('text', ''), ensure_ascii=False)}"
    ]
    if comment.get("picture"):
        lines.append(f"   picture: {comment['picture']}")
    else:
        lines.append(
            f"   no picture ({comment.get('picture_error') or 'unknown reason'})"
        )
    for reply in comment.get("replies") or []:
        if reply.get("from") is None and reply.get("sent") == sent:
            text = json.dumps(reply.get("text", ""), ensure_ascii=False)
            lines.append(f"   reply on #{comment.get('n')}: {text}")
    return lines


def _data_text(data: dict[str, Any]) -> str:
    """Return the data ranges of a comment over a plot (ANC-05)."""
    axes = []
    for axis in ("x", "y"):
        value = data.get(axis)
        if value is None:
            continue
        shown = f"{value[0]} to {value[1]}" if isinstance(value, list) else str(value)
        axes.append(f"{axis} {shown}")
    return "data " + ", ".join(axes)


def _screenshot_text(event: dict[str, Any]) -> str:
    """Return the screenshot path, or say that there is none and why."""
    if event.get("screenshot"):
        return f"screenshot: {event['screenshot']}"
    reason = event.get("screenshot_error") or "unknown reason"
    return f"no screenshot available ({reason})"


def _target_text(target: dict[str, Any] | None) -> str:
    """Name an element by canvas id, else selector, else visible text."""
    if not target:
        return "the page"
    for key in ("canvas_id", "selector", "text"):
        if target.get(key):
            return str(target[key])
    return "the page"


def _action_text(action: dict[str, Any]) -> str:
    """One action; those already delivered as events are context only."""
    text = f"{action.get('kind')} {_target_text(action.get('target'))}"
    if action.get("not_from_owner"):
        text = f"[{action['not_from_owner']}] {text}"
    if action.get("value") is not None:
        text += f" = {json.dumps(action['value'])}"
    if action.get("event"):
        text += f" [already delivered as {action['event']}; do not act on it again]"
    return text


def _mark_text(mark: dict[str, Any]) -> str:
    """One mark: type, note, target and data coordinates over a plot."""
    text = str(mark.get("type"))
    if mark.get("text"):
        text += f" {json.dumps(mark['text'])}"
    target = mark.get("target") or {}
    text += f" over {_target_text(target)}"
    box = target.get("data_bbox")
    if box:
        text += (
            f", data x {box['x'][0]} to {box['x'][1]}, y {box['y'][0]} to {box['y'][1]}"
        )
    if mark.get("bbox"):
        text += f", box {mark['bbox']}"
    return text
