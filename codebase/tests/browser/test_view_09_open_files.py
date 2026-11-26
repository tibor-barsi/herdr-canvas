"""Opening files by picker and drop, and the file list (VIEW-09, PAGE-06)."""

from __future__ import annotations

import json

import pytest

from .support import call

pytestmark = pytest.mark.browser

PDF = b"%PDF-1.4 test"
PAGE = "<!doctype html><title>t</title><p>hello</p>"
MAKE_TRANSFER = """(files) => {
  const transfer = new DataTransfer();
  for (const [name, type, text] of files) {
    transfer.items.add(new File([text], name, {type}));
  }
  return transfer;
}"""


def drop(studio, selector: str, *files: tuple[str, str, str]) -> None:  # noqa: ANN001
    """Drop files on an element the way a file manager does (enter, over, drop)."""
    transfer = studio.page.evaluate_handle(MAKE_TRANSFER, list(files))
    for kind in ("dragenter", "dragover", "drop"):
        studio.page.dispatch_event(selector, kind, {"dataTransfer": transfer})


def pdf_file(name: str = "report.pdf") -> tuple[str, str, str]:
    return (name, "application/pdf", PDF.decode())


def pages_of(studio, sid: str) -> list[str]:  # noqa: ANN001
    meta = json.loads(
        (
            studio.owner.hub.state.session_of(studio.owner.hub.pool_of(sid)).folder
            / "session.json"
        ).read_text()
    )
    return meta["pages"]


def shown_frame(studio) -> str:  # noqa: ANN001
    return studio.page.evaluate("document.getElementById('frame').src")


def wait_open(studio, name: str) -> None:  # noqa: ANN001
    studio.page.wait_for_function(
        "(n) => document.getElementById('frame').src.includes('/' + n + '?ac-view=1')",
        arg=name,
    )


def second_session(studio) -> str:  # noqa: ANN001
    body = {
        "project": str(studio.tmp_path / "beta"),
        "agent": "claude",
        "title": "beta",
    }
    (studio.tmp_path / "beta").mkdir()
    sid = call(studio.owner, "POST", "/api/sessions", json=body)["session"]
    studio.page.wait_for_function(
        "(id) => homeSnapshot.sessions.some((s) => s.id === id)", arg=sid
    )
    return sid


def test_view_09_a_zip_is_refused_with_a_notice(studio) -> None:  # noqa: ANN001
    sid = studio.make(PAGE)
    drop(studio, "main", ("more.zip", "application/zip", "PK"))
    studio.page.keyboard.press("Enter")
    studio.page.wait_for_function(
        "document.getElementById('notice-text').textContent.includes('more.zip')"
    )
    folder = studio.owner.hub.state.session_of(studio.owner.hub.pool_of(sid)).folder
    assert not list(folder.glob("*.zip"))
    assert pages_of(studio, sid) == ["page.html"]


def test_view_09_the_hub_refusing_a_file_shows_its_reason(studio) -> None:  # noqa: ANN001
    studio.make(PAGE)
    drop(studio, "main", ("empty.pdf", "application/pdf", ""))
    studio.page.keyboard.press("Enter")
    studio.page.wait_for_selector("#notice.visible")
    assert "empty" in studio.page.inner_text("#notice-text")


def test_view_09_a_drag_that_carries_no_file_does_nothing(studio) -> None:  # noqa: ANN001
    studio.make(PAGE)
    transfer = studio.page.evaluate_handle(
        "() => { const t = new DataTransfer(); t.setData('text/plain', 'x');"
        " return t; }"
    )
    for kind in ("dragenter", "dragover"):
        studio.page.dispatch_event("main", kind, {"dataTransfer": transfer})
    assert not studio.page.evaluate("document.body.classList.contains('file-drag')")
    studio.page.dispatch_event("main", "drop", {"dataTransfer": transfer})
    assert not studio.page.locator(".file-dialog").count()


def post_drag_notice(studio) -> None:  # noqa: ANN001
    """What any page script can do: post the helper's drag notice with no drag."""
    studio.frame.evaluate("window.parent.postMessage({type: 'drag-notice'}, '*')")
    studio.page.wait_for_function("document.body.classList.contains('file-drag')")
    assert (
        studio.page.evaluate(
            "getComputedStyle(document.getElementById('frame')).pointerEvents"
        )
        == "none"
    )


def test_view_09_a_stray_drag_notice_lets_go_of_the_frame_by_itself(studio) -> None:  # noqa: ANN001
    """F6: no drag follows the notice, so the frame takes pointer input again."""
    studio.make(PAGE)
    post_drag_notice(studio)
    studio.page.wait_for_function(
        "!document.body.classList.contains('file-drag')", timeout=8000
    )
    assert (
        studio.page.evaluate(
            "getComputedStyle(document.getElementById('frame')).pointerEvents"
        )
        != "none"
    )


def test_view_09_a_pointer_move_over_the_shell_ends_a_stray_drag_notice(studio) -> None:  # noqa: ANN001
    studio.make(PAGE)
    post_drag_notice(studio)
    studio.page.mouse.move(5, 5)
    studio.page.mouse.move(40, 30)
    assert not studio.page.evaluate("document.body.classList.contains('file-drag')")


def test_view_09_a_real_drag_keeps_the_shield_while_it_lasts(studio) -> None:  # noqa: ANN001
    """Positive control: drag events over the shell hold the shield past the timeout."""
    studio.make(PAGE)
    transfer = studio.page.evaluate_handle(MAKE_TRANSFER, [list(pdf_file())])
    post_drag_notice(studio)
    for _ in range(8):  # about 4.8 s, longer than the 3 s timeout
        studio.page.dispatch_event("main", "dragover", {"dataTransfer": transfer})
        studio.page.wait_for_timeout(600)
    assert studio.page.evaluate("document.body.classList.contains('file-drag')")
