"""Hub process, health, Host guard and access control (HUB/SEC)."""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from helpers import raw_get

pytestmark = pytest.mark.integration


def listening_addresses(port: int) -> set[str]:
    """Local addresses of all TCP sockets listening on ``port`` (from /proc)."""
    found = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in Path(table).read_text().splitlines()[1:]:
            fields = line.split()
            address, _, hex_port = fields[1].partition(":")
            if int(hex_port, 16) == port and fields[3] == "0A":  # LISTEN
                found.add(address)
    return found


def test_hub_01_nfr_03_listens_on_loopback_only(hub) -> None:
    with socket.create_connection(("127.0.0.1", hub.port), timeout=3):
        pass
    assert listening_addresses(hub.port) == {"0100007F"}  # 127.0.0.1 only


def test_hub_01_cli_hub_command_serves_on_configured_port(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        **os.environ,
        "AGENT_CANVAS_PORT": str(port),
        "AGENT_CANVAS_STATE_DIR": str(tmp_path / "state"),
        "AGENT_CANVAS_CONFIG_DIR": str(tmp_path / "config"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", "hub"], env=env
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                answer = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except httpx.TransportError:
                assert time.monotonic() < deadline, "hub did not come up"
                time.sleep(0.1)
        assert answer.json()["app"] == "agent-canvas"
        assert listening_addresses(port) == {"0100007F"}
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_hub_03_health_shape_without_key(hub) -> None:
    answer = httpx.get(f"{hub.base_url}/health")
    assert answer.status_code == 200
    body = answer.json()
    assert body["app"] == "agent-canvas"
    assert isinstance(body["version"], str) and body["version"]


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:{port}", "127.0.0.1:1", "localhost", ""]
)
def test_sec_01_bad_host_header_gets_403(hub, host: str) -> None:
    status, _, _ = raw_get(hub.port, "/health", host=host.format(port=hub.port))
    assert status == 403


@pytest.mark.parametrize("host", ["127.0.0.1:{port}", "localhost:{port}"])
def test_sec_01_both_hub_hosts_are_accepted(hub, host: str) -> None:
    status, _, _ = raw_get(hub.port, "/health", host=host.format(port=hub.port))
    assert status == 200


def test_sec_02_hub_created_key_with_private_modes(hub) -> None:
    key_file = hub.state_dir / "key"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(hub.state_dir.stat().st_mode) == 0o700
    assert len(key_file.read_text().strip()) == 43


def test_sec_02_group_readable_key_makes_hub_exit_1_naming_the_file(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    key_file = state / "key"
    key_file.write_text("abc\n")
    key_file.chmod(0o644)
    env = {
        **os.environ,
        "AGENT_CANVAS_STATE_DIR": str(state),
        "AGENT_CANVAS_CONFIG_DIR": str(tmp_path / "config"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "agent_canvas.cli", "hub"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    assert str(key_file) in result.stderr


API_ROUTES = [
    ("GET", "/api/sessions"),
    ("POST", "/api/sessions"),
    ("GET", "/api/sessions/s1"),
    ("POST", "/api/sessions/s1/show"),
    ("POST", "/api/sessions/s1/ask"),
    ("GET", "/api/sessions/s1/watch"),
    ("POST", "/api/sessions/s1/pending"),
    ("POST", "/api/sessions/s1/end"),
    ("POST", "/api/sessions/s1/title"),
    ("POST", "/api/cleanup"),
    ("GET", "/api/anything-else"),
    ("GET", "/ws/anything"),
    ("GET", "/"),
]


@pytest.mark.parametrize(("method", "path"), API_ROUTES)
def test_sec_03_every_api_route_rejects_missing_credentials(
    hub, method: str, path: str
) -> None:
    assert httpx.request(method, hub.base_url + path).status_code == 401


@pytest.mark.parametrize(("method", "path"), API_ROUTES)
def test_sec_03_wrong_key_is_rejected(hub, method: str, path: str) -> None:
    headers = {"X-Agent-Canvas-Key": "not-the-key"}
    assert (
        httpx.request(method, hub.base_url + path, headers=headers).status_code == 401
    )


def test_sec_03_valid_key_header_is_accepted_and_open_routes_need_none(hub) -> None:
    assert (
        httpx.get(hub.base_url + "/api/sessions", headers=hub.key_headers).json() == []
    )
    assert httpx.get(hub.base_url + "/static/helper.js").status_code == 200
    assert httpx.get(hub.base_url + "/health").status_code == 200


@pytest.mark.parametrize("path", ["/ws/shell", "/api/sessions/s1/watch"])
def test_sec_03_websocket_without_credentials_closes_4401(hub, path: str) -> None:
    with connect(f"ws://127.0.0.1:{hub.port}{path}") as socket_:
        with pytest.raises(ConnectionClosed) as closed:
            socket_.recv(timeout=5)
    assert closed.value.rcvd.code == 4401


def login(hub) -> httpx.Response:
    return httpx.get(hub.login_url(), follow_redirects=False)


def test_sec_04_login_sets_cookie_flags_and_redirects_without_token(hub) -> None:
    answer = login(hub)
    assert answer.status_code == 302
    assert answer.headers["location"] == "/"
    cookie = answer.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "?t=" not in answer.headers["location"]
    with httpx.Client(base_url=hub.base_url, cookies=answer.cookies) as client:
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/").status_code == 200


def test_sec_04_token_is_single_use(hub) -> None:
    url = hub.login_url()
    assert httpx.get(url, follow_redirects=False).status_code == 302
    assert httpx.get(url, follow_redirects=False).status_code == 401


def test_sec_04_token_expires_after_60_seconds(hub) -> None:
    fresh = hub.login_url()
    stale = hub.login_url()
    hub.clock.advance(59)
    assert httpx.get(fresh, follow_redirects=False).status_code == 302
    hub.clock.advance(2)
    assert httpx.get(stale, follow_redirects=False).status_code == 401


def test_sec_04_key_is_not_a_login_token(hub) -> None:
    answer = httpx.get(f"{hub.base_url}/login?t={hub.key}", follow_redirects=False)
    assert answer.status_code == 401


@pytest.mark.parametrize(
    "origin",
    ["null", "http://localhost:{port}", "http://evil.example", "http://127.0.0.1:1"],
)
def test_sec_05_websocket_with_foreign_origin_is_rejected(hub, origin: str) -> None:
    with pytest.raises(InvalidStatus) as refused:
        connect(
            f"ws://127.0.0.1:{hub.port}/ws/shell",
            origin=origin.format(port=hub.port),
            additional_headers=hub.key_headers,
        )
    assert refused.value.response.status_code == 403


def test_sec_05_shell_origin_and_absent_origin_are_accepted(hub) -> None:
    url = f"ws://127.0.0.1:{hub.port}/ws/shell"
    cookie = httpx.get(hub.login_url(), follow_redirects=False).cookies
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookie.items())
    with connect(
        url, origin=hub.base_url, additional_headers={"Cookie": cookie_header}
    ) as shell:
        shell.send("hello")
    with connect(url, additional_headers=hub.key_headers) as cli:
        cli.send("hello")


def test_tst_01_hub_fixture_is_isolated_and_has_a_recorder(hub) -> None:
    real_state = Path.home() / ".local" / "state" / "agent-canvas"
    assert hub.state_dir != real_state
    assert str(hub.state_dir).startswith(str(hub.project_dir.parent))
    assert os.access(hub.recorder, os.X_OK)
    assert os.environ["AGENT_CANVAS_STATE_DIR"] == str(hub.state_dir)
