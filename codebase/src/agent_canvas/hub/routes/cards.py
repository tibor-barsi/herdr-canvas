"""Route group: the result card (RES-01, RES-02).

The agent's key stores the card; only the owner's cookie answers it. No CLI
waits for a result, so its answer does not use the ask socket.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from agent_canvas.hub.registry import RegistryError
from agent_canvas.hub.results import ResultError
from agent_canvas.hub.routes.comments import _is_agent, _is_owner
from agent_canvas.hub.routes.helper import (
    Declaration,
    Publish,
    Services,
    body_of,
    change_route,
    failure,
)
from agent_canvas.hub.routes.sessions import known_session

BASE = "/api/sessions/{id}/result"


def routes(services: Services) -> list[BaseRoute]:
    """Return the result card routes."""
    declared = Declaration(views=("tabs",))  # published by the result service
    return [
        change_route(services, BASE, store_result, ["POST"], declared),
        change_route(services, BASE + "/answer", answer_result, ["POST"], declared),
    ]


def _refused(message: str, status: int, error: str) -> Response:
    return JSONResponse({"error": error, "message": message}, status_code=status)


async def store_result(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Store the session's result card (key only, RES-01).

    The body is ``{summary, files?, decision?, choices?}``; the answer is
    ``{result, window}``.
    """
    if not _is_agent(request, svc):
        return _refused("Only an agent stores a result.", 403, "unauthorised")
    if known_session(svc, request) is None:
        return failure(RegistryError("no-session", "Unknown session."))
    try:
        card = svc.results.store(request.path_params["id"], await body_of(request))
    except ResultError as error:
        return _refused(str(error), 422, "usage")
    return JSONResponse({"result": card["id"], "window": await svc.launcher.ensure()})


async def answer_result(request: Request, svc: Services, publish: Publish) -> Response:
    """
    Take the owner's choice or Dismiss (cookie only, RES-02).

    The body is ``{result, choice}`` or ``{result, dismiss: true}``.
    """
    if not _is_owner(request, svc):
        return _refused("Only the owner's window answers the cards.", 403, "forbidden")
    if known_session(svc, request) is None:
        return failure(RegistryError("no-session", "Unknown session."))
    session_id, body = request.path_params["id"], await body_of(request)
    result_id, choice = body.get("result"), body.get("choice")
    try:
        if body.get("dismiss") is True and choice is None:
            svc.results.dismiss(session_id, str(result_id))
            return JSONResponse(
                {"result": result_id, "state": "dismissed", "event": None}
            )
        event = svc.results.choose(session_id, str(result_id), str(choice))
    except ResultError as error:
        return _refused(str(error), 409, "invalid-result")
    return JSONResponse({"result": result_id, "state": "decided", "event": event["id"]})
