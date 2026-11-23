"""State-changing routes declare the views they publish, and publish those (ARC-02)."""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

import agent_canvas.hub as hub_package
from agent_canvas.config import Config
from agent_canvas.hub.app import create_app
from agent_canvas.hub.auth import KEY_HEADER, cookie_name
from agent_canvas.hub.watcher import PageHistory

pytestmark = pytest.mark.integration

HUB = Path(hub_package.__file__).parent
PORT = 4321
SAFE_METHODS = {"GET", "HEAD"}
SEND_ALLOWED = {"channel.py", "routes/sockets.py"}


def state_changing(app):  # noqa: ANN001, ANN201
    """Return the routes that take a declaration: not GET/HEAD, and all sockets."""
    found = []
    for route in app.routes:
        if isinstance(route, Mount):
            continue
        methods = getattr(route, "methods", None)
        if methods is None or not set(methods) <= SAFE_METHODS:
            found.append(route)
    return found


@pytest.fixture
def hub_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """An app with a recording channel and a client that holds the access key."""
    monkeypatch.setenv("AGENT_CANVAS_STATE_DIR", str(tmp_path / "state"))
    config = Config(port=PORT, open_window=False, show_audit=False)
    app = create_app(config, tmp_path / "state", build_id="test")
    calls: list[str] = []
    # the Herdr poll publishes on its own clock, not for a route
    app.state.hub.channel.publish = lambda view: view != "herdr" and calls.append(view)
    key = (tmp_path / "state" / "key").read_text().strip()
    client = TestClient(
        app, base_url=f"http://127.0.0.1:{PORT}", headers={KEY_HEADER: key}
    )
    with client:
        yield app, client, calls, tmp_path


def test_arc_02_every_state_changing_route_carries_a_declaration(hub_app) -> None:  # noqa: ANN001
    """Each such route has views, or none with a reason string."""
    app = hub_app[0]
    routes = state_changing(app)
    assert len(routes) >= 18
    for route in routes:
        declaration = route.endpoint.declaration
        assert declaration.views or declaration.reason.strip(), route.path
        assert all(
            view in ("tabs", "comments", "answers")
            for view in declaration.views
        )


def test_arc_02_a_route_cannot_publish_a_view_it_did_not_declare(hub_app) -> None:  # noqa: ANN001
    """The helper's publish refuses an undeclared view and a route without views."""
    app, client, calls, tmp_path = hub_app
    reserve = next(r for r in app.routes if r.path.endswith("/reserve"))
    services = app.state.services
    from agent_canvas.hub.routes.helper import _publisher

    publish = _publisher(services, reserve.endpoint.declaration)
    with pytest.raises(ValueError):
        publish("tabs")
    assert calls == []


def step_plan(app, tmp_path: Path, client: TestClient, calls: list[str]):  # noqa: ANN001, ANN201
    """Yield (name, call) pairs in the order that gives each route valid input."""
    project = tmp_path / "project"
    project.mkdir()
    page = tmp_path / "page.html"
    page.write_text("<p>hi</p>")
    base = {"project": str(project), "agent": "t"}

    def post(path: str, body: dict | None = None):  # noqa: ANN202
        return lambda: client.post(path, json=base if body is None else body)

    yield "start_session", post("/api/sessions")
    yield "session_path", post("/api/sessions/a/path")
    yield "project_page", post("/api/sessions/a/project-page", {})
    yield "session_reserve", post("/api/sessions/r/reserve")
    yield (
        "session_show",
        post("/api/sessions/b/show", {**base, "copy": str(page), "audit": False}),
    )
    yield "session_title", post("/api/sessions/a/title", {"title": "T"})
    yield (
        "page_action",
        post(
            "/api/sessions/b/pages",
            {"action": "kind", "name": "page.html", "kind": "long-term"},
        ),
    )
    owner = {KEY_HEADER: "", "Origin": f"http://127.0.0.1:{PORT}"}  # cookie, no key
    comment = {"page": "page.html", "kind": "rect", "text": "q", "anchor": {}}

    def as_owner(path: str, body: dict):  # noqa: ANN202
        def call():  # noqa: ANN202
            token = app.state.hub.new_login_token()
            client.get(f"/login?t={token}", follow_redirects=False)
            return client.post(path, json=body, headers=owner)

        return call

    yield "create_comment", as_owner("/api/sessions/b/comments", comment)
    yield (
        "edit_comment",
        as_owner(
            "/api/sessions/b/comments/edit",
            {"page": "page.html", "n": 1, "delete": True},
        ),
    )
    yield "session_rename", post("/api/sessions/a/rename", {"title": "R"})
    yield "session_hide", post("/api/sessions/a/hide")
    yield "session_unhide", post("/api/sessions/a/unhide")
    yield "session_look", post("/api/sessions/a/look", {})
    yield "create_comment", as_owner("/api/sessions/b/comments", comment)
    cards = (
        '<canvas-ask data-canvas-id="q1"><script type="application/json">'
        '{"question": "Q?"}</script></canvas-ask>'
        '<canvas-do data-canvas-id="w1"><script type="application/json">'
        '{"title": "T", "steps": [{"text": "a"}]}</script></canvas-do>'
    )

    def with_cards(path: str, body: dict):  # noqa: ANN202
        owner_call = as_owner(path, body)

        def call():  # noqa: ANN202
            folder = app.state.hub.session_of("b").folder
            PageHistory(folder).save("cards.html", cards.encode())
            return owner_call()

        return call

    item = {"page": "cards.html", "id": "q1", "value": {"answer": "yes"}}
    yield "post_answer", with_cards("/api/sessions/b/answers/answer", item)
    tick = {"page": "cards.html", "id": "w1", "ticked": [1]}
    yield "post_tick", with_cards("/api/sessions/b/answers/tick", tick)
    lost = {"page": "page.html", "reports": [{"n": 2, "lost": True}]}
    yield "report_lost", as_owner("/api/sessions/b/comments/lost", lost)
    yield (
        "session_send",
        post(
            "/api/sessions/b/send",
            {
                "delivery": "now",
                "message": "m",
                "page": "page.html",
                "screenshot_error": "none",
                "viewport": {"width": 10, "height": 10, "scroll_x": 0, "scroll_y": 0},
            },
        ),
    )
    sent = {"page": "page.html", "n": 2}
    yield (
        "reply_comment",
        post("/api/sessions/b/comments/reply", {**sent, "text": "ok"}),
    )
    yield "done_comments", post("/api/sessions/b/comments/done", {**sent, "n": [2]})
    octet = {KEY_HEADER: "", "Origin": f"http://127.0.0.1:{PORT}"}

    def upload():  # noqa: ANN202
        token = app.state.hub.new_login_token()
        client.get(f"/login?t={token}", follow_redirects=False)
        return client.post(
            "/api/sessions/b/files?name=up.png",
            content=b"\x89PNG",
            headers={**octet, "Content-Type": "application/octet-stream"},
        )

    yield "upload_file", upload

    def open_file():  # noqa: ANN202
        (Path(app.state.hub.session_of("b").folder) / "o.md").write_text("# o")
        token = app.state.hub.new_login_token()
        client.get(f"/login?t={token}", follow_redirects=False)
        return client.post(
            "/api/sessions/b/open-file", json={"name": "o.md"}, headers=octet
        )

    yield "open_file", open_file
    yield "store_result", post("/api/sessions/b/result", {"summary": "s"})

    def answer_result():  # noqa: ANN202
        card = app.state.services.registry.get("b").result["id"]
        body = {"result": card, "dismiss": True}
        return as_owner("/api/sessions/b/result/answer", body)()

    yield "answer_result", answer_result
    page_body = {"session": "b", "page": "page.html", "kind": "long-term"}
    yield "set_page", as_owner("/api/home/pages", page_body)
    yield "session_pending", post("/api/sessions/a/pending", {"peek": True})
    yield "session_end", post("/api/sessions/b/end")
    yield "cleanup", post("/api/cleanup", {"session": "b", "yes": True, "force": True})
    yield "open_window", post("/api/open", {"print_url": True})
    herdr_app = app.state.services.herdr_app
    herdr_app.snapshot = lambda: {"available": True, "spaces": []}
    herdr_app.focus = lambda snapshot, key, value: True
    yield "focus", post("/api/herdr/focus", {"terminal": "t1"})
    yield "save_owner_keys", post("/api/keys", {"keys": {}})
    yield "shutdown", post("/api/shutdown")


def wait_for(calls: list[str], expected: list[str]) -> None:
    """Wait until the server thread has made the calls (sockets are asynchronous)."""
    deadline = time.monotonic() + 10
    while calls != expected and time.monotonic() < deadline:
        time.sleep(0.02)


def test_arc_02_each_declared_route_publishes_exactly_its_declaration(hub_app) -> None:  # noqa: ANN001
    """Call each state-changing route once; its publishes equal its declaration."""
    app, client, calls, tmp_path = hub_app
    app.state.hub.looks.headless = None
    app.state.hub.shutdown = lambda: None
    declared = {r.endpoint.handler.__name__: r.endpoint.declaration
                for r in state_changing(app)}  # fmt: skip
    called = set()

    for name, call in step_plan(app, tmp_path, client, calls):
        calls.clear()
        answer = call()
        assert answer.status_code < 500, (name, answer.text)
        assert answer.status_code == (204 if name == "agent_event" else 200) or (
            name == "session_look"
        ), (
            name,
            answer.text,
        )
        assert calls == list(declared[name].views), name
        called.add(name)

    origin = {"Origin": f"http://127.0.0.1:{PORT}", "Host": f"127.0.0.1:{PORT}"}
    calls.clear()
    with client.websocket_connect("/api/sessions/r/watch", headers=origin) as watch:
        watch.send_json({"type": "ack", "id": "x"})
        wait_for(calls, ["tabs"])
    assert calls == list(declared["watch_socket"].views)
    called.add("watch_socket")

    calls.clear()
    session = "a"
    with client.websocket_connect(
        f"/api/sessions/{session}/ask", headers=origin
    ) as ask:
        ask.send_json({"question": "Q?", "choices": ["x"]})
        assert ask.receive_json()["type"] == "registered"
    assert calls == list(declared["ask_socket"].views)
    called.add("ask_socket")

    calls.clear()
    with client.websocket_connect(
        "/api/sessions/a/answers/wait", headers=origin
    ) as waiting:
        waiting.send_json({"ids": [], "page": None, "timeout": 5})
        assert waiting.receive_json()["status"] == "answered"  # nothing waits
    assert calls == list(declared["answers_wait_socket"].views)
    called.add("answers_wait_socket")

    calls.clear()
    app_state = app.state.hub
    cookie = f"{cookie_name(PORT)}={app_state.credentials.cookie_value}"
    with client.websocket_connect(
        "/ws/shell",
        headers={"Cookie": cookie, **origin},
    ) as shell:
        assert shell.receive_json()["type"] == "hello"
        shell.send_json({"type": "ask-answer", "session": "a", "ask": "nope"})
        wait_for(calls, ["tabs"])
    assert calls == list(declared["shell_socket"].views)
    called.add("shell_socket")

    assert called == set(declared)


def send_calls(path: Path) -> list[str]:
    """Return ``file:line`` of every ``send_json``/``send_text`` call in a file."""
    tree = ast.parse(path.read_text())
    return [
        f"{path.relative_to(HUB)}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("send_json", "send_text")
    ]


def test_arc_02_send_json_appears_only_in_the_channel_and_the_socket_group() -> None:
    """Only ``channel.py`` and ``routes/sockets.py`` write to a socket."""
    found = [call for path in HUB.rglob("*.py") for call in send_calls(path)]
    assert found, "the search found no send at all"
    assert {call.split(":")[0] for call in found} <= SEND_ALLOWED
    assert any(call.startswith("routes/sockets.py") for call in found)
