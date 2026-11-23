"""``stop``, the shutdown API and how the CLI starts a hub (review finding M3)."""

from __future__ import annotations

import time

import httpx
import pytest

from agent_canvas import service
from agent_canvas.client import HubClient
from agent_canvas.config import Config

pytestmark = pytest.mark.integration


def test_cli_17_stop_shuts_a_running_hub_down_over_the_api(lone) -> None:  # noqa: ANN001
    assert lone.run("status").code == 0
    assert len(lone.pids()) == 1
    done = lone.run("stop")
    assert done.code == 0 and done.json == {"stopped": True, "via": "api"}
    deadline = time.monotonic() + 5
    while lone.pids() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert lone.pids() == []
    assert lone.run("stop").json == {"stopped": False, "via": "api"}  # none running


def test_cli_17_shutdown_needs_credentials(hub) -> None:  # noqa: ANN001
    answer = httpx.post(f"{hub.base_url}/api/shutdown", json={})
    assert answer.status_code == 401 and not hub.server.should_exit


def test_cli_17_shutdown_with_the_key_stops_the_hub(hub) -> None:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/shutdown", json={}, headers=hub.key_headers
    )
    assert answer.status_code == 200 and answer.json() == {"stopping": True}
    hub.wait_for(lambda: hub.server.should_exit)


class Recorder:
    """Stand-ins for the start paths of :class:`HubClient`."""

    def __init__(self, tmp_path, service_starts: bool) -> None:  # noqa: ANN001
        self.service_starts = service_starts
        self.spawned = 0
        self.client = HubClient(Config(port=1), tmp_path)
        self.client._probe = lambda: "ok"  # type: ignore[method-assign]
        self.client._spawn_detached = self.spawn  # type: ignore[method-assign]

    def spawn(self, log):  # noqa: ANN001, ANN201
        self.spawned += 1
        return type("Process", (), {"poll": lambda self: None})()


@pytest.mark.parametrize("service_starts", [True, False])
def test_cli_12_auto_start_prefers_the_enabled_service(
    tmp_path, monkeypatch, service_starts
) -> None:  # noqa: ANN001
    started: list[bool] = []

    def start(probe=None) -> bool:  # noqa: ANN001
        started.append(True)
        return service_starts

    monkeypatch.setattr(service, "start_enabled_service", start)
    recorder = Recorder(tmp_path, service_starts)
    recorder.client._start_and_wait()
    assert started == [True]
    assert recorder.spawned == (0 if service_starts else 1)


def test_cli_12_spawned_hub_does_not_import_from_the_working_directory(
    lone, tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    decoy_dir = tmp_path / "decoy"
    decoy_dir.mkdir()
    marker = tmp_path / "marker"
    (decoy_dir / "uvicorn.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    for name, value in lone.run.environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.chdir(decoy_dir)
    lone.state_dir.mkdir(parents=True, mode=0o700)
    client = HubClient(Config(port=lone.port), lone.state_dir)
    client._spawn_detached(lone.state_dir / "hub.log")
    deadline = time.monotonic() + 15
    while client._probe() != "ok" and time.monotonic() < deadline:
        time.sleep(0.1)
    assert client._probe() == "ok"
    assert not marker.exists()
