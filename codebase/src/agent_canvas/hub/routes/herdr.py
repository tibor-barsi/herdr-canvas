"""Route group: the Herdr link (the snapshot and a focus request)."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    body_of,
    change_route,
    read_route,
)

KEYS = ("terminal", "tab", "space")


def routes(services: Services) -> list[BaseRoute]:
    """Return the Herdr routes."""
    return [
        read_route(services, "/api/herdr", snapshot, ["GET"]),
        change_route(
            services,
            "/api/herdr/focus",
            focus,
            ["POST"],
            Declaration(reason="Herdr moves its own focus; the poll publishes it"),
        ),
    ]


async def snapshot(request: Request, svc: Services) -> Response:
    """Return the current ``herdr`` snapshot."""
    return JSONResponse(await asyncio.to_thread(svc.herdr_app.snapshot))


async def focus(request: Request, svc: Services, publish: Publish) -> Response:
    """Focus the pane of a terminal, tab or space in Herdr."""
    body = await body_of(request)
    key = next(iter(body), None)
    if len(body) != 1 or key not in KEYS or not isinstance(body[key], str):
        return _error(400, "give exactly one of terminal, tab, space")

    def work() -> bool | None:
        current = svc.herdr_app.snapshot()
        if not current["available"]:
            return None
        return svc.herdr_app.focus(current, key, body[key])

    found = await asyncio.to_thread(work)
    if found is None:
        return _error(503, "Herdr is not running")
    if not found:
        return _error(404, f"no pane for this {key}")
    return JSONResponse({"ok": True})


def _error(status: int, message: str) -> Response:
    return JSONResponse({"error": message}, status_code=status)
