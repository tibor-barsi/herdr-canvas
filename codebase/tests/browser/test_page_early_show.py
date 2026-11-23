"""A page shown just after it is written keeps its drawing (PAGE-13, #54)."""

from __future__ import annotations

import pytest

from .support import call

PAGE = """<!doctype html><html><body><h1>early</h1>
<script>
  const c = document.createElement("canvas");
  c.id = "drawn";
  document.body.appendChild(c);
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.id = "svg-drawn";
  document.body.appendChild(s);
</script></body></html>"""


@pytest.mark.parametrize("delay", [20, 40])
def test_page_13_drawing_survives_an_early_show(owner, tmp_path, delay) -> None:  # noqa: ANN001
    """The watcher's push of the version the frame loaded does not wipe the drawing."""
    for _ in range(200):
        if owner.hub.state.shells:
            break
        owner.page.wait_for_timeout(50)
    directory = tmp_path / "early"
    directory.mkdir()
    body = {"project": str(directory), "agent": "claude", "title": "early"}
    sid = call(owner, "POST", "/api/sessions", json=body)["session"]
    folder = owner.hub.state.session_of(sid).folder
    owner.visit(sid)
    (folder / "page.html").write_text(PAGE)
    owner.page.wait_for_timeout(delay)
    call(
        owner,
        "POST",
        f"/api/sessions/{sid}/show",
        json={"project": str(directory), "name": "page.html"},
    )
    owner.frame.wait_for_function("window.agentCanvas !== undefined")
    saved = folder / "history" / "pages" / "page.0001.html"
    for _ in range(200):
        if saved.exists():
            break
        owner.page.wait_for_timeout(10)
    owner.page.wait_for_timeout(1000)
    assert owner.frame.locator("#drawn").count() == 1
    assert owner.frame.locator("#svg-drawn").count() == 1
