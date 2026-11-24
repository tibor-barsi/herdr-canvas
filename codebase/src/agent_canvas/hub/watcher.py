"""Page watching and history versions (HUB-05, HIST-01, HIST-04).

Each registered session folder is watched with ``watchfiles.awatch`` (lowered
debounce and step, because a page may change continuously). A change is read
only after the file has been stable for a short time, saved as a history
version when its content is new, and pushed to the connected shells as the
agent's raw HTML.
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from collections.abc import Awaitable, Callable, Collection
from pathlib import Path

from watchfiles import Change, awatch

from agent_canvas.drafts import is_draft_name
from agent_canvas.files_safe import EVENTS_FILE, HISTORY_PAGES, write_safely
from agent_canvas.hub.serve import source_digest
from agent_canvas.hub.state import HubState, Session
from agent_canvas.hub.viewers import viewer_type
from agent_canvas.paths import make_private_dirs
from agent_canvas.paths_safe import VIEWER_EXTENSIONS

DEBOUNCE_MS = 200
STEP_MS = 20
STABLE_SECONDS = 0.05
POLL_SECONDS = 0.01
# Files the hub itself keeps in a session folder; they are not page assets.
PUSHED_VIEWERS = frozenset({"markdown", "image", "pdf"})
INTERNAL_NAMES = frozenset({"session.json", EVENTS_FILE})
INTERNAL_DIRECTORY = "history"


def is_page_name(name: str) -> bool:
    """
    Tell whether a top-level file name is a page (HUB-05).

    Parameters
    ----------
    name : str
        File name without directories.

    Returns
    -------
    bool
        True for ``*.html`` files that are neither dotfiles nor drafts
        (``*.draft.html``, DRAFT-01).
    """
    return (
        name.lower().endswith(".html")
        and not name.startswith(".")
        and not is_draft_name(name)
    )


def is_asset_path(folder: Path, path: Path) -> bool:
    """
    Tell whether ``path`` is a data file an agent put in the session folder.

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    path : pathlib.Path
        Absolute path of a changed file.

    Returns
    -------
    bool
        False for pages, drafts, the hub's own files, ``history/`` and dotfiles
        or files below dot directories; True for other files.
    """
    try:
        parts = path.relative_to(folder).parts
    except ValueError:
        return False
    if not parts or any(part.startswith(".") for part in parts):
        return False
    if parts[0] == INTERNAL_DIRECTORY or (
        len(parts) == 1 and parts[0] in INTERNAL_NAMES
    ):
        return False
    if len(parts) == 1 and (is_page_name(parts[0]) or is_draft_name(parts[0])):
        return False
    return True


def _extension(page: str) -> str:
    """Return the extension of a version file: ``.html`` or the viewer's own."""
    suffix = Path(page).suffix.lower()
    return suffix if suffix in VIEWER_EXTENSIONS else ".html"


class PageHistory:
    """
    Versions of the pages of one session folder (HIST-01).

    Parameters
    ----------
    folder : pathlib.Path
        Session folder; versions live in ``history/pages/``.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._directory = folder / HISTORY_PAGES

    def latest(self, page: str) -> tuple[int, bytes] | None:
        """
        Return the newest saved version of ``page``.

        Returns
        -------
        tuple[int, bytes] | None
            Version number and content, or None if nothing is saved.
        """
        numbers = self._numbers(page)
        if not numbers:
            return None
        newest = max(numbers)
        return newest, self.path(page, newest).read_bytes()

    def save(self, page: str, content: bytes) -> int | None:
        """
        Save ``content`` as a new version unless it equals the newest one.

        Parameters
        ----------
        page : str
            Page file name, for example ``page.html``.
        content : bytes
            Complete page content.

        Returns
        -------
        int | None
            The new version number, or None if the content is not new.
        """
        newest = self.latest(page)
        if newest is not None and newest[1] == content:
            return None
        number = 1 if newest is None else newest[0] + 1
        make_private_dirs(self._directory)
        target = self.path(page, number)
        write_safely(target, content)
        return number

    def versions(self, page: str) -> list[tuple[int, float]]:
        """
        List the saved versions of ``page``, oldest first.

        Returns
        -------
        list[tuple[int, float]]
            Version number and modification time (seconds since the epoch).
        """
        return [
            (number, self.path(page, number).stat().st_mtime)
            for number in sorted(self._numbers(page))
        ]

    def read(self, page: str, number: int) -> bytes | None:
        """Return the content of version ``number`` of ``page``, or None."""
        try:
            return self.path(page, number).read_bytes()
        except OSError:
            return None

    def path(self, page: str, number: int) -> Path:
        """Return the file of version ``number`` of ``page``."""
        return self._directory / f"{Path(page).stem}.{number:04d}{_extension(page)}"

    def _numbers(self, page: str) -> list[int]:
        stem, extension = re.escape(Path(page).stem), re.escape(_extension(page))
        pattern = re.compile(rf"^{stem}\.(\d{{4,}}){extension}$")
        if not self._directory.is_dir():
            return []
        matches = (pattern.match(p.name) for p in self._directory.iterdir())
        return [int(m.group(1)) for m in matches if m]


async def read_stable(path: Path) -> bytes | None:
    """
    Read ``path`` once its size and mtime have been stable for 50 ms (HUB-05).

    A file whose mtime is already older than the stability window is read
    at once.

    Parameters
    ----------
    path : pathlib.Path
        The page file.

    Returns
    -------
    bytes | None
        The content, or None if the file is missing or empty.
    """
    last: tuple[int, int] | None = None
    changed_at = time.monotonic()
    while True:
        try:
            stat = path.stat()
        except OSError:
            return None
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature != last:
            quiet_for = time.time() - stat.st_mtime_ns / 1e9
            if last is None and quiet_for >= STABLE_SECONDS:
                changed_at -= STABLE_SECONDS
            else:
                changed_at = time.monotonic()
            last = signature
        if time.monotonic() - changed_at >= STABLE_SECONDS:
            break
        await asyncio.sleep(POLL_SECONDS)
    try:
        content = path.read_bytes()
        after = path.stat()
    except OSError:
        return None
    if (after.st_size, after.st_mtime_ns) != last:
        return await read_stable(path)
    return content or None


async def watch_folders(
    folders: list[Path],
    on_page_change: Callable[[Path, str], Awaitable[None]],
    stop: asyncio.Event,
    on_armed: Callable[[], Awaitable[None]] | None = None,
    on_file_change: Callable[[Path, str], Awaitable[None]] | None = None,
    is_listed_viewer: Callable[[Path, str], bool] | None = None,
) -> None:
    """
    Watch several session folders with one ``awatch`` and report changes.

    One call holds one worker thread however many folders there are (review
    finding C1).

    Parameters
    ----------
    folders : list[pathlib.Path]
        Session folders (existing directories, resolved, none inside another).
    on_page_change : Callable[[pathlib.Path, str], Awaitable[None]]
        Awaited with the folder and the page name for every changed page of a
        batch (pages are the top-level ``*.html`` files and listed viewer files).
    stop : asyncio.Event
        Set to end the watch.
    on_armed : Callable[[], Awaitable[None]] | None, optional
        Awaited once the file system watch is in place, so that the caller can
        pick up files written before that moment.
    on_file_change : Callable[[pathlib.Path, str], Awaitable[None]] | None
        Awaited with the folder and the POSIX path relative to it of every
        added or modified data file of a batch (BLK-09). Without it only
        pages are watched, and only the top level.
    is_listed_viewer : Callable[[pathlib.Path, str], bool] | None, optional
        Tells whether a top-level file of a folder is a listed Markdown, PDF or
        picture page (VIEW-01); such a file is a page, not a data file.
    """
    roots = set(folders)

    def is_page(folder: Path, name: str) -> bool:
        return is_page_name(name) or (
            is_listed_viewer is not None and is_listed_viewer(folder, name)
        )

    def folder_of(path: Path) -> Path | None:
        return next((p for p in path.parents if p in roots), None)

    def is_page_event(change: Change, path: str) -> bool:
        candidate = Path(path)
        if candidate.parent in roots and is_page(candidate.parent, candidate.name):
            return True
        folder = folder_of(candidate)
        return (
            on_file_change is not None
            and folder is not None
            and change != Change.deleted
            and is_asset_path(folder, candidate)
            and candidate.is_file()
        )

    changes_stream = awatch(
        *folders,
        watch_filter=is_page_event,
        debounce=DEBOUNCE_MS,
        step=STEP_MS,
        stop_event=stop,
        recursive=on_file_change is not None,
    )
    # awatch arms the OS watch synchronously when its first item is requested,
    # so one scheduler turn after that request the watch is in place.
    next_batch = asyncio.ensure_future(anext(changes_stream, None))
    await asyncio.sleep(0)
    if on_armed is not None:
        await on_armed()
    while (changes := await next_batch) is not None:
        for path in sorted({Path(path) for _, path in changes}):
            folder = folder_of(path)
            if folder is None:
                continue
            if path.parent == folder and is_page(folder, path.name):
                await on_page_change(folder, path.name)
            elif on_file_change is not None:
                await on_file_change(folder, path.relative_to(folder).as_posix())
        next_batch = asyncio.ensure_future(anext(changes_stream, None))


async def watch_folder(
    folder: Path,
    on_page_change: Callable[[str], Awaitable[None]],
    stop: asyncio.Event,
    on_armed: Callable[[], Awaitable[None]] | None = None,
    on_file_change: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """
    Watch one ``folder`` and report changed page names and data files.

    A thin wrapper of :func:`watch_folders` for a single folder.

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    on_page_change : Callable[[str], Awaitable[None]]
        Awaited with the page name for every changed page of a batch.
    stop : asyncio.Event
        Set to end the watch.
    on_armed : Callable[[], Awaitable[None]] | None, optional
        Awaited once the file system watch is in place.
    on_file_change : Callable[[str], Awaitable[None]] | None, optional
        Awaited with the POSIX path relative to ``folder`` of every added or
        modified data file of a batch (BLK-09).
    """

    async def page(_: Path, name: str) -> None:
        await on_page_change(name)

    async def data(_: Path, relative: str) -> None:
        assert on_file_change is not None
        await on_file_change(relative)

    await watch_folders(
        [folder], page, stop, on_armed, data if on_file_change else None
    )


class PageWatcher:
    """
    Watch the active session folders and push page updates to the shells.

    A single task watches all folders at once and restarts when the set of
    folders changes: a registered session that is ended or hidden is not
    watched (HUB-05). ``show`` always ingests its page itself.

    Parameters
    ----------
    state : HubState
        Hub state; its ``session_listeners`` trigger a refresh and its
        shells receive the updates.
    is_watched : Callable[[str], bool] | None, optional
        Tells whether a session id is to be watched; default is all.
    on_page_change : Callable[[str, str, int], None] | None, optional
        Called with session id, page and version when a new version of a page
        is saved (AGT-19).
    pages_of : Callable[[str], Collection[str]] | None, optional
        Gives the listed pages of a session id; a Markdown, PDF or picture file
        is watched only once it is listed (HUB-05, VIEW-01).
    """

    def __init__(
        self,
        state: HubState,
        is_watched: Callable[[str], bool] | None = None,
        on_page_change: Callable[[str, str, int], None] | None = None,
        pages_of: Callable[[str], Collection[str]] | None = None,
    ) -> None:
        self._state = state
        self._pages_of = pages_of or (lambda _: ())
        self._is_watched = is_watched or (lambda _: True)
        self._on_page_change = on_page_change
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._folders_changed: asyncio.Event | None = None
        self._run_stop: asyncio.Event | None = None
        self._current: dict[str, Session] = {}
        self._histories: dict[str, PageHistory] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.scanned = asyncio.Event()  # set when the start scan ran or had no folder
        state.session_listeners.append(self.start_soon)

    def start_soon(self, session: Session | None = None) -> None:
        """Re-evaluate the watched folders; safe to call from any thread."""
        loop = self._state.loop
        if loop is not None:
            loop.call_soon_threadsafe(self.refresh)

    @property
    def watching(self) -> set[str]:
        """Ids of the sessions the running watch covers."""
        return set(self._current)

    def refresh(self) -> None:
        """Restart the watch if the set of watched folders changed (loop only)."""
        if self._folders_changed is None:
            return
        self._folders_changed.set()
        if self._run_stop is not None and self._watched() != self._current:
            self._run_stop.set()

    async def run(self) -> None:
        """Start watching the sessions registered so far."""
        self._stop = asyncio.Event()
        self._folders_changed = asyncio.Event()
        self._task = asyncio.ensure_future(self._watch_all())

    async def close(self) -> None:
        """Stop the watch and wait for it."""
        if self._stop is not None:
            self._stop.set()
        if self._run_stop is not None:
            self._run_stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def ingest(
        self, session: Session, page: str, push: bool = True, notify: bool = True
    ) -> int:
        """
        Read ``page`` once stable, save a new version and optionally push it.

        Parameters
        ----------
        session : Session
            The owning session.
        page : str
            Page file name in the session folder.
        push : bool, optional
            Send the new content to the shells (default True). ``show`` passes
            False because the frame loads the file itself.
        notify : bool, optional
            Call ``on_page_change`` for a new version (default True). ``show``
            passes False because its route does the rest itself.

        Returns
        -------
        int
            The newest version number of the page (0 if there is none).
        """
        async with self._locks.setdefault(session.session_id, asyncio.Lock()):
            history = self._history(session)
            content = await read_stable(session.folder / page)
            if content is not None and (number := history.save(page, content)):
                # HTML and Markdown go as text; a picture or PDF as a bare notice.
                if push and (is_page_name(page) or viewer_type(page) in PUSHED_VIEWERS):
                    await self._push(session, page, content, number)
                if notify and self._on_page_change is not None:
                    self._on_page_change(session.session_id, page, number)
                return number
            newest = history.latest(page)
            return 0 if newest is None else newest[0]

    def _watched(self) -> dict[str, Session]:
        """Return the sessions to watch: existing folder, not ended or hidden."""
        return {
            s.session_id: s
            for s in self._state.sessions()
            if s.folder.is_dir() and self._is_watched(s.session_id)
        }

    async def _watch_all(self) -> None:
        """Run one multi-folder watch, restarting it when the set changes."""
        assert self._stop is not None and self._folders_changed is not None
        while not self._stop.is_set():
            self._folders_changed.clear()
            self._current = self._watched()
            if not self._current:
                self.scanned.set()
                await self._folders_changed.wait()
                continue
            self._run_stop = asyncio.Event()
            try:
                await self._watch_once(self._current)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the hub must go on
                print(f"agent-canvas: watching stopped: {error}", file=sys.stderr)
                await asyncio.sleep(1.0)
            finally:
                self._run_stop = None

    async def _watch_once(self, sessions: dict[str, Session]) -> None:
        by_folder = {s.folder: s for s in sessions.values()}
        assert self._run_stop is not None
        run_stop = self._run_stop

        async def changed(folder: Path, page: str) -> None:
            await self.ingest(by_folder[folder], page)

        async def scan() -> None:
            for session in by_folder.values():
                for entry in sorted(session.folder.glob("*.html")):
                    if is_page_name(entry.name):
                        await self.ingest(session, entry.name)
                for name in sorted(self._pages_of(session.session_id)):
                    if viewer_type(name) and (session.folder / name).is_file():
                        await self.ingest(session, name)
            self.scanned.set()

        async def file_changed(folder: Path, path: str) -> None:
            session = by_folder[folder]
            await read_stable(folder / path)
            self._state.channel.broadcast(
                {"type": "file-changed", "session": session.session_id, "path": path}
            )

        def is_listed_viewer(folder: Path, name: str) -> bool:
            session = by_folder.get(folder)
            return (
                session is not None
                and viewer_type(name) is not None
                and not name.startswith(".")
                and name in self._pages_of(session.session_id)
            )

        await watch_folders(
            list(by_folder), changed, run_stop, scan, file_changed, is_listed_viewer
        )

    def _history(self, session: Session) -> PageHistory:
        return self._histories.setdefault(
            session.session_id, PageHistory(session.folder)
        )

    async def _push(
        self, session: Session, page: str, content: bytes, version: int
    ) -> None:
        url = self._state.frame_url(session.session_id, page)
        message: dict[str, object] = {"type": "update", "url": url, "version": version}
        if (kind := viewer_type(page)) is not None:
            message["url"] = f"{url}?ac-view=1"
            message["viewer"] = kind
        if kind not in ("image", "pdf"):
            message["html"] = content.decode("utf-8", errors="replace")
            if kind is None:
                message["digest"] = source_digest(content)
        self._state.channel.broadcast(message)
