"""Tracer bullet of revision 12 (M21 P21.4): a rectangle comment reaches a real agent.

A nested ``claude -p --plugin-dir plugin/`` (``haiku``, one retry with
``sonnet``) shows a page in the temporary hub of the ``hub`` fixture and waits
with ``agent-canvas watch --count 1`` in its Bash tool. Headless Chromium plays
the owner: ``C``, a rectangle drag over the paragraph, "units?", Enter, Send
now. The line ``watch`` printed must hold one ``rect`` comment with its anchor,
target, ``text_inside`` and the path of a picture that exists; the agent's
answer must quote the comment. Never uses the owner's hub or window.
Run by hand: ``scripts/gate.sh -m e2e -k com_tracer -n 0 -s``.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from harness import (
    ClaudeRun,
    comment_mode_on,
    comment_rectangle,
    frame_has,
    open_first_tab,
    pump,
    session_events,
    wait_listening,
    wait_reply,
)
from test_acceptance_claude import assert_no_denials

pytestmark = [pytest.mark.e2e, pytest.mark.retry_once]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

PROMPT = """Use the agent-canvas canvas (the plugin is installed; \
follow its guideline). \
Show me an HTML page whose body is exactly: \
<h1 id="title">Beam test</h1><p id="claim">The first bending mode of the clamped \
beam is 83.5 Hz.</p>. Then, in your Bash tool and in the foreground, run exactly \
`agent-canvas watch --count 1 --timeout 100` and wait for its output. It prints \
one line of JSON when I send something; the `comments` list in it holds my \
comment on the page. When the line arrives, answer in one or two sentences that \
quote my comment text word for word and say which text it was about."""


@pytest.fixture(autouse=True)
def claude_installed() -> None:
    """Fail (not skip) when the claude command is missing."""
    assert shutil.which("claude"), "the claude command is not installed"


def watch_line(run: ClaudeRun) -> dict | None:
    """The JSON line the agent's ``watch --count 1`` printed, from the stream."""
    commands: dict[str, str] = {}
    for event in run.events():
        content = event.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                commands[block["id"]] = str(block["input"].get("command", ""))
            elif block.get("type") == "tool_result":
                if "agent-canvas watch" not in commands.get(block["tool_use_id"], ""):
                    continue
                body = block.get("content")
                text = (
                    body
                    if isinstance(body, str)
                    else "".join(part.get("text", "") for part in body or [])
                )
                for line in text.splitlines():
                    if line.startswith("{") and '"comments"' in line:
                        return json.loads(line)
    return None


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from the PNG header."""
    data = path.read_bytes()
    assert data.startswith(PNG_SIGNATURE), path
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_e2e_com_tracer_a_rectangle_comment_reaches_the_agent(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    run = ClaudeRun(hub, tmp_path, claude_model)
    session = str(uuid.uuid4())
    run.start(PROMPT, session)
    answer = ""
    try:
        shown = run.wait(
            lambda: open_first_tab(owner) and frame_has(owner, "#claim"),
            200,
            tick=lambda: pump(owner),
        )
        assert shown, f"no page appeared\n{run.report()}"
        assert wait_listening(owner, run, session, 150), run.report()
        comment_mode_on(owner)  # the panel narrows the frame: measure after it
        box = owner.frame.locator("#claim").bounding_box()
        # the frame's own coordinates: the page is not scrolled
        origin = owner.page.locator("#frame").bounding_box()
        start = (box["x"] - origin["x"] - 4, box["y"] - origin["y"] - 4)
        end = (start[0] + box["width"] + 8, start[1] + box["height"] + 8)
        comment_rectangle(owner, start, end, "units?")
        assert owner.page.inner_text("#comment-count").startswith("1")
        assert not owner.page.is_disabled("#send-button")
        assert "Ctrl+Enter" in owner.page.inner_text("#send-button")
        owner.page.click("#send-button")
        answer = wait_reply(owner, run, session, ("units?",), 150)
    finally:
        run.finish(10)
    print(run.report(), f"\nANSWER: {answer}")
    assert_no_denials(run)

    line = watch_line(run)
    assert line is not None, f"watch printed no comment line\n{run.report()}"
    assert line["kind"] == "send" and line["part"] == [1, 1]
    [comment] = line["comments"]
    assert comment["kind"] == "rect" and comment["text"] == "units?"
    assert comment["status"] == "sent" and comment["n"] == 1
    anchor = comment["anchor"]
    assert anchor["space"] == "page-px" and anchor["w"] > 100 and anchor["h"] > 10
    assert comment["target"]["selector"], comment
    assert "83.5 Hz" in (comment["text_inside"] or ""), comment
    picture = Path(comment["picture"])
    assert picture.is_absolute() and picture.name == "0001.c1.png", picture
    width, height = png_size(picture)
    assert width > anchor["w"] and height > anchor["h"], (width, height, anchor)
    assert picture.parent == Path(line["send_file"]).parent

    [event] = [e for e in session_events(hub, session) if e["kind"] == "send"]
    assert event["comments"][0]["text"] == "units?" and event["state"] == "delivered"
    stored = json.loads(
        (picture.parents[2] / ".comments" / "page.html.json").read_text()
    )
    assert stored["comments"][0]["send_event"] == event["id"]
    assert "units?" in answer.lower(), answer
