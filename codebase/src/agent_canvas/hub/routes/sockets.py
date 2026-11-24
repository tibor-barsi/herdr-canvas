"""Route group: WebSocket endpoints of the shell and the CLI (ARC-01, ARC-02)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.routing import BaseRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from agent_canvas.hub.answers import AnswerError, AnswerStore
from agent_canvas.hub.events import EventService
from agent_canvas.hub.messages import note_unknown
from agent_canvas.hub.registry import (
    RegistryError,
    SessionRegistry,
    is_project_id,
    validate_or_raise,
)
from agent_canvas.hub.routes.answers import answers_message
from agent_canvas.hub.routes.comments import comments_message
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    change_socket,
    resumed,
)
from agent_canvas.hub.state import HubState
from agent_canvas.hub.viewers import viewer_type
from agent_canvas.hub.watcher import PageHistory, is_page_name

WS_NO_SESSION = 4404
WS_BAD_ASK = 4400
SHELL_EVENT_KINDS = ("button", "choice", "text", "custom")
SHELL_EVENT_DELIVERIES = ("now", "next-message")
MAX_SHELL_EVENT_BYTES = 100_000
MAX_WAIT_SECONDS = 86_400
TARGET_LIMITS = {"canvas_id": 200, "selector": 500, "text": 80}


def routes(services: Services) -> list[BaseRoute]:
    """Return the WebSocket routes."""
    return [
        change_socket(
            services,
            "/ws/shell",
            shell_socket,
            Declaration(("tabs",)),
        ),
        change_socket(
            services,
            "/api/sessions/{id}/watch",
            watch_socket,
            Declaration(("tabs",)),
        ),
        change_socket(
            services,
            "/api/sessions/{id}/answers/wait",
            answers_wait_socket,
            # reading answers publishes through the store, not through this route
            Declaration(reason="a wait only reads; the store tells the windows"),
        ),
        change_socket(
            services,
            "/api/sessions/{id}/ask",
            ask_socket,
            # published by the ask service
            Declaration(("tabs",)),
        ),
    ]


async def watch_socket(websocket: WebSocket, svc: Services, publish: Publish) -> None:
    """Stream a session's events to a ``watch`` command."""
    state, registry, events = svc.state, svc.registry, svc.events
    session_id = websocket.path_params["id"]
    await websocket.accept()
    if is_project_id(session_id):  # a pool's events go to its sessions (POOL-05)
        await websocket.close(WS_NO_SESSION)
        return
    if registry.promote(session_id):
        publish("tabs")  # a watch is the first use of the canvas
    if state.loop is None or not _known_session(registry, session_id):
        await websocket.close(WS_NO_SESSION)
        return
    listener = events.add_listener(session_id, "watch")
    sender = asyncio.create_task(_send_events(websocket, listener))
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "ack":
                via = "mcp" if message.get("via") == "mcp" else "watch"
                events.ack(session_id, str(message.get("id")), via)
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        sender.cancel()
        events.remove_listener(listener)


async def ask_socket(websocket: WebSocket, svc: Services, publish: Publish) -> None:
    """Carry one question card from an ``ask`` command to its answer."""
    state, registry, events, asks = svc.state, svc.registry, svc.events, svc.asks
    session_id = websocket.path_params["id"]
    await websocket.accept()
    if state.loop is None or not _known_session(registry, session_id):
        await websocket.close(WS_NO_SESSION)
        return
    resumed(svc, publish, session_id)
    try:
        request = await websocket.receive_json()
        entry, waiter = asks.register(
            session_id, request if isinstance(request, dict) else {}
        )
    except (WebSocketDisconnect, RuntimeError):
        return
    except ValueError as error:  # AskError, or a body that is not JSON
        await websocket.close(WS_BAD_ASK, reason=str(error)[:120])
        return
    listener = events.add_listener(session_id, "ask")
    try:
        await svc.launcher.ensure()
        await websocket.send_json({"type": "registered", "ask": entry["ask"]})
        result = await _wait_for_result(websocket, waiter.future)
        if result is not None:
            await websocket.send_json({"type": "result", **result})
            await websocket.close()
    except (WebSocketDisconnect, RuntimeError):
        pass  # the CLI went away; a card stays for a late answer (CLI-05)
    finally:
        asks.detach(waiter)
        events.remove_listener(listener)


async def answers_wait_socket(
    websocket: WebSocket, svc: Services, publish: Publish
) -> None:
    """
    Wait until the named items are answered, as a listener (ANS-05, FB-06).

    The CLI sends ``{ids, page, timeout}`` once; the hub answers
    ``{"type": "result", "status": "answered"|"timeout", "items": [...]}``.
    A finished wait marks the answer events delivered via ``answers``.
    """
    state, registry, events = svc.state, svc.registry, svc.events
    session_id = websocket.path_params["id"]
    await websocket.accept()
    if state.loop is None or not _known_session(registry, session_id):
        await websocket.close(WS_NO_SESSION)
        return
    try:
        request = await websocket.receive_json()
        ids, page, timeout = request["ids"], request["page"], float(request["timeout"])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise AnswerError("ids must be a list of strings.")
        if not 0 < timeout <= MAX_WAIT_SECONDS:
            raise AnswerError(
                f"timeout must be above 0 and at most {MAX_WAIT_SECONDS}."
            )
        targets = svc.answers.targets(session_id, ids, page)
    except (WebSocketDisconnect, RuntimeError):
        return
    except (AnswerError, KeyError, TypeError, ValueError) as error:
        await websocket.close(WS_BAD_ASK, reason=str(error)[:120])
        return
    listener = events.add_listener(session_id, "answers")
    future = asyncio.ensure_future(svc.answers.wait(session_id, targets, timeout))
    try:
        answered = await _wait_for_result(websocket, future)
        if answered is None:
            return  # the CLI went away
        rows = svc.answers.rows_of(session_id, targets)
        if answered:
            for row in rows:
                events.ack(session_id, row["event"], "answers")
        status = "answered" if answered else "timeout"
        await websocket.send_json({"type": "result", "status": status, "items": rows})
        await websocket.close()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        future.cancel()
        events.remove_listener(listener)


Message = dict[str, Any]
Handler = Callable[[WebSocket, Message, Services, Publish], Awaitable[None]]


async def _page_report(ws: WebSocket, m: Message, svc: Services, _: Publish) -> None:
    svc.state.record_page_report(
        str(m.get("url", "")), str(m.get("name", "")), m.get("data")
    )


async def _window_info(ws: WebSocket, m: Message, svc: Services, _: Publish) -> None:
    svc.looks.on_window_info(ws, m)


async def _render_result(ws: WebSocket, m: Message, svc: Services, _: Publish) -> None:
    svc.looks.on_render_result(ws, m)


async def _ask_answer(
    ws: WebSocket, m: Message, svc: Services, publish: Publish
) -> None:
    session_id, ask_id = str(m.get("session")), str(m.get("ask"))
    if svc.asks.answer(session_id, ask_id, m.get("value")) is None:
        publish("tabs")  # re-enables the card that was refused


async def _ask_dismiss(
    ws: WebSocket, m: Message, svc: Services, publish: Publish
) -> None:
    if not svc.asks.dismiss(str(m.get("session")), str(m.get("ask"))):
        publish("tabs")  # re-enables the card that was refused


async def _seen(ws: WebSocket, m: Message, svc: Services, _: Publish) -> None:
    seen_from_shell(svc, m)


async def _comments_get(ws: WebSocket, m: Message, svc: Services, _: Publish) -> None:
    answer = comments_message(svc, str(m.get("session")), str(m.get("page")))
    if answer is not None:
        await svc.channel.send_to(ws, answer)


async def _answers_get(ws: WebSocket, m: Message, svc: Services, _: Publish) -> None:
    answer = answers_message(svc, str(m.get("session")), str(m.get("page")))
    if answer is not None:
        await svc.channel.send_to(ws, answer)


async def _event(ws: WebSocket, m: Message, svc: Services, _: Publish) -> None:
    created = event_from_shell(svc.state, svc.events, m, svc.answers)
    if created is not None:
        await ws.send_json(
            {"type": "event-created", "ref": m.get("ref"), "event": created["id"]}
        )


# The messages a window sends the hub (P33.2): type -> field names and handler. A test
# checks that the window sends no type without a row here.
SHELL_MESSAGES: dict[str, tuple[tuple[str, ...], Handler]] = {
    "page-report": (("url", "name", "data"), _page_report),
    "window-info": (("width", "height", "scheme", "build"), _window_info),
    "render-result": (
        (
            "id",
            "ok",
            "png",
            "scheme",
            "errors",
            "audit",
            "notes",
            "viewer_error",
            "error",
            "code",
        ),
        _render_result,
    ),
    "ask-answer": (("session", "ask", "value"), _ask_answer),
    "ask-dismiss": (("session", "ask"), _ask_dismiss),
    "seen": (("session", "page", "version"), _seen),
    "comments-get": (("session", "page"), _comments_get),
    "answers-get": (("session", "page"), _answers_get),
    "event": (
        ("ref", "session", "kind", "page", "value", "target", "delivery", "no_gesture"),
        _event,
    ),
}


async def handle_shell_message(
    websocket: WebSocket, text: str, svc: Services, publish: Publish
) -> None:
    """Store page reports (PAGE-08) and create events the shell relays."""
    try:
        message = json.loads(text)
    except ValueError:
        return
    if not isinstance(message, dict):
        return
    kind = message.get("type")
    row = SHELL_MESSAGES.get(kind) if isinstance(kind, str) else None
    note_unknown("from a window", message, None if row is None else row[0])
    if svc.machines is not None and svc.machines.route(message):
        return  # it names a session or page of another machine
    if row is not None:
        await row[1](websocket, message, svc, publish)


async def shell_socket(websocket: WebSocket, svc: Services, publish: Publish) -> None:
    """Connect the owner's window: greeting, then its messages."""
    await websocket.accept()
    try:
        await svc.channel.add(websocket)
        while True:
            await handle_shell_message(
                websocket, await websocket.receive_text(), svc, publish
            )
    except WebSocketDisconnect:
        pass
    finally:
        svc.channel.discard(websocket)
        svc.looks.drop_shell(websocket)


def _known_session(registry: SessionRegistry, session_id: str) -> bool:
    """Return True for a well-formed id of an existing session (no creation)."""
    try:
        return registry.get(validate_or_raise(session_id)) is not None
    except RegistryError:
        return False


async def _send_events(websocket: WebSocket, listener: Any) -> None:
    """Send each event offered to a watch's listener as one JSON message."""
    try:
        while True:
            await websocket.send_json(await listener.next_event())
    except (WebSocketDisconnect, RuntimeError):
        return  # unacknowledged events stay queued (CLI-08)


async def _wait_for_result(
    websocket: WebSocket, future: asyncio.Future[dict[str, Any]]
) -> dict[str, Any] | None:
    """
    Wait for an ask's result or for its CLI to disconnect.

    Returns
    -------
    dict[str, Any] | None
        The result, or None when the CLI went away first.
    """

    async def until_disconnect() -> None:
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            return

    watcher = asyncio.ensure_future(until_disconnect())
    try:
        await asyncio.wait({future, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        watcher.cancel()
    return future.result() if future.done() else None


def seen_from_shell(svc: Services, message: dict[str, Any]) -> None:
    """Record a version shown for 2 s as seen (NEW-01); bad reports are ignored."""
    session_id, page, version = (message.get(k) for k in ("session", "page", "version"))
    if not (isinstance(session_id, str) and isinstance(page, str)):
        return
    if type(version) is not int or not (is_page_name(page) or viewer_type(page)):
        return
    holder = svc.registry.pool_of(session_id) or session_id  # POOL-01
    try:
        session = svc.state.session_of(holder)
    except KeyError:
        return
    latest = PageHistory(session.folder).latest(page)
    if latest is not None and 0 < version <= latest[0]:
        svc.registry.note_seen(holder, page, version)


def event_from_shell(
    state: HubState,
    events: EventService,
    message: dict[str, Any],
    answers: AnswerStore | None = None,
) -> dict[str, Any] | None:
    """
    Create the event a shell relays from a page (PAGE-07), or return None.

    The shell is trusted but the content comes from an untrusted page, so the
    kind, delivery, size and target are checked here. An event from the element
    an ``ask --block`` waits on becomes delivery ``ask`` and goes to that ask
    only (FB-08); any other one about a pool page goes to the pool's log for
    the card (POOL-05). A ``choice`` from an Options box with a submit button is also
    stored as its answer (ANS-01, #19). One the shell relayed with no action of
    the owner (``no_gesture``) is marked as not from the owner (SEC-09).
    """
    session_id = message.get("session")
    kind = message.get("kind")
    delivery = message.get("delivery", "now")
    too_big = len(json.dumps(message.get("value"))) > MAX_SHELL_EVENT_BYTES
    if kind not in SHELL_EVENT_KINDS or delivery not in SHELL_EVENT_DELIVERIES:
        return None
    if too_big or not isinstance(session_id, str):
        return None
    try:
        session = state.session_of(events.pool_of(session_id) or session_id)
    except KeyError:
        return None
    page = message.get("page")
    is_page = isinstance(page, str) and (is_page_name(page) or viewer_type(page))
    page = page if is_page else None
    version = None
    if page is not None and (latest := PageHistory(session.folder).latest(page)):
        version = latest[0]
    target = _clean_target(message.get("target"))
    awaited = state.asks.intercept(
        session_id, kind, target["canvas_id"] if target else None
    )
    event = events.create_for(
        session_id,
        kind,
        delivery="ask" if awaited else delivery,
        page=page,
        page_version=version,
        target=target,
        value=message.get("value"),
        not_from_owner=message.get("no_gesture") is True,
    )
    if answers is not None and kind == "choice" and page and target:
        _store_choice(answers, session_id, page, target["canvas_id"], event)
    if awaited:
        state.asks.complete_block(session_id, awaited, event["id"])
        event = events.get(session_id, event["id"]) or event
    return event


def _store_choice(
    answers: AnswerStore, session_id: str, page: str, item_id: str | None, event: dict
) -> None:
    """Store a ``choice`` event as the answer of its Options box, if it has one."""
    try:
        item = answers.item_of(session_id, page, item_id or "")
    except AnswerError:
        return
    if item.kind == "choices":
        answers.record(
            session_id, page, item, state="answered", value=event["value"],
            event=event["id"], time=event["time"],
            not_from_owner=event.get("not_from_owner"),
        )  # fmt: skip


def _clean_target(value: Any) -> dict[str, Any] | None:
    """Keep ``canvas_id``, ``selector`` and ``text`` of an event target (5.3)."""
    if not isinstance(value, dict):
        return None
    return {
        key: value[key][:limit] if isinstance(value.get(key), str) else None
        for key, limit in TARGET_LIMITS.items()
    }
