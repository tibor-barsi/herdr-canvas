"""A remote machine in the window: its cards load from the remote hub's own origin (herdr-canvas T)."""

# ruff: noqa: E501
from __future__ import annotations

import copy
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_canvas.hub.machines import Machine
from agent_canvas.hub.serve import inject_helper

from .test_hcw_01_herdr_window import pane, session

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src/agent_canvas/static"
SHOT = "/tmp/claude-scratch/t"
PAGE = b"<!doctype html><html><head><title>remote</title></head><body><p>remote page</p></body></html>"
OFFLINE_DETAIL = "devbox is not reachable right now."


class Remote:
    """A small stand-in for another machine's hub: its pages and the window's static files."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages, self.hits = pages, []
        remote = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?")[0]
                if path.startswith("/static/"):
                    file = STATIC / path[len("/static/") :]
                    body = file.read_bytes() if file.is_file() else None
                    kind = "text/javascript" if path.endswith(".js") else "text/css"
                else:
                    remote.hits.append(path)
                    body, kind = remote.pages.get(path.rsplit("/", 1)[-1]), "text/html"
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:  # noqa: ANN002
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://localhost:{self.port}/s/tok/"


@pytest.fixture
def remotes():  # noqa: ANN201
    """The remote hub's origin and an unrelated origin the remote's page jumps to."""
    other = Remote(
        {"alpha.html": inject_helper(PAGE), "jump.html": inject_helper(PAGE)}
    )
    remote = Remote({"alpha.html": inject_helper(PAGE)})
    remote.pages["jump.html"] = (
        f'<script>location.href="{other.base}jump.html"</script>'.encode()
    )
    yield remote, other
    remote.server.shutdown()
    other.server.shutdown()


def test_hcw_02_remote_card_from_a_second_origin_and_machine_states(
    owner, tmp_path, remotes
) -> None:  # noqa: ANN001
    remote, other = remotes
    for origin in (remote, other):
        owner.context.route(
            f"http://localhost:{origin.port}/**", lambda route: route.continue_()
        )
    while not owner.hub.state.shells:
        owner.page.wait_for_timeout(25)
    page = owner.page
    a, b = session(owner, tmp_path, "alpha"), session(owner, tmp_path, "jump")
    c = session(owner, tmp_path, "local")
    bases = {a: remote.base, b: remote.base}
    state = owner.hub.state
    original = state.tabs_provider
    state.tabs_provider = lambda: [
        {**t, "machine": "devbox", "base": bases[t["id"]]} if t["id"] in bases else t
        for t in original()
    ]
    # The hub's link service owns each machine's state; a link object stands in for the real one.
    machine = Machine("devbox", "devbox", True, state="online")
    links = owner.hub.app.state.services.machines
    links.machines["devbox"] = machine
    herdr = {
        "available": True,
        "focus": {"space": "devbox/sp1", "tab": "devbox/tb1", "pane": "pt1"},
        "spaces": [
            {
                "id": "sp1",
                "machine": None,
                "name": "lab",
                "color": "#22a99a",
                "active": True,
                "tabs": [
                    {
                        "id": "tb1",
                        "name": "rig",
                        "active": True,
                        "panes": [pane("t3", c, True)],
                    }
                ],
            },
            {
                "id": "devbox/sp1",
                "machine": "devbox",
                "name": "sim",
                "color": "#5b8def",
                "active": False,
                "tabs": [
                    {
                        "id": "devbox/tb1",
                        "name": "run",
                        "active": True,
                        "panes": [pane("t1", a, True), pane("t2", b, False)],
                    }
                ],
            },
        ],
        "machines": [{"name": "devbox"}],
        "other": [],
    }
    app = owner.hub.app.state.services.herdr_app
    app.snapshot = lambda: copy.deepcopy(herdr)
    app.focus = lambda *_: True
    state.channel.broadcast(state.tabs_message())

    # The remote session sits under its machine, shown from the second origin with its helper ready.
    page.wait_for_selector(".hv-mhead[data-machine='devbox']")
    page.wait_for_function("(id) => activeId === id", arg=a)
    # The first tabs message (before the remote base was patched in) may still be shown.
    page.wait_for_function(
        "(src) => document.querySelector('#frame').getAttribute('src') === src",
        arg=f"{remote.base}alpha.html",
    )
    page.wait_for_function("() => active && active.relayOpen", timeout=15000)
    assert (
        page.locator(f'.hv-card[data-session="{b}"] iframe').get_attribute("src")
        == f"{remote.base}jump.html"
    )
    page.screenshot(path=f"{SHOT}/window-online.png")

    # A page of an unrelated origin (the remote's page jumps there) gets no relay and a warning.
    page.locator(f'.hv-card[data-session="{b}"] .hv-chead').click()
    page.wait_for_function("(id) => activeId === id", arg=b)
    page.wait_for_selector("#warning.visible", timeout=15000)
    assert page.evaluate("() => active.relayOpen") is False
    page.locator(f'.hv-card[data-session="{a}"] .hv-chead').click()
    page.wait_for_function("() => active && active.relayOpen", timeout=15000)

    # Offline: placeholder instead of a frame, the detail under the heading.
    links._set(machine, "offline", OFFLINE_DETAIL)
    page.wait_for_selector(".hv-mnote")
    assert page.locator(".hv-mnote").inner_text() == OFFLINE_DETAIL
    assert page.locator(".hv-card iframe").count() == 0
    assert page.locator("#content").is_hidden()
    assert page.locator(".hv-card .hv-none").first.inner_text() == OFFLINE_DETAIL
    page.screenshot(path=f"{SHOT}/window-offline.png")

    # Online again: the frame loads once more from the remote.
    before = remote.hits.count("/s/tok/alpha.html")
    links._set(machine, "online", None)
    page.wait_for_function("() => active && active.relayOpen", timeout=15000)
    assert remote.hits.count("/s/tok/alpha.html") > before
    assert page.locator(".hv-mnote").count() == 0
