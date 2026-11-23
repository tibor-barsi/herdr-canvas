"""Tabs, page selector, links and the history panel in the browser (M5)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.browser


def call(owner, method: str, path: str, **kwargs) -> dict:  # noqa: ANN001
    """Call the hub API while keeping Playwright's event loop running."""
    hub = owner.hub
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            httpx.request,
            method,
            f"{hub.base_url}{path}",
            headers=hub.key_headers,
            timeout=15,
            **kwargs,
        )
        while not future.done():
            owner.page.wait_for_timeout(20)
        return future.result().json()


class Canvas:
    """Agent-side helper: create sessions and show pages through the API."""

    def __init__(self, owner, tmp_path: Path) -> None:  # noqa: ANN001
        self.owner = owner
        self.tmp_path = tmp_path
        owner.page.wait_for_function("true")
        deadline = 100
        while not owner.hub.state.shells and deadline:
            owner.page.wait_for_timeout(50)
            deadline -= 1

    def session(self, project: str, agent: str = "claude", title: str | None = None):  # noqa: ANN201
        directory = self.tmp_path / project
        directory.mkdir(exist_ok=True)
        body = {"project": str(directory), "agent": agent, "title": title}
        answer = call(self.owner, "POST", "/api/sessions", json=body)
        return answer["session"], Path(answer["folder"]), directory

    def show(self, sid, directory, name="page.html", html=None, title=None):  # noqa: ANN001, ANN201
        folder = self.owner.hub.state.session_of(sid).folder
        if html is not None:
            (folder / name).write_text(html)
        body = {"project": str(directory), "name": name}
        if title:
            body["title"] = title
        return call(self.owner, "POST", f"/api/sessions/{sid}/show", json=body)

    def make(self, project, agent="claude", title="T", html="<p>x</p>"):  # noqa: ANN001, ANN201
        sid, folder, directory = self.session(project, agent)
        answer = self.show(sid, directory, html=html, title=title)
        # The window starts on the start page: the owner opens the first tab.
        if self.owner.page.locator(".hv-card.focus[data-session]").count() == 0:
            self.owner.visit(sid)
        return sid, folder, directory, answer


@pytest.fixture
def canvas(owner, tmp_path: Path) -> Canvas:
    return Canvas(owner, tmp_path)


def tab_names(owner) -> list[str]:  # noqa: ANN001
    return [t.get_attribute("aria-label") for t in owner.page.get_by_role("tab").all()]


def active_name(owner) -> str:  # noqa: ANN001
    return owner.page.locator("[role=tab][aria-selected=true]").get_attribute(
        "aria-label"
    )


def frame_text(owner) -> str:  # noqa: ANN001
    return owner.frame.evaluate("document.body.textContent").strip()


def tab(owner, name: str):  # noqa: ANN001, ANN201
    return owner.page.get_by_role("tab", name=name, exact=True)


def set_draft(owner, sid: str, draft: dict) -> None:  # noqa: ANN001
    owner.page.evaluate("([s, d]) => { window.__drafts[s] = d; }", [sid, draft])


# ---- SES-05 -----------------------------------------------------------------------


# ---- SES-06 -----------------------------------------------------------------------


# ---- SES-07 and SES-11 ------------------------------------------------------------


# ---- SES-08 -----------------------------------------------------------------------


# ---- PAGE-06 ----------------------------------------------------------------------


def test_page_06_selector_and_edit_of_inactive_page_keeps_the_view(
    owner, canvas
) -> None:
    sid, folder, directory, _ = canvas.make("alpha", html="<p id=a>page a</p>")
    canvas.show(sid, directory, "b.html", "<p>page b</p>")
    owner.page.wait_for_function(
        "document.querySelectorAll('.hv-card.focus .hv-pt').length === 2"
    )
    assert owner.page.locator('.hv-card.focus .hv-pt[title="b.html"]').is_visible()
    owner.frame.wait_for_function("document.body?.textContent.includes('page b')")
    (folder / "page.html").write_text("<p id=a>page a, edited</p>")
    versions = folder / "history" / "pages"
    for _ in range(60):
        if (versions / "page.0002.html").exists():
            break
        owner.page.wait_for_timeout(50)
    assert (versions / "page.0002.html").exists()
    owner.page.wait_for_timeout(300)
    assert frame_text(owner) == "page b"
    owner.page.click('.hv-card.focus .hv-pt[title="page.html"]')
    owner.frame.wait_for_function("document.body?.textContent.includes('edited')")


# ---- PAGE-11 ----------------------------------------------------------------------


# ---- layout -------------------------------------------------------------------------
