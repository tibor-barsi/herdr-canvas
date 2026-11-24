"""``look``: render a page so that an agent can see it (LOOK-01 to LOOK-09).

A look is rendered by the owner's window (a hidden frame in the shell, so that
the owner's fonts are used) or, when no window answers, by a headless Chromium
(:mod:`agent_canvas.hub.headless`). :class:`LookService` picks the renderer,
stores the PNG as ``history/looks/NNNN.png`` and builds the answer.

Also here: the pure helpers (request validation, crop maths, PNG size) that
the unit tests cover.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
import re
import secrets
import struct
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from agent_canvas.drafts import draft_name_for, is_draft_name, published_name_for
from agent_canvas.hub.audit import attach_crops, build_audit, show_audit
from agent_canvas.hub.sends import MAX_SCREENSHOT_BYTES, PNG_SIGNATURE
from agent_canvas.hub.state import VIEWER_REASONS, HubState, Session, _error_record
from agent_canvas.hub.viewers import viewer_type
from agent_canvas.paths import make_private_dirs
from agent_canvas.paths_safe import UnsafePathError, validate_page_name

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
DEFAULT_SCHEME = "light"
MIN_SIZE = 100
MAX_SIZE = 8000
SCHEMES = ("light", "dark")
SECTION_PADDING = 8
WINDOW_TIMEOUT_SECONDS = 10.0
SETTLE_SECONDS = 5.0
SHOW_AUDIT_SECONDS = 4.0
SHOW_SETTLE_SECONDS = 3.0
LOOKS_DIR = Path("history") / "looks"
LOOK_FILE = re.compile(r"^(\d{4,})\.png$")
MAX_ERRORS = 50
MAX_NOTES = 10
MAX_AUDIT_BYTES = 200_000
NO_RENDERER = (
    "No renderer is available. Open the canvas window (`agent-canvas open`) so "
    "that it can render the page, or install a Chromium (set "
    "AGENT_CANVAS_BROWSER to its path) for headless rendering."
)
WINDOW_SILENT = (
    "The canvas tab is connected but did not answer the render request in "
    "time. Reload the canvas tab, or install a Chromium (set "
    "AGENT_CANVAS_BROWSER to its path) for headless rendering."
)
WINDOW_OLDER = (
    "The canvas tab did not answer the render request: the canvas tab runs an "
    "older version; it reloads by itself, or reload it. Or install a Chromium "
    "(set AGENT_CANVAS_BROWSER to its path) for headless rendering."
)


class LookError(ValueError):
    """
    A look that cannot be made; the message tells the agent what to change.

    Parameters
    ----------
    code : str
        CLI error code: ``usage``, ``failed`` or ``no-session``.
    message : str
        Human-readable text.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RenderFailed(Exception):
    """A renderer could not produce the picture; the next one is tried."""


class WindowSilent(RenderFailed):
    """A connected window did not answer the render request in time."""


@dataclass(frozen=True)
class WindowInfo:
    """
    What the owner's window reported about its page frame (LOOK-02).

    Attributes
    ----------
    width, height : int
        Viewport size of the frame in CSS pixels.
    scheme : str
        ``light`` or ``dark`` (``prefers-color-scheme``).
    build : str | None
        The shell build the window runs (SHELL-02); None for an old shell
        that does not report one.
    """

    width: int
    height: int
    scheme: str
    build: str | None = None


@dataclass(frozen=True)
class RenderJob:
    """
    One render order for a renderer.

    Attributes
    ----------
    url : str
        Frame-site URL of the page or draft.
    width, height : int
        Viewport size.
    scheme : str
        ``light`` or ``dark``.
    section : str | None
        Element ``id`` or ``data-canvas-id`` to crop to.
    full : bool
        Capture the whole page height.
    settle_seconds : float
        How long to wait for the page and its blocks to finish rendering.
    audit : bool
        Run the page checks (CHK-01).
    picture : bool
        Take the picture; False when only the checks are wanted (``show``).
    answers : dict | None
        The page's ``answers`` message, handed to the rendered page as the
        window does, so answered cards show as answered.
    scale : float
        Device scale factor of the headless browser (thumbnails use 0.2 so that
        the picture comes out small).
    """

    url: str
    width: int
    height: int
    scheme: str
    section: str | None
    full: bool
    settle_seconds: float = SETTLE_SECONDS
    audit: bool = True
    picture: bool = True
    scale: float = 1.0
    answers: dict[str, Any] | None = None


@dataclass
class RenderOutcome:
    """
    A finished render.

    Attributes
    ----------
    png : bytes
        The picture (empty when the job asked for none).
    scheme : str
        The colour scheme that was rendered.
    errors : list[dict[str, Any]]
        Page and block errors seen while rendering (5.7 shape).
    audit : Any
        Raw result of the page audit hook (``runPageAudit``); see
        :func:`agent_canvas.hub.audit.build_audit`.
    notes : list[str]
        Remarks such as "the page did not settle".
    source : str
        ``window`` or ``headless``.
    viewer_error : str | None
        Why a viewer page could not be shown (VIEW-14), else None.
    """

    png: bytes
    scheme: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    audit: Any = None
    notes: list[str] = field(default_factory=list)
    source: str = "window"
    viewer_error: str | None = None


@dataclass(frozen=True)
class RenderAccess:
    """
    What a headless browser needs to reach the hub as the owner.

    Attributes
    ----------
    origin : str
        Shell origin of the hub.
    cookie_name, cookie_value : str
        The owner cookie. Never printed or stored.
    """

    origin: str
    cookie_name: str
    cookie_value: str = field(repr=False)


class Renderer(Protocol):
    """A renderer other than the window (:class:`HeadlessRenderer`)."""

    async def render(self, job: RenderJob, access: RenderAccess) -> RenderOutcome:
        """Render ``job`` or raise :class:`RenderFailed`."""
        ...


@dataclass(frozen=True)
class LookRequest:
    """
    A validated ``look`` request (LOOK-01).

    Attributes
    ----------
    page : str | None
        Published page name (``NAME.html``); None for the active page.
    draft : bool
        Render the draft ``NAME.draft.html``.
    section : str | None
        Element ``id`` or ``data-canvas-id`` to crop to.
    full : bool
        Capture the whole page height.
    width, height : int | None
        Viewport size; None for the window's.
    scheme : str | None
        ``light`` or ``dark``; None for the window's.
    audit : bool
        Run the page checks (default True).
    """

    page: str | None
    draft: bool
    section: str | None
    full: bool
    width: int | None
    height: int | None
    scheme: str | None
    audit: bool = True

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> LookRequest:
        """
        Validate the JSON body of a look request.

        Parameters
        ----------
        body : dict[str, Any]
            Keys ``page``, ``draft``, ``section``, ``full``, ``width``,
            ``height``, ``scheme`` and ``audit``, all optional.

        Returns
        -------
        LookRequest
            The request; a draft file name as ``page`` turns on ``draft``.

        Raises
        ------
        LookError
            ``usage`` for any bad value.
        """
        page, draft = _page_and_draft(body.get("page"), body.get("draft", False))
        section = body.get("section")
        if section is not None and not (
            isinstance(section, str) and 0 < len(section) <= 200
        ):
            raise LookError("usage", "section must be a non-empty element id.")
        full = body.get("full", False)
        if not isinstance(full, bool):
            raise LookError("usage", "full must be true or false.")
        scheme = body.get("scheme")
        if scheme is not None and scheme not in SCHEMES:
            raise LookError("usage", f"scheme must be one of {', '.join(SCHEMES)}.")
        audit = body.get("audit", True)
        if not isinstance(audit, bool):
            raise LookError("usage", "audit must be true or false.")
        return cls(
            page,
            draft,
            section,
            full,
            _size(body.get("width"), "width"),
            _size(body.get("height"), "height"),
            scheme,
            audit,
        )


def _page_and_draft(page: Any, draft: Any) -> tuple[str | None, bool]:
    """Return the published page name and the draft flag of a request."""
    if not isinstance(draft, bool):
        raise LookError("usage", "draft must be true or false.")
    if page is None:
        return None, draft
    if not isinstance(page, str):
        raise LookError("usage", "page must be a page name.")
    try:
        validate_page_name(page)
    except UnsafePathError as error:
        raise LookError("usage", str(error)) from error
    if page.startswith("."):
        raise LookError("usage", f"Invalid page name {page!r}: dotfiles are not pages.")
    if viewer_type(page):
        return page, draft
    published = published_name_for(page if page.endswith(".html") else f"{page}.html")
    return published, draft or is_draft_name(page)


def _size(value: Any, name: str) -> int | None:
    """Validate an optional viewport size."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LookError("usage", f"{name} must be a whole number of pixels.")
    if not MIN_SIZE <= value <= MAX_SIZE:
        raise LookError("usage", f"{name} must be between {MIN_SIZE} and {MAX_SIZE}.")
    return value


def crop_region(
    rect: dict[str, float], padding: int, width: int, height: int
) -> dict[str, int]:
    """
    Compute the pixel box of an element, padded and clamped to the image.

    Parameters
    ----------
    rect : dict[str, float]
        ``x``, ``y``, ``width``, ``height`` of the element in image pixels.
    padding : int
        Pixels added on every side.
    width, height : int
        Size of the image the box must stay inside.

    Returns
    -------
    dict[str, int]
        ``x``, ``y``, ``width``, ``height`` of the crop; the box rounds
        outwards, so the element is always inside it.

    Raises
    ------
    ValueError
        If the element has no area or lies outside the image.
    """
    if rect["width"] <= 0 or rect["height"] <= 0:
        raise ValueError("the section has no visible area")
    left = max(0, math.floor(rect["x"] - padding))
    top = max(0, math.floor(rect["y"] - padding))
    right = min(width, math.ceil(rect["x"] + rect["width"] + padding))
    bottom = min(height, math.ceil(rect["y"] + rect["height"] + padding))
    if right <= left or bottom <= top:
        raise ValueError("the section has no visible area")
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def png_size(data: bytes) -> tuple[int, int]:
    """
    Read the size of a PNG from its header.

    Parameters
    ----------
    data : bytes
        The file content.

    Returns
    -------
    tuple[int, int]
        Width and height in pixels.

    Raises
    ------
    ValueError
        If ``data`` does not start like a PNG.
    """
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG image")
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1:
        raise ValueError("not a PNG image: empty size")
    return width, height


def next_look_number(folder: Path) -> int:
    """Return the number of the next look of a session folder (from 1)."""
    directory = folder / LOOKS_DIR
    if not directory.is_dir():
        return 1
    found = [
        int(m.group(1)) for p in directory.iterdir() if (m := LOOK_FILE.match(p.name))
    ]
    return max(found, default=0) + 1


def store_look(folder: Path, png: bytes) -> Path:
    """
    Write ``png`` as the next ``history/looks/NNNN.png``.

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    png : bytes
        The picture.

    Returns
    -------
    pathlib.Path
        Absolute path of the stored file.
    """
    directory = folder.resolve() / LOOKS_DIR
    make_private_dirs(directory)
    path = directory / f"{next_look_number(folder):04d}.png"
    path.write_bytes(png)
    return path


class LookService:
    """
    Choose a renderer, render, store and describe a look.

    Parameters
    ----------
    state : HubState
        Hub state (shells, port, credentials).
    headless : Renderer | None
        The fallback renderer; None disables the fallback.

    Attributes
    ----------
    window_timeout : float
        Seconds the window gets to answer before the fallback is used.
    settle_seconds : float
        Seconds a page gets to finish rendering (sent to the renderer).
    show_audit : bool
        Whether ``show`` runs the page checks (CHK-15); tests switch it off.
    show_audit_seconds : float
        How long ``show`` waits for the checks before it answers ``pending``.
    """

    def __init__(self, state: HubState, headless: Renderer | None) -> None:
        self.state = state
        self.headless = headless
        self.window_timeout = WINDOW_TIMEOUT_SECONDS
        self.settle_seconds = SETTLE_SECONDS
        self.show_audit = True
        self.show_audit_seconds = SHOW_AUDIT_SECONDS
        self._background: set[asyncio.Task[Any]] = set()
        self._windows: dict[Any, tuple[int, WindowInfo]] = {}
        self._waiting: dict[str, tuple[Any, asyncio.Future[dict[str, Any]]]] = {}
        self._reports = 0
        self.window_problem: str | None = None
        # The ``answers`` message of (session id, page), for the pages ``look`` draws.
        self.answers_of: Callable[[str, str], dict[str, Any] | None] | None = None

    # ---- what the shell tells us ------------------------------------------

    def on_window_info(self, shell: Any, message: dict[str, Any]) -> None:
        """Remember the size and colour scheme a shell reported (LOOK-02)."""
        width, height = message.get("width"), message.get("height")
        scheme = message.get("scheme")
        sizes = (width, height)
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in sizes):
            return
        if scheme not in SCHEMES:
            return
        build = message.get("build")
        info = WindowInfo(
            int(min(MAX_SIZE, max(MIN_SIZE, width))),
            int(min(MAX_SIZE, max(MIN_SIZE, height))),
            scheme,
            build if isinstance(build, str) and build else None,
        )
        self._reports += 1
        self._windows[shell] = (self._reports, info)

    def on_render_result(self, shell: Any, message: dict[str, Any]) -> None:
        """Hand an answer to the look that asked for it; ignore others."""
        waiting = self._waiting.get(message.get("id"))  # type: ignore[arg-type]
        if waiting is None or waiting[0] is not shell or waiting[1].done():
            return
        waiting[1].set_result(message)

    def drop_shell(self, shell: Any) -> None:
        """Forget a closed window and fail its pending looks at once."""
        self._windows.pop(shell, None)
        for owner, future in self._waiting.values():
            if owner is shell and not future.done():
                future.set_exception(RenderFailed("the window closed"))

    def window_info(self) -> WindowInfo | None:
        """Return the newest window report, or None without a known window."""
        newest = self._newest_window()
        return None if newest is None else newest[1]

    def _newest_window(self) -> tuple[Any, WindowInfo] | None:
        live = [
            (n, s, i) for s, (n, i) in self._windows.items() if s in self.state.shells
        ]
        if not live:
            return None
        _, shell, info = max(live, key=lambda item: item[0])
        return shell, info

    # ---- the look ------------------------------------------------------------

    async def look(
        self,
        session: Session,
        request: LookRequest,
        active_page: str | None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """
        Render a page or draft of ``session`` and store the picture.

        Parameters
        ----------
        session : Session
            The session whose folder holds the page.
        request : LookRequest
            What to render.
        active_page : str | None
            The session's active page, used when the request names none.
        tag : str | None, optional
            The caller's draft tag when ``session`` is its pool (POOL-11).

        Returns
        -------
        dict[str, Any]
            ``png``, ``width``, ``height``, ``scheme``, ``source``, ``errors``,
            ``notes``, ``page``, ``draft`` and ``audit`` (LOOK-01).

        Raises
        ------
        LookError
            For a missing page or draft, an unknown section, or when no
            renderer works.
        """
        page = request.page or active_page or "page.html"
        file_name = draft_name_for(page, tag) if request.draft else page
        self._require_file(session, file_name, request.draft)
        return await self._look(session, request, page, file_name)

    async def _look(
        self, session: Session, request: LookRequest, page: str, file_name: str
    ) -> dict[str, Any]:
        newest = self._newest_window()
        info = newest[1] if newest else None
        viewer = viewer_type(file_name) is not None
        job = RenderJob(
            url=self.state.render_url(session.session_id, file_name),
            width=request.width or (info.width if info else DEFAULT_WIDTH),
            height=request.height or (info.height if info else DEFAULT_HEIGHT),
            scheme=request.scheme or (info.scheme if info else DEFAULT_SCHEME),
            section=request.section,
            full=request.full,
            settle_seconds=self.settle_seconds,
            audit=request.audit and not viewer,
            answers=None
            if viewer or request.draft or not self.answers_of
            else self.answers_of(session.session_id, page),
        )
        outcome = await self._render(job, newest)
        path = store_look(session.folder, outcome.png)
        width, height = png_size(outcome.png)
        audit = await self._audit(request, job, outcome, path)
        extra = {"viewer_error": outcome.viewer_error} if viewer else {}
        return {
            "png": str(path),
            "width": width,
            "height": height,
            "scheme": outcome.scheme,
            "source": outcome.source,
            "errors": outcome.errors,
            "notes": outcome.notes,
            "page": page,
            "draft": request.draft,
            "audit": audit,
            **extra,
        }

    async def render(
        self,
        url: str,
        width: int,
        height: int,
        scheme: str,
        *,
        headless_only: bool = False,
        scale: float = 1.0,
    ) -> bytes:
        """
        Render a page and return the picture, with no side effect (THUMB-01).

        Nothing is stored and no check runs; no history entry, event or window
        state changes. The renderer is chosen as for ``look``.

        Parameters
        ----------
        url : str
            Frame-site URL of the page or draft.
        width, height : int
            Viewport size in CSS pixels.
        scheme : str
            ``light`` or ``dark``.
        headless_only : bool, optional
            Never ask the owner's window (thumbnails, THUMB-03).
        scale : float, optional
            Device scale factor of the headless browser; the picture is
            ``width * scale`` pixels wide.

        Returns
        -------
        bytes
            The PNG.

        Raises
        ------
        LookError
            When no renderer works.
        """
        job = RenderJob(
            url=url,
            width=width,
            height=height,
            scheme=scheme,
            section=None,
            full=False,
            settle_seconds=self.settle_seconds,
            audit=False,
            scale=scale,
        )
        if headless_only:
            return (await self._render_headless(job)).png
        return (await self._render(job, self._newest_window())).png

    async def _render_headless(self, job: RenderJob) -> RenderOutcome:
        """Render with the headless browser only; the window is never asked."""
        failures: list[RenderFailed] = []
        if self.headless is not None:
            access = self._access()
            outcome = await self._try(self.headless.render(job, access), failures)
            if outcome is not None:
                return outcome
        detail = "; ".join(str(failure) for failure in failures)
        raise LookError(
            "failed", f"{NO_RENDERER} ({detail})" if detail else NO_RENDERER
        )

    @staticmethod
    async def _audit(
        request: LookRequest, job: RenderJob, outcome: RenderOutcome, path: Path
    ) -> dict[str, Any] | None:
        """Build the page checks of a look and attach the crops (CHK-01)."""
        if not job.audit:
            return None
        audit = build_audit(outcome.audit, outcome.errors)
        if request.section is None:
            outcome.notes += await asyncio.to_thread(
                attach_crops, audit, outcome.png, path, job.width
            )
        return audit

    async def audit_for_show(
        self, session: Session, page: str
    ) -> dict[str, Any] | str | None:
        """
        Run the page checks for ``show`` within a time budget (CHK-15).

        The page is rendered through the same renderers as a look, at the size
        of the owner's window, without a picture.

        Parameters
        ----------
        session : Session
            The session that shows the page.
        page : str
            The page name.

        Returns
        -------
        dict[str, Any] | str | None
            The summary with the errors and warnings; ``"pending"`` when the
            checks did not finish within ``show_audit_seconds`` (they go on
            in the background and are dropped); ``"unavailable"`` when no
            renderer works; None when ``show`` does not run them.
        """
        if not self.show_audit:
            return None
        newest = self._newest_window()
        info = newest[1] if newest else None
        job = RenderJob(
            url=self.state.frame_url(session.session_id, page),
            width=info.width if info else DEFAULT_WIDTH,
            height=info.height if info else DEFAULT_HEIGHT,
            scheme=info.scheme if info else DEFAULT_SCHEME,
            section=None,
            full=False,
            settle_seconds=min(self.settle_seconds, SHOW_SETTLE_SECONDS),
            picture=False,
        )
        task = asyncio.ensure_future(self._audit_only(job, newest))
        task.add_done_callback(self._forget)
        self._background.add(task)
        done, _ = await asyncio.wait({task}, timeout=self.show_audit_seconds)
        if not done:
            return "pending"
        try:
            return task.result()
        except Exception:  # noqa: BLE001 - a failing check must never fail show
            return "unavailable"

    async def viewer_error_for_show(self, session: Session, page: str) -> str | None:
        """
        Load a viewer page once in the headless browser for ``show`` (VIEW-14).

        The owner's window is never used, nothing is stored and no page check
        runs. The load has the time budget of the page checks.

        Parameters
        ----------
        session : Session
            The session that shows the page.
        page : str
            The page name (a viewer page).

        Returns
        -------
        str | None
            The reason the viewer could not show the file; None when it showed
            it, when ``show`` does not load pages, or when the load did not
            finish in time or no browser works.
        """
        if not self.show_audit:
            return None
        info = self.window_info()
        job = RenderJob(
            url=self.state.render_url(session.session_id, page),
            width=info.width if info else DEFAULT_WIDTH,
            height=info.height if info else DEFAULT_HEIGHT,
            scheme=info.scheme if info else DEFAULT_SCHEME,
            section=None,
            full=False,
            settle_seconds=min(self.settle_seconds, SHOW_SETTLE_SECONDS),
            audit=False,
            picture=False,
        )
        task = asyncio.ensure_future(self._render_headless(job))
        task.add_done_callback(self._forget)
        self._background.add(task)
        done, _ = await asyncio.wait({task}, timeout=self.show_audit_seconds)
        if not done or task.exception() is not None:
            return None
        return task.result().viewer_error

    def _forget(self, task: asyncio.Task[Any]) -> None:
        """Drop a finished background audit and read its outcome."""
        self._background.discard(task)
        if not task.cancelled():
            task.exception()

    async def _audit_only(
        self, job: RenderJob, window: tuple[Any, WindowInfo] | None
    ) -> dict[str, Any] | str:
        """Render for the checks only; a failure never fails ``show``."""
        try:
            outcome = await self._render(job, window)
        except (LookError, RenderFailed):
            return "unavailable"
        return show_audit(build_audit(outcome.audit, outcome.errors))

    @staticmethod
    def _require_file(session: Session, file_name: str, draft: bool) -> None:
        if (session.folder / file_name).is_file():
            return
        hint = " Write it first, or drop --draft." if draft else ""
        raise LookError(
            "failed", f"{file_name} not found in session folder {session.folder}.{hint}"
        )

    async def _render(
        self, job: RenderJob, window: tuple[Any, WindowInfo] | None
    ) -> RenderOutcome:
        """Try the window, then headless; the window again as a last resort."""
        failures: list[RenderFailed] = []
        self.window_problem = None
        same_scheme = window is not None and window[1].scheme == job.scheme
        if window is not None and same_scheme:
            outcome = await self._try(self._ask_window(window[0], job), failures)
            if outcome is not None:
                return outcome
        if self.headless is not None:
            access = self._access()
            outcome = await self._try(self.headless.render(job, access), failures)
            if outcome is not None:
                return outcome
        if window is not None and not same_scheme:
            # A window cannot render another colour scheme; better its own than
            # nothing, and the answer says which one it is.
            own = replace(job, scheme=window[1].scheme)
            outcome = await self._try(self._ask_window(window[0], own), failures)
            if outcome is not None:
                outcome.notes.append(
                    f"The window renders {outcome.scheme}; {job.scheme} was "
                    "requested but no headless browser is available."
                )
                return outcome
        detail = "; ".join(str(failure) for failure in failures)
        silent = any(isinstance(failure, WindowSilent) for failure in failures)
        headline = NO_RENDERER
        if silent and window is not None:
            headline = self._silent_window_message(window[1])
            self.window_problem = headline
        raise LookError("failed", f"{headline} ({detail})" if detail else headline)

    def _silent_window_message(self, info: WindowInfo) -> str:
        """Say why a connected window did not answer (SHELL-05, SHELL-06)."""
        if info.build != self.state.build_id:
            return WINDOW_OLDER
        return WINDOW_SILENT

    @staticmethod
    async def _try(work: Any, failures: list[RenderFailed]) -> RenderOutcome | None:
        try:
            return await work
        except RenderFailed as error:
            failures.append(error)
            return None

    def _access(self) -> RenderAccess:
        from agent_canvas.hub.auth import cookie_name

        return RenderAccess(
            origin=f"http://127.0.0.1:{self.state.port}",
            cookie_name=cookie_name(self.state.port),
            cookie_value=self.state.credentials.cookie_value,
        )

    async def _ask_window(self, shell: Any, job: RenderJob) -> RenderOutcome:
        """Send a render request to a window and parse its answer (LOOK-03)."""
        request_id = secrets.token_hex(8)
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._waiting[request_id] = (shell, future)
        message = {
            "type": "render",
            "id": request_id,
            "url": job.url,
            "width": job.width,
            "height": job.height,
            "scheme": job.scheme,
            "section": job.section,
            "full": job.full,
            "settle_ms": int(job.settle_seconds * 1000),
            "audit": job.audit,
            "picture": job.picture,
            "answers": job.answers,
        }
        try:
            await self.state.channel.send_to(shell, message)
            answer = await asyncio.wait_for(future, self.window_timeout)
        except TimeoutError:
            raise WindowSilent(
                f"the window did not answer within {self.window_timeout:g} s"
            ) from None
        except RuntimeError as error:
            raise RenderFailed(f"the window could not be reached: {error}") from error
        finally:
            self._waiting.pop(request_id, None)
        return parse_window_answer(answer, job)


def parse_window_answer(answer: dict[str, Any], job: RenderJob) -> RenderOutcome:
    """
    Turn the shell's ``render-result`` into a :class:`RenderOutcome`.

    Parameters
    ----------
    answer : dict[str, Any]
        The message from the shell (untrusted content from a page).
    job : RenderJob
        The order it answers.

    Returns
    -------
    RenderOutcome
        The checked outcome.

    Raises
    ------
    LookError
        When the page itself is the problem (``code`` is ``section``).
    RenderFailed
        When the window failed or sent something unusable.
    """
    if answer.get("ok") is not True:
        reason = str(answer.get("error") or "the window could not render")[:300]
        if answer.get("code") == "section":
            raise LookError("failed", reason)
        raise RenderFailed(f"the window failed: {reason}")
    png = _decode_png(answer.get("png")) if job.picture else b""
    scheme = answer.get("scheme")
    return RenderOutcome(
        png=png,
        scheme=scheme if scheme in SCHEMES else job.scheme,
        errors=clean_errors(answer.get("errors")),
        audit=clean_audit(answer.get("audit")),
        notes=clean_notes(answer.get("notes")),
        source="window",
        viewer_error=clean_viewer_error(answer.get("viewer_error")),
    )


def _decode_png(value: Any) -> bytes:
    """Decode and check the PNG a window sent."""
    if not isinstance(value, str) or len(value) > MAX_SCREENSHOT_BYTES * 4 // 3 + 8:
        raise RenderFailed("the window sent no usable image")
    try:
        data = base64.b64decode(value, validate=True)
        png_size(data)
    except (binascii.Error, ValueError) as error:
        raise RenderFailed(f"the window sent an invalid image: {error}") from error
    return data


def clean_errors(value: Any) -> list[dict[str, Any]]:
    """Normalise reported page errors to the 5.7 shape (at most 50)."""
    if not isinstance(value, list):
        return []
    return [_error_record(e) for e in value[:MAX_ERRORS] if isinstance(e, dict)]


def clean_notes(value: Any) -> list[str]:
    """Keep at most 10 short strings."""
    if not isinstance(value, list):
        return []
    return [str(n)[:300] for n in value[:MAX_NOTES] if isinstance(n, str)]


def clean_viewer_error(value: Any) -> str | None:
    """Return a viewer load error reason (VIEW-14), or None for anything else."""
    return value if isinstance(value, str) and value in VIEWER_REASONS else None


def clean_audit(value: Any) -> Any:
    """Return the audit result unless it is too large to pass on."""
    try:
        too_big = len(json.dumps(value)) > MAX_AUDIT_BYTES
    except (TypeError, ValueError):
        return {"error": "the audit result is not JSON"}
    return {"error": "the audit result is too large"} if too_big else value
