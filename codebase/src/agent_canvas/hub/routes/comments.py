"""Route group: the comment store's routes (ARC-01, COM-04, COM-09, RPL-01 to RPL-03).

Who may do what (RPL-03): the key lists, replies and marks done; the owner's
cookie creates, edits, deletes, replies, marks done, reopens and marks read.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from agent_canvas.hub import comments
from agent_canvas.hub.auth import KEY_HEADER, cookie_name
from agent_canvas.hub.comments import CommentError
from agent_canvas.hub.registry import RegistryError
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    change_route,
    changed,
    failure,
    read_route,
)
from agent_canvas.hub.routes.sessions import _read_limited, card_of, page_session
from agent_canvas.hub.watcher import PageHistory

MAX_BODY_BYTES = 14 * 1024 * 1024  # a 10 MB picture in base64 and the other fields
BASE = "/api/sessions/{id}/comments"
OWNER_LABELS = ("owner", "you", "me")
MAX_AUTHOR = 40
EDIT_ACTIONS = ("text", "delete", "done", "reopen", "reply", "read")
REMEMBERED_REQUESTS = 500
_answered: OrderedDict[tuple[str, str], Any] = OrderedDict()


def routes(services: Services) -> list[BaseRoute]:
    """Return the comment routes."""
    declared = Declaration(views=("comments",))
    return [
        read_route(services, BASE, list_comments, ["GET"]),
        change_route(services, BASE, create_comment, ["POST"], declared),
        change_route(services, BASE + "/edit", edit_comment, ["POST"], declared),
        change_route(services, BASE + "/lost", report_lost, ["POST"], declared),
        change_route(services, BASE + "/reply", reply_comment, ["POST"], declared),
        change_route(services, BASE + "/done", done_comments, ["POST"], declared),
    ]


def comments_message(
    svc: Services, session_id: str, page: str
) -> dict[str, Any] | None:
    """
    Build the ``comments`` message of one page (5.14).

    Parameters
    ----------
    svc : Services
        The service bundle.
    session_id, page : str
        The card's session and the page; a pool page's comments come from the
        pool, and ``unsent`` counts the card's own drafts (A-1025).

    Returns
    -------
    dict[str, Any] | None
        The message; None for an unknown session or page name.
    """
    session = page_session(svc, session_id)
    if session is None:
        return None
    folder = session.folder
    try:
        document = comments.load(folder, page)
    except CommentError:
        return None
    return {
        "type": "comments",
        "session": session_id,
        "page": page,
        "next": document["next"],
        "comments": comments.with_status(document),
        "unsent": comments.unsent(folder, card_of(session, session_id)),
    }


def build_comments_view(svc: Services, initial: bool) -> dict[str, Any] | None:
    """Window view ``comments``: the page of the oldest change not yet pushed."""
    if initial or not svc.changed_pages:
        return None  # a window gets a page's comments when it asks for them
    return comments_message(svc, *svc.changed_pages.popleft())


def _refused(error: CommentError) -> Response:
    code = "usage" if error.usage else "invalid-comment"
    body = {"error": code, "message": str(error)}
    return JSONResponse(body, status_code=error.status)


def _is_owner(request: Request, svc: Services) -> bool:
    credentials = svc.state.credentials
    return credentials.cookie_ok(request.cookies.get(cookie_name(svc.state.port)))


def _owner_only(
    message: str = "Only the owner's window may change comments.",
) -> Response:
    return JSONResponse({"error": "invalid-comment", "message": message}, 403)


async def _body(request: Request) -> dict[str, Any]:
    raw = await _read_limited(request, MAX_BODY_BYTES)
    if raw is None:
        raise CommentError("The request is larger than 14 MB.")
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise CommentError("Body is not a JSON object.")
    return body


def _repeat(session_id: str, body: dict[str, Any]) -> tuple[Any, Any]:
    """Take ``request_id`` out of ``body``; give its key and the kept answer."""
    request_id = body.pop("request_id", None)
    key = (session_id, request_id) if isinstance(request_id, str) else None
    return key, _answered.get(key)


def _remember(key: Any, answer: Any) -> None:
    """Keep the answer to a request id; a repeat is answered, not applied (COM-16)."""
    if key is None:
        return
    _answered[key] = answer
    while len(_answered) > REMEMBERED_REQUESTS:
        _answered.popitem(last=False)


async def create_comment(request: Request, svc: Services, publish: Publish) -> Response:
    """Store a draft comment and answer its record (cookie only, COM-04)."""
    if not _is_owner(request, svc):
        return _owner_only()
    card = request.path_params["id"]
    session = page_session(svc, card)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        body = await _body(request)
        key, kept = _repeat(card, body)
        if kept is not None:
            return JSONResponse(kept)
        page = body.get("page")
        if not isinstance(page, str) or not (session.folder / page).is_file():
            raise CommentError("page must name a page of the session.")
        record = comments.create(session.folder, page, body, card_of(session, card))
    except CommentError as error:
        return _refused(error)
    _remember(key, record)
    changed(svc, publish, card, page)
    return JSONResponse(record)


async def edit_comment(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Change a comment as the owner (cookie only, COM-09, RPL-03).

    The body is ``{page, n}`` and exactly one of ``text`` (edit a draft),
    ``delete: true``, ``reply`` (text), ``done: true``, ``reopen: true`` or
    ``read: true``. Editing or deleting a sent comment answers 409 (A-49).
    """
    if not _is_owner(request, svc):
        return _owner_only()
    card = request.path_params["id"]
    session = page_session(svc, card)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        body = await _body(request)
        key, kept = _repeat(card, body)
        if kept is not None:
            return JSONResponse(kept)
        page, number = body.get("page"), body.get("n")
        if (
            not isinstance(page, str)
            or not isinstance(number, int)
            or isinstance(number, bool)
        ):
            raise CommentError("page and n are required.")
        actions = set(body) - {"page", "n"}
        if len(actions) != 1 or not actions <= set(EDIT_ACTIONS):
            raise CommentError(f"Send page, n and one of {', '.join(EDIT_ACTIONS)}.")
        [action] = actions
        value = body[action]
        if action in ("text", "reply"):
            if not isinstance(value, str) or not value.strip():
                raise CommentError(f"{action} must not be empty.")
        elif value is not True:
            raise CommentError(f"{action} must be true.")
        folder = session.folder
        if action == "text":
            result = comments.edit(folder, page, number, value)
        elif action == "reply":
            result = comments.reply(folder, page, number, value)
        elif action == "done":
            result = comments.set_done(folder, page, number, "owner")
        elif action == "reopen":
            result = comments.reopen(folder, page, number)
        elif action == "read":
            result = comments.mark_read(folder, page, number)
        else:
            comments.delete(folder, page, number)
            result = {"page": page, "n": number, "deleted": True}
    except CommentError as error:
        return _refused(error)
    _remember(key, result)
    changed(svc, publish, card, page)
    return JSONResponse(result)


def _author(body: dict[str, Any], default: str) -> str:
    """Return the name of a reply's author, or raise the usage error of RPL-02."""
    if body.get("from") is None:
        return default
    name = body["from"].strip() if isinstance(body["from"], str) else ""
    if not name or len(name) > MAX_AUTHOR or name.lower() in OWNER_LABELS:
        raise CommentError(
            f"from must be a name of 1 to {MAX_AUTHOR} characters, not an owner label.",
            usage=True,
        )
    return name


def _is_agent(request: Request, svc: Services) -> bool:
    return svc.state.credentials.key_ok(request.headers.get(KEY_HEADER))


async def reply_comment(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Add the agent's reply, and mark the comment done on request (key only, RPL-02).

    The body is ``{page, n, text, from?, done?}``; the answer is
    ``{page, n, replies, done}``. The window replies through ``edit``.
    """
    if not _is_agent(request, svc):
        return _owner_only("Only an agent replies here; the window replies by edit.")
    card = request.path_params["id"]
    session = page_session(svc, card)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        body = await _body(request)
        page, number, text = body.get("page"), body.get("n"), body.get("text")
        if (
            not isinstance(page, str)
            or type(number) is not int
            or not isinstance(text, str)
            or not text.strip()
            or type(body.get("done", False)) is not bool
        ):
            raise CommentError("Body must be {page, n, text, from?, done?}.")
        registered = svc.registry.get(card)
        author = _author(body, (registered.agent if registered else None) or "agent")
        record = comments.reply(
            session.folder,
            page,
            number,
            text,
            author,
            body.get("done", False),
            card_of(session, card),
        )
    except CommentError as error:
        return _refused(error)
    changed(svc, publish, card, page)
    answer = {
        "page": page,
        "n": number,
        "replies": len(comments.visible_replies(record)),
        "done": record["done"] is not None,
    }
    return JSONResponse(answer)


async def done_comments(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Mark sent comments done, by the agent (key) or the owner (cookie) (RPL-02).

    The body is ``{page, n: [..]}``; nothing changes unless every number names
    a sent comment, and a comment already done stays as it is.
    """
    by = "agent" if _is_agent(request, svc) else "owner"
    if by == "owner" and not _is_owner(request, svc):
        return _owner_only()
    card = request.path_params["id"]
    session = page_session(svc, card)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        body = await _body(request)
        page, numbers = body.get("page"), body.get("n")
        if (
            not isinstance(page, str)
            or not isinstance(numbers, list)
            or not numbers
            or not all(type(n) is int for n in numbers)
        ):
            raise CommentError("Body must be {page, n: [numbers]}.")
        stored = {c["n"]: c for c in comments.load(session.folder, page)["comments"]}
        if by == "agent":  # an agent closes only what it may answer (A-1021, A-1140)
            mine = card_of(session, card)
            stored = {n: c for n, c in stored.items() if comments.answerable(c, mine)}
        for number in numbers:
            if number not in stored:
                raise CommentError(f"No comment {number}.", 404)
            if stored[number]["sent"] is None:
                raise CommentError(f"Comment {number} is not sent yet.", 409)
        for number in numbers:
            comments.set_done(session.folder, page, number, by)
    except CommentError as error:
        return _refused(error)
    changed(svc, publish, card, page)
    return JSONResponse({"page": page, "done": numbers})


async def report_lost(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Store which anchors the window found again after a page change (ANC-06).

    The body is ``{page, reports: [{n, lost}]}``; the version stored is the
    page's newest. Nothing is published when no record changes.
    """
    if not _is_owner(request, svc):
        return _owner_only()
    card = request.path_params["id"]
    session = page_session(svc, card)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        body = await _body(request)
        page, reports = body.get("page"), body.get("reports")
        if (
            not isinstance(page, str)
            or not isinstance(reports, list)
            or len(reports) > comments.MAX_COMMENTS
            or not all(
                isinstance(r, dict)
                and type(r.get("n")) is int
                and type(r.get("lost")) is bool
                for r in reports
            )
        ):
            raise CommentError("Body must be {page, reports: [{n, lost}]}.")
        comments.load(session.folder, page)  # refuses a bad page name
        latest = PageHistory(session.folder).latest(page)
        stored = comments.set_lost_many(
            session.folder,
            page,
            [(r["n"], r["lost"]) for r in reports],
            latest[0] if latest else None,
        )
    except CommentError as error:
        return _refused(error)
    if stored:
        changed(svc, publish, card, page)
    return JSONResponse({"page": page, "stored": stored})


async def list_comments(request: Request, svc: Services) -> Response:
    """
    List comments: sent ones for the key (RPL-01), a page's all for the cookie.

    With the key the listed comments are marked seen. The window's cookie needs
    ``page`` and gets the page's drafts too, as they must survive a reload.
    """
    card = request.path_params["id"]
    session = page_session(svc, card)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    page = request.query_params.get("page")
    try:
        if svc.state.credentials.key_ok(request.headers.get(KEY_HEADER)):
            listed = comments.listing(
                session.folder,
                page,
                mark_seen=True,
                include_all=request.query_params.get("all") == "1",
                card=card_of(session, card),
            )
            return JSONResponse({"session": card, "comments": listed})
        if page is None:
            raise CommentError("page is required.")
        message = comments_message(svc, card, page)
        if message is None:
            raise CommentError("Invalid page name.")
    except CommentError as error:
        return _refused(error)
    return JSONResponse(message)
