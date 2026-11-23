"""The hub tells the shell about non-page file changes (BLK-09)."""

from __future__ import annotations

import queue
import time

import pytest
from test_page_watching import FakeShell

pytestmark = pytest.mark.integration


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    fake = FakeShell(hub)
    yield fake
    fake.close()


def file_changes(shell: FakeShell, wait: float) -> list[dict]:
    """Collect ``file-changed`` messages arriving within ``wait`` seconds."""
    found: list[dict] = []
    deadline = time.monotonic() + wait
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = shell.messages.get(timeout=left)
        except queue.Empty:
            break
        if message["type"] == "file-changed":
            found.append(message)
    return found


def first_file_change(shell: FakeShell, timeout: float) -> dict | None:
    """Return the next ``file-changed`` message, or None after ``timeout`` s."""
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = shell.messages.get(timeout=left)
        except queue.Empty:
            break
        if message["type"] == "file-changed":
            return message
    return None


def test_blk_09_a_changed_data_file_is_announced_with_its_relative_path(
    hub, shell
) -> None:
    session = hub.add_session("f")
    time.sleep(0.5)  # the watcher arms asynchronously; a write before it is lost
    (session.folder / "plot.json").write_text("{}")
    (session.folder / "data").mkdir()
    time.sleep(0.5)  # a file created in a brand-new directory can beat its watch
    (session.folder / "data" / "cube.stl").write_text("solid")
    changes = file_changes(shell, 1.0)
    assert {c["path"] for c in changes} == {"plot.json", "data/cube.stl"}
    assert {c["session"] for c in changes} == {"f"}


def test_blk_09_a_rewrite_is_announced_again_and_pages_are_not(hub, shell) -> None:
    session = hub.add_session("g")
    time.sleep(0.5)  # one watch serves all sessions and restarts for a new one
    (session.folder / "plot.json").write_text("{}")
    assert len(file_changes(shell, 0.8)) == 1
    (session.folder / "plot.json").write_text('{"data": []}')
    started = time.monotonic()
    change = first_file_change(shell, 1.0)
    assert change is not None and change["path"] == "plot.json"
    assert time.monotonic() - started < 0.9  # leaves room for the 1 s of BLK-09
    (session.folder / "page.html").write_text("<p>x</p>")
    assert file_changes(shell, 0.8) == []


def test_blk_09_hub_own_files_and_dotfiles_are_not_announced(hub, shell) -> None:
    session = hub.add_session("h")
    folder = session.folder
    (folder / "events.jsonl").write_text("{}\n")
    (folder / "session.json").write_text("{}")
    (folder / ".hidden.json").write_text("{}")
    (folder / "history" / "sends").mkdir(parents=True)
    (folder / "history" / "sends" / "0001.json").write_text("{}")
    assert file_changes(shell, 1.0) == []
