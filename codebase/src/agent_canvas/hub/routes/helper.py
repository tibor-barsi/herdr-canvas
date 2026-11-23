"""Route helper: service bundle, parsing, error mapping, declared publishes."""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from agent_canvas.hub.answers import AnswerStore
from agent_canvas.hub.asks import AskService
from agent_canvas.hub.channel import WindowChannel
from agent_canvas.hub.events import EventService
from agent_canvas.hub.herdr_app import HerdrApp
from agent_canvas.hub.looks import LookService
from agent_canvas.hub.registry import RegistryError, SessionRegistry
from agent_canvas.hub.results import ResultService
from agent_canvas.hub.state import HubState
from agent_canvas.hub.watcher import PageWatcher
from agent_canvas.hub.window import WindowLauncher

Publish = Callable[[str], None]


@dataclass
class Services:
    """
    The services every route group shares.

    Attributes
    ----------
    state, registry, events, asks, looks, watcher, launcher
        The hub's services.
    static_dir : pathlib.Path
        Directory of the served shell files.
    answers : AnswerStore
        The cards' answers per page (ANS-01).
    results : ResultService
        The result cards (RES-01).
    changed_pages : collections.deque
        (session, page) pairs whose ``comments`` message is still to be built.
    changed_answers : collections.deque
        (session, page) pairs whose ``answers`` message is still to be built.
    """

    state: HubState
    registry: SessionRegistry
    events: EventService
    asks: AskService
    looks: LookService
    watcher: PageWatcher
    launcher: WindowLauncher
    static_dir: Path
    answers: AnswerStore
    results: ResultService
    changed_pages: deque[tuple[str, str]] = field(default_factory=deque)
    changed_answers: deque[tuple[str, str]] = field(default_factory=deque)
    herdr_app: HerdrApp = field(default_factory=HerdrApp)

    @property
    def channel(self) -> WindowChannel:
        """The window channel of the hub state."""
        return self.state.channel


@dataclass(frozen=True)
class Declaration:
    """
    What a state-changing route publishes.

    Attributes
    ----------
    views : tuple[str, ...]
        Window views the route may publish, e.g. ``("tabs",)``.
    reason : str
        Why it publishes none, when ``views`` is empty.
    """

    views: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        """Require views or a reason, never neither."""
        if not self.views and not self.reason:
            raise ValueError("a route declares views or a reason for none")


def changed(svc: Services, publish: Publish, session_id: str, page: str) -> None:
    """Queue the page's comments for every window and publish the view."""
    svc.changed_pages.append((session_id, page))
    publish("comments")


def resumed(svc: Services, publish: Publish, session_id: str) -> None:
    """Bring an ended session back: watch its folder again and refresh the views."""
    if svc.registry.resume(session_id):
        svc.watcher.refresh()
        publish("tabs")


def failure(error: RegistryError) -> Response:
    """Map a registry error to its JSON response (404 unknown session, else 422)."""
    status = 404 if error.code == "no-session" else 422
    body = {"error": error.code, "message": str(error)}
    return JSONResponse(body, status_code=status)


async def body_of(request: Request) -> dict[str, Any]:
    """Return the JSON object of the request body, ``{}`` for anything else."""
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _publisher(services: Services, declaration: Declaration) -> Publish:
    def publish(view: str) -> None:
        if view not in declaration.views:
            raise ValueError(f"route did not declare publishing {view!r}")
        services.channel.publish(view)

    return publish


def read_route(
    services: Services,
    path: str,
    handler: Callable[[Request, Services], Awaitable[Response]],
    methods: list[str] | None = None,
) -> Route:
    """Build a route that changes no state; ``handler(request, services)``."""

    async def endpoint(request: Request) -> Response:
        return await handler(request, services)

    endpoint.__name__ = handler.__name__
    endpoint.handler = handler  # type: ignore[attr-defined]
    return Route(path, endpoint, methods=methods)


def change_route(
    services: Services,
    path: str,
    handler: Callable[[Request, Services, Publish], Awaitable[Response]],
    methods: list[str],
    declaration: Declaration,
) -> Route:
    """Build a state-changing route; ``handler(request, services, publish)``."""
    publish = _publisher(services, declaration)

    async def endpoint(request: Request) -> Response:
        return await handler(request, services, publish)

    endpoint.__name__ = handler.__name__
    endpoint.handler = handler  # type: ignore[attr-defined]
    endpoint.declaration = declaration  # type: ignore[attr-defined]
    return Route(path, endpoint, methods=methods)


def change_socket(
    services: Services,
    path: str,
    handler: Callable[[WebSocket, Services, Publish], Awaitable[None]],
    declaration: Declaration,
) -> WebSocketRoute:
    """Build a WebSocket route whose messages change state; declared like a route."""
    publish = _publisher(services, declaration)

    async def endpoint(websocket: WebSocket) -> None:
        await handler(websocket, services, publish)

    endpoint.__name__ = handler.__name__
    endpoint.handler = handler  # type: ignore[attr-defined]
    endpoint.declaration = declaration  # type: ignore[attr-defined]
    return WebSocketRoute(path, endpoint)
