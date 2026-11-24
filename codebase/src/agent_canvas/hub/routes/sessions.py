"""Route group: sessions, their pages, sends, history and cleanup (ARC-01, ARC-02)."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import BaseRoute

from agent_canvas.drafts import session_tag
from agent_canvas.hub import changes, comments
from agent_canvas.hub.cleanup import CleanupError, CleanupRequest, run_cleanup
from agent_canvas.hub.events import new_event_id
from agent_canvas.hub.lifetime import KINDS
from agent_canvas.hub.looks import LookError, LookRequest, LookService
from agent_canvas.hub.registry import (
    RegistryError,
    _page_title,
    is_project_id,
    now_iso,
    pool_key,
    validate_or_raise,
)
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    body_of,
    change_route,
    changed,
    failure,
    read_route,
    resumed,
)
from agent_canvas.hub.sends import (
    NOT_SHOWN,
    SENDS_DIR,
    clean_send,
    comments_for_send,
    event_fields,
    list_sends,
    new_send_id,
    next_number,
    read_screenshot,
    store_send,
)
from agent_canvas.hub.state import HubState
from agent_canvas.hub.viewers import viewer_type
from agent_canvas.hub.waiting import Waiting, for_agent
from agent_canvas.hub.watcher import PageHistory, is_page_name
from agent_canvas.hub.window import WindowLauncher

logger = logging.getLogger(__name__)

RENDER_WAIT_SECONDS = 2.0
MAX_SEND_BYTES = 16 * 1024 * 1024
SEND_PNG = re.compile(r"^(\d+)(?:\.c(\d+))?\.png$")


def routes(services: Services) -> list[BaseRoute]:
    """Return the session routes."""
    tabs = Declaration(("tabs",))
    base = "/api/sessions"

    def change(path: str, handler: Any, declaration: Declaration) -> BaseRoute:
        return change_route(services, path, handler, ["POST"], declaration)

    return [
        read_route(services, base, list_sessions, ["GET"]),
        change_route(services, base, start_session, ["POST"], tabs),
        read_route(services, base + "/{id}", get_session),
        change(base + "/{id}/path", session_path, tabs),
        change(
            base + "/{id}/reserve",
            session_reserve,
            Declaration(reason="a reserved id shows no tab until a command uses it"),
        ),
        change(base + "/{id}/show", session_show, tabs),
        change(base + "/{id}/title", session_title, tabs),
        change(base + "/{id}/end", session_end, tabs),
        change(base + "/{id}/rename", session_rename, tabs),
        change(base + "/{id}/hide", session_hide, tabs),
        change(base + "/{id}/unhide", session_unhide, tabs),
        read_route(services, base + "/{id}/versions", session_versions),
        read_route(services, base + "/{id}/changes", session_changes),
        change(
            base + "/{id}/look",
            session_look,
            Declaration(reason="the look service reports to the window itself"),
        ),
        change(
            base + "/{id}/send",
            session_send,
            Declaration(views=("comments",)),
        ),
        read_route(services, base + "/{id}/sends", session_sends),
        read_route(services, base + "/{id}/sends/{name}", send_screenshot),
        change_route(
            services,
            "/api/cleanup",
            cleanup,
            ["POST"],
            Declaration(("tabs", "comments", "answers")),
        ),
        change(
            base + "/{id}/pending",
            session_pending,
            Declaration(reason="the event service moves the listening light itself"),
        ),
    ]


def summary(svc: Services, meta: dict[str, Any]) -> dict[str, Any]:
    """Return the listing entry of a session."""
    return {
        "id": meta["id"],
        "project": meta["project"],
        "agent": meta["agent"],
        "title": svc.registry.effective_title(meta),
        "state": meta["state"],
        "listening": svc.events.listening(meta["id"]) and meta["state"] != "ended",
    }


def folder_result(
    svc: Services, publish: Publish, meta: dict[str, Any], published: bool
) -> Response:
    """
    Answer with a session's id, its pool folder and draft tag (POOL-01, POOL-11).

    A pool made here sends ``tabs`` unless the caller ``published`` it already.
    """
    new = svc.registry.pool_of(meta["id"]) is None
    try:
        pool = svc.registry.pool_session(pool_key(meta["project"]))
    except RegistryError as error:
        return failure(error)
    if new and not published:
        publish("tabs")
    folder = str(svc.registry.folder_of(pool))
    return JSONResponse(
        {"session": meta["id"], "folder": folder, "tag": session_tag(meta["id"])}
    )


def known_session(svc: Services, request: Request) -> Any:
    """Return the registered session of the request, or None."""
    try:
        return svc.state.session_of(request.path_params["id"])
    except KeyError:
        return None


def page_session(svc: Services, session_id: str) -> Any:
    """
    Return the registered session that holds a card's pages, or None.

    A session of a project with a pool resolves to the pool; any other one
    (and a pool itself) to itself (POOL-01).
    """
    try:
        return svc.state.session_of(svc.registry.pool_of(session_id) or session_id)
    except KeyError:
        return None


def card_of(session: Any, session_id: str) -> str | None:
    """Return the card a page request comes from when its pages are a pool's."""
    return session_id if is_project_id(session.session_id) else None


async def list_sessions(request: Request, svc: Services) -> Response:
    """List sessions (GET); a project's pool is not one (A-1146)."""
    params = request.query_params
    metas = svc.registry.list(params.get("all") == "1", params.get("project"))
    return JSONResponse([summary(svc, m) for m in metas if not is_project_id(m["id"])])


async def start_session(request: Request, svc: Services, publish: Publish) -> Response:
    """Start a session (POST)."""
    body = await body_of(request)
    try:
        meta = svc.registry.start(
            str(body.get("project", "")),
            str(body.get("agent") or "agent"),
            body.get("title"),
        )
    except RegistryError as error:
        return failure(error)
    publish("tabs")
    return folder_result(svc, publish, meta, published=True)


async def get_session(request: Request, svc: Services) -> Response:
    """Return one session's registry entry."""
    try:
        meta = svc.registry.get(validate_or_raise(request.path_params["id"]))
    except RegistryError as error:
        return failure(error)
    if meta is None:
        return failure(RegistryError("no-session", "Unknown session."))
    return JSONResponse(meta.raw)


async def session_path(request: Request, svc: Services, publish: Publish) -> Response:
    """Ensure a session exists and return its folder."""
    body = await body_of(request)
    try:
        meta, created = svc.registry.ensure(
            request.path_params["id"],
            str(body.get("project", "")),
            str(body.get("agent") or "agent"),
        )
    except RegistryError as error:
        return failure(error)
    if created:
        publish("tabs")
    resumed(svc, publish, request.path_params["id"])
    return folder_result(svc, publish, meta, published=created)


async def session_reserve(
    request: Request, svc: Services, publish: Publish
) -> Response:
    """Reserve the id of a new agent session without creating anything."""
    body = await body_of(request)
    try:
        reserved = svc.registry.reserve(
            request.path_params["id"],
            str(body.get("project", "")),
            str(body.get("agent") or "agent"),
        )
    except RegistryError as error:
        return failure(error)
    return JSONResponse({"session": request.path_params["id"], "reserved": reserved})


async def session_show(request: Request, svc: Services, publish: Publish) -> Response:
    """Show a page of the session's pool (POOL-01, POOL-06)."""
    state, registry, watcher = svc.state, svc.registry, svc.watcher
    body = await body_of(request)
    session_id = request.path_params["id"]
    kind = body.get("kind")
    if kind is not None and kind not in KINDS:
        return failure(RegistryError("usage", f"Unknown kind {kind!r}."))
    try:
        _, created = registry.ensure(
            session_id,
            str(body.get("project", "")),
            str(body.get("agent") or "agent"),
        )
        if created:
            publish("tabs")
        resumed(svc, publish, session_id)
        pool_meta, page, path = registry.show(
            session_id,
            body.get("name"),
            body.get("title"),
            body.get("copy"),
            publish=body.get("publish") is True,
        )
        pool = pool_meta["id"]
        chosen = registry.set_kind(pool, page, kind) if kind else None
    except RegistryError as error:
        return failure(error)
    watcher.refresh()  # a hidden session is watched again once shown
    # show_page only scheduled the broadcast, so the shell cannot have
    # reported yet: stale reports are dropped before it does.
    state.reset_page_status(pool, page)
    session = state.session_of(pool)
    # A published draft replaces a page that may be on screen: push it, so the
    # open frame is morphed in place (blocks keep their state) and not left stale.
    version = await watcher.ingest(
        session, page, push=body.get("publish") is True, notify=False
    )
    svc.answers.page_changed(pool, page)  # a new version may reopen an item
    window = await svc.launcher.ensure()
    if window == "launched":
        state.open_on_connect = (session_id, page)
    rendered = await _rendered(state, svc.launcher, pool, page)
    audit = None
    extra: dict[str, Any] = {}
    if viewer_type(page):
        # The page checks run on HTML pages only (VIEW-12).
        extra["viewer_error"] = (
            await svc.looks.viewer_error_for_show(session, page)
            if body.get("audit") is not False
            else None
        )
    elif body.get("audit") is not False:
        audit = await svc.looks.audit_for_show(session, page)
    return JSONResponse(
        {
            "session": session_id,
            "page": page,
            "path": str(path),
            "url": state.frame_url(pool, page),
            "version": version,
            "window": window,
            "rendered": rendered,
            "errors": state.page_status(pool, page).errors,
            "audit": audit,
            "next": _next_step(page, path, body.get("title")),
            **({"kind": chosen["kind"], "set_by": chosen["set_by"]} if chosen else {}),
            **_audit_note(svc.looks, audit),
            **extra,
        }
    )


async def session_look(request: Request, svc: Services, publish: Publish) -> Response:
    """Render a page or draft and store the picture (LOOK-01, LOOK-07)."""
    card = request.path_params["id"]
    session = page_session(svc, card)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    pooled = card_of(session, card)
    try:
        wanted = LookRequest.from_body(await body_of(request))
        meta = svc.registry.get(card)
        tab = svc.registry.tab_of(meta.raw) if meta else {}
        active = tab.get("active_page")
        tag = session_tag(card) if pooled else None
        result = await svc.looks.look(session, wanted, active, tag)
    except LookError as error:
        status = 404 if error.code == "no-session" else 422
        body = {"error": error.code, "message": str(error)}
        return JSONResponse(body, status_code=status)
    return JSONResponse(result)


async def session_title(request: Request, svc: Services, publish: Publish) -> Response:
    """Set the agent's title of a session."""
    body = await body_of(request)
    title = body.get("title")
    if not isinstance(title, str) or not title:
        return failure(RegistryError("failed", "A non-empty title is required."))
    try:
        meta = svc.registry.set_title(request.path_params["id"], title)
    except RegistryError as error:
        return failure(error)
    publish("tabs")
    return JSONResponse({"session": meta["id"], "title": meta["title"]})


async def session_end(request: Request, svc: Services, publish: Publish) -> Response:
    """End a session."""
    try:
        meta = svc.registry.end(request.path_params["id"])
    except RegistryError as error:
        return failure(error)
    svc.asks.dismiss_all(meta["id"], "session-ended")
    svc.watcher.refresh()
    publish("tabs")
    return JSONResponse({"session": meta["id"], "state": meta["state"]})


async def session_rename(request: Request, svc: Services, publish: Publish) -> Response:
    """Set the owner's title of a session."""
    body = await body_of(request)
    title = body.get("title")
    if not isinstance(title, str):
        return failure(RegistryError("failed", "A title string is required."))
    try:
        meta = svc.registry.rename(request.path_params["id"], title)
    except RegistryError as error:
        return failure(error)
    publish("tabs")
    return JSONResponse({"session": meta["id"], "owner_title": meta["owner_title"]})


async def session_hide(request: Request, svc: Services, publish: Publish) -> Response:
    """Hide a session."""
    try:
        meta = svc.registry.set_hidden(request.path_params["id"], True)
    except RegistryError as error:
        return failure(error)
    svc.watcher.refresh()
    publish("tabs")
    return JSONResponse({"session": meta["id"], "hidden": True})


async def session_unhide(request: Request, svc: Services, publish: Publish) -> Response:
    """Unhide a session."""
    try:
        meta = svc.registry.set_hidden(request.path_params["id"], False)
    except RegistryError as error:
        return failure(error)
    svc.watcher.refresh()
    publish("tabs")
    return JSONResponse({"session": meta["id"], "hidden": False})


async def session_versions(request: Request, svc: Services) -> Response:
    """List the versions of a page; a card's pages are its pool's (POOL-01)."""
    session = page_session(svc, request.path_params["id"])
    page = request.query_params.get("page", "")
    if session is None or "/" in page or not (is_page_name(page) or viewer_type(page)):
        return failure(RegistryError("no-session", "Unknown session or page."))
    versions = PageHistory(session.folder).versions(page)
    listing = [{"version": number, "time": _iso(mtime)} for number, mtime in versions]
    return JSONResponse({"page": page, "versions": listing})


async def session_changes(request: Request, svc: Services) -> Response:
    """
    Say what changed in a page since the owner last saw it (NEW-03).

    ``since`` names the version to compare from; without it the recorded
    ``seen_version`` is used, and a page never seen has no changes. Reading
    this never counts as seeing (NEW-01). A card's pages are its pool's.
    """
    session = page_session(svc, request.path_params["id"])
    page = request.query_params.get("page", "")
    if session is None or "/" in page or not (is_page_name(page) or viewer_type(page)):
        return failure(RegistryError("no-session", "Unknown session or page."))
    history = PageHistory(session.folder)
    latest = history.latest(page)
    if latest is None:
        return failure(RegistryError("no-session", "Unknown session or page."))
    meta = svc.registry.get(session.session_id)
    entry = (meta.page_meta if meta else {}).get(page, {})
    seen = entry.get("seen_version")
    since = request.query_params.get("since")
    since = int(since) if since and since.isascii() and since.isdigit() else seen
    old = history.read(page, since) if since and since < latest[0] else None
    result = changes.compare(page, old, latest[1]) if old is not None else None
    body: dict[str, Any] = {"page": page, "version": latest[0], "since": None}
    body |= {
        "since_time": None,
        "added": [],
        "changed": [],
        "removed": [],
        "outside": False,
    }
    if result is not None and changes.count(result):
        when = entry.get("seen_at") if since == seen else None
        if when is None:
            when = _iso(dict(history.versions(page))[since])
        body |= {"since": since, "since_time": when, **result}
    body["count"] = changes.count(body)
    return JSONResponse(body)


async def session_send(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Store an uploaded send and create its events, one per page (COM-10, COM-11).

    A send about a pool page takes only the card's comments, and its events go
    to the pool's log with ``for`` naming the card (POOL-05); a send without a
    page stays the session's own (A-1019).
    """
    own = known_session(svc, request)
    if own is None:
        return failure(RegistryError("no-session", "Unknown session."))
    raw = await _read_limited(request, MAX_SEND_BYTES)
    if raw is None:
        return _send_refused("The send is larger than 16 MB.", 413)
    try:
        clean = clean_send(json.loads(raw))
    except ValueError as error:  # SendError is a ValueError; so is bad JSON
        return _send_refused(str(error) or "Body is not JSON.", 400)
    session = page_session(svc, own.session_id) if clean["page"] else own
    card = card_of(session, own.session_id)
    folder, page, delivery = session.folder, clean["page"], clean["delivery"]
    if clean["marks"]:
        logger.warning(
            "send of session %s: dropped %d marks from a shell older than revision 12",
            session.session_id,
            len(clean["marks"]),
        )
    # The hub, not the window, decides which comments go (COM-11).
    names = [page, *clean["pages"]] if page else [None]
    event_ids = {name: new_event_id() for name in names}
    sent_at = now_iso()  # also the events' time: a reply's `sent` equals it (5.3)
    taken = {
        name: comments.take_unsent(
            folder, name, delivery, event_ids[name], sent_at, card
        )
        if name
        else []
        for name in names
    }
    if not (any(taken.values()) or clean["message"].strip() or clean["actions"]):
        return _send_refused("Nothing to send: no comment, message or action.", 400)
    parts = [names[0], *(name for name in names[1:] if taken[name])]
    send_id, stored, numbers = new_send_id(), [], []
    try:
        for k, name in enumerate(parts, 1):
            numbers.append(number := next_number(folder))
            part = {**clean, "page": name}
            if k > 1:
                part.update(
                    message="", actions=[], actions_dropped=0, png=None,
                    screenshot_error=NOT_SHOWN, screenshot_warnings=[],
                )  # fmt: skip
            part["comments"] = comments_for_send(folder, taken[name], number)
            latest = PageHistory(folder).latest(name) if name else None
            record = store_send(
                folder, card or session.session_id, event_ids[name],
                latest[0] if latest else None, part, send_id, [k, len(parts)],
            )  # fmt: skip
            stored.append((name, number, record))
    except Exception:
        for number in numbers:
            for leftover in (folder / SENDS_DIR).glob(f"{number:04d}.*"):
                leftover.unlink()
        for name in names:
            if name:
                comments.restore_drafts(folder, name, event_ids[name])
        raise
    finally:
        for name in names:
            if name and taken[name]:
                changed(svc, publish, own.session_id, name)
    pooled = {"for": card} if card else {}
    events = [
        svc.events.create(
            session.session_id,
            "send",
            event_id=event_ids[name],
            delivery=delivery,
            page=name,
            page_version=record["page_version"],
            fields={**event_fields(folder, record, number), "time": sent_at, **pooled},
        )
        for name, number, record in stored
    ]
    return JSONResponse({"event": events[0], "number": stored[0][1], "events": events})


async def session_sends(request: Request, svc: Services) -> Response:
    """List the sends of a session: its own and its card's in the pool (A-1035)."""
    session = known_session(svc, request)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    return JSONResponse({"sends": _card_sends(svc, session)})


def _card_sends(svc: Services, session: Any) -> list[dict[str, Any]]:
    """Return a session's own sends, then its card's sends in its pool."""
    own = list_sends(session.folder)
    holder = page_session(svc, session.session_id)
    if holder is None or holder.session_id == session.session_id:
        return own
    card = session.session_id
    return own + [s for s in list_sends(holder.folder) if s.get("session") == card]


async def send_screenshot(request: Request, svc: Services) -> Response:
    """
    Return the screenshot of a send, or with ``.c<n>`` its comment's picture.

    A pool member's number names its card's send in the pool when there is one,
    else its own send (A-1035).
    """
    session = known_session(svc, request)
    match = SEND_PNG.match(request.path_params["name"])
    data = None
    if session and match:
        number = int(match[1])
        holder = page_session(svc, session.session_id)
        pooled = holder is not None and holder.session_id != session.session_id
        mine = pooled and any(
            s["number"] == number and s.get("session") == session.session_id
            for s in list_sends(holder.folder)
        )
        folder = holder.folder if mine else session.folder
        data = read_screenshot(folder, number, match[2])
    if data is None:
        return PlainTextResponse("not found", status_code=404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


async def cleanup(request: Request, svc: Services, publish: Publish) -> Response:
    """Delete history by age or for one session (CLI-11)."""
    try:
        wanted = CleanupRequest.from_body(await body_of(request))
        result = run_cleanup(svc.registry, svc.state, svc.events, wanted)
    except CleanupError as error:
        status = 404 if error.code == "no-session" else 422
        return JSONResponse(
            {"error": error.code, "message": str(error)}, status_code=status
        )
    if wanted.yes:
        svc.watcher.refresh()
        publish("tabs")
        publish("comments")
        publish("answers")
    return JSONResponse(result)


async def session_pending(
    request: Request, svc: Services, publish: Publish
) -> Response:
    """Return the pending events of a session."""
    registry = svc.registry
    try:
        session_id = validate_or_raise(request.path_params["id"])
        meta = registry.get(session_id)
    except RegistryError as error:
        return failure(error)
    if is_project_id(session_id):  # a pool's events go to its sessions (POOL-05)
        return failure(
            RegistryError(
                "no-session", f"{session_id} is a project's page pool, not a session."
            )
        )
    if meta is None and not registry.is_reserved(session_id):
        return failure(RegistryError("no-session", "Unknown session."))
    body = await body_of(request)
    via = body.get("via")
    via = via if via in ("hook", "mcp") else "pending"
    peek = bool(body.get("peek"))
    if meta is None:  # reserved: no folder, but the project's inbox (PROJ-09)
        taken = svc.events.project_pending(session_id, peek=peek, via=via)
        return JSONResponse({"session": session_id, "events": taken, "reminders": []})
    summary = Waiting(
        feedback=svc.events.pending(meta.id, peek=peek, via=via),
        reminders=registry.reminders(
            meta.id,
            stamp=not peek,
            alive=lambda writer: (
                svc.events.listening(writer) or svc.herdr_app.alive(writer)
            ),
        ),
        boxes=svc.answers.open_boxes(meta.id),
    )
    told = for_agent(summary)
    return JSONResponse(
        {"session": meta.id, **told}
        | (
            {"listening": svc.events.listening(meta.id)}
            if {"waiting", "waiting_todos"} & told.keys()
            else {}
        )
    )


async def _rendered(
    state: HubState,
    launcher: WindowLauncher,
    session_id: str,
    page: str,
) -> bool | str:
    """
    Wait up to 2 s for the page's load report (CLI-03).

    Returns
    -------
    bool | str
        True once loaded, ``"pending"`` if a shell is connected or a window is
        launching but the page did not load in time, False otherwise.
    """
    if not state.shells and not launcher.launching:
        return False
    if await state.wait_loaded(session_id, page, RENDER_WAIT_SECONDS):
        return True
    return "pending"


async def _read_limited(request: Request, limit: int) -> bytes | None:
    """Read the request body; None once it exceeds ``limit`` bytes (any framing)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _send_refused(message: str, status: int) -> Response:
    """Return the error response for a send that cannot be stored."""
    body = {"error": "invalid-send", "message": message}
    return JSONResponse(body, status_code=status)


def _next_step(page: str, path: Path, given: str | None) -> str:
    """Return the one-line next step after ``show`` (AGI-06, AGI-22)."""
    title = given or _page_title(path) or page
    return (
        f'Tell the owner the page "{title}" is on the canvas. Answers come with '
        "the owner's next message; to get them now, run `agent-canvas watch "
        "--timeout 540` under Monitor."
    )


def _audit_note(looks: LookService, audit: Any) -> dict[str, str]:
    """Return ``audit_note`` when a connected window is why the audit failed."""
    note = looks.window_problem if audit == "unavailable" else None
    return {"audit_note": note} if note else {}


def _iso(timestamp: float) -> str:
    """Format a POSIX time as UTC ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
