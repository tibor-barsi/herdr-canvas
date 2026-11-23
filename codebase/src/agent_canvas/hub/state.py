"""In-memory hub state: credentials, sessions, page tokens, shell sockets."""

from __future__ import annotations

import asyncio
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent_canvas import __version__
from agent_canvas.hub.auth import Credentials
from agent_canvas.hub.channel import WindowChannel


@dataclass(frozen=True)
class Session:
    """
    A registered session.

    Attributes
    ----------
    session_id : str
        Session id.
    folder : pathlib.Path
        Session folder (resolved).
    page_token : str
        Capability token in the frame URL (``/s/<token>/``).
    """

    session_id: str
    folder: Path
    page_token: str


MAX_PAGE_ERRORS = 50
VIEWER_REASONS = frozenset(
    {"pdf-corrupt", "pdf-password", "image-undecodable", "image-too-large"}
)


@dataclass
class PageStatus:
    """
    What the shell reported about one page (PAGE-08, CLI-03).

    Attributes
    ----------
    loaded : bool
        True once the helper reported the page load.
    errors : list[dict[str, Any]]
        Script and block errors reported since the page was last shown.
    viewer_errors : dict[int | None, str]
        Newest viewer load error reason per page version (VIEW-14); the key
        is None for the live file.
    """

    loaded: bool = False
    errors: list[dict[str, Any]] = field(default_factory=list)
    viewer_errors: dict[int | None, str] = field(default_factory=dict)


class HubState:
    """
    Mutable state shared by the hub's routes.

    Parameters
    ----------
    port : int
        Port the hub listens on.
    key : str
        Access key.
    clock : Callable[[], float]
        Monotonic time source.
    """

    def __init__(self, port: int, key: str, clock: Callable[[], float]) -> None:
        self.port = port
        self.credentials = Credentials(key, clock)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._sessions: dict[str, Session] = {}
        self._by_token: dict[str, Session] = {}
        self.channel = WindowChannel(self._hello, lambda: self.loop)
        self.channel.register(
            "tabs", lambda initial: self.tabs_message(initial=initial), 0
        )
        self.events: Any = None  # the EventService, set by the app
        self.asks: Any = None  # the AskService, set by the app
        self.looks: Any = None  # the LookService, set by the app
        self.build_id = ""  # identity of the served shell files, set by the app
        self.active_url: str | None = None
        # The page a window launched by ``show`` opens on (SES-07), used once.
        self.open_on_connect: tuple[str, str] | None = None
        # Set by the app: build the tab dict of one session / of all visible ones
        # / of all hidden ones.
        self.tab_provider: Callable[[str], dict[str, Any]] = self.bare_tab
        self.tabs_provider: Callable[[], list[dict[str, Any]]] = list
        self.closed_provider: Callable[[], list[dict[str, Any]]] = list
        self.shutdown: Callable[[], None] | None = None  # set by the server
        self.session_listeners: list[Callable[[Session], None]] = []
        self._page_status: dict[tuple[str, str], PageStatus] = {}
        self._loaded_events: dict[tuple[str, str], asyncio.Event] = {}

    @property
    def shells(self) -> set[Any]:
        """The connected windows."""
        return self.channel.windows

    def _hello(self) -> dict[str, Any]:
        return {"type": "hello", "build": self.build_id, "version": __version__}

    def new_login_token(self) -> str:
        """Issue a login token for the owner window."""
        return self.credentials.new_login_token()

    def register_session(
        self, session_id: str, folder: Path, page_token: str | None = None
    ) -> Session:
        """
        Register a session folder and give it a page token.

        Parameters
        ----------
        session_id : str
            Session id.
        folder : pathlib.Path
            Session folder.
        page_token : str | None, optional
            Token to reuse (loaded from the registry); default is a new one.

        Returns
        -------
        Session
            The new (or existing) session record.
        """
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        session = Session(
            session_id, folder.resolve(), page_token or secrets.token_urlsafe(16)
        )
        self._sessions[session_id] = session
        self._by_token[session.page_token] = session
        for listener in self.session_listeners:
            listener(session)
        return session

    def unregister_session(self, session_id: str) -> None:
        """Forget a session and its page token (its folder was deleted)."""
        session = self._sessions.pop(session_id, None)
        if session is not None:
            self._by_token.pop(session.page_token, None)

    def sessions(self) -> list[Session]:
        """Return all registered sessions."""
        return list(self._sessions.values())

    def session_of(self, session_id: str) -> Session:
        """Return the registered session ``session_id`` (KeyError if unknown)."""
        return self._sessions[session_id]

    def session_by_token(self, token: str) -> Session | None:
        """Return the session owning ``token``, if any."""
        return self._by_token.get(token)

    def frame_url(self, session_id: str, page: str) -> str:
        """Return the frame-site URL of ``page`` in a session."""
        session = self._sessions[session_id]
        return f"http://localhost:{self.port}/s/{session.page_token}/{page}"

    def render_url(self, session_id: str, page: str) -> str:
        """Return the URL a renderer loads: a viewer page as its viewer document."""
        from agent_canvas.hub.viewers import viewer_type

        url = self.frame_url(session_id, page)
        return f"{url}?ac-view=1" if viewer_type(page) else url

    def show_page(self, session_id: str, page: str) -> None:
        """
        Make ``page`` the active page and tell connected shells.

        Safe to call from any thread.
        """
        self.active_url = self.frame_url(session_id, page)
        message = {
            "type": "show",
            "session": session_id,
            "page": page,
            "url": self.active_url,
            "tab": self.tab_provider(session_id),
        }
        self.channel.broadcast(message)

    def tabs_message(self, *, initial: bool = False) -> dict[str, Any]:
        """
        Build the ``tabs`` message: every visible and every closed session's tab.

        Parameters
        ----------
        initial : bool, optional
            True for a newly connected shell: in a window launched by ``show``
            the message then also names that page, so that the shell opens it.
        """
        shown = None
        if initial and self.open_on_connect is not None:
            session_id, page = self.open_on_connect
            shown = {"session": session_id, "page": page}
            self.open_on_connect = None
        return {
            "type": "tabs",
            "sessions": self.tabs_provider(),
            "closed": self.closed_provider(),
            "show": shown,
        }

    def bare_tab(self, session_id: str) -> dict[str, Any]:
        """Return the tab of a session that has no registry entry (tests)."""
        session = self._sessions[session_id]
        return {
            "id": session_id,
            "project": "",
            "agent": "agent",
            "title": session_id[:8],
            "owner_title": None,
            "state": "active",
            "pages": [],
            "active_page": None,
            "base": self.frame_url(session.session_id, ""),
        }

    # ---- page reports from the shell -----------------------------------------

    def page_status(self, session_id: str, page: str) -> PageStatus:
        """Return the (possibly empty) report status of a page."""
        return self._page_status.setdefault((session_id, page), PageStatus())

    def reset_page_status(self, session_id: str, page: str) -> None:
        """Forget load and error reports before a page is shown again."""
        key = (session_id, page)
        self._page_status[key] = PageStatus()
        self._loaded_events[key] = asyncio.Event()

    def record_page_report(self, url: str, name: str, data: Any) -> None:
        """
        Store a report the shell relayed for the page at ``url``.

        Parameters
        ----------
        url : str
            Frame URL of the page; anything not matching a session is ignored.
        name : str
            ``loaded``, ``error``, ``clear-errors`` or ``viewer-error``; other
            names are ignored.
        data : Any
            Report payload (an error object for ``error``).
        """
        key = self.page_of_url(url)
        if key is None:
            return
        status = self.page_status(*key)
        if name == "loaded":
            status.loaded = True
            if (event := self._loaded_events.get(key)) is not None:
                event.set()
        elif name == "clear-errors":
            status.errors.clear()
        elif name == "error" and isinstance(data, dict):
            if len(status.errors) < MAX_PAGE_ERRORS:
                status.errors.append(_error_record(data))
        elif name == "viewer-error" and isinstance(data, dict):
            reason, version = data.get("reason"), data.get("version")
            if reason in VIEWER_REASONS and (version is None or type(version) is int):
                status.viewer_errors[version] = reason
                print(
                    f"agent-canvas: {key[1]} could not be shown: {reason}"
                    f" (version {version})",
                    file=sys.stderr,
                )

    async def wait_loaded(self, session_id: str, page: str, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for the page's load report."""
        key = (session_id, page)
        event = self._loaded_events.setdefault(key, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return False
        return True

    def page_of_url(self, url: str) -> tuple[str, str] | None:
        """Map a frame URL to ``(session id, page name)``, or None."""
        parts = urlparse(url).path.split("/")
        if len(parts) != 4 or parts[0] != "" or parts[1] != "s":
            return None
        session = self._by_token.get(parts[2])
        return None if session is None else (session.session_id, parts[3])


def _error_record(data: dict[str, Any]) -> dict[str, Any]:
    """Normalise an error report to the 5.7 shape."""
    line = data.get("line")
    canvas_id = data.get("canvas_id")
    return {
        "source": str(data.get("source", "script"))[:20],
        "message": str(data.get("message", ""))[:500],
        "line": line if isinstance(line, int) else None,
        "canvas_id": canvas_id if isinstance(canvas_id, str) else None,
    }
