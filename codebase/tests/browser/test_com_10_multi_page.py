"""Send over several pages and the comments in the history panel (COM-10, HIST-03)."""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE, call
from .test_comment_layer import comment_mode, wait_saved, write_comment

pytestmark = pytest.mark.browser


def open_other_page(studio, sid: str) -> None:  # noqa: ANN001
    (studio.folder / "other.html").write_text(SCROLL_PAGE)
    body = {"project": str(studio.tmp_path / "alpha"), "name": "other.html"}
    call(studio.owner, "POST", f"/api/sessions/{sid}/show", json=body)
    studio.page.wait_for_function(
        "document.querySelector('.hv-card.focus .hv-pt[title=\"other.html\"]') !== null"
    )


def go_to(studio, page: str) -> None:  # noqa: ANN001
    studio.page.click(f'.hv-card.focus .hv-pt[title="{page}"]')
    studio.page.wait_for_function(
        f"document.getElementById('frame').src.includes('/{page}')"
    )
    studio.frame.wait_for_function("document.readyState === 'complete'")
    studio.frame.wait_for_function("window.agentCanvas !== undefined")


def test_com_10_send_now_takes_the_drafts_of_every_page_of_the_tab(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    open_other_page(studio, sid)
    go_to(studio, "other.html")
    comment_mode(studio)
    write_comment(studio, (60, 60), (200, 160), "on the other page")
    wait_saved(studio, 1)
    go_to(studio, "page.html")
    write_comment(studio, (60, 60), (200, 160), "on the first page")
    wait_saved(studio, 1)
    studio.page.keyboard.press("Control+Enter")
    first, second = studio.wait_events(sid, 2)
    assert (first["page"], first["part"]) == ("page.html", [1, 2])
    assert (second["page"], second["part"]) == ("other.html", [2, 2])
    assert first["send_id"] == second["send_id"]
    assert first["message"] == "" and second["message"] == ""
    assert first["screenshot"] and second["screenshot"] is None
    assert second["screenshot_error"] == "page not shown"
    assert [c["text"] for c in first["comments"]] == ["on the first page"]
    assert [c["text"] for c in second["comments"]] == ["on the other page"]
    studio.page.wait_for_function(
        "window.__shell.unsentComments().comments === 0"
    )
