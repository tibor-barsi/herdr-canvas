"""The hub stays responsive with many sessions (HUB-05, review finding C1)."""

from __future__ import annotations

import time

import httpx
import pytest
from test_page_watching import FakeShell

pytestmark = pytest.mark.integration

SESSION_COUNT = 100


def fetch_seconds(hub, path: str) -> float:  # noqa: ANN001
    start = time.monotonic()
    answer = httpx.get(f"{hub.base_url}{path}", timeout=30)
    assert answer.status_code == 200
    return time.monotonic() - start


@pytest.mark.timing
def test_hub_05_100_sessions_do_not_starve_static_files_or_updates(hub) -> None:
    for number in range(SESSION_COUNT):
        hub.add_session(f"s{number:03d}")
    hub.add_session("live")
    time.sleep(1.0)  # let the watches settle
    slowest = max(fetch_seconds(hub, "/static/helper.js") for _ in range(5))
    assert slowest < 0.3
    shell = FakeShell(hub)
    try:
        page = hub.sessions["live"].folder / "page.html"
        start = time.monotonic()
        page.write_text("<p>changed</p>")
        update = {"type": None}
        while update["type"] != "update":
            update = shell.messages.get(timeout=0.5)
        assert time.monotonic() - start < 0.5
        assert update["html"] == "<p>changed</p>"
    finally:
        shell.close()


def test_hub_05_ended_and_hidden_sessions_are_not_watched(hub) -> None:
    registry = hub.app.state.registry
    project = str(hub.project_dir)
    for name in ("active-one", "ended-one", "hidden-one"):
        registry.create(name, project, "agent", None)
    registry.end("ended-one")
    registry.set_hidden("hidden-one", True)
    watcher = hub.app.state.watcher
    hub.on_loop(watcher.refresh)
    hub.wait_for(lambda: hub.on_loop(lambda: watcher.watching) == {"active-one"})
