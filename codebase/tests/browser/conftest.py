"""Playwright fixtures for browser tests (headless Chromium, sync API)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Route,
    sync_playwright,
)

# User-space copy of Chromium's shared libraries (see AGENTS.md); used only
# when present, for hosts where `playwright install-deps` needs root.
EXTRA_LIBS = (
    Path.home() / ".cache" / "ac-libs" / "root" / "usr" / "lib" / "x86_64-linux-gnu"
)


SYSTEM_FONT_DIRS = (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"))
FALLBACK_FONT = (
    Path(__file__).resolve().parents[2]
    / "src/agent_canvas/static/vendor/katex/fonts/KaTeX_SansSerif-Regular.woff2"
)


def _fallback_fontconfig() -> Path | None:
    """
    Build a fontconfig file for hosts without system fonts, or return None.

    Headless Chromium aborts as soon as a page contains a form control when
    fontconfig finds no font at all. The vendored KaTeX sans-serif face is
    converted to TTF (fontconfig cannot read woff2) so the tests can use inputs.
    """
    if any(d.is_dir() and any(d.rglob("*.[ot]tf")) for d in SYSTEM_FONT_DIRS):
        return None
    from fontTools.ttLib import TTFont

    root = Path(tempfile.gettempdir()) / "agent-canvas-test-fonts"
    root.mkdir(exist_ok=True)
    font_file = root / "fallback.ttf"
    if not font_file.exists():
        font = TTFont(FALLBACK_FONT)
        font.flavor = None
        font.save(font_file)
    config = root / "fonts.conf"
    config.write_text(
        '<?xml version="1.0"?><fontconfig>'
        f"<dir>{root}</dir><cachedir>{root}/cache</cachedir>"
        "</fontconfig>"
    )
    return config


def _launch_env() -> dict[str, str]:
    """Return the environment for Chromium: user-space libraries, fallback font."""
    env = dict(os.environ)
    if (fontconfig := _fallback_fontconfig()) is not None:
        env["FONTCONFIG_FILE"] = str(fontconfig)
    if EXTRA_LIBS.is_dir():
        existing = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = (
            f"{EXTRA_LIBS}:{existing}" if existing else str(EXTRA_LIBS)
        )
    return env


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """Launch one headless Chromium for the whole session."""
    with sync_playwright() as playwright:
        # Playwright's headless Chromium does not isolate the sandboxed frame
        # (localhost) from the shell (127.0.0.1) by default; desktop Chromium
        # does. The flag restores the desktop behaviour that PAGE-10 relies on.
        chromium = playwright.chromium.launch(
            env=_launch_env(), args=["--site-per-process"]
        )
        yield chromium
        chromium.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """Provide a fresh page in an isolated browser context."""
    context = browser.new_context()
    yield context.new_page()
    context.close()


@dataclass
class Owner:
    """The owner's headless window: a page logged in to the hub."""

    page: Page
    context: BrowserContext
    hub: object
    foreign_requests: list[str]
    reports: list[dict] = field(default_factory=list)

    def reports_of(self, name: str) -> list:
        """Return all page reports called ``name`` seen by the shell."""
        return self.page.evaluate(
            "(n) => window.__reports.filter((r) => r.name === n).map((r) => r.data)",
            name,
        )

    def count_reports(self, name: str) -> int:
        """Return how many page reports called ``name`` the shell has seen."""
        return self.page.evaluate(
            "(n) => window.__reports.filter((r) => r.name === n).length", name
        )

    def wait_report_after(self, name: str, seen: int, timeout: float = 15000):  # noqa: ANN201
        """Wait for more than ``seen`` reports called ``name``; return the last."""
        self.page.wait_for_function(
            "([n, k]) => window.__reports.filter((r) => r.name === n).length > k",
            arg=[name, seen],
            timeout=timeout,
        )
        return self.reports_of(name)[-1]

    def visit(self, session_id: str) -> None:
        """Click a session's pill under "Not in Herdr", as the owner does."""
        self.page.locator(f'.hv-pill[data-session="{session_id}"]').click()
        self.page.wait_for_selector(f'.hv-card.focus[data-session="{session_id}"]')

    def show(self, session_id: str, page: str) -> None:
        """Show ``page`` through the hub and open its tab."""
        # A shell that connects later is not told about this page: wait for it.
        for _ in range(200):
            if self.hub.state.shells:
                break
            self.page.wait_for_timeout(25)
        self.hub.show(session_id, page)
        self.visit(session_id)

    @property
    def frame(self):  # noqa: ANN201
        """The Playwright frame of the shown page (SES-15: one frame per page)."""
        return self.page.locator("#frame").element_handle().content_frame()

    def wait_report(self, name: str, timeout: float = 30000):  # noqa: ANN201
        """Wait for a page report called ``name`` and return its data."""
        self.page.wait_for_function(
            "(n) => window.__reports && window.__reports.some((r) => r.name === n)",
            arg=name,
            timeout=timeout,
        )
        return self.reports_of(name)[-1]


@pytest.fixture
def owner(browser: Browser, hub) -> Iterator[Owner]:  # noqa: ANN001
    """
    Log in to the hub in headless Chromium and act as the owner (TST-02).

    A route guard aborts every request to an origin other than the hub's two
    hosts and fails the test at teardown (NFR-02, NFR-06).
    """
    allowed = {f"127.0.0.1:{hub.port}", f"localhost:{hub.port}"}
    foreign: list[str] = []
    # The Herdr view's sidebar, tab bar and card header take about 250 x 120 px:
    # this size leaves the page frame what 1280 x 720 left beside the tab column.
    context = browser.new_context(viewport={"width": 1440, "height": 840})

    def guard(route: Route) -> None:
        url = route.request.url
        if urlparse(url).netloc in allowed or url.startswith(("data:", "blob:")):
            route.continue_()
        else:
            foreign.append(url)
            route.abort()

    context.route("**/*", guard)
    page = context.new_page()
    page.goto(hub.login_url())
    yield Owner(page, context, hub, foreign)
    context.close()
    assert foreign == [], f"requests to foreign origins: {foreign}"


@pytest.fixture
def studio(owner, tmp_path: Path):  # noqa: ANN001, ANN201
    """An owner window with the drawing helpers (M9)."""
    from .support import Studio

    return Studio(owner, tmp_path)


@pytest.fixture
def make(owner, tmp_path: Path):  # noqa: ANN001, ANN201
    """Create a session, show ``html`` in it and wait for the page to load."""
    deadline = 100
    while not owner.hub.state.shells and deadline:
        owner.page.wait_for_timeout(50)
        deadline -= 1

    from .support import Made, call

    def build(html: str, name: str = "alpha", files: dict | None = None) -> Made:
        directory = tmp_path / name
        directory.mkdir(exist_ok=True)
        body = {"project": str(directory), "agent": "claude", "title": name}
        sid = call(owner, "POST", "/api/sessions", json=body)["session"]
        folder = owner.hub.state.session_of(sid).folder
        for filename, content in (files or {}).items():
            data = content.encode() if isinstance(content, str) else content
            (folder / filename).write_bytes(data)
        (folder / "page.html").write_text(html)
        # The watcher takes the new file on its own and pushes it as an update. Wait
        # until it has saved it: shown sooner, the push lands in the frame that show
        # just opened, and its morph removes what the page's scripts built.
        saved = folder / "history" / "pages" / "page.0001.html"
        for _ in range(200):
            if saved.exists():
                break
            owner.page.wait_for_timeout(10)
        # A shown page never opens itself: the owner has the tab open first, so
        # that ``show`` reports what the window rendered.
        owner.visit(sid)
        shown = call(
            owner,
            "POST",
            f"/api/sessions/{sid}/show",
            json={"project": str(directory), "name": "page.html"},
        )
        owner.frame.wait_for_function("document.readyState === 'complete'")
        owner.frame.wait_for_function("window.agentCanvas !== undefined")
        return Made(owner, sid, folder, shown)

    return build
