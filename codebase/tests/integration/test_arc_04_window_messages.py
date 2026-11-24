"""Baseline of what the hub pushes to a window (ARC-04); the golden file records it."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub.watcher import PageHistory
from shellfake import FakeShell

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).with_name("test_arc_04_window_messages.golden.txt")
WINDOW = {"width": 900, "height": 700, "scheme": "dark"}
SETTLE_SECONDS = 0.5
CARDS = (
    '<canvas-ask data-canvas-id="q1"><script type="application/json">'
    '{"question": "Q?"}</script></canvas-ask>'
    '<canvas-do data-canvas-id="w1"><script type="application/json">'
    '{"title": "T", "steps": [{"text": "a"}]}</script></canvas-do>'
)


class Recorder:
    """Run steps against the hub and note the message types the window got per step."""

    def __init__(self, hub, shell: FakeShell) -> None:  # noqa: ANN001
        self.hub, self.shell = hub, shell
        self.lines: list[str] = []
        self.seen = 0

    def settle(self, step: str) -> None:
        """Wait until the window has been quiet for a moment, then record the step."""
        count = -1
        while count != len(self.shell.messages):
            count = len(self.shell.messages)
            time.sleep(SETTLE_SECONDS)
        types = [m.get("type", "") for m in self.shell.messages[self.seen :]]
        if step != "connect":  # the Herdr poll sends on its own clock
            types = [t for t in types if t != "herdr"]
        self.lines += [f"{step}: {kind}" for kind in types] or [f"{step}: (nothing)"]
        self.seen = len(self.shell.messages)

    def post(self, path: str, **body: object) -> httpx.Response:
        """POST to the hub API and require success."""
        answer = httpx.post(
            self.hub.base_url + path, json=body, headers=self.hub.key_headers
        )
        assert answer.status_code == 200, answer.text
        return answer


def spawn(cli, *args: str) -> subprocess.Popen:  # noqa: ANN001
    """Start an agent-canvas command that keeps running until it is stopped."""
    return subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", *args],
        cwd=cli.cwd,
        env=cli.environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_arc_04_the_window_gets_the_recorded_messages_in_the_recorded_order(
    cli,
    hub,  # noqa: ANN001
) -> None:
    """Drive two sessions through a fixed sequence; compare types to the golden file."""
    shell = FakeShell(hub, WINDOW)
    rec = Recorder(hub, shell)
    try:
        rec.settle("connect")

        assert cli("session", "path", "--session", "a").code == 0
        rec.settle("session a")
        assert cli("session", "path", "--session", "b").code == 0
        rec.settle("session b")

        folder = hub.state.session_of(hub.pool_of("a")).folder  # the pages' folder
        (folder / "page.html").write_text("<p>one</p>")
        rec.settle("write page")
        assert cli("show", "page.html", "--session", "a", "--no-audit").code == 0
        rec.settle("show")

        # The file watcher is the only source of update and file-changed pushes.
        (folder / "page.html").write_text("<p>two</p>")
        rec.settle("edit page")
        (folder / "data.json").write_text("{}")
        rec.settle("edit asset")

        # A watch lights "listening"; a shell event is answered to that socket only.
        watch = spawn(cli, "watch", "--session", "a", "--timeout", "30")
        hub.wait_for(lambda: hub.listening("a"))
        rec.settle("watch starts")
        shell.send({
            "type": "event", "session": "a", "kind": "button", "value": 1,
            "delivery": "now", "target": None, "page": None, "ref": "r1",
        })  # fmt: skip
        rec.settle("shell event")
        watch.terminate()
        watch.communicate(timeout=10)
        hub.wait_for(lambda: not hub.listening("a"))
        rec.settle("watch ends")

        ask = spawn(cli, "ask", "Which?", "--choice", "A", "--session", "a")
        card = hub.wait_for_ask("a")
        rec.settle("ask")
        shell.send(
            {"type": "ask-answer", "session": "a", "ask": card["ask"], "value": ["A"]}
        )
        ask.communicate(timeout=20)
        rec.settle("answer")

        rec.post("/api/sessions/b/rename", title="Renamed")
        rec.settle("rename")
        rec.post("/api/sessions/b/hide")
        rec.settle("hide")
        rec.post("/api/sessions/b/unhide")
        rec.settle("unhide")

        assert cli("look", "--session", "a").code == 0
        rec.settle("look")

        # Revision 12 (P21.2): each save and delete of a comment gives one message.
        owner = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
        owner.get(hub.login_url(), follow_redirects=False)
        comment = {"page": "page.html", "kind": "rect", "text": "q", "anchor": {}}
        assert owner.post("/api/sessions/a/comments", json=comment).status_code == 200
        rec.settle("comment")
        gone = {"page": "page.html", "n": 1, "delete": True}
        assert owner.post("/api/sessions/a/comments/edit", json=gone).status_code == 200
        rec.settle("delete comment")
        assert owner.post("/api/sessions/a/comments", json=comment).status_code == 200
        rec.settle("comment again")
        lost = {"page": "page.html", "reports": [{"n": 2, "lost": True}]}
        assert owner.post("/api/sessions/a/comments/lost", json=lost).status_code == 200
        rec.settle("lost")
        sent = {"delivery": "now", "message": "", "page": "page.html"}
        sent |= {"viewport": {"width": 1, "height": 1, "scroll_x": 0, "scroll_y": 0}}
        sent |= {"screenshot": None, "screenshot_error": "none"}
        rec.post("/api/sessions/a/send", **sent)
        rec.settle("send")

        # Revision 13 (P26.5): each change of a page's answers gives one message,
        # also the read stamp a delivery leaves on an answer.
        PageHistory(folder).save("cards.html", CARDS.encode())
        item = {"page": "cards.html", "id": "q1", "value": {"answer": "yes"}}
        answered = owner.post("/api/sessions/a/answers/answer", json=item)
        assert answered.status_code == 200
        rec.settle("answer item")
        tick = {"page": "cards.html", "id": "w1", "ticked": [1]}
        assert owner.post("/api/sessions/a/answers/tick", json=tick).status_code == 200
        rec.settle("tick")
        event_id = answered.json()["event"]
        hub.on_loop(lambda: hub.state.events.ack("a", event_id, "pending"))
        rec.settle("read")
    finally:
        shell.close()
        for process in (locals().get("watch"), locals().get("ask")):
            if process is not None and process.poll() is None:
                process.kill()

    recorded = "\n".join(rec.lines) + "\n"
    assert recorded == GOLDEN.read_text()
