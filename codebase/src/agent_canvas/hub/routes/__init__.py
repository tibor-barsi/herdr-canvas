"""Route groups of the hub: one module per area (ARC-01)."""

from __future__ import annotations

from starlette.routing import BaseRoute

from agent_canvas.hub.routes import (
    answers,
    cards,
    comments,
    core,
    files,
    herdr,
    pages,
    sessions,
    sockets,
)
from agent_canvas.hub.routes.helper import Services


def all_routes(services: Services) -> list[BaseRoute]:
    """Return the routes of every group, in matching order."""
    groups = (core, sessions, comments, answers, cards, files, pages, herdr, sockets)
    return [route for group in groups for route in group.routes(services)]
