"""Route group: hub control, owner pages and page files (ARC-01, ARC-02)."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import BaseRoute

from agent_canvas import __version__
from agent_canvas.config import load_keys, save_keys
from agent_canvas.hub.auth import cookie_name
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    body_of,
    change_route,
    read_route,
)
from agent_canvas.hub.serve import (
    content_type,
    frame_csp,
    inject_helper,
    resolve_session_file,
    source_digest,
)
from agent_canvas.hub.viewers import viewer_document, viewer_type
from agent_canvas.hub.watcher import PageHistory

ACTION_NAME = re.compile(r"[a-z][a-z0-9._:-]{0,59}")
MAX_KEY_ACTIONS = 300
MAX_KEYS_PER_ACTION = 12
MAX_KEY_LENGTH = 40
BUILD_PLACEHOLDER = "__AGENT_CANVAS_BUILD__"
# No other site may put the owner's pages in a frame (SEC-11).
OWNER_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def routes(services: Services) -> list[BaseRoute]:
    """Return the hub-control and page routes."""
    return [
        read_route(services, "/health", health),
        read_route(services, "/login", login),
        read_route(services, "/", shell),
        read_route(services, "/render", render_host),
        read_route(services, "/api/status", status),
        read_route(services, "/api/keys", keys),
        change_route(
            services,
            "/api/keys",
            save_owner_keys,
            ["POST"],
            Declaration(reason="the window applies its own key change at once"),
        ),
        change_route(
            services,
            "/api/shutdown",
            shutdown,
            ["POST"],
            Declaration(reason="the hub stops; there is no window state to update"),
        ),
        change_route(
            services,
            "/api/open",
            open_window,
            ["POST"],
            Declaration(reason="the window launcher connects the window itself"),
        ),
        read_route(
            services, "/s/{token}/{path:path}", page_file, methods=["GET", "HEAD"]
        ),
    ]


async def health(request: Request, svc: Services) -> Response:
    """Answer that the hub runs; prove the key for a ``challenge`` (SEC-13)."""
    answer = {"app": "agent-canvas", "version": __version__}
    if (challenge := request.query_params.get("challenge")) is not None:
        answer["proof"] = svc.state.credentials.health_proof(svc.state.port, challenge)
    return JSONResponse(answer)


async def login(request: Request, svc: Services) -> Response:
    """Exchange a one-time token for the owner's cookie."""
    state = svc.state
    if not state.credentials.consume_login_token(request.query_params.get("t")):
        return PlainTextResponse("invalid or expired login token", status_code=401)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        cookie_name(state.port),
        state.credentials.cookie_value,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


async def shell(request: Request, svc: Services) -> Response:
    """Serve the shell page."""
    # The page records the build it was loaded with (SHELL-02).
    html = (svc.static_dir / "shell.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html.replace(BUILD_PLACEHOLDER, svc.state.build_id),
        headers=OWNER_PAGE_HEADERS,
    )


async def render_host(request: Request, svc: Services) -> Response:
    """Serve the page a headless browser loads to prepare a look (LOOK-06)."""
    return FileResponse(svc.static_dir / "render.html", headers=OWNER_PAGE_HEADERS)


async def keys(request: Request, svc: Services) -> Response:
    """Answer the owner's key file, read afresh (KMAP-02)."""
    return JSONResponse(load_keys())


def _valid_keys(keys: object) -> bool:
    """Return True for ``{action: [key, ...]}`` within the size limits."""
    return (
        isinstance(keys, dict)
        and len(keys) <= MAX_KEY_ACTIONS
        and all(
            isinstance(action, str)
            and ACTION_NAME.fullmatch(action)
            and isinstance(listed, list)
            and len(listed) <= MAX_KEYS_PER_ACTION
            and all(isinstance(k, str) and 0 < len(k) <= MAX_KEY_LENGTH for k in listed)
            for action, listed in keys.items()
        )
    )


async def save_owner_keys(
    request: Request, svc: Services, publish: Publish
) -> Response:
    """Save the chosen key profile and the owner's own changes to ``keys.toml``."""
    body = await body_of(request)
    profile, keys = body.get("profile"), body.get("keys")
    known = {p["name"] for p in load_keys()["profiles"]}
    if not body or set(body) - {"profile", "keys"}:
        return JSONResponse({"message": "give profile and/or keys"}, status_code=400)
    if "profile" in body and profile not in known:
        return JSONResponse({"message": "unknown profile"}, status_code=400)
    if "keys" in body and not _valid_keys(keys):
        return JSONResponse(
            {"message": "keys must map actions to lists of keys"}, status_code=400
        )
    save_keys(profile, keys)
    return JSONResponse(load_keys())


async def status(request: Request, svc: Services) -> Response:
    """Report the hub's state."""
    state = svc.state
    return JSONResponse(
        {
            "hub": "running",
            "version": __version__,
            "build": state.build_id,
            "port": state.port,
            "window_connected": bool(state.shells),
            "sessions": len(svc.registry.list(False, None)),
        }
    )


async def shutdown(request: Request, svc: Services, publish: Publish) -> Response:
    """Stop the hub gracefully (M3); the answer is sent first."""
    state = svc.state
    if state.shutdown is None or state.loop is None:
        return JSONResponse({"stopping": False}, status_code=501)
    state.loop.call_later(0.1, state.shutdown)
    return JSONResponse({"stopping": True})


async def open_window(request: Request, svc: Services, publish: Publish) -> Response:
    """Open the canvas window, or print its login URL."""
    if (await body_of(request)).get("print_url") is True:
        # For a hub reached through an SSH tunnel: no window is launched.
        return JSONResponse({"url": svc.launcher.login_url()})
    return JSONResponse({"window": await svc.launcher.ensure(force=True)})


async def page_file(request: Request, svc: Services) -> Response:
    """Serve a file of a session's page (sandboxed site)."""
    state = svc.state
    session = state.session_by_token(request.path_params["token"])
    if session is None:
        return PlainTextResponse("not found", status_code=404)
    path = resolve_session_file(session.folder, request.path_params["path"])
    if path is None:
        return PlainTextResponse("not found", status_code=404)
    headers = {
        "Content-Security-Policy": frame_csp(state.port, session.page_token),
        "Cache-Control": "no-store",
    }
    is_html = path.suffix.lower() in (".html", ".htm")
    kind = viewer_type(path.name) if path.parent == session.folder else None
    content = b""
    if (version := request.query_params.get("v")) is not None:
        # HIST-02, VIEW-02: an earlier version of a top-level page, under the
        # page's own URL so that relative assets resolve to the current files.
        # Only history/pages/ is read.
        history = PageHistory(session.folder)
        found = None
        if (
            version.isascii()
            and version.isdigit()
            and path.parent == session.folder
            and (is_html or kind)
        ):
            found = history.read(path.name, int(version))
        if found is None:
            return PlainTextResponse("not found", status_code=404)
        content = found
    elif is_html:
        content = path.read_bytes()  # large data files are streamed instead
    if kind and request.query_params.get("ac-view") == "1":
        meta = svc.registry.get(session.session_id)
        if path.name in (meta.pages if meta else ()):
            # VIEW-02: the viewer document of a listed Markdown, PDF or picture.
            return Response(
                viewer_document(path.name),
                media_type="text/html; charset=utf-8",
                headers=headers,
            )
    if is_html:
        return Response(
            inject_helper(content, source_digest(content)),
            media_type="text/html; charset=utf-8",
            headers=headers,
        )
    if version is not None:
        return Response(content, media_type=content_type(path), headers=headers)
    return FileResponse(path, media_type=content_type(path), headers=headers)
