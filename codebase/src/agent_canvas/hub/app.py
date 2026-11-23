"""The hub's ASGI application and its server entry point (HUB-01, HUB-03).

One Starlette app serves both sites: the shell at ``http://127.0.0.1:<port>``
and the sandboxed pages at ``http://localhost:<port>``. A guard middleware
applies the Host, Origin and credential rules (SEC-01, SEC-03, SEC-05) and the
CORS header (SEC-06) before routing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocket

from agent_canvas import __version__
from agent_canvas.config import Config
from agent_canvas.hub.answers import READ_KINDS, AnswerStore
from agent_canvas.hub.asks import AskService
from agent_canvas.hub.auth import KEY_HEADER, cookie_name, load_or_create_key
from agent_canvas.hub.build import compute_build_id
from agent_canvas.hub.clock import check_environment
from agent_canvas.hub.events import EventService
from agent_canvas.hub.headless import HeadlessRenderer
from agent_canvas.hub.herdr_app import HerdrApp
from agent_canvas.hub.looks import LookService
from agent_canvas.hub.purge import PURGE_INTERVAL_SECONDS, purge
from agent_canvas.hub.registry import (
    SessionRegistry,
    git_top_folder,
    is_project_id,
    project_session_id,
)
from agent_canvas.hub.results import ResultService
from agent_canvas.hub.routes import all_routes
from agent_canvas.hub.routes.answers import answers_message, build_answers_view
from agent_canvas.hub.routes.comments import build_comments_view
from agent_canvas.hub.routes.helper import Services
from agent_canvas.hub.routes.sockets import event_from_shell  # noqa: F401
from agent_canvas.hub.state import HubState
from agent_canvas.hub.waiting import agent_pages
from agent_canvas.hub.watcher import PageWatcher, is_page_name
from agent_canvas.hub.window import WindowLauncher

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
WS_UNAUTHORIZED = 4401
OWNER_PAGES = ("/", "/render")
UPLOAD_PATH = re.compile(r"/api/sessions/[^/]+/files")  # VIEW-10: octet-stream body


class GuardMiddleware:
    """
    Pure-ASGI guard: Host, Origin, credentials and CORS header.

    Parameters
    ----------
    app : ASGIApp
        The wrapped application.
    state : HubState
        Hub state (port and credentials).
    """

    def __init__(self, app: ASGIApp, state: HubState) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Apply the guards, then pass the request on."""
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        if not self._host_allowed(conn):
            await self._reject(scope, receive, send, 403, "bad Host header")
            return
        if scope["type"] == "websocket" and not self._origin_allowed(conn):
            await self._reject(scope, receive, send, 403, "bad Origin")
            return
        if self._needs_credentials(scope):
            how = self._authenticated(scope, conn)
            if how is None:
                await self._reject(scope, receive, send, 401, "credentials required")
                return
            if scope["type"] == "http" and how == "cookie":
                refusal = self._forgery_refusal(scope, conn)
                if refusal is not None:
                    await self._reject(scope, receive, send, *refusal)
                    return
        if scope["type"] == "http" and not self._page_origin_allowed(scope, conn):
            await self._reject(scope, receive, send, 403, "bad Origin")
            return
        if scope["type"] == "http" and self._wants_cors(scope):
            send = self._with_cors(send)
        await self.app(scope, receive, send)

    def _host_allowed(self, conn: HTTPConnection) -> bool:
        """Accept only the two hub hosts (DNS-rebinding guard, SEC-01)."""
        port = self.state.port
        return conn.headers.get("host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _origin_allowed(self, conn: HTTPConnection) -> bool:
        """Accept WebSocket origins: absent (CLI) or the shell origin (SEC-05)."""
        origin = conn.headers.get("origin")
        return origin is None or origin == f"http://127.0.0.1:{self.state.port}"

    @staticmethod
    def _needs_credentials(scope: Scope) -> bool:
        """Return True for /api, /ws, the shell page ``/`` and ``/render``."""
        path = scope["path"]
        return path in OWNER_PAGES or path.startswith(("/api", "/ws"))

    def _authenticated(self, scope: Scope, conn: HTTPConnection) -> str | None:
        """Return ``key`` or ``cookie`` for valid credentials, else None (SEC-03)."""
        credentials = self.state.credentials
        # The shell page and the render host are for the owner only (cookie).
        is_shell_page = scope["path"] in OWNER_PAGES
        if not is_shell_page and credentials.key_ok(conn.headers.get(KEY_HEADER)):
            return "key"
        cookie = conn.cookies.get(cookie_name(self.state.port))
        return "cookie" if credentials.cookie_ok(cookie) else None

    def _forgery_refusal(
        self, scope: Scope, conn: HTTPConnection
    ) -> tuple[int, str] | None:
        """
        Refuse state-changing cookie requests that may come from another page.

        Other ports of 127.0.0.1 are the same site for the browser, and cookies
        ignore ports, so a page on another local port could act as the owner
        (SEC-10). The key header is never sent by a browser on its own and is
        not checked here.
        """
        if scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return None
        origin = conn.headers.get("origin")
        fetch_site = conn.headers.get("sec-fetch-site")
        if origin is not None:
            same_origin = origin == f"http://127.0.0.1:{self.state.port}"
        else:
            same_origin = fetch_site == "same-origin"
        if not same_origin:
            return 403, "bad Origin"
        content_type = conn.headers.get("content-type", "")
        wanted = "application/json"
        if UPLOAD_PATH.fullmatch(scope["path"]):
            wanted = "application/octet-stream"
        if content_type.split(";")[0].strip().lower() != wanted:
            return 415, f"Content-Type must be {wanted}"
        return None

    def _page_origin_allowed(self, scope: Scope, conn: HTTPConnection) -> bool:
        """
        Serve page files only to no origin, the frame (``null``) or the hub (SEC-06).

        The wildcard CORS header exists for the sandboxed frame's opaque origin;
        another website that learned a page address must not read the files.
        """
        if not scope["path"].startswith("/s/"):
            return True
        port = self.state.port
        own = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
        return conn.headers.get("origin") in (None, "null", *own)

    @staticmethod
    def _wants_cors(scope: Scope) -> bool:
        """Return True for GET/HEAD below /static and /s/ (SEC-06)."""
        path = scope["path"]
        return scope["method"] in ("GET", "HEAD") and path.startswith(
            ("/static/", "/s/")
        )

    @staticmethod
    def _with_cors(send: Send) -> Send:
        """Wrap ``send`` to add ``Access-Control-Allow-Origin: *``."""

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"access-control-allow-origin", b"*"))
                message = {**message, "headers": headers}
            await send(message)

        return wrapped

    @staticmethod
    async def _reject(
        scope: Scope, receive: Receive, send: Send, status: int, text: str
    ) -> None:
        """Answer an HTTP request or WebSocket handshake with a refusal."""
        if scope["type"] == "http":
            await PlainTextResponse(text, status_code=status)(scope, receive, send)
            return
        websocket = WebSocket(scope, receive, send)
        if status == 401:
            # Accept first so that the client sees close code 4401 (SEC-03).
            await websocket.accept()
            await websocket.close(WS_UNAUTHORIZED)
        else:
            await websocket.close(1008)


def _announce(
    state: HubState,
    registry: SessionRegistry,
    session_id: str,
    listening: bool,
    watching: bool,
) -> None:
    """Tell the shells that a tab's light or watch changed (FB-06, CLI-14, FB-10)."""
    meta = registry.get(session_id)
    ended = meta is not None and meta.state == "ended"
    message = {
        "type": "listening",
        "session": session_id,
        "listening": listening and not ended,
        "watching": watching and not ended,
    }
    state.channel.broadcast(message)


def _asks_changed(state: HubState, kind: str, session_id: str) -> None:
    """Tell the shells about a question card; a new one may take focus."""
    if kind == "opened":
        message = {
            "type": "ask-opened",
            "session": session_id,
            "tab": state.tab_provider(session_id),
        }
        state.channel.broadcast(message)
    else:
        state.channel.publish("tabs")


def _page_changed(
    state: HubState,
    answers: AnswerStore,
    registry: SessionRegistry,
    session_id: str,
    page: str,
    version: int,
) -> None:
    """Note a new page version in the registry and reopen a changed question."""
    registry.note_page(session_id, page)  # LIFE-03; a meta tag may have changed
    if registry.restore(session_id, page):  # a new version restores (LIFE-04)
        state.channel.publish("tabs")
    answers.page_changed(session_id, page)  # a changed question is open again


def _event_created(
    registry: SessionRegistry, session_id: str, event: dict[str, Any]
) -> None:
    """Record the event's time as the page's ``answered`` stamp (LIFE-02)."""
    if event.get("page"):
        registry.note_answered(session_id, event["page"], event["time"])


def _send_changed(
    state: HubState, events: EventService, session_id: str, event: dict[str, Any]
) -> None:
    """Tell the windows what became of the session's newest send (FB-10)."""
    if event["kind"] == "send":
        send = events.latest_send(session_id)
        state.channel.broadcast(
            {"type": "send-state", "session": session_id, "send": send}
        )


def _comments_seen(services: Services, session_id: str, page: str) -> None:
    """Show the windows the comments of ``page`` that a delivery stamped seen."""
    services.changed_pages.append((session_id, page))
    services.state.channel.publish("comments")


def _answers_changed(services: Services, session_id: str, page: str) -> None:
    """Show the windows the stored items of ``page``, which just changed (ANS-02)."""
    services.changed_answers.append((session_id, page))
    services.state.channel.publish("answers")


def _pages_of(registry: SessionRegistry, session_id: str) -> tuple[str, ...]:
    """Return the pages a session lists, empty for an unknown session."""
    meta = registry.get(session_id)
    return meta.pages if meta else ()


def _shown_pages(registry: SessionRegistry, session_id: str) -> list[str]:
    """Return the HTML pages a session has shown (ANS-04)."""
    return [p for p in _pages_of(registry, session_id) if is_page_name(p)]


def _event_delivered(answers: AnswerStore, session_id: str, event: dict) -> None:
    """Stamp the item of an answer, to-do or change event the agent got (ANS-03)."""
    target = event.get("target") or {}
    if event["kind"] in READ_KINDS and event.get("page") and target.get("canvas_id"):
        answers.mark_read(session_id, event["page"], target["canvas_id"], event["id"])


def _project_session(registry: SessionRegistry, session_id: str) -> str | None:
    """Return the registered project session of a real or reserved session (PROJ-07)."""
    project = registry.project_of(session_id)
    if project is None or is_project_id(session_id):
        return None
    found = project_session_id(git_top_folder(project))
    return found if registry.project_of(found) is not None else None


def _project_receiver(
    registry: SessionRegistry,
    events: EventService,
    project_id: str,
    event: dict[str, Any],
) -> str | None:
    """Return the page's last updater while it runs, else None: the inbox (PROJ-07)."""
    meta = registry.get(project_id)
    page = event.get("page") or (meta.active_page if meta else None)
    updater = ((meta.page_meta if meta else {}).get(page) or {}).get("updated_by")
    session_id = updater["session"] if updater else None
    if session_id and events.listening(session_id):
        return session_id
    return None


def _with_light(
    tab: dict[str, Any],
    events: EventService,
    asks: AskService,
    results: ResultService,
) -> dict[str, Any]:
    """Add the light, the question cards, the result card and the last send to a tab."""
    session_id = tab["id"]
    ended = tab["state"] == "ended"
    return {
        **tab,
        "listening": events.listening(session_id) and not ended,
        "watching": events.watching(session_id) and not ended,
        "asks": asks.public(session_id),
        "result": results.public(session_id),
        "send": events.latest_send(session_id),
    }


def _results_changed(state: HubState, session_id: str) -> None:
    """Tell the shells about a result card."""
    state.channel.publish("tabs")


@asynccontextmanager
async def _lifespan(app: Starlette) -> AsyncIterator[None]:
    """Start the page watcher with the hub's loop and stop it at the end."""
    services: Services = app.state.services
    services.state.loop = asyncio.get_running_loop()
    await services.watcher.run()
    follows = services.registry.follow_file is not None
    purging = None if follows else asyncio.create_task(_purge_archived(services))
    herdr_poll = asyncio.create_task(_poll_herdr(services))
    try:
        yield
    finally:
        if purging:
            purging.cancel()
        herdr_poll.cancel()
        await services.watcher.close()


logger = logging.getLogger(__name__)
START_SCAN_WAIT_SECONDS = 30.0
HERDR_POLL_SECONDS = 1.0


async def _purge_archived(services: Services) -> None:
    """Delete the data of pages archived 30 days ago, at start and daily (LIFE-08)."""
    with contextlib.suppress(TimeoutError):  # a new version restores before it deletes
        await asyncio.wait_for(services.watcher.scanned.wait(), START_SCAN_WAIT_SECONDS)
    while True:
        try:
            changed = purge(services.registry)
        except Exception:  # noqa: BLE001  # one bad folder must not end the daily run
            logger.exception("purge failed")
            changed = []
        if changed:
            services.state.channel.publish("tabs")
            services.state.channel.publish("comments")
            services.state.channel.publish("answers")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


async def _poll_herdr(services: Services) -> None:
    """Read the Herdr app once a second; send the ``herdr`` view when it changed."""
    while True:
        paired = services.herdr_app.paired()
        if await asyncio.to_thread(services.herdr_app.poll):
            services.state.channel.publish("herdr")
        followed = services.registry.follow()
        if followed or services.herdr_app.paired() != paired:
            services.state.channel.publish("tabs")
        await asyncio.sleep(HERDR_POLL_SECONDS)


def create_app(
    config: Config,
    state_dir: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    build_id: str | None = None,
) -> Starlette:
    """
    Build the hub application.

    Parameters
    ----------
    config : Config
        Effective configuration (``port`` is used for the Host guard and CSP).
    state_dir : pathlib.Path
        State directory holding the access key.
    clock : Callable[[], float], optional
        Monotonic clock; tests inject a fake one.
    build_id : str | None, optional
        Identity of the served shell files (SHELL-01); computed from the
        version and the static directory when None. Tests inject one.

    Returns
    -------
    starlette.applications.Starlette
        The application; its hub state is ``app.state.hub``.

    Raises
    ------
    agent_canvas.hub.auth.KeyFileError
        If the key file has unsafe permissions.
    agent_canvas.hub.registry.RegistryError
        If ``sessions.json`` is unreadable.
    """
    check_environment()
    key = load_or_create_key(state_dir)
    state = HubState(config.port, key, clock)
    state.build_id = build_id or compute_build_id(STATIC_DIR, __version__)

    registry = SessionRegistry(state_dir, state, config.project_dir_name)
    if config.follow_state:
        registry.follow_file = Path(config.follow_state) / "sessions.json"
    looks = LookService(state, HeadlessRenderer())
    looks.show_audit = config.show_audit
    state.looks = looks
    answers = AnswerStore(
        lambda sid: state.session_of(sid).folder,
        lambda sid: agent_pages(_pages_of(registry, sid)),
        lambda sid, page: _answers_changed(services, sid, page),
    )
    watcher = PageWatcher(
        state,
        lambda sid: _is_watched(registry, sid),
        lambda sid, page, version: _page_changed(
            state, answers, registry, sid, page, version
        ),
        lambda sid: _pages_of(registry, sid),
    )
    registry.load()
    for session in registry.list(True, None):
        registry.note_pages(session["id"])  # pages that exist now start their count
    launcher = WindowLauncher(config, state, clock)

    events = EventService(
        state,
        on_listening=lambda sid, on: _announce(
            state, registry, sid, on, events.watching(sid)
        ),
        on_seen=lambda sid, page: _comments_seen(services, sid, page),
        on_delivered=lambda sid, event: (
            _event_delivered(answers, sid, event),
            _send_changed(state, events, sid, event),
        ),
        on_created=lambda sid, event: (
            _event_created(registry, sid, event),
            _send_changed(state, events, sid, event),
        ),
        project_of=lambda sid: _project_session(registry, sid),
        receiver_of=lambda project, event: _project_receiver(
            registry, events, project, event
        ),
    )
    state.events = events
    asks = AskService(
        registry, events, lambda kind, sid: _asks_changed(state, kind, sid)
    )
    asks.restore()
    state.asks = asks
    results = ResultService(registry, events, lambda sid: _results_changed(state, sid))

    state.tab_provider = lambda sid: _with_light(
        _tab(registry, state, sid), events, asks, results
    )
    herdr_app = HerdrApp(known_sessions=lambda: [t["id"] for t in registry.tabs()])
    # A session closed in the daily hub still shows in the Herdr pane that holds it.
    state.tabs_provider = lambda: [
        _with_light(t, events, asks, results) for t in registry.tabs(herdr_app.paired())
    ]
    state.closed_provider = registry.closed_tabs

    state.channel.register(
        "herdr", lambda initial: {"type": "herdr", **herdr_app.last}, 0
    )
    services = Services(
        state,
        registry,
        events,
        asks,
        looks,
        watcher,
        launcher,
        STATIC_DIR,
        answers,
        results,
        herdr_app=herdr_app,
    )
    looks.answers_of = lambda session, page: answers_message(services, session, page)
    state.channel.register(
        "comments", lambda initial: build_comments_view(services, initial), 0
    )
    state.channel.register(
        "answers", lambda initial: build_answers_view(services, initial), 0
    )
    app = Starlette(
        middleware=[Middleware(GuardMiddleware, state=state)],
        routes=[
            *all_routes(services),
            Mount("/static", _FreshStaticFiles(directory=STATIC_DIR), name="static"),
        ],
        lifespan=_lifespan,
    )
    app.state.services = services
    app.state.hub = state
    app.state.events = events
    app.state.registry = registry
    app.state.launcher = launcher
    app.state.watcher = watcher
    app.state.looks = looks
    return app


class _FreshStaticFiles(StaticFiles):
    """Static files the browser revalidates on every load (ETag, cheap on localhost).

    Without this a browser may keep an old ``shell.js`` after an update and run
    it with the new ``shell.html``.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Serve ``path`` with ``Cache-Control: no-cache``."""
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _is_watched(registry: SessionRegistry, session_id: str) -> bool:
    """Watch a session unless it is ended or hidden (HUB-05)."""
    meta = registry.get(session_id)
    return meta is None or (meta.state == "active" and not meta.hidden)


def _tab(registry: SessionRegistry, state: HubState, session_id: str) -> dict[str, Any]:
    """Tab description of a session for the shell (registry first)."""
    meta = registry.get(session_id)
    if meta is None:
        return state.bare_tab(session_id)
    return registry.tab_of(meta.raw)


def run_hub(config: Config, state_dir: Path) -> None:
    """
    Run the hub until interrupted.

    Parameters
    ----------
    config : Config
        Effective configuration.
    state_dir : pathlib.Path
        State directory.

    Raises
    ------
    agent_canvas.hub.auth.KeyFileError
        If the key file has unsafe permissions.
    """
    import uvicorn

    app = create_app(config, state_dir)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=config.port, log_level="warning")
    )
    app.state.hub.shutdown = lambda: setattr(server, "should_exit", True)
    server.run()
