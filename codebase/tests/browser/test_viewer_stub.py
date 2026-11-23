"""A shown Markdown file opens as the viewer document with the helper once (VIEW-02)."""

from __future__ import annotations

import pytest

from .support import call

pytestmark = pytest.mark.browser


def test_view_02_a_shown_markdown_file_opens_as_the_viewer_document(make) -> None:  # noqa: ANN001
    made = make("<p>first</p>")
    (made.folder / "notes.md").write_text("# Notes\n")
    owner = made.owner
    call(
        owner,
        "POST",
        f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parents[1]), "name": "notes.md"},
    )
    frame = owner.frame
    frame.wait_for_selector("main.markdown h1")
    assert "Notes" in frame.evaluate("document.body.textContent")
    assert frame.evaluate("location.search") == "?ac-view=1"
    assert (
        frame.evaluate(
            "document.querySelectorAll('script[src$=\"/static/helper.js\"]').length"
        )
        == 1
    )
    frame.wait_for_function("window.agentCanvas !== undefined")
