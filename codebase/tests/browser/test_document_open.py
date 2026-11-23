"""Open through the real shell (CNT-01, SEC-09) and old-version frames that cannot report lost comments (A-151)."""

# ruff: noqa: E501
from __future__ import annotations

import json
import time

import pytest

from .support import block

pytestmark = pytest.mark.browser

DOCUMENT = block("canvas-document", "d", {"src": "notes.md"})


def active_page(studio) -> str:  # noqa: ANN001
    return json.loads((studio.folder / "session.json").read_text())["active_page"]


def count_opens(studio) -> list:  # noqa: ANN001
    seen: list[str] = []
    studio.page.on(
        "request", lambda r: seen.append(r.url) if "/open-file" in r.url else None
    )
    return seen


def forge(studio, path) -> None:  # noqa: ANN001
    message = json.dumps({"type": "open-file", "path": path})
    studio.page.evaluate(f"privateMessage({message})")


def wait_active(studio, name: str) -> None:  # noqa: ANN001
    end = time.monotonic() + 8
    while time.monotonic() < end and active_page(studio) != name:
        studio.page.wait_for_timeout(50)
    assert active_page(studio) == name


def test_cnt_01_the_open_button_shows_the_file_as_a_page_through_the_shell(
    studio,
) -> None:  # noqa: ANN001
    studio.make(DOCUMENT, files={"notes.md": "# Opened note\n"})
    studio.frame.locator('canvas-document >> button:text-is("Open")').wait_for()
    assert active_page(studio) == "page.html"
    studio.frame.locator('canvas-document >> button:text-is("Open")').click()
    wait_active(studio, "notes.md")
    studio.page.wait_for_function(
        "document.getElementById('frame').src.includes('notes.md')"
    )
    meta = json.loads((studio.folder / "session.json").read_text())
    assert meta["pages"] == ["page.html", "notes.md"]


def test_sec_09_a_forged_open_message_opens_nothing_outside_the_session_folder(
    studio,
) -> None:  # noqa: ANN001
    studio.make(DOCUMENT, files={"notes.md": "# Opened note\n"})
    studio.frame.locator('canvas-document >> button:text-is("Open")').wait_for()
    (studio.folder.parent / "outside.md").write_text("# outside")
    opens = count_opens(studio)
    before = studio.page.evaluate("window.__guard.accepted['open-file'] || 0")
    forged = [
        "../outside.md",
        "/etc/passwd",
        "sub/inner.md",
        "page.html",
        "tool.py",
        "..\\x.md",
        5,
    ]
    for path in forged:
        forge(studio, path)
    # Positive control: the messages reached the shell and the relay refused them.
    studio.page.wait_for_function(
        f"(window.__guard.accepted['open-file'] || 0) >= {before + len(forged)}"
    )
    studio.page.wait_for_timeout(400)
    assert opens == [] and active_page(studio) == "page.html"
    forge(studio, "notes.md")
    wait_active(studio, "notes.md")
    assert len(opens) == 1


def token_in_shell(studio) -> str:  # noqa: ANN001
    """The token the shell holds for comment 1 (it gives it to the frame with the markers)."""
    studio.page.wait_for_function("commentTokens.size > 0")
    return studio.page.evaluate("[...commentTokens.values()].pop()")
