"""Headless Chromium as the fallback renderer of ``look`` (LOOK-06).

Used when no owner window answers. Playwright drives a Chromium found on the
machine; it opens the hub's render host page (``/render``) with the owner
cookie, which loads the page in a frame and prepares it exactly as the owner's
window does (:file:`static/render.js`), and a native screenshot follows.
Playwright is imported only when a look needs it, so that the hub starts fast.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable, Mapping
from typing import Any

from agent_canvas.hub.looks import (
    SECTION_PADDING,
    LookError,
    RenderAccess,
    RenderFailed,
    RenderJob,
    RenderOutcome,
    clean_audit,
    clean_errors,
    clean_notes,
    clean_viewer_error,
    crop_region,
)

BROWSER_NAMES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)
BROWSER_VARIABLE = "AGENT_CANVAS_BROWSER"
# Isolates the sandboxed frame (localhost) from the shell (127.0.0.1) as desktop
# Chromium does; the render host page relies on the same split as the shell.
DEFAULT_ARGS = ("--site-per-process",)
GOTO_TIMEOUT_MS = 15_000


def find_browser(
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """
    Find the Chromium executable to use (LOOK-06a).

    Parameters
    ----------
    environ : Mapping[str, str] | None, optional
        Environment; default is ``os.environ``.
    which : Callable[[str], str | None], optional
        Looks a program up on ``PATH``.

    Returns
    -------
    str | None
        ``AGENT_CANVAS_BROWSER`` if set, else the first of
        :data:`BROWSER_NAMES` on ``PATH``; None means "use Playwright's own
        Chromium".

    Raises
    ------
    FileNotFoundError
        If ``AGENT_CANVAS_BROWSER`` names something that is not a file.
    """
    environ = os.environ if environ is None else environ
    if chosen := environ.get(BROWSER_VARIABLE):
        if not os.path.isfile(chosen):
            raise FileNotFoundError(f"{BROWSER_VARIABLE}={chosen} is not a file")
        return chosen
    for name in BROWSER_NAMES:
        if found := which(name):
            return found
    return None


class HeadlessRenderer:
    """
    Render a look with headless Chromium in a worker thread.

    Parameters
    ----------
    launch_env : Mapping[str, str] | None, optional
        Environment of the browser process (default: inherited).
    launch_args : tuple[str, ...], optional
        Extra Chromium arguments.
    environ : Mapping[str, str] | None, optional
        Environment used to find the browser (default ``os.environ``).
    """

    def __init__(
        self,
        launch_env: Mapping[str, str] | None = None,
        launch_args: tuple[str, ...] = DEFAULT_ARGS,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._env = dict(launch_env) if launch_env is not None else None
        self._args = list(launch_args)
        self._environ = environ
        self._lock = asyncio.Lock()

    async def render(self, job: RenderJob, access: RenderAccess) -> RenderOutcome:
        """
        Render ``job``; one browser at a time, off the event loop.

        Raises
        ------
        RenderFailed
            If no browser can be started or the page cannot be rendered.
        LookError
            If the section is not on the page.
        """
        async with self._lock:
            return await asyncio.to_thread(self._render, job, access)

    # ---- worker thread ---------------------------------------------------------

    def _render(self, job: RenderJob, access: RenderAccess) -> RenderOutcome:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RenderFailed(f"Playwright is not installed: {error}") from error
        try:
            executable = find_browser(self._environ)
        except FileNotFoundError as error:
            raise RenderFailed(str(error)) from error
        try:
            with sync_playwright() as playwright:
                browser = self._launch(playwright, executable, PlaywrightError)
                try:
                    return self._shoot(browser, job, access)
                finally:
                    browser.close()
        except PlaywrightError as error:
            raise RenderFailed(
                f"headless rendering failed: {_first_line(error)}"
            ) from error

    def _launch(self, playwright: Any, executable: str | None, error_type: type) -> Any:
        options: dict[str, Any] = {"args": self._args}
        if executable:
            options["executable_path"] = executable
        if self._env is not None:
            options["env"] = self._env
        try:
            return playwright.chromium.launch(**options)
        except error_type as error:
            where = executable or "Playwright's own Chromium"
            raise RenderFailed(
                f"could not start {where}: {_first_line(error)}. Install a "
                f"Chromium or set {BROWSER_VARIABLE}."
            ) from error

    def _shoot(
        self, browser: Any, job: RenderJob, access: RenderAccess
    ) -> RenderOutcome:
        context = browser.new_context(
            viewport={"width": job.width, "height": job.height},
            device_scale_factor=job.scale,
            color_scheme=job.scheme,
        )
        try:
            context.add_cookies(
                [
                    {
                        "name": access.cookie_name,
                        "value": access.cookie_value,
                        "url": access.origin,
                    }
                ]
            )
            page = context.new_page()
            page.goto(f"{access.origin}/render", timeout=GOTO_TIMEOUT_MS)
            result = page.evaluate(
                "(request) => window.canvasRender.prepareHost(request)",
                {
                    "url": job.url,
                    "width": job.width,
                    "height": job.height,
                    "section": job.section,
                    "full": job.full,
                    "settle_ms": int(job.settle_seconds * 1000),
                    "audit": job.audit,
                    "answers": job.answers,
                },
            )
            if not result.get("ok"):
                _raise_prepare_failure(result)
            png = self._screenshot(page, job, result) if job.picture else b""
        finally:
            context.close()
        return RenderOutcome(
            png=png,
            scheme=job.scheme,
            errors=clean_errors(result.get("errors")),
            audit=clean_audit(result.get("audit")),
            notes=clean_notes(result.get("notes")),
            source="headless",
            viewer_error=clean_viewer_error(result.get("viewer_error")),
        )

    @staticmethod
    def _screenshot(page: Any, job: RenderJob, result: dict[str, Any]) -> bytes:
        frame_height = int(result["frame_height"])
        if frame_height > job.height:
            # A full-page screenshot leaves the part of an out-of-process frame
            # below the viewport blank, so the window itself grows instead.
            page.set_viewport_size({"width": job.width, "height": frame_height})
            page.evaluate(
                "() => new Promise((done) => requestAnimationFrame("
                "() => requestAnimationFrame(done)))"
            )
            page.wait_for_timeout(100)
        if not job.section:
            return page.screenshot()
        try:
            clip = crop_region(result["rect"], SECTION_PADDING, job.width, frame_height)
        except ValueError as error:
            raise LookError("failed", f"{job.section}: {error}") from error
        return page.screenshot(clip=clip)


def _raise_prepare_failure(result: dict[str, Any]) -> None:
    """Raise the right error for a failed preparation in the render host."""
    reason = str(result.get("error") or "the page could not be prepared")[:300]
    if result.get("code") == "section":
        raise LookError("failed", reason)
    raise RenderFailed(f"headless rendering failed: {reason}")


def _first_line(error: Exception) -> str:
    """Return the first line of an exception message (Playwright adds logs)."""
    return (str(error).strip().splitlines() or [type(error).__name__])[0]
