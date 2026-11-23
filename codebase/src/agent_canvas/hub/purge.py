"""Deletion of the data of pages archived 30 days ago (LIFE-08, HIST-04).

Only files of the page inside its own session folder go: history versions,
comments and their pictures, the answers file, the thumbnail, the draft and,
unless the current version of a page that stays refers to it, the page file.
Events, send records and every other file stay. Each deletion and each kept
file is written to stderr, which is ``hub.log``.

The same run deletes saved page versions 30 days old that nothing keeps
(HIST-86); the pages themselves stay.
"""

from __future__ import annotations

import posixpath
import re
import stat
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from agent_canvas.drafts import draft_name_for
from agent_canvas.files_safe import ANSWERS_DIR, COMMENTS_DIR, HISTORY_PAGES
from agent_canvas.hub import clock
from agent_canvas.hub import comments as comment_store
from agent_canvas.hub.lifetime import ARCHIVE_DAYS, DAY_SECONDS, VERSION_DAYS
from agent_canvas.hub.sends import list_sends
from agent_canvas.hub.watcher import PageHistory
from agent_canvas.paths_safe import (
    VIEWER_EXTENSIONS,
    UnsafePathError,
    ensure_inside,
    validate_page_name,
    validate_page_type,
)

if TYPE_CHECKING:
    from agent_canvas.hub.registry import SessionRegistry

PURGE_INTERVAL_SECONDS = DAY_SECONDS
LINK_ATTRIBUTES = ("src", "href", "data", "poster")
CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\s'\"]*))")
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)")
MARKDOWN_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+)", re.MULTILINE)
READABLE_SUFFIXES = (".html", ".md", ".markdown")
VERSION_FILE = re.compile(
    r"^(?P<stem>.+)\.(?P<number>[0-9]{4,})"
    rf"(?P<suffix>{'|'.join(map(re.escape, ('.html', *VIEWER_EXTENSIONS)))})$"
)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._in_style = tag == "style"
        for key, value in attrs:
            if not value:
                continue
            if key in LINK_ATTRIBUTES:
                self.found.append(value)
            elif key == "srcset":
                self.found += [c.split()[0] for c in value.split(",") if c.strip()]
            elif key == "style":
                self.found += _css_urls(value)

    def handle_endtag(self, tag: str) -> None:
        self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.found += _css_urls(data)


def _css_urls(css: str) -> list[str]:
    """Return the targets of the ``url(...)`` terms in a piece of CSS."""
    return [g for groups in CSS_URL.findall(css) for g in groups if g]


def purge(registry: SessionRegistry) -> list[str]:
    """
    Delete the data of every page archived 30 days ago or more (LIFE-08).

    Then delete the saved versions 30 days old that nothing keeps (HIST-86).

    Runs without awaiting, so a restore cannot come between the check and the
    deletion; a restored page is never deleted.

    Parameters
    ----------
    registry : SessionRegistry
        The sessions to look through.

    Returns
    -------
    list[str]
        ``session/page`` of every page that left its session.
    """
    now = clock.now()
    removed: list[str] = []
    for listed in registry.list(True, None):
        try:
            removed += _purge_session(registry, listed["id"], now)
        except Exception as error:  # noqa: BLE001  # one bad session must not stop the others
            _log(f"failed {listed['id']}: {type(error).__name__}: {error}")
        try:
            _prune_versions(registry, listed["id"], now)
        except Exception as error:  # noqa: BLE001  # one bad session must not stop the others
            _log(f"failed versions of {listed['id']}: {type(error).__name__}: {error}")
    return removed


def _purge_session(registry: SessionRegistry, session_id: str, now: float) -> list[str]:
    """Purge the due pages of one session; ``session/page`` of each page removed."""
    meta = registry.get(session_id)
    if meta is None:
        return []
    due = [n for n in meta.pages if _is_due(meta.raw, n, now)]
    if not due:
        return []
    folder = registry.folder_of(meta)
    history = PageHistory(folder)
    changed = [n for n in due if _changed_since_archived(history, folder, n)]
    for name in changed:
        _log(f"kept {session_id}/{name} (changed since it was archived)")
        registry.restore(session_id, name)
    due = [n for n in due if n not in changed]
    referenced = _referenced(folder, [n for n in meta.pages if n not in due])
    for name in due:
        _delete_page(session_id, folder, name, referenced)
    registry.drop_pages(session_id, due)
    return [f"{session_id}/{name}" for name in due]


def _changed_since_archived(history: PageHistory, folder: Path, name: str) -> bool:
    """Tell whether the page file differs from its newest saved version (LIFE-04)."""
    path = folder / name
    if path.is_symlink():  # a link is unlinked, its target never read
        return False
    try:
        content = path.read_bytes()
    except OSError:
        return False
    newest = history.latest(name)
    return newest is None or content != newest[1]


def _is_due(meta: dict[str, Any], name: str, now: float) -> bool:
    """Tell whether the page was archived 30 days ago or more and is safe to name."""
    archived = (meta.get("page_meta", {}).get(name) or {}).get("archived")
    if not archived:
        return False
    try:
        validate_page_type(validate_page_name(name))
        deadline = clock.seconds_of(archived) + ARCHIVE_DAYS * DAY_SECONDS
    except (UnsafePathError, ValueError, TypeError):
        _log(f"kept {meta['id']}/{name!r} (not a page name or archive time)")
        return False
    return now >= deadline


def _delete_page(
    session_id: str,
    folder: Path,
    name: str,
    referenced: dict[str, str],
) -> None:
    """Delete one page's files; the page and draft stay when another page uses them."""
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    versions = re.compile(rf"^{re.escape(stem)}\.\d{{4,}}{re.escape(suffix)}$")
    pictures = re.compile(rf"^{re.escape(name)}\.\d+\.png$")
    where = f"{session_id}/"
    for entry in _names(folder / HISTORY_PAGES):
        if versions.match(entry):
            _remove(folder, HISTORY_PAGES / entry, where)
    for entry in _names(folder / COMMENTS_DIR):
        if entry == f"{name}.json" or pictures.match(entry):
            _remove(folder, Path(COMMENTS_DIR) / entry, where)
    _remove(folder, Path(ANSWERS_DIR) / f"{name}.json", where)
    files = [name] + ([draft_name_for(name)] if suffix == ".html" else [])
    for file in files:
        if file in referenced:
            _log(f"kept {where}{file} (referenced by {referenced[file]})")
        else:
            _remove(folder, Path(file), where)


def _names(directory: Path) -> list[str]:
    """List a real directory's entries; a symbolic link or missing folder gives none."""
    if directory.is_symlink() or not directory.is_dir():
        return []
    return [p.name for p in directory.iterdir()]


def _remove(folder: Path, relative: Path, where: str) -> None:
    """Delete one file or link inside the session folder, never anything outside."""
    path = folder / relative
    if not (path.is_symlink() or path.is_file()):
        return
    if not path.parent.resolve().is_relative_to(folder.resolve()):
        _log(f"kept {where}{relative} (outside the session folder)")
        return
    path.unlink()
    _log(f"deleted {where}{relative}")


def _referenced(folder: Path, pages: list[str]) -> dict[str, str]:
    """Map each file a staying page's current version refers to, to that page."""
    found: dict[str, str] = {}
    for page in pages:
        if not page.lower().endswith(READABLE_SUFFIXES):
            continue
        try:
            text = (folder / page).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for target in _targets(text, page.lower().endswith(".html")):
            found.setdefault(target, page)
    return found


def _targets(text: str, html: bool) -> set[str]:
    """Return the session-folder file names a page's source points at."""
    links = _Links()
    links.feed(text)
    values = links.found
    if not html:
        values += MARKDOWN_LINK.findall(text) + MARKDOWN_DEFINITION.findall(text)
    return {t for t in map(_local_name, values) if t}


def _local_name(value: str) -> str | None:
    """Return the normalised relative path of a link inside the folder, else None."""
    parts = urlsplit(value.strip())
    path = unquote(parts.path)
    if parts.scheme or parts.netloc or not path or path.startswith("/"):
        return None
    path = posixpath.normpath(path)
    return None if path.startswith("..") else path


def _prune_versions(registry: SessionRegistry, session_id: str, now: float) -> None:
    """Delete one session's saved versions that are due under HIST-86."""
    meta = registry.get(session_id)
    if meta is None:
        return
    folder = registry.folder_of(meta)
    pages = folder / HISTORY_PAGES
    if not pages.is_dir():
        return
    try:
        real = ensure_inside(folder, pages) == folder.resolve() / HISTORY_PAGES
    except UnsafePathError:
        real = False
    if not real:
        _log(f"kept {session_id}/{HISTORY_PAGES} (a linked folder)")
        return
    found: list[tuple[Path, tuple[str, str], int, float]] = []
    newest: dict[tuple[str, str], int] = {}
    for entry in pages.iterdir():
        match = VERSION_FILE.match(entry.name)
        if match is None:
            continue
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode):
            continue
        key, number = (match["stem"], match["suffix"]), int(match["number"])
        found.append((entry, key, number, info.st_mtime))
        newest[key] = max(newest.get(key, 0), number)
    deadline = now - VERSION_DAYS * DAY_SECONDS
    due = [
        (e, k, n) for e, k, n, saved in found if saved <= deadline and n != newest[k]
    ]
    if not due:
        return
    kept = _pointed_at(folder, meta.raw)
    for entry, key, number in due:
        if (key[0], number) in kept:
            continue
        where = f"{session_id}/{HISTORY_PAGES / entry.name}"
        try:
            entry.unlink()
        except OSError as error:
            _log(f"failed {where}: {type(error).__name__}: {error}")
            continue
        _log(f"deleted {where}")


def _pointed_at(folder: Path, meta: dict[str, Any]) -> set[tuple[str, int]]:
    """Return (stem, number) of the versions a look, comment or send still needs."""
    found = {
        (Path(page).stem, entry["seen_version"])
        for page, entry in meta.get("page_meta", {}).items()
        if entry and entry.get("seen_version")
    }
    statuses: dict[str, dict[int, str]] = {}
    for page in comment_store.pages(folder):
        records = comment_store.load(folder, page)["comments"]
        statuses[page] = {r["n"]: comment_store.status(r) for r in records}
        found |= {
            (Path(page).stem, r["page_version"])
            for r in records
            if statuses[page][r["n"]] != "done"
        }
    for send in list_sends(folder):
        status_of = statuses.get(send["page"], {})
        if any(status_of.get(c["n"]) != "done" for c in send.get("comments") or ()):
            found.add((Path(send["page"]).stem, send["page_version"]))
    return found


def _log(text: str) -> None:
    print(f"agent-canvas: purge: {text}", file=sys.stderr, flush=True)
