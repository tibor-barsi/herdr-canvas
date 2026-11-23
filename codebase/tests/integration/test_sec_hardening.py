"""Hardening after the security audit: page origins, framing, health proof.

SEC-06 (page files refuse foreign origins), SEC-11 (owner pages cannot be
framed), SEC-13 (the client sends the key only to a hub that proves it).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from agent_canvas.client import HubClient
from agent_canvas.config import Config
from agent_canvas.output import CliError

pytestmark = pytest.mark.integration


@pytest.fixture
def page(hub):  # noqa: ANN001, ANN201
    session = hub.add_session("s1", {"data.json": '{"secret": 1}'})
    return f"{hub.frame_origin}/s/{session.page_token}/data.json"


def test_sec_06_page_files_refuse_a_foreign_origin(hub, page) -> None:  # noqa: ANN001
    for origin in ("http://evil.example", f"http://127.0.0.1:{hub.port + 1}"):
        answer = httpx.get(page, headers={"Origin": origin})
        assert answer.status_code == 403, origin
        assert "secret" not in answer.text
        assert "access-control-allow-origin" not in answer.headers


def test_sec_06_page_files_serve_no_origin_null_and_the_hub_origins(hub, page) -> None:  # noqa: ANN001
    origins = [None, "null", hub.base_url, hub.frame_origin]
    for origin in origins:
        headers = {} if origin is None else {"Origin": origin}
        for method in ("GET", "HEAD"):
            answer = httpx.request(method, page, headers=headers)
            assert answer.status_code == 200, (origin, method)
            assert answer.headers["access-control-allow-origin"] == "*"


def test_sec_06_static_files_stay_open_to_any_origin(hub) -> None:  # noqa: ANN001
    answer = httpx.get(
        f"{hub.frame_origin}/static/helper.js",
        headers={"Origin": "http://evil.example"},
    )
    assert answer.status_code == 200


def test_sec_11_shell_and_render_host_cannot_be_framed(hub) -> None:  # noqa: ANN001
    login = httpx.get(hub.login_url(), follow_redirects=False)
    with httpx.Client(base_url=hub.base_url, cookies=login.cookies) as client:
        for path in ("/", "/render"):
            answer = client.get(path)
            assert answer.status_code == 200, path
            policy = answer.headers["content-security-policy"]
            assert "frame-ancestors 'none'" in policy, path


def test_sec_13_health_proves_the_key_for_a_challenge(hub) -> None:  # noqa: ANN001
    from agent_canvas.client import health_proof

    answer = httpx.get(f"{hub.base_url}/health", params={"challenge": "abc"}).json()
    assert answer["proof"] == health_proof(hub.key, hub.port, "abc")
    assert answer["proof"] != health_proof(hub.key, hub.port + 1, "abc")
    assert answer["proof"] != health_proof(hub.key + "x", hub.port, "abc")
    assert "proof" not in httpx.get(f"{hub.base_url}/health").json()


def test_sec_13_client_talks_to_the_real_hub(hub) -> None:  # noqa: ANN001
    client = HubClient(Config(port=hub.port), hub.state_dir)
    assert client.request("GET", "/api/status", start=False)["hub"] == "running"
    assert client.request("GET", "/api/status")["hub"] == "running"


class _Impostor(BaseHTTPRequestHandler):
    """Answers every request like a hub's ``/health`` and records the headers."""

    seen: list[dict[str, str]] = []

    def do_GET(self) -> None:  # noqa: N802
        self.seen.append(dict(self.headers))
        body = json.dumps({"app": "agent-canvas", "version": "0", "proof": "x"})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    do_POST = do_GET  # noqa: N815

    def log_message(self, *args: object) -> None:
        pass


@pytest.mark.parametrize("start", [True, False])
def test_sec_13_client_sends_no_key_to_a_listener_without_proof(
    tmp_path, start: bool
) -> None:  # noqa: ANN001
    (tmp_path / "key").write_text("the-owners-key\n")
    _Impostor.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Impostor)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = HubClient(Config(port=server.server_address[1]), tmp_path)
        with pytest.raises(CliError) as refused:
            client.request("GET", "/api/status", start=start)
        assert refused.value.code == "unauthorised"  # claims to be a hub (CLI-15)
    finally:
        server.shutdown()
        server.server_close()
    assert _Impostor.seen, "the client never reached the listener"
    for headers in _Impostor.seen:
        assert "the-owners-key" not in json.dumps(headers)


def test_sec_14_the_refusal_names_the_upgrade_step(tmp_path) -> None:  # noqa: ANN001
    (tmp_path / "key").write_text("the-owners-key\n")
    _Impostor.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Impostor)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = HubClient(Config(port=server.server_address[1]), tmp_path)
        with pytest.raises(CliError) as refused:
            client.request("GET", "/api/status", start=False)
    finally:
        server.shutdown()
        server.server_close()
    message = refused.value.message
    assert "stop the old hub" in message and "older than this client" in message
    assert "Upgrading" in message
