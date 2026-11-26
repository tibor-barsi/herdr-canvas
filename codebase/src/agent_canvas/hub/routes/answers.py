"""Route group: answers to the cards of a page (ANS-01 to ANS-04, SEC-09).

Who may do what: the owner's cookie answers and ticks; the key lists. The page
and item named by a request must exist in the page's current version, so a
forged answer reaches only an item of the page the shell names. The wait is a
WebSocket and lives with the other sockets (``routes/sockets.py``).
"""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from agent_canvas.hub.answers import AnswerError, Item
from agent_canvas.hub.events import ticks_not_from_owner
from agent_canvas.hub.registry import RegistryError
from agent_canvas.hub.routes.comments import (
    _is_agent,
    _is_owner,
    _remember,
    _repeat,
)
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    change_route,
    failure,
    read_route,
)
from agent_canvas.hub.routes.sessions import _read_limited, known_session, page_session
from agent_canvas.hub.watcher import PageHistory

BASE = "/api/sessions/{id}/answers"
MAX_VALUE_BYTES = 100_000
MAX_BODY_BYTES = 256 * 1024
MAX_NOTE = 4000
MAX_REASON = 300
STATUSES = ("done", "problem", "later")
EVENT_KINDS = {"ask": "answer", "do": "todo", "decision": "change"}


def routes(services: Services) -> list[BaseRoute]:
    """Return the answer routes."""
    declared = Declaration(views=("answers",))
    return [
        read_route(services, BASE, list_answers, ["GET"]),
        read_route(services, BASE + "/copy", copy_text, ["GET"]),
        change_route(services, BASE + "/answer", post_answer, ["POST"], declared),
        change_route(services, BASE + "/tick", post_tick, ["POST"], declared),
    ]


def answers_message(svc: Services, session_id: str, page: str) -> dict[str, Any] | None:
    """
    Build the ``answers`` message of one page (5.16).

    Returns
    -------
    dict[str, Any] | None
        The message; None for an unknown session or a name that is not a page.
    """
    holder = page_session(svc, session_id)
    if holder is None:
        return None
    try:
        items = svc.answers.public(session_id, page)
    except (KeyError, ValueError):
        return None
    folder = str(holder.folder)
    return {
        "type": "answers",
        "session": session_id,
        "page": page,
        "items": items,
        "folder": folder,
    }


def build_answers_view(svc: Services, initial: bool) -> dict[str, Any] | None:
    """Window view ``answers``: the page of the oldest change not yet pushed."""
    if initial or not svc.changed_answers:
        return None  # a window gets a page's items when it asks for them
    return answers_message(svc, *svc.changed_answers.popleft())


def _refused(error: AnswerError) -> Response:
    body = {"error": "invalid-answer", "message": str(error)}
    return JSONResponse(body, status_code=error.status)


def _owner_only() -> Response:
    message = "Only the owner's window answers the cards."
    return JSONResponse({"error": "invalid-answer", "message": message}, 403)


async def _body(request: Request) -> dict[str, Any]:
    raw = await _read_limited(request, MAX_BODY_BYTES)
    if raw is None:
        raise AnswerError("The request is larger than 256 kB.", 413)
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise AnswerError("Body is not a JSON object.")
    return body


def _text(value: Any, name: str, limit: int, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise AnswerError(
            f"{name} must be {'a non-empty ' if required else 'a '}string."
        )
    if len(value) > limit:
        raise AnswerError(f"{name} is longer than {limit} characters.")
    return value


def _steps(value: Any, item: Item) -> list[int]:
    if not isinstance(value, list) or not all(
        type(n) is int and 1 <= n <= item.steps for n in value
    ):
        raise AnswerError(f"ticked must list step numbers from 1 to {item.steps}.")
    return sorted(set(value))


def _event_value(
    item: Item, given: Any, replaces: str | None, ticked: list[int]
) -> tuple[Any, str]:
    """Return the event's value (5.3) and the item's new state."""
    if not isinstance(given, dict) or len(json.dumps(given)) > MAX_VALUE_BYTES:
        raise AnswerError("value must be a JSON object under 100 kB.")
    if item.kind == "ask":
        if given.get("answer") is None:
            raise AnswerError("value needs an answer.")
        value = {
            "question": item.text, "form": item.form, "answer": given["answer"],
            "other": _text(given.get("other"), "other", MAX_NOTE),
            "note": _text(given.get("note"), "note", MAX_NOTE),
            "replaces": replaces,
        }  # fmt: skip
        return value, "answered"
    if item.kind == "do":
        status = given.get("status")
        if status not in STATUSES:
            raise AnswerError(f"status must be one of {', '.join(STATUSES)}.")
        note = _text(given.get("note"), "note", MAX_NOTE, required=status == "problem")
        value = {
            "title": item.text, "status": status, "ticked": ticked,
            "note": note, "replaces": replaces,
        }  # fmt: skip
        return value, status
    reason = _text(given.get("reason"), "reason", MAX_REASON, required=True)
    return {"decision": item.text, "reason": reason, "replaces": replaces}, "changed"


async def post_answer(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Answer an item as the owner (cookie only, ANS-02, ASK-02, DO-03, KIND-07).

    The body is ``{page, id, value}``; the hub completes ``value`` from the
    page's own source (question, title, text) and from the store (``replaces``),
    refuses with 409 when ``seen``, the config the card showed, no longer gives
    the item's key (the question changed since), creates the ``answer``, ``todo``
    or ``change`` event and stores the answer. ``no_gesture: true`` (the window
    saw no action of the owner) marks both as not from the owner (SEC-09); a Do's
    answer names in ``ticks_not_from_owner`` the steps the page's script ticked.
    """
    if not _is_owner(request, svc):
        return _owner_only()
    session = known_session(svc, request)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    sid, store = session.session_id, svc.answers
    try:
        body = await _body(request)
        key, kept = _repeat(session.session_id, body)
        if kept is not None:
            return JSONResponse(kept)
        page, item_id = body.get("page"), body.get("id")
        if not isinstance(page, str) or not isinstance(item_id, str):
            raise AnswerError("Body must be {page, id, value}.")
        item = store.item_of(sid, page, item_id)
        if item.kind not in EVENT_KINDS:
            raise AnswerError("An Options box answers with its choice event.")
        seen = body.get("seen")
        if seen is not None and store.key_of(item.kind, seen) != item.key:
            raise AnswerError("The question changed since you saw it; look again.", 409)
        entry = store.entries(sid, page).get(item_id) or {"ticked": []}
        value, state = _event_value(
            item,
            body.get("value"),
            store.latest_event(sid, page, item_id),
            entry["ticked"],
        )
        if item.kind == "do" and isinstance(body["value"].get("ticked"), list):
            value["ticked"] = _steps(body["value"]["ticked"], item)
        if item.kind == "do" and (
            by_page := store.page_ticks(sid, page, item_id, value["ticked"])
        ):
            value["ticks_not_from_owner"] = ticks_not_from_owner(by_page)
    except AnswerError as error:
        return _refused(error)
    event_kind = EVENT_KINDS[item.kind]
    target = {
        "canvas_id": item_id,
        "selector": f"[data-canvas-id={json.dumps(item_id)}]",
        "text": item.text[:80],
    }
    awaited = svc.asks.intercept(sid, event_kind, item_id)
    latest = PageHistory(page_session(svc, sid).folder).latest(page)
    event = svc.events.create_for(
        sid, event_kind, delivery="ask" if awaited else "now", page=page,
        page_version=latest[0] if latest else None, target=target, value=value,
        not_from_owner=body.get("no_gesture") is True,
    )  # fmt: skip
    store.record(
        sid, page, item, state=state, value=value, event=event["id"],
        time=event["time"], ticked=value.get("ticked"),
        not_from_owner=event.get("not_from_owner"),
    )  # fmt: skip
    if awaited:
        svc.asks.complete_block(sid, awaited, event["id"])
    result = {"page": page, "id": item_id, "event": event["id"], "state": state}
    _remember(key, result)
    return JSONResponse(result)


async def post_tick(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Store the ticked steps of a Do as the owner (cookie only, DO-01); no event.

    ``no_gesture: true`` keeps the newly ticked steps as the page's (SEC-09).
    """
    if not _is_owner(request, svc):
        return _owner_only()
    session = known_session(svc, request)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        body = await _body(request)
        key, kept = _repeat(session.session_id, body)
        if kept is not None:
            return JSONResponse(kept)
        page, item_id = body.get("page"), body.get("id")
        if not isinstance(page, str) or not isinstance(item_id, str):
            raise AnswerError("Body must be {page, id, ticked}.")
        item = svc.answers.item_of(session.session_id, page, item_id)
        if item.kind != "do":
            raise AnswerError("Only a Do has steps to tick.")
        ticked = _steps(body.get("ticked"), item)
    except AnswerError as error:
        return _refused(error)
    svc.answers.tick(
        session.session_id, page, item, ticked, body.get("no_gesture") is True
    )
    result = {"page": page, "id": item_id, "ticked": ticked}
    _remember(key, result)
    return JSONResponse(result)


async def copy_text(request: Request, svc: Services) -> Response:
    """
    Give the owner's window the ``run`` text of one Do step (cookie only, DO-02).

    Query: ``page``, ``id`` (the Do) and ``step`` (1 to 20); or ``page``, ``kind``
    (``path`` or ``source``) and ``text``, which is given back only when a file
    card or source card of the page's current version has it (CNT-03, CNT-04).
    The text is read from the page's current version, never from what the frame sends.
    """
    if not _is_owner(request, svc):
        return _owner_only()
    session = known_session(svc, request)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    params = request.query_params
    if params.get("kind") is not None:
        return _copy_written(svc, session.session_id, params)
    try:
        item = svc.answers.item_of(
            session.session_id, params.get("page", ""), params.get("id", "")
        )
        step = int(params.get("step", ""))
        run = item.step_runs[step - 1] if item.kind == "do" and step >= 1 else None
    except AnswerError as error:
        return _refused(error)
    except (ValueError, IndexError):
        run = None
    if run is None:
        return _refused(AnswerError("That step has no command to copy.", 404))
    return JSONResponse({"text": run})


def _copy_written(svc: Services, session_id: str, params: Any) -> Response:
    found = svc.answers.scan_of(session_id, params.get("page", ""))
    written = {"path": found.paths, "source": found.sources} if found else {}
    text = params.get("text", "")
    if not text or text not in written.get(params["kind"], ()):
        return _refused(AnswerError("The page does not hold that text.", 404))
    return JSONResponse({"text": text})


async def list_answers(request: Request, svc: Services) -> Response:
    """
    List the items of the shown pages (key only, ANS-04); consumes nothing.

    Query: ``page`` limits the list to one page, ``open=1`` keeps open Ask and
    Do items. The answers listed count as read (ANS-03).
    """
    if not _is_agent(request, svc):
        return JSONResponse(
            {"error": "invalid-answer", "message": "Only an agent lists answers."}, 403
        )
    session = known_session(svc, request)
    if session is None:
        return failure(RegistryError("no-session", "Unknown session."))
    params = request.query_params
    items = svc.answers.listing(
        session.session_id, params.get("page"), params.get("open") == "1"
    )
    return JSONResponse({"session": session.session_id, "items": items})
