"""Session registry: ``sessions.json``, ``session.json`` and ``.gitignore``.

``sessions.json`` in the state directory maps each session id to its project
and page token (requirements 5.1, HUB-04). Everything else about a session
lives in ``<project>/<project_dir_name>/<id>/session.json`` (5.2, SES-01), which is
read from disk on each access so that the file stays the single source of truth.
"""

from __future__ import annotations

import difflib
import hashlib
import html
import itertools
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Container, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_canvas.config import DEFAULT_PROJECT_DIR_NAME
from agent_canvas.drafts import (
    DraftError,
    is_draft_name,
    publish_draft,
    published_name_for,
)
from agent_canvas.files_safe import write_safely
from agent_canvas.hub import clock
from agent_canvas.hub.lifetime import (
    ARCHIVE_DAYS,
    DAY_SECONDS,
    DEFAULT_KIND,
    KINDS,
    due_reminders,
    expiry,
    is_expired,
)
from agent_canvas.hub.state import HubState
from agent_canvas.paths import make_private_dirs
from agent_canvas.paths_safe import (
    InvalidSessionId,
    UnsafePathError,
    resolve_page,
    validate_page_name,
    validate_page_type,
    validate_project,
    validate_session_id,
)

SESSION_SCHEMA = "agent-canvas/session@1"
DEFAULT_PAGE = "page.html"
TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TITLE_SCAN_BYTES = 64 * 1024
MAX_TITLE_CHARS = 80
KIND_TAG = re.compile(
    r"<meta\s+(?:name=[\"']agent-canvas-kind[\"']\s+content=[\"']([^\"']*)[\"']"
    r"|content=[\"']([^\"']*)[\"']\s+name=[\"']agent-canvas-kind[\"'])",
    re.IGNORECASE,
)
# A reserved id (SessionStart hook) that was never used is forgotten after this.
RESERVED_MAX_AGE_SECONDS = 7 * 24 * 3600
# A project's pages live in one folder of this name (PROJ-01).
PROJECT_FOLDER = "project"
PROJECT_PREFIX = "project-"
# Keys the hub reads without a fallback; a file lacking one counts as unreadable.
CORE_KEYS = ("agent", "state", "hidden", "pages", "active_page", "created", "updated")

logger = logging.getLogger(__name__)


class RegistryError(Exception):
    """
    A registry operation failed.

    Parameters
    ----------
    code : str
        CLI error code: ``failed`` or ``no-session``.
    message : str
        Human-readable text.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SessionMeta:
    """
    One session as the readers see it: the cleaned ``session.json`` content.

    Attributes
    ----------
    id, project, agent, state, created, updated : str
        Identity and clock stamps; ``id`` and ``project`` come from the registry
        entry, not from the file.
    hidden : bool
        Whether the session is off the tab strip.
    pages : tuple[str, ...]
        Page names in order.
    active_page : str | None
        The page shown first.
    title, owner_title : str | None
        The agent's and the owner's title.
    page_meta : Mapping[str, Mapping[str, Any]]
        The lifetime entry of each page.
    open_asks : tuple[dict[str, Any], ...]
        The stored open question cards.
    result : dict[str, Any] | None
        The result card.
    raw : Mapping[str, Any]
        The whole cleaned file content, for helpers that take the dict; read only.
    """

    id: str
    project: str
    agent: str
    state: str
    hidden: bool
    pages: tuple[str, ...]
    active_page: str | None
    created: str
    updated: str
    title: str | None
    owner_title: str | None
    page_meta: Mapping[str, Mapping[str, Any]]
    open_asks: tuple[dict[str, Any], ...]
    result: dict[str, Any] | None
    raw: Mapping[str, Any]

    @classmethod
    def from_dict(cls, meta: Mapping[str, Any]) -> SessionMeta:
        """Build the typed view of a cleaned ``session.json`` dict."""
        return cls(
            id=meta["id"],
            project=meta["project"],
            agent=meta["agent"],
            state=meta["state"],
            hidden=meta["hidden"],
            pages=tuple(meta["pages"]),
            active_page=meta["active_page"],
            created=meta["created"],
            updated=meta["updated"],
            title=meta.get("title"),
            owner_title=meta.get("owner_title"),
            page_meta=meta.get("page_meta", {}),
            open_asks=tuple(meta.get("open_asks", ())),
            result=meta.get("result"),
            raw=meta,
        )


def now_iso() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    stamp = datetime.now(UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"


def git_top_folder(folder: str) -> str:
    """Return the nearest folder from ``folder`` up with ``.git``, else ``folder``."""
    start = Path(folder)
    try:
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                return str(candidate)
    except (OSError, ValueError):  # unreadable or malformed path: event content
        pass
    return folder


def project_session_id(project_key: str) -> str:
    """Return the id of a project's pages: ``project-`` and 16 hex of SHA-256."""
    return PROJECT_PREFIX + hashlib.sha256(project_key.encode()).hexdigest()[:16]


def is_project_id(session_id: str) -> bool:
    """Tell whether an id is reserved for project pages (PROJ-05)."""
    lowered = session_id.lower()
    return lowered == PROJECT_FOLDER or lowered.startswith(PROJECT_PREFIX)


def _write_json_atomic(path: Path, data: Any, mode: int = 0o644) -> None:
    """Write ``data`` as JSON via a temporary file and an atomic rename."""
    write_safely(path, json.dumps(data, indent=2) + "\n", mode)


class SessionRegistry:
    """
    Create, find and update sessions and keep ``sessions.json`` current.

    Parameters
    ----------
    state_dir : pathlib.Path
        State directory holding ``sessions.json``.
    hub_state : HubState
        In-memory hub state that serves the page files.
    project_dir_name : str, optional
        Session folder below the project root (config ``project_dir_name``,
        already validated by the config loader). Default ``.agent-canvas``.
    """

    def __init__(
        self,
        state_dir: Path,
        hub_state: HubState,
        project_dir_name: str = DEFAULT_PROJECT_DIR_NAME,
    ) -> None:
        self._subdir = Path(project_dir_name)
        self._file = state_dir / "sessions.json"
        self._hub = hub_state
        self._index: dict[str, dict[str, str]] = {}
        self._lacking: set[str] = set()
        self._malformed: set[tuple[str, str]] = set()
        self.follow_file: Path | None = None
        self._followed_mtime = 0

    def follow(self) -> bool:
        """
        Take over sessions of ``follow_file`` (another hub's list), read-only.

        Adds the sessions not known yet and takes over changed entries. Nothing
        is removed and the followed file is never written.

        Returns
        -------
        bool
            True when the followed file changed since the last call.
        """
        if self.follow_file is None:
            return False
        try:
            mtime = self.follow_file.stat().st_mtime_ns
            if mtime == self._followed_mtime:
                return False
            entries = json.loads(self.follow_file.read_text())
        except (OSError, json.JSONDecodeError):
            return False  # half-written or gone: try again at the next change
        self._followed_mtime = mtime
        changed = False
        for session_id, entry in entries.items():
            folder = self._folder(session_id, entry.get("project", ""))
            if "reserved" in entry or self._index.get(session_id) == entry:
                continue
            if not (folder / "session.json").is_file():
                continue
            self._index[session_id] = entry
            self._hub.register_session(session_id, folder, entry["page_token"])
            changed = True
        if changed:
            self._save_index()
        return True

    def load(self, keep: Callable[[str], bool] | None = None) -> None:
        """
        Read ``sessions.json`` and register every session with the hub (HUB-04).

        Entries whose ``session.json`` has vanished are skipped with a warning.
        ``keep`` names the ids whose reservation is never pruned (SES-10).

        Raises
        ------
        RegistryError
            If ``sessions.json`` is not a JSON object (the message names it).
        """
        if not self._file.exists():
            return
        try:
            entries = json.loads(self._file.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RegistryError(
                "failed", f"Cannot read {self._file}: {error}"
            ) from error
        if not isinstance(entries, dict):
            raise RegistryError("failed", f"{self._file} must hold a JSON object")
        for session_id, entry in entries.items():
            if "reserved" in entry:
                self._index[session_id] = entry
                continue
            folder = self._folder(session_id, entry["project"])
            if not (folder / "session.json").is_file():
                print(
                    f"agent-canvas: skipping session {session_id}: "
                    f"{folder / 'session.json'} is missing",
                    file=sys.stderr,
                )
                continue
            self._index[session_id] = entry
            self._hub.register_session(session_id, folder, entry["page_token"])
        for session_id in [s for s, e in self._index.items() if "reserved" in e]:
            self._meta(session_id)  # a synced folder makes it a real session
        self.prune_reserved(RESERVED_MAX_AGE_SECONDS, keep=keep)

    # ---- lookup -----------------------------------------------------------

    def get(self, session_id: str) -> SessionMeta | None:
        """Return a known session as :class:`SessionMeta`, else None."""
        meta = self._meta(session_id)
        return None if meta is None else SessionMeta.from_dict(meta)

    def _meta(self, session_id: str) -> dict[str, Any] | None:
        """Return the ``session.json`` content of a known session, else None."""
        entry = self._index.get(session_id)
        if entry is None:
            return None
        path = self._folder(session_id, entry["project"]) / "session.json"
        try:
            meta = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(meta, dict):
            return None
        if not all(key in meta for key in CORE_KEYS):
            if session_id not in self._lacking:
                self._lacking.add(session_id)
                logger.warning("session.json of %s lacks keys; skipped", session_id)
            return None
        if "reserved" in entry:
            self._adopt(session_id, entry["project"])
        # The agent can write in this folder; the registry entry is the truth
        # for who and where this session is (review finding L5).
        return {
            **self._clean_shape(session_id, meta),
            "id": session_id,
            "project": entry["project"],
        }

    def _adopt(self, session_id: str, project: str) -> None:
        """Turn a reserved id whose session folder exists into a real session."""
        session = self._hub.register_session(
            session_id, self._folder(session_id, project)
        )
        self._index[session_id] = {"project": project, "page_token": session.page_token}
        self._save_index()

    def _clean_shape(self, session_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        """Give ``pages`` and ``page_meta`` the shape the readers expect (LIFE-08)."""
        pages, entries = meta["pages"], meta.get("page_meta", {})
        if not (isinstance(pages, list) and all(isinstance(n, str) for n in pages)):
            self._log_malformed(session_id, "pages")
            pages = []
        if not isinstance(entries, dict):
            self._log_malformed(session_id, "page_meta")
            entries = {}
        if (
            pages is meta["pages"]
            and entries is meta.get("page_meta")
            and all(
                isinstance(e, dict) and _ENTRY_KEYS <= e.keys()
                for e in entries.values()
            )
        ):
            return meta
        entries = {
            n: e
            if _ENTRY_KEYS <= e.keys()
            else {**_new_entry(DEFAULT_KIND, "default"), **e}
            for n, e in entries.items()
            if isinstance(e, dict)
        }
        return {**meta, "pages": pages, "page_meta": entries}

    def _log_malformed(self, session_id: str, key: str) -> None:
        if (session_id, key) not in self._malformed:
            self._malformed.add((session_id, key))
            logger.warning("session.json of %s: malformed %s; ignored", session_id, key)

    def is_reserved(self, session_id: str) -> bool:
        """Return True for an id the hook reserved and nothing has used yet."""
        return "reserved" in self._index.get(session_id, {})

    def promote(self, session_id: str) -> dict[str, Any] | None:
        """
        Turn a reserved id into a real session; None if it is not reserved.

        Used by commands that mean to use the canvas but carry no project
        (``watch``, ``wait_for_feedback``).
        """
        if not self.is_reserved(session_id):
            return None
        entry = self._index[session_id]
        return self.create(session_id, entry["project"], entry["agent"], None)

    def folder_of(self, meta: SessionMeta | dict[str, Any]) -> Path:
        """Return the (resolved) session folder of ``meta``."""
        if isinstance(meta, SessionMeta):
            return self._folder(meta.id, meta.project)
        return self._folder(meta["id"], meta["project"])

    def list(self, include_all: bool, project: str | None) -> list[dict[str, Any]]:
        """
        List sessions, oldest first.

        Parameters
        ----------
        include_all : bool
            Include ended and hidden sessions.
        project : str | None
            Only sessions of this project directory.

        Returns
        -------
        list[dict[str, Any]]
            ``session.json`` contents.
        """
        wanted = str(Path(project).resolve()) if project else None
        metas = [m for sid in self._index if (m := self._meta(sid)) is not None]
        metas = [m for m in metas if wanted is None or m["project"] == wanted]
        if not include_all:
            metas = [
                m for m in metas if m.get("state") == "active" and not m.get("hidden")
            ]
        return sorted(metas, key=lambda m: str(m.get("created", "")))

    def effective_title(self, meta: dict[str, Any]) -> str:
        """
        Return the title a tab shows (SES-06).

        The owner's name wins over the agent's title; without either, the
        ``<title>`` of the active page, else the first 8 characters of the id.
        """
        for candidate in (meta.get("owner_title"), meta.get("title")):
            if candidate:
                return str(candidate)
        page = meta.get("active_page")
        if (
            page
            and page.lower().endswith(".html")
            and (found := _page_title(self.folder_of(meta) / page))
        ):
            return found
        return meta["id"][:8]

    def tab_of(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Return the tab description the shell needs for session ``meta``."""
        entries = meta.get("page_meta", {})
        live = live_pages(meta)
        starred = [n for n in live if (entries.get(n) or {}).get("starred")]
        return {
            "id": meta["id"],
            "project": meta["project"],
            "agent": meta["agent"],
            "title": self.effective_title(meta),
            "owner_title": meta.get("owner_title"),
            "state": meta["state"],
            "pages": starred + [n for n in live if n not in starred],
            "starred": starred,
            "active_page": meta["active_page"],
            "base": self._hub.frame_url(meta["id"], ""),
        }

    def tabs(self, shown: Container[str] = ()) -> list[dict[str, Any]]:
        """
        Return the tabs of all visible (not hidden) sessions, oldest first.

        Parameters
        ----------
        shown : Container[str], optional
            Hidden sessions that get a tab all the same.
        """
        return self._tabs_of(
            m for m in self.list(True, None) if not m["hidden"] or m["id"] in shown
        )

    def closed_tabs(self) -> list[dict[str, Any]]:
        """Return the tabs of all hidden (closed) sessions, newest first (SES-12)."""
        metas = reversed(self.list(True, None))
        return self._tabs_of(m for m in metas if m["hidden"])

    def _tabs_of(self, metas: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build tabs, skipping (and logging once) a session the hub cannot serve."""
        tabs = []
        for meta in metas:
            try:
                tabs.append(self.tab_of(meta))
            except KeyError:
                if (meta["id"], "tab") not in self._malformed:
                    self._malformed.add((meta["id"], "tab"))
                    logger.warning("session %s is not registered; no tab", meta["id"])
        return tabs

    # ---- creation ---------------------------------------------------------

    def start(self, project: str, agent: str, title: str | None) -> dict[str, Any]:
        """Create a session with a fresh UUID4 id (SES-04)."""
        return self.create(str(uuid.uuid4()), project, agent, title)

    def create(
        self, session_id: str, project: str, agent: str, title: str | None
    ) -> dict[str, Any]:
        """
        Create a session folder, its ``session.json`` and the registry entry.

        Parameters
        ----------
        session_id : str
            Valid session id not yet registered.
        project : str
            Absolute project directory.
        agent : str
            Agent name.
        title : str | None
            Initial title.

        Returns
        -------
        dict[str, Any]
            The new ``session.json`` content.

        Raises
        ------
        RegistryError
            ``no-session`` for a malformed id, ``failed`` for an unusable project.
        """
        self._refuse_project_id(session_id)
        return self._create(session_id, project, agent, title)

    def _create(
        self, session_id: str, project: str, agent: str, title: str | None
    ) -> dict[str, Any]:
        project_dir = self._check(session_id, project)
        folder = self._folder(session_id, str(project_dir))
        make_private_dirs(folder)
        _ensure_gitignore(folder.parent)
        adopted = self._read_existing(folder)
        if adopted is not None:  # never trust the id and project it names
            adopted = {**adopted, "id": session_id, "project": str(project_dir)}
        meta = adopted or {
            "schema": SESSION_SCHEMA,
            "id": session_id,
            "agent": agent,
            "title": title,
            "owner_title": None,
            "project": str(project_dir),
            "state": "active",
            "hidden": False,
            "pages": [],
            "active_page": None,
            "created": (stamp := now_iso()),
            "updated": stamp,
            "open_asks": [],
        }
        self._write_meta(meta)
        session = self._hub.register_session(session_id, folder)
        self._index[session_id] = {
            "project": str(project_dir),
            "page_token": session.page_token,
        }
        self._save_index()
        return meta

    def project_session(self, project_key: str) -> dict[str, Any]:
        """
        Return the pages session of a project, creating it if needed (PROJ-01).

        Parameters
        ----------
        project_key : str
            The project key: the git top folder of the caller's project.

        Returns
        -------
        dict[str, Any]
            Its ``session.json`` content (agent ``project``).
        """
        folder = Path(project_key) / self._subdir / PROJECT_FOLDER
        if folder.is_symlink():
            raise RegistryError("failed", f"{folder} is a symlink; refused.")
        meta = self._meta(project_session_id(project_key))
        if meta is not None:
            return meta
        return self._create(
            project_session_id(project_key), project_key, "project", "Project pages"
        )

    def project_of(self, session_id: str) -> str | None:
        """Return the project directory of a known (real or reserved) session."""
        entry = self._index.get(session_id)
        return None if entry is None else entry["project"]

    def updater(self, session_id: str) -> dict[str, Any] | None:
        """Describe a known (real or reserved) session as ``updated_by``, now."""
        entry = self._index.get(session_id)
        if entry is None:
            return None
        meta = self._meta(session_id)
        return {
            "session": session_id,
            "title": self.effective_title(meta) if meta else None,
            "agent": (meta or entry)["agent"],
            "time": now_iso(),
        }

    def reserve(self, session_id: str, project: str, agent: str) -> bool:
        """
        Reserve an id without creating folder, tab or watcher (SES-10).

        The SessionStart hook reserves the id of every agent session; the
        session becomes real on first use (:meth:`ensure`). A session that
        exists already is left alone.

        Parameters
        ----------
        session_id : str
            Valid session id.
        project : str
            Absolute project directory (the agent's working directory).
        agent : str
            Agent name.

        Returns
        -------
        bool
            True if the id was newly reserved.

        Raises
        ------
        RegistryError
            ``no-session`` for a malformed id, ``failed`` for an unusable project.
        """
        self._refuse_project_id(session_id)
        project_dir = self._check(session_id, project)
        if session_id in self._index:
            return False
        self._index[session_id] = {
            "project": str(project_dir),
            "agent": agent,
            "reserved": now_iso(),
        }
        self._save_index()
        self._meta(session_id)  # a synced folder makes it a real session
        return True

    def prune_reserved(
        self,
        max_age_seconds: float,
        now: float | None = None,
        keep: Callable[[str], bool] | None = None,
    ) -> int:
        """
        Forget reserved ids older than ``max_age_seconds`` (SES-10).

        Parameters
        ----------
        max_age_seconds : float
            Age limit in seconds.
        now : float | None, optional
            Current POSIX time; default is the clock.
        keep : Callable[[str], bool] | None, optional
            True for an id that stays whatever its age (a running session).

        Returns
        -------
        int
            Number of ids forgotten.
        """
        cutoff = (time.time() if now is None else now) - max_age_seconds
        stale = [
            sid
            for sid, entry in self._index.items()
            if "reserved" in entry
            and _stamp_seconds(entry["reserved"]) < cutoff
            and not (keep and keep(sid))
        ]
        for session_id in stale:
            del self._index[session_id]
        if stale:
            self._save_index()
        return len(stale)

    def ensure(
        self, session_id: str, project: str, agent: str
    ) -> tuple[dict[str, Any], bool]:
        """
        Return a known session unchanged, or create it (SES-03).

        A reserved id is created here; without ``project`` it keeps the
        reserved one.

        Returns
        -------
        tuple[dict[str, Any], bool]
            The session and whether it was just created. A known session keeps
            its recorded project and its folder is recreated if it vanished.
        """
        meta = self._meta(validate_or_raise(session_id))
        if meta is None:
            if not project and self.is_reserved(session_id):
                project = self._index[session_id]["project"]
            return self.create(session_id, project, agent, None), True
        make_private_dirs(self.folder_of(meta))
        return meta, False

    # ---- updates ------------------------------------------------------------

    def set_title(self, session_id: str, title: str) -> dict[str, Any]:
        """Set the agent title of a known session."""
        self._refuse_project_id(session_id)
        return self._update(session_id, title=title)

    def end(self, session_id: str) -> dict[str, Any]:
        """Mark a known session ``ended`` (the hub dismisses its asks, CLI-14)."""
        self._refuse_project_id(session_id)
        return self._update(session_id, state="ended")

    def resume(self, session_id: str) -> bool:
        """Make an ended session ``active`` again; True if it was ended (SES-08)."""
        meta = self._meta(session_id)
        if meta is None or meta["state"] != "ended":
            return False
        self._update(session_id, state="active")
        return True

    def set_open_asks(
        self, session_id: str, asks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Replace the ``open_asks`` list of a known session (5.2)."""
        return self._update(session_id, open_asks=asks)

    def set_result(
        self, session_id: str, result: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Replace the ``result`` card of a known session (5.2)."""
        return self._update(session_id, result=result)

    def rename(self, session_id: str, title: str) -> dict[str, Any]:
        """Set the owner's name of a session; an empty name clears it (SES-06)."""
        return self._update(session_id, owner_title=title.strip() or None)

    def set_hidden(
        self, session_id: str, hidden: bool, touch: bool = True
    ) -> dict[str, Any]:
        """Hide or unhide a known session; ``touch=False`` keeps its ``updated`` time."""
        if touch:
            return self._update(session_id, hidden=hidden)
        meta = {**self._require(session_id), "hidden": hidden}
        self._write_meta(meta)
        return meta

    def show(
        self,
        session_id: str,
        name: str | None,
        title: str | None,
        copy_from: str | None,
        publish: bool = False,
    ) -> tuple[dict[str, Any], str, Path]:
        """
        Register a page of a known session as active and tell the shells.

        Parameters
        ----------
        session_id : str
            A known session.
        name : str | None
            Page name or absolute path inside the folder; default ``page.html``.
        title : str | None
            New agent title.
        copy_from : str | None
            External file to copy into the folder under its base name first.
        publish : bool, optional
            Replace the page by its draft ``NAME.draft.html`` first (DRAFT-03).

        Returns
        -------
        tuple[dict[str, Any], str, pathlib.Path]
            Updated session, page name and page path.

        Raises
        ------
        RegistryError
            ``failed`` if the page is missing, unsafe or the copy fails, if
            the name is a draft and ``publish`` is not given, or if there is
            no draft to publish; ``no-session`` for an unknown session.
        """
        meta = self._require(session_id)
        folder = self.folder_of(meta)
        try:
            if copy_from is not None:
                # Refuse a bad type or a stem clash before anything is copied.
                self._check_page(meta, folder, Path(copy_from).name)
                name = self._copy_into(folder, copy_from)
            name = name or DEFAULT_PAGE
            if not Path(name).suffix:
                name += ".html"
            if publish:
                name = published_name_for(name)
            page, path = resolve_page(folder, name)
            if is_draft_name(page):
                raise RegistryError(
                    "failed",
                    f"{page} is a private draft and is never shown. Publish it "
                    f"with `show {published_name_for(page)} --publish`, or look "
                    f"at it with `look {published_name_for(page)} --draft`.",
                )
            if publish:
                publish_draft(folder, page)
            self._check_page(meta, folder, page)
        except (UnsafePathError, DraftError) as error:
            raise RegistryError("failed", str(error)) from error
        if not path.is_file():
            raise RegistryError(
                "failed",
                f"Page {page} not found in session folder {folder}."
                + _closest_page(folder, page),
            )
        pages = meta["pages"] if page in meta["pages"] else [*meta["pages"], page]
        fields: dict[str, Any] = {"pages": pages, "active_page": page, "hidden": False}
        if title:
            fields["title"] = title
        meta = self._update(session_id, **fields)
        self.note_page(session_id, page)
        self.restore(session_id, page)
        self._hub.show_page(session_id, page)
        return meta, page, path

    def note_updater(self, session_id: str, name: str, who: dict[str, Any]) -> None:
        """Record who updated a project page last: session, title, agent, time."""
        meta = self._require(session_id)
        self._store_entry(meta, name, {**self._entry(meta, name), "updated_by": who})

    def note_pages(self, session_id: str) -> None:
        """Give every page of a session its ``page_meta`` entry (LIFE-03)."""
        meta = self._require(session_id)
        folder = self.folder_of(meta)
        before = meta.get("page_meta", {})
        kind = _default_kind(session_id)
        entries = {
            n: self._noted(folder, n, before.get(n), kind) for n in meta["pages"]
        }
        entries = {**before, **entries}
        if entries != before:
            self._write_meta({**meta, "page_meta": entries})

    def note_page(self, session_id: str, name: str) -> None:
        """Give one page its ``page_meta`` entry, or refresh its meta-tag kind."""
        meta = self._meta(session_id)  # the watcher also sees sessions not registered
        if meta is not None and name in meta["pages"]:
            self._store_entry(meta, name, self._entry(meta, name))

    def set_kind(
        self, session_id: str, name: str, kind: str, by: str = "agent"
    ) -> dict[str, str]:
        """
        Set the kind of a page; the owner's choice wins over an agent's (LIFE-01).

        Parameters
        ----------
        session_id : str
            A known session.
        name : str
            A page of the session.
        kind : str
            One of the kinds.
        by : str, optional
            ``agent`` or ``owner``.

        Returns
        -------
        dict[str, str]
            ``page``, ``kind`` and ``set_by`` as they are now.

        Raises
        ------
        RegistryError
            ``usage`` for an unknown kind, ``failed`` for a page not in the session.
        """
        if kind not in KINDS:
            raise RegistryError(
                "usage", f"Unknown kind {kind!r}; use one of {', '.join(KINDS)}."
            )
        meta = self._require(session_id)
        if name not in meta["pages"]:
            raise RegistryError("failed", f"{name} is not a page of this session.")
        entry = self._entry(meta, name)
        if not (entry["set_by"] == "owner" and by == "agent"):
            entry = {**entry, "kind": kind, "set_by": by}
        self._store_entry(meta, name, entry)
        return {"page": name, "kind": entry["kind"], "set_by": entry["set_by"]}

    def archive(
        self, session_id: str, name: str, by: str = "agent"
    ) -> dict[str, str | None]:
        """
        Take a page off its tab and the home page; its files stay (LIFE-04).

        An archived page that was active gives way to the newest other page of
        the session, or to none. Archiving twice keeps the first time.

        Returns
        -------
        dict[str, str | None]
            ``page``, ``archived`` and ``deleted_after`` (30 days later, LIFE-08).

        Raises
        ------
        RegistryError
            ``failed`` for a page not in the session or, when ``by`` is ``agent``,
            a starred page (STAR-04),
            ``no-session`` for an unknown session.
        """
        meta = self._require(session_id)
        entry = self._known_entry(meta, name)
        if entry.get("starred") and by == "agent":
            raise RegistryError(
                "failed", f"{name} is starred; only the owner can unstar it first."
            )
        if entry["archived"] is None:
            entry = {**entry, "archived": clock.iso(clock.now())}
        entries = {**meta.get("page_meta", {}), name: entry}
        pages = live_pages({**meta, "page_meta": entries})
        active = meta["active_page"]
        if active not in pages:
            active = pages[-1] if pages else None
        self._write_meta({**meta, "page_meta": entries, "active_page": active})
        deadline = clock.seconds_of(entry["archived"]) + ARCHIVE_DAYS * DAY_SECONDS
        return {
            "page": name,
            "archived": entry["archived"],
            "deleted_after": clock.iso(deadline),
        }

    def restore(self, session_id: str, name: str) -> bool:
        """
        Bring an archived page back to its tab; True when it was archived (LIFE-04).

        A session with no active page takes the restored page as its active one;
        a session the registry does not know has nothing to restore.
        """
        meta = self._meta(session_id)
        entry = (meta or {}).get("page_meta", {}).get(name)
        if entry is None or entry["archived"] is None:
            return False
        entries = {**meta["page_meta"], name: {**entry, "archived": None}}
        active = meta["active_page"] or name
        self._write_meta({**meta, "page_meta": entries, "active_page": active})
        return True

    def restore_page(self, session_id: str, name: str) -> dict[str, None]:
        """Restore a page for the ``restore`` action; ``archived`` is null after it."""
        self._known_entry(self._require(session_id), name)
        self.restore(session_id, name)
        return {"page": name, "archived": None}

    def drop_pages(self, session_id: str, names: list[str]) -> None:
        """
        Remove pages and their ``page_meta`` from a session (LIFE-08).

        Only ``session.json`` changes; ``updated`` stays as it is and the active
        page moves to the newest page left when it was one of the dropped.
        """
        meta = self._require(session_id)
        entries = {n: e for n, e in meta.get("page_meta", {}).items() if n not in names}
        pages = [n for n in meta["pages"] if n not in names]
        left = live_pages({**meta, "pages": pages, "page_meta": entries})
        active = meta["active_page"]
        if active not in left:
            active = left[-1] if left else None
        self._write_meta(
            {**meta, "pages": pages, "page_meta": entries, "active_page": active}
        )

    def set_star(self, session_id: str, name: str, starred: bool) -> dict[str, Any]:
        """Set or clear the owner's star of a page (STAR-01); the owner's route only."""
        meta = self._require(session_id)
        entry = {**self._known_entry(meta, name), "starred": starred}
        self._store_entry(meta, name, entry)
        return {"page": name, "starred": starred}

    def extend(self, session_id: str, name: str) -> dict[str, str | None]:
        """Set ``extended`` of a page to now; answer its new expiry (LIFE-05)."""
        meta = self._require(session_id)
        entry = {**self._known_entry(meta, name), "extended": clock.iso(clock.now())}
        self._store_entry(meta, name, entry)
        when = expiry(entry, self._changed(meta, name))
        return {"page": name, "expires": None if when is None else clock.iso(when)}

    def page_list(
        self, session_id: str, archived: bool = False
    ) -> list[dict[str, Any]]:
        """Return the page rows of ``page list``; archived pages only on request."""
        meta = self._require(session_id)
        rows = [{"name": n, **self.page_info(meta, n)} for n in meta["pages"]]
        return [r for r in rows if archived or r["archived"] is None]

    def reminders(self, session_id: str, stamp: bool) -> list[dict[str, str]]:
        """Return the reminders due now, and stamp ``reminded`` on them if ``stamp``."""
        meta = self._require(session_id)
        now = clock.now()
        pages = [
            (n, self._entry(meta, n), self._changed(meta, n)) for n in meta["pages"]
        ]
        due = due_reminders(pages, now)
        if stamp and due:
            named = {r["page"] for r in due}
            entries = {
                n: {**e, "reminded": clock.iso(now)} if n in named else e
                for n, e, _ in pages
            }
            self._write_meta(
                {**meta, "page_meta": {**meta.get("page_meta", {}), **entries}}
            )
        return due

    def page_info(self, meta: dict[str, Any], name: str) -> dict[str, Any]:
        """
        Return kind, ``set_by``, expiry, expired and archive time of a page.

        Nothing is written: a page without an entry yet counts from now.
        """
        entry = self._entry(meta, name)
        changed = self._changed(meta, name)
        when = expiry(entry, changed)
        return {
            "kind": entry["kind"],
            "set_by": entry["set_by"],
            "expires": None if when is None else clock.iso(when),
            "expired": is_expired(entry, changed, clock.now()),
            "archived": entry["archived"],
            "starred": bool(entry.get("starred")),
            **({"updated_by": entry["updated_by"]} if "updated_by" in entry else {}),
        }

    def note_answered(self, session_id: str, name: str, stamp: str) -> None:
        """Record the time of the newest event of a page (5.2 ``answered``)."""
        meta = self._meta(session_id)
        if meta is not None and name in meta["pages"]:
            entry = {**self._entry(meta, name), "answered": stamp}
            self._store_entry(meta, name, entry)

    def note_seen(self, session_id: str, name: str, version: int) -> bool:
        """
        Record that the owner saw a version of a page (NEW-01).

        Only a newer version than the recorded one is kept; the stamp is the
        real time, like the other stamps of what happened (A-250).

        Returns
        -------
        bool
            True when ``seen_version`` and ``seen_at`` were written.
        """
        meta = self._meta(session_id)
        if meta is None or name not in meta["pages"]:
            return False
        entry = self._entry(meta, name)
        if (entry.get("seen_version") or 0) >= version:
            return False
        stamp = clock.iso(time.time())
        entry = {**entry, "seen_version": version, "seen_at": stamp}
        self._store_entry(meta, name, entry)
        return True

    def store_upload(self, session_id: str, name: str, source: Path) -> str:
        """
        Move an uploaded file into a session folder under a free page name.

        A name in use, or one whose stem another page has, gets ``-2``, ``-3``
        before the extension (VIEW-09, VIEW-11). The file is not yet a page.

        Parameters
        ----------
        session_id : str
            A known session.
        name : str
            Validated page name of the upload.
        source : pathlib.Path
            The finished temporary file; it is removed.

        Returns
        -------
        str
            The page name the file now has.

        Raises
        ------
        RegistryError
            ``failed`` if the name is not of a type a page can have.
        """
        meta = self._require(session_id)
        folder = self.folder_of(meta)
        make_private_dirs(folder)
        path = Path(name)
        try:
            validate_page_type(name)
            for number in itertools.count(1):
                candidate = (
                    name if number == 1 else f"{path.stem}-{number}{path.suffix}"
                )
                try:
                    self._check_page(meta, folder, candidate)
                    os.link(source, folder / candidate)  # refuses a name in use
                except (UnsafePathError, FileExistsError):
                    continue
                return candidate
        except UnsafePathError as error:
            raise RegistryError("failed", str(error)) from error
        finally:
            source.unlink(missing_ok=True)

    def forget(self, session_id: str) -> None:
        """Drop a session from ``sessions.json``; its files are left alone."""
        if self._index.pop(session_id, None) is not None:
            self._save_index()

    # ---- internals ---------------------------------------------------------

    def _folder(self, session_id: str, project: str) -> Path:
        name = PROJECT_FOLDER if session_id.startswith(PROJECT_PREFIX) else session_id
        return Path(project) / self._subdir / name

    @staticmethod
    def _refuse_project_id(session_id: str) -> None:
        """Refuse what no caller may do with the id of project pages (PROJ-05)."""
        if is_project_id(session_id):
            raise RegistryError(
                "no-session", f"{session_id} is reserved for the project pages."
            )

    @staticmethod
    def _check(session_id: str, project: str) -> Path:
        """Validate id and project; map problems to ``RegistryError``."""
        validate_or_raise(session_id)
        try:
            return validate_project(project, Path.home())
        except UnsafePathError as error:
            raise RegistryError("failed", str(error)) from error

    def _known_entry(self, meta: dict[str, Any], name: str) -> dict[str, Any]:
        """Return the page's entry; the page must be one of the session."""
        if name not in meta["pages"]:
            raise RegistryError("failed", f"{name} is not a page of this session.")
        return self._entry(meta, name)

    def _changed(self, meta: dict[str, Any], name: str) -> float:
        """Return the time of the page file's newest version (0 if it is gone)."""
        try:
            return (self.folder_of(meta) / name).stat().st_mtime
        except OSError:
            return 0.0

    def _entry(self, meta: dict[str, Any], name: str) -> dict[str, Any]:
        """Return the page's ``page_meta`` entry, made or kept current."""
        folder = self.folder_of(meta)
        entry = meta.get("page_meta", {}).get(name)
        return self._noted(folder, name, entry, _default_kind(meta["id"]))

    def _store_entry(
        self, meta: dict[str, Any], name: str, entry: dict[str, Any]
    ) -> None:
        """Write one ``page_meta`` entry if it changed; ``updated`` stays as it is."""
        entries = meta.get("page_meta", {})
        if entries.get(name) != entry:
            self._write_meta({**meta, "page_meta": {**entries, name: entry}})

    @staticmethod
    def _noted(
        folder: Path,
        name: str,
        entry: dict[str, Any] | None,
        default: str = DEFAULT_KIND,
    ) -> dict[str, Any]:
        """
        Return the ``page_meta`` entry of a page, made or kept current.

        A new entry starts its lifetime now, at the real time (A-250). The kind
        follows the page's meta tag until an agent or the owner sets it.
        """
        if entry is not None and entry["set_by"] not in ("meta", "default"):
            return entry
        tagged = _page_kind(folder / name) if name.lower().endswith(".html") else None
        kind, set_by = (tagged, "meta") if tagged else (default, "default")
        if entry is None:
            return _new_entry(kind, set_by)
        return {**entry, "kind": kind, "set_by": set_by}

    @staticmethod
    def _read_existing(folder: Path) -> dict[str, Any] | None:
        """Adopt a ``session.json`` left in the folder (registry was lost)."""
        try:
            meta = json.loads((folder / "session.json").read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return meta if isinstance(meta, dict) else None

    @staticmethod
    def _copy_into(folder: Path, source_text: str) -> str:
        """Copy an external file into ``folder``; return its page name."""
        source = Path(source_text)
        if not source.is_absolute() or not source.is_file():
            raise UnsafePathError(f"--copy source {source_text} is not a file.")
        name = validate_page_name(source.name)
        target = folder / name
        if source.resolve() != target.resolve():
            # A copy is a file, never a link: write beside the target and
            # replace it, so that a link already there is not written through.
            temporary = folder / f".copy-{uuid.uuid4().hex[:12]}"
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return name

    @staticmethod
    def _check_page(meta: dict[str, Any], folder: Path, name: str) -> None:
        """
        Check the type of page ``name`` and that its stem is not taken (VIEW-11).

        Raises
        ------
        UnsafePathError
            For a type that cannot be a page, or when another page of the
            session has the same stem (the message names that page).
        """
        if is_draft_name(name):
            return
        validate_page_type(name)
        stem = Path(name).stem
        on_disk = (p.name for p in sorted(folder.glob("*.html")) if p.name[0] != ".")
        taken = [*meta["pages"], *on_disk]
        for other in taken:
            if other != name and Path(other).stem == stem and not is_draft_name(other):
                raise UnsafePathError(
                    f"{name} would share the name {stem!r} with the page {other}; "
                    "pages of a session need distinct names without the extension."
                )

    def _require(self, session_id: str) -> dict[str, Any]:
        meta = self._meta(validate_or_raise(session_id))
        if meta is None:
            raise RegistryError("no-session", f"Unknown session {session_id}.")
        return meta

    def _update(self, session_id: str, **fields: Any) -> dict[str, Any]:
        meta = {**self._require(session_id), **fields, "updated": now_iso()}
        self._write_meta(meta)
        return meta

    def _write_meta(self, meta: dict[str, Any]) -> None:
        _write_json_atomic(self.folder_of(meta) / "session.json", meta)

    def _save_index(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self._file, self._index, mode=0o600)


def _new_entry(kind: str, set_by: str) -> dict[str, Any]:
    """Return a fresh ``page_meta`` entry whose lifetime starts now (A-250)."""
    return {
        "kind": kind,
        "set_by": set_by,
        "counted_from": clock.iso(time.time()),
        "extended": None,
        "answered": None,
        "reminded": None,
        "archived": None,
        "seen_version": None,
        "seen_at": None,
    }


_ENTRY_KEYS = frozenset(_new_entry(DEFAULT_KIND, "default"))


def _default_kind(session_id: str) -> str:
    """Return the kind a new page gets: project pages stay (PROJ-06)."""
    return "long-term" if session_id.startswith(PROJECT_PREFIX) else DEFAULT_KIND


def live_pages(meta: dict[str, Any]) -> list[str]:
    """Return the pages of a session that are not archived (LIFE-04)."""
    entries = meta.get("page_meta", {})
    return [n for n in meta["pages"] if not (entries.get(n) or {}).get("archived")]


def _closest_page(folder: Path, page: str) -> str:
    """Return `` Did you mean X?`` for the shown page nearest to ``page``, or ``""``."""
    names = [
        p.name
        for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".") and not is_draft_name(p.name)
    ]
    close = difflib.get_close_matches(page, names, n=1)
    return f" Did you mean {close[0]}?" if close else ""


def _page_title(path: Path) -> str | None:
    """Return the ``<title>`` text near the start of ``path``, if any."""
    try:
        with path.open("rb") as handle:
            head = handle.read(TITLE_SCAN_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    match = TITLE_TAG.search(head)
    if match is None:
        return None
    text = " ".join(html.unescape(match.group(1)).split())
    return text[:MAX_TITLE_CHARS] or None


def _page_kind(path: Path) -> str | None:
    """Return the kind of the page's ``agent-canvas-kind`` meta tag, if valid."""
    try:
        with path.open("rb") as handle:
            head = handle.read(TITLE_SCAN_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    match = KIND_TAG.search(head.split("</head>", 1)[0])
    kind = (match.group(1) or match.group(2)).strip().lower() if match else None
    return kind if kind in KINDS else None


def _stamp_seconds(stamp: str) -> float:
    """Return the POSIX time of a ``now_iso`` stamp (0 if it is unreadable)."""
    try:
        return (
            datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
            .replace(tzinfo=UTC)
            .timestamp()
        )
    except ValueError:
        return 0.0


def validate_or_raise(session_id: str) -> str:
    """Validate a session id, raising ``RegistryError('no-session', ...)``."""
    try:
        return validate_session_id(session_id)
    except InvalidSessionId as error:
        raise RegistryError("no-session", str(error)) from error


def _ensure_gitignore(canvas_dir: Path) -> None:
    """Create ``.gitignore`` with ``*`` unless one exists (HUB-07)."""
    try:
        descriptor = os.open(
            canvas_dir / ".gitignore", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
        )
    except FileExistsError:
        return
    with os.fdopen(descriptor, "w") as handle:
        handle.write("*\n")
