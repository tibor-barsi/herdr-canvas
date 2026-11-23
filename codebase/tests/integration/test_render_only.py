"""The render-only call: a picture and nothing else (THUMB-01)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from agent_canvas.hub.looks import LookError, png_size
from shellfake import FakeHeadless

pytestmark = pytest.mark.integration


def _snapshot(folder: Path) -> dict[str, str | None]:
    """Map every path under ``folder`` to its content hash (None for a folder)."""
    return {
        str(p.relative_to(folder)): (
            None if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest()
        )
        for p in sorted(folder.rglob("*"))
    }


@pytest.fixture
def setup(hub):  # noqa: ANN001, ANN201
    session = hub.add_session("s1", {"page.html": "<p>page</p>"})
    headless = FakeHeadless()
    hub.app.state.looks.headless = headless
    return session, headless


def _render(hub, url: str, width: int, height: int, scheme: str) -> bytes:  # noqa: ANN001
    looks = hub.app.state.looks
    future = asyncio.run_coroutine_threadsafe(
        looks.render(url, width, height, scheme), hub.state.loop
    )
    return future.result(30)


def test_thumb_01_render_returns_a_png_of_the_asked_size(hub, setup) -> None:  # noqa: ANN001
    _, headless = setup
    url = hub.state.frame_url("s1", "page.html")
    png = _render(hub, url, 640, 360, "dark")
    assert png_size(png) == (640, 360)
    [job] = headless.jobs
    assert (job.url, job.scheme, job.audit) == (url, "dark", False)


def test_thumb_01_render_leaves_folder_history_events_and_windows_untouched(
    hub, setup
) -> None:  # noqa: ANN001
    session, _ = setup
    before = _snapshot(session.folder)
    shells = set(hub.state.shells)
    _render(hub, hub.state.frame_url("s1", "page.html"), 1280, 720, "light")
    assert _snapshot(session.folder) == before
    assert not (session.folder / "history" / "looks").exists()
    assert hub.on_loop(lambda: hub.state.events.all("s1")) == []
    assert set(hub.state.shells) == shells


def test_thumb_01_a_failing_render_raises_and_writes_nothing(hub, setup) -> None:  # noqa: ANN001
    session, _ = setup
    hub.app.state.looks.headless = FakeHeadless(error="boom")
    before = _snapshot(session.folder)
    with pytest.raises(LookError):
        _render(hub, hub.state.frame_url("s1", "page.html"), 640, 360, "light")
    assert _snapshot(session.folder) == before
