"""Route group: the owner's file upload (VIEW-10) and Open (CNT-01)."""

from __future__ import annotations

import uuid
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from agent_canvas.drafts import is_draft_name
from agent_canvas.hub.auth import KEY_HEADER
from agent_canvas.hub.registry import RegistryError, pool_key
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    body_of,
    change_route,
    failure,
)
from agent_canvas.hub.viewers import viewer_type
from agent_canvas.paths import make_private_dirs
from agent_canvas.paths_safe import UnsafePathError, validate_page_name

MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def routes(services: Services) -> list[BaseRoute]:
    """Return the file routes."""
    return [
        change_route(
            services,
            "/api/sessions/{id}/files",
            upload_file,
            ["POST"],
            Declaration(views=("tabs",)),
        ),
        change_route(
            services,
            "/api/sessions/{id}/open-file",
            open_file,
            ["POST"],
            Declaration(views=("tabs",)),
        ),
    ]


def _refused(message: str, status: int) -> Response:
    return JSONResponse({"error": "invalid-file", "message": message}, status)


async def upload_file(request: Request, svc: Services, publish: Publish) -> Response:
    """Store the request body as a page of a session's pool and open it (VIEW-10)."""
    if svc.state.credentials.key_ok(request.headers.get(KEY_HEADER)):
        return _refused("Only the owner's window may upload files.", 403)
    session_id, registry = request.path_params["id"], svc.registry
    name = request.query_params.get("name", "")
    try:
        validate_page_name(name)
        if is_draft_name(name):
            raise UnsafePathError(f"{name!r} is a draft name; drafts are never shown.")
    except UnsafePathError as error:
        return _refused(str(error), 400)
    if registry.get(session_id) is None:
        if not registry.is_reserved(session_id):
            return failure(RegistryError("no-session", "Unknown session."))
        registry.ensure(session_id, "", "agent")
    try:
        pool = registry.pool_session(pool_key(registry.get(session_id).project))
    except RegistryError as error:
        return failure(error)
    folder = registry.folder_of(pool)
    make_private_dirs(folder)
    temporary = folder / f".upload-{uuid.uuid4().hex[:12]}"
    try:
        size = await _save_limited(request, temporary)
        if size is None:
            return _refused("The file is larger than 64 MB.", 413)
        if size == 0:
            return _refused("The file is empty.", 400)
        try:
            page = registry.store_upload(session_id, name, temporary)
        except RegistryError as error:
            return _refused(str(error), 400)
        try:
            _, page, path = registry.show(session_id, page, None, None)
        except RegistryError as error:
            (folder / page).unlink(missing_ok=True)  # do not leave an unlisted file
            return _refused(str(error), 400)
    finally:
        temporary.unlink(missing_ok=True)
    version = await _listed(svc, publish, session_id, page)
    return JSONResponse(
        {"session": session_id, "page": page, "path": str(path), "version": version}
    )


async def open_file(request: Request, svc: Services, publish: Publish) -> Response:
    """Show a Markdown, PDF or picture file of the session folder as a page (CNT-01)."""
    if svc.state.credentials.key_ok(request.headers.get(KEY_HEADER)):
        return _refused("Only the owner's window may open files.", 403)
    session_id, registry = request.path_params["id"], svc.registry
    name = (await body_of(request)).get("name")
    try:
        if not isinstance(name, str):
            raise UnsafePathError("The file name is missing.")
        validate_page_name(name)
        if is_draft_name(name) or viewer_type(name) is None:
            raise UnsafePathError(f"{name!r} is not a Markdown, PDF or picture file.")
    except UnsafePathError as error:
        return _refused(str(error), 400)
    if registry.get(session_id) is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        _, page, path = registry.show(session_id, name, None, None)
    except RegistryError as error:
        return _refused(str(error), 400)
    version = await _listed(svc, publish, session_id, page)
    return JSONResponse(
        {"session": session_id, "page": page, "path": str(path), "version": version}
    )


async def _listed(svc: Services, publish: Publish, session_id: str, page: str) -> int:
    """Watch and version a page that ``registry.show`` just listed; tell the windows."""
    svc.watcher.refresh()
    holder = svc.registry.pool_of(session_id) or session_id  # the page is the pool's
    svc.state.reset_page_status(holder, page)
    version = await svc.watcher.ingest(
        svc.state.session_of(holder), page, push=False, notify=False
    )
    publish("tabs")
    return version


async def _save_limited(request: Request, target: Path) -> int | None:
    """Write the body to ``target``; None once it exceeds the upload limit."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        return None
    total = 0
    with target.open("wb") as out:
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                return None
            out.write(chunk)
    return total
