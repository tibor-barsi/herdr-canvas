"""Shared helpers for the drawing and send tests (M9)."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import httpx

from agent_canvas.hub.routes import sessions

# A page that scrolls: a 400 px light-blue filler, a teal target 200x120 with
# its left edge at x = 100, then a long tail. Scrolled to 340 px the target
# occupies viewport rows 60..179 and columns 100..299.
SCROLL_PAGE = """<!doctype html><html><head><style>
body { margin: 0; background: #ffffff; }
#filler { height: 400px; background: #cfe8ff; }
#target { margin-left: 100px; width: 200px; height: 120px; background: #2a9d8f; }
#tail { height: 1500px; }
</style></head><body>
<div id="filler"><button id="b" onclick="document.title='pressed'">press</button>
 <input id="t" type="text"> <div id="plain" tabindex="0">plain</div></div>
<div id="target" data-canvas-id="spectrum"></div>
<div id="tail"></div>
</body></html>"""

RED = (229, 72, 77)
TEAL = (42, 157, 143)
FILLER = (207, 232, 255)


def until(page, check, timeout: float = 15.0):  # noqa: ANN001, ANN201
    """Poll ``check()`` while the page runs; return its first truthy value.

    Parameters
    ----------
    page : playwright.sync_api.Page
        The page whose event loop is kept running between polls.
    check : callable
        Returns a truthy value when the condition holds.
    timeout : float
        Seconds to wait before failing.
    """
    end = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        assert time.monotonic() < end, f"condition not met in {timeout} s"
        page.wait_for_timeout(50)


def call(owner, method: str, path: str, **kwargs) -> dict:  # noqa: ANN001
    """Call the hub API while keeping Playwright's event loop running."""
    hub = owner.hub
    kwargs.setdefault("timeout", 15)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            httpx.request,
            method,
            f"{hub.base_url}{path}",
            headers=hub.key_headers,
            **kwargs,
        )
        while not future.done():
            owner.page.wait_for_timeout(20)
        return future.result().json()


def owner_field(page) -> str:  # noqa: ANN001
    """Add a text field to the shell (it has none of its own); return its selector."""
    page.evaluate(
        """() => document.getElementById('owner-field') ||
             document.getElementById('content').append(Object.assign(
               document.createElement('textarea'), {id: 'owner-field'}))"""
    )
    return "#owner-field"


class Studio:
    """An owner window with one or more sessions and drawing helpers."""

    def __init__(self, owner, tmp_path: Path) -> None:  # noqa: ANN001
        self.owner, self.tmp_path = owner, tmp_path
        self.page = owner.page
        deadline = 100
        while not owner.hub.state.shells and deadline:
            self.page.wait_for_timeout(50)
            deadline -= 1

    def make(self, html: str, name: str = "alpha", files: dict | None = None) -> str:
        """Create a session showing ``html`` (and ``files``) and wait for the frame."""
        directory = self.tmp_path / name
        directory.mkdir(exist_ok=True)
        body = {"project": str(directory), "agent": "claude", "title": name}
        sid = call(self.owner, "POST", "/api/sessions", json=body)["session"]
        folder = self.owner.hub.state.session_of(sid).folder
        self.folder = folder
        for filename, content in (files or {}).items():
            data = content.encode() if isinstance(content, str) else content
            (folder / filename).write_bytes(data)
        (folder / "page.html").write_text(html)
        # The tab is visited only after ``show``, so no window loads the page
        # and the hub would wait its 2 s for a report that cannot come; the
        # answer ("pending") is the same with a short wait and is not used here.
        with mock.patch.object(sessions, "RENDER_WAIT_SECONDS", 0.05):
            call(
                self.owner,
                "POST",
                f"/api/sessions/{sid}/show",
                json={"project": str(directory), "name": "page.html"},
            )
        # A later session does not take over the window: visit it as the owner would.
        self.owner.visit(sid)
        self.frame.wait_for_function("document.readyState === 'complete'")
        self.frame.wait_for_function("window.agentCanvas !== undefined")
        return sid

    @property
    def frame(self):  # noqa: ANN201
        """The Playwright frame holding the page."""
        return self.owner.frame

    def origin(self) -> tuple[float, float]:
        """Top-left of the page frame in window coordinates."""
        box = self.page.locator("#frame").bounding_box()
        assert box is not None, "frame is not rendered"
        return box["x"], box["y"]

    # ---- sending ------------------------------------------------------------

    def queue_action(self) -> None:
        """Give the shown session's draft one click action: something to send."""
        self.page.evaluate(
            """() => {
              const shell = window.__shell;
              shell.draftOf(shell.activeTab().id).actions.push({
                kind: "click", time: "", value: null, at: null, event: null,
                card: false, target: {tag: "body", href: "", canvas_id: null,
                selector: null, text: ""},
              });
              window.drawUi.updateBar();
            }"""
        )

    def events(self, sid: str) -> list[dict]:
        """All events of a session."""
        return self.owner.hub.on_loop(lambda: self.owner.hub.state.events.all(sid))

    def wait_events(self, sid: str, count: int, timeout: float = 15) -> list[dict]:
        """Wait for ``count`` events and return all of them."""
        for _ in range(int(timeout * 50)):
            found = self.events(sid)
            if len(found) >= count:
                return found
            self.page.wait_for_timeout(20)
        raise AssertionError(f"expected {count} events, got {self.events(sid)}")

    def send_record(self, event: dict) -> dict:
        """The stored send record of a ``send`` event."""
        return json.loads(Path(event["send_file"]).read_text())

    def screenshot(self, event: dict) -> bytes:
        """The stored PNG of a ``send`` event."""
        assert event["screenshot"], event
        return Path(event["screenshot"]).read_bytes()


def block(tag: str, canvas_id: str, config: dict | str, extra: str = "") -> str:
    """Return the markup an agent writes for one block."""
    body = config if isinstance(config, str) else json.dumps(config)
    return (
        f'<{tag} data-canvas-id="{canvas_id}">'
        f'<script type="application/json">{body}</script>{extra}</{tag}>'
    )


class Made:
    """A session showing a page, with helpers to rewrite it."""

    def __init__(self, owner, sid: str, folder: Path, shown: dict) -> None:  # noqa: ANN001
        self.owner, self.sid, self.folder, self.shown = owner, sid, folder, shown

    def rewrite(self, html: str) -> None:
        """Write the page file; the watcher pushes the update."""
        (self.folder / "page.html").write_text(html)

    @property
    def events(self) -> list[dict]:
        """All events of the session."""
        return self.owner.hub.on_loop(lambda: self.owner.hub.state.events.all(self.sid))

    def wait_events(self, count: int) -> list[dict]:
        """Wait for ``count`` events and return all of them."""
        for _ in range(300):
            if len(self.events) >= count:
                return self.events
            self.owner.page.wait_for_timeout(20)
        raise AssertionError(f"expected {count} events, got {self.events}")

    def wait_action(self, kind: str, count: int = 1) -> list[dict]:
        """Wait for ``count`` draft actions of ``kind``; return them."""
        script = (
            f"(window.__drafts['{self.sid}'] || {{actions: []}}).actions"
            f".filter((a) => a.kind === '{kind}').length >= {count}"
        )
        self.owner.page.wait_for_function(script)
        return [
            a
            for a in self.owner.page.evaluate(f"window.__drafts['{self.sid}'].actions")
            if a["kind"] == kind
        ]
