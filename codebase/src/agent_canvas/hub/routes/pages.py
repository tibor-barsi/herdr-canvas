"""Route group: page lifetime calls of the agent (LIFE-01, LIFE-04, LIFE-05)."""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from agent_canvas.hub.migrate import left_behind, migrate_project
from agent_canvas.hub.registry import RegistryError, pool_key
from agent_canvas.hub.routes.comments import _is_agent, _is_owner
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    body_of,
    change_route,
    failure,
    read_route,
)

ACTIONS = ("kind", "archive", "restore", "extend", "pin", "unpin")
OWNER_PAGE_KEYS = {"session", "page", "kind", "archive", "restore", "star", "pin"}


def routes(services: Services) -> list[BaseRoute]:
    """Return the page routes."""
    declared = Declaration(views=("tabs",))
    return [
        change_route(
            services, "/api/sessions/{id}/pages", page_action, ["POST"], declared
        ),
        # the owner's window still calls this path; it keeps its old name
        change_route(services, "/api/home/pages", set_page, ["POST"], declared),
        read_route(services, "/api/sessions/{id}/pages", page_list),
        change_route(
            services,
            "/api/pages/migrate",
            migrate_pages,
            ["POST"],
            Declaration(("tabs", "comments", "answers")),
        ),
    ]


async def page_action(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Run a page action of the agent (key only); the body is ``{action, name, ...}``.

    ``kind`` takes ``kind`` and answers ``{page, kind, set_by}``; ``archive``
    answers ``{page, archived, deleted_after}``, ``restore`` ``{page, archived}``,
    ``extend`` ``{page, expires}`` and ``pin``, ``unpin`` ``{page, pinned, kind,
    set_by}`` (POOL-04). Each publishes ``tabs``.
    """
    if not _is_agent(request, svc):
        message = "Only an agent changes a page."
        return JSONResponse(
            {"error": "unauthorised", "message": message}, status_code=403
        )
    body = await body_of(request)
    action, name = body.get("action"), body.get("name")
    if action not in ACTIONS or not isinstance(name, str):
        message = f"action must be one of {', '.join(ACTIONS)}, with a page name."
        return failure(RegistryError("usage", message))
    session_id, registry = request.path_params["id"], svc.registry
    try:
        if action == "kind":
            answer = registry.set_kind(session_id, name, str(body.get("kind")))
        elif action == "archive":
            answer = registry.archive(session_id, name)
        elif action == "restore":
            answer = registry.restore_page(session_id, name)
        elif action in ("pin", "unpin"):
            answer = registry.set_pin(session_id, name, action == "pin")
        else:
            answer = registry.extend(session_id, name)
    except RegistryError as error:
        return failure(error)
    publish("tabs")
    return JSONResponse({"session": session_id, **answer})


async def page_list(request: Request, svc: Services) -> Response:
    """List the session's pages; ``?archived=1`` adds the archived ones (LIFE-05)."""
    try:
        pages = svc.registry.page_list(
            request.path_params["id"], request.query_params.get("archived") == "1"
        )
    except RegistryError as error:
        return failure(error)
    answer = {"session": request.path_params["id"], "pages": pages}
    found = svc.registry.pool_of(request.path_params["id"])
    pool = svc.registry.get(found) if found else None
    if pool and (rows := left_behind(svc.registry.folder_of(pool), pool.project)):
        answer["left_behind"] = rows  # the migration's older copies and clashes (Q3)
    return JSONResponse(answer)


async def migrate_pages(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Plan the migration of a project into its pool; ``yes`` carries it out (POOL-09).

    The body is ``{project, yes}``; the answer is the plan, or the migration log.
    """
    if svc.registry.follow_file is not None:
        message = "This canvas runs beside the daily one; it does not migrate pages."
        return failure(RegistryError("failed", message))
    body = await body_of(request)
    project = body.get("project")
    if not isinstance(project, str) or not project:
        return failure(RegistryError("usage", "Give the project folder."))
    yes = body.get("yes") is True
    key = pool_key(str(Path(project).resolve()))
    known = {pool_key(m["project"]) for m in svc.registry.list(True, None)}
    if key not in known:
        message = f"No session of this canvas works in {key}; nothing to migrate."
        return failure(RegistryError("failed", message))
    try:
        result = migrate_project(svc.registry, key, apply=yes)
    except RegistryError as error:
        return failure(error)
    if yes:
        svc.watcher.refresh()
        publish("tabs")
        publish("comments")
        publish("answers")
    return JSONResponse({"project": key, "applied": yes, **result})


async def set_page(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Set a page's kind, star or pin, archive or restore it, for the owner (LIFE-10).

    The body is ``{session, page, kind | star: bool | pin: bool | archive: true |
    restore: true}`` (STAR-01, POOL-04);
    only the owner's window may call it, so the kind it sets is the owner's. A
    restore also unhides the session. The answer is that of the registry call.
    """
    if not _is_owner(request, svc):
        return _page_refused("Only the owner's window changes a page here.", 403)
    body = await body_of(request)
    actions = [
        key for key in ("kind", "star", "pin", "archive", "restore") if key in body
    ]
    session_id, page = body.get("session"), body.get("page")
    if (
        not set(body) <= OWNER_PAGE_KEYS
        or not isinstance(session_id, str)
        or not isinstance(page, str)
        or len(actions) != 1
        or (actions[0] in ("star", "pin") and not isinstance(body[actions[0]], bool))
        or (actions[0] in ("archive", "restore") and body[actions[0]] is not True)
    ):
        return _page_refused(
            "Send session, page and exactly one of kind, star: true or false, "
            "pin: true or false, archive: true, restore: true."
        )
    registry = svc.registry
    try:
        if "kind" in body:
            answer = registry.set_kind(session_id, page, str(body["kind"]), by="owner")
        elif "star" in body:
            answer = registry.set_star(session_id, page, body["star"])
        elif "pin" in body:
            answer = registry.set_pin(session_id, page, body["pin"], by="owner")
        elif "archive" in body:
            answer = registry.archive(session_id, page, by="owner")
        else:
            answer = registry.restore_page(session_id, page)
            registry.set_hidden(session_id, False)
            svc.watcher.refresh()
    except RegistryError as error:
        return failure(error)
    publish("tabs")
    return JSONResponse({"session": session_id, **answer})


def _page_refused(message: str, status: int = 400) -> Response:
    return JSONResponse({"error": "invalid-page", "message": message}, status)
