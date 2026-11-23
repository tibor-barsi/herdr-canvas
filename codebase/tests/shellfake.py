"""A scripted owner window: a shell WebSocket client for hub tests (no browser)."""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Callable
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from agent_canvas.hub.auth import cookie_name
from agent_canvas.hub.looks import RenderFailed, RenderOutcome
from helpers import solid_png


def png_answer(request: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Answer a render request with a solid PNG of the requested size."""
    png = solid_png(request["width"], request["height"])
    return {
        "type": "render-result",
        "id": request["id"],
        "ok": True,
        "png": base64.b64encode(png).decode(),
        "scheme": request["scheme"],
        "errors": [],
        "audit": None,
        "notes": [],
        **extra,
    }


class FakeShell:
    """
    Connect to the hub as an owner window and answer render requests.

    Parameters
    ----------
    hub : HubHandle
        The test hub.
    info : dict | None
        ``{"width", "height", "scheme"}`` reported as ``window-info``.
    answer : Callable | None
        Called with each render request; returns the message to send back, or
        None to stay silent. The default answers with a solid PNG.
    """

    def __init__(
        self,
        hub: Any,
        info: dict[str, Any] | None = None,
        answer: Callable[[dict[str, Any]], dict[str, Any] | None] = png_answer,
    ) -> None:
        self.hub = hub
        cookie = f"{cookie_name(hub.port)}={hub.state.credentials.cookie_value}"
        self.ws = connect(
            f"ws://127.0.0.1:{hub.port}/ws/shell",
            additional_headers={"Cookie": cookie},
            origin=hub.base_url,
        )
        self.answer = answer
        self.messages: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        if info is not None:
            self.send({"type": "window-info", **info})
            hub.wait_for(lambda: hub.on_loop(hub.state.looks.window_info) is not None)

    def send(self, message: dict[str, Any]) -> None:
        """Send one JSON message to the hub."""
        self.ws.send(json.dumps(message))

    def close(self) -> None:
        """Close the socket (the window went away)."""
        self.ws.close()

    def types(self) -> list[str]:
        """Types of all messages received so far."""
        return [m.get("type", "") for m in list(self.messages)]

    def _loop(self) -> None:
        try:
            for raw in self.ws:
                message = json.loads(raw)
                self.messages.append(message)
                if message.get("type") != "render":
                    continue
                self.requests.append(message)
                reply = self.answer(message)
                if reply is not None:
                    self.send(reply)
        except ConnectionClosed:
            return


class FakeHeadless:
    """Stand-in for :class:`HeadlessRenderer`: records jobs, answers a solid PNG."""

    def __init__(
        self,
        error: str | None = None,
        audit: Any = None,
        errors: list[dict[str, Any]] | None = None,
        viewer_error: str | None = None,
    ) -> None:
        self.error = error
        self.viewer_error = viewer_error
        self.audit = audit
        self.errors = errors or []
        self.jobs: list[Any] = []
        self.access: list[Any] = []

    async def render(self, job: Any, access: Any) -> RenderOutcome:
        """Return a solid PNG for ``job``, or fail with the configured error."""
        self.jobs.append(job)
        self.access.append(access)
        if self.error is not None:
            raise RenderFailed(self.error)
        return RenderOutcome(
            png=solid_png(job.width, job.height, (10, 120, 200)),
            scheme=job.scheme,
            errors=list(self.errors),
            audit=self.audit,
            notes=[],
            source="headless",
            viewer_error=self.viewer_error,
        )
