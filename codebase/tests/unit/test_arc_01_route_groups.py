"""Route groups: handlers in ``hub/routes/``, ``create_app`` only wires (ARC-01)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from starlette.routing import Mount, Route, WebSocketRoute

import agent_canvas.hub as hub_package
from agent_canvas.config import Config
from agent_canvas.hub.app import create_app

pytestmark = pytest.mark.unit

HUB = Path(hub_package.__file__).parent
APP_FILE = HUB / "app.py"
ROUTES_DIR = HUB / "routes"
MAX_CREATE_APP_LINES = 200

REVISION_10_ROUTES = {
    ("/health", "GET"), ("/health", "HEAD"),
    ("/login", "GET"), ("/login", "HEAD"),
    ("/", "GET"), ("/", "HEAD"),
    ("/render", "GET"), ("/render", "HEAD"),
    ("/api/status", "GET"), ("/api/status", "HEAD"),
    ("/api/sessions", "GET"), ("/api/sessions", "HEAD"), ("/api/sessions", "POST"),
    ("/api/sessions/{id}", "GET"), ("/api/sessions/{id}", "HEAD"),
    ("/api/sessions/{id}/path", "POST"),
    ("/api/sessions/{id}/reserve", "POST"),
    ("/api/sessions/{id}/show", "POST"),
    ("/api/sessions/{id}/title", "POST"),
    ("/api/sessions/{id}/pages", "GET"), ("/api/sessions/{id}/pages", "HEAD"),
    ("/api/sessions/{id}/pages", "POST"),
    ("/api/sessions/{id}/end", "POST"),
    ("/api/sessions/{id}/rename", "POST"),
    ("/api/sessions/{id}/hide", "POST"),
    ("/api/sessions/{id}/unhide", "POST"),
    ("/api/sessions/{id}/versions", "GET"), ("/api/sessions/{id}/versions", "HEAD"),
    ("/api/sessions/{id}/look", "POST"),
    ("/api/sessions/{id}/send", "POST"),
    ("/api/sessions/{id}/sends", "GET"), ("/api/sessions/{id}/sends", "HEAD"),
    ("/api/sessions/{id}/sends/{name}", "GET"),
    ("/api/sessions/{id}/sends/{name}", "HEAD"),
    ("/api/shutdown", "POST"),
    ("/api/open", "POST"),
    ("/api/cleanup", "POST"),
    ("/api/sessions/{id}/pending", "POST"),
    ("/s/{token}/{path:path}", "GET"), ("/s/{token}/{path:path}", "HEAD"),
    ("/ws/shell", "WEBSOCKET"),
    ("/api/sessions/{id}/watch", "WEBSOCKET"),
    ("/api/sessions/{id}/ask", "WEBSOCKET"),
    ("/static", "MOUNT"),
}  # fmt: skip

REVISION_11_ROUTES = {
    ("/api/home/pages", "POST"),  # the owner's window sets kind, star, archive
}

KEYS_ROUTES = {  # KMAP-02
    ("/api/keys", "GET"),
    ("/api/keys", "HEAD"),
    ("/api/keys", "POST"),
}

HERDR_ROUTES = {
    ("/api/herdr", "GET"),
    ("/api/herdr", "HEAD"),
    ("/api/herdr/focus", "POST"),
}

POOL_ROUTES = {("/api/pages/migrate", "POST")}  # POOL-09, A-1123

REVISION_12_ROUTES = {  # P21.2: the comments route group
    ("/api/sessions/{id}/comments", "GET"),
    ("/api/sessions/{id}/comments", "HEAD"),
    ("/api/sessions/{id}/comments", "POST"),
    ("/api/sessions/{id}/comments/edit", "POST"),
    ("/api/sessions/{id}/comments/lost", "POST"),  # P22.3
    ("/api/sessions/{id}/comments/reply", "POST"),  # P23.1
    ("/api/sessions/{id}/comments/done", "POST"),  # P23.1
    ("/api/sessions/{id}/files", "POST"),  # P24.3: the files route group
    ("/api/sessions/{id}/open-file", "POST"),  # P31.1: Open in the files route group
    ("/api/sessions/{id}/answers", "GET"),  # P26.5: the answers route group
    ("/api/sessions/{id}/answers", "HEAD"),
    ("/api/sessions/{id}/answers/copy", "GET"),  # P26.7
    ("/api/sessions/{id}/answers/copy", "HEAD"),
    ("/api/sessions/{id}/answers/answer", "POST"),
    ("/api/sessions/{id}/answers/tick", "POST"),
    ("/api/sessions/{id}/answers/wait", "WEBSOCKET"),
    ("/api/sessions/{id}/result", "POST"),  # P30.1: the cards route group
    ("/api/sessions/{id}/result/answer", "POST"),
    ("/api/sessions/{id}/changes", "GET"),  # P31.6: what is new since the owner looked
    ("/api/sessions/{id}/changes", "HEAD"),
}


def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Build an app with temporary state."""
    monkeypatch.setenv("AGENT_CANVAS_STATE_DIR", str(tmp_path / "state"))
    config = Config(port=1, open_window=False, show_audit=False)
    return create_app(config, tmp_path / "state", build_id="test")


def route_pairs(app) -> set[tuple[str, str]]:  # noqa: ANN001
    """Return the (path, method) pairs of the app's routes."""
    pairs = set()
    for route in app.routes:
        if isinstance(route, Route):
            pairs |= {(route.path, method) for method in route.methods}
        elif isinstance(route, WebSocketRoute):
            pairs.add((route.path, "WEBSOCKET"))
        elif isinstance(route, Mount):
            pairs.add((route.path, "MOUNT"))
    return pairs


def create_app_node() -> ast.FunctionDef:
    """Return the syntax tree of ``create_app``."""
    tree = ast.parse(APP_FILE.read_text())
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )


def nested_functions(function: ast.FunctionDef) -> list[str]:
    """Return the names of functions defined inside ``function``."""
    return [
        node.name
        for node in ast.walk(function)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node is not function
    ]


def test_arc_01_create_app_defines_no_nested_function() -> None:
    """The handlers and helpers are not closures of ``create_app``."""
    assert nested_functions(create_app_node()) == []


def test_arc_01_create_app_is_at_most_200_lines() -> None:
    """``create_app`` only wires services, channel and route lists."""
    node = create_app_node()
    assert node.end_lineno - node.lineno + 1 <= MAX_CREATE_APP_LINES


def test_arc_01_every_handler_is_a_module_level_function_of_a_routes_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each route's handler is found at module level in ``hub/routes/``."""
    app = make_app(tmp_path, monkeypatch)
    found = 0
    for route in app.routes:
        if isinstance(route, Mount):
            continue
        handler = route.endpoint.handler
        module = Path(handler.__code__.co_filename)
        assert module.parent == ROUTES_DIR, route.path
        tree = ast.parse(module.read_text())
        top_level = {n.name for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
        assert handler.__name__ in top_level, route.path
        found += 1
    assert found == len(app.routes) - 1 > 20


def test_arc_01_the_urls_and_methods_of_revision_10_are_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No (path, method) pair is lost; later revisions add only their own."""
    app = make_app(tmp_path, monkeypatch)
    expected = REVISION_10_ROUTES | REVISION_11_ROUTES | REVISION_12_ROUTES
    expected |= KEYS_ROUTES | HERDR_ROUTES | POOL_ROUTES
    assert route_pairs(app) == expected
