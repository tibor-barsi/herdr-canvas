"""
Move the pages of old session folders into the project's pool (POOL-09).

:func:`plan_migration` reads and returns what would happen; :func:`apply_migration`
does it. Nothing is ever written, moved or deleted in an old session folder, and
nothing the pool already holds is ever overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_canvas.drafts import is_draft_name
from agent_canvas.files_safe import (
    ANSWERS_DIR,
    COMMENTS_DIR,
    set_aside,
    write_safely,
)
from agent_canvas.hub import clock
from agent_canvas.hub.registry import is_project_id, pool_id, pool_key
from agent_canvas.hub.watcher import PageHistory, is_page_name
from agent_canvas.paths import make_private_dirs
from agent_canvas.paths_safe import (
    UnsafePathError,
    validate_page_name,
    validate_page_type,
)

if TYPE_CHECKING:
    from agent_canvas.hub.registry import SessionRegistry

LOG_NAME = ".migration.json"
LOG_SCHEMA = "agent-canvas/migration@1"
LEGACY_FOLDER = "project"
_SESSION_FILES = ("session.json", "events.jsonl")
_ERRORS = (OSError, ValueError, KeyError, TypeError)


def plan_migration(
    known: Mapping[str, Mapping[str, Any]],
    pool: Path,
    project_key: str,
    recorded: Collection[str] = (),
) -> dict[str, Any]:
    """
    Work out what the migration would do, writing nothing.

    Parameters
    ----------
    known : Mapping[str, Mapping[str, Any]]
        The hub's own sessions by id, each with ``folder`` (the real session
        folder, wherever it is), ``project`` and optionally ``title`` and
        ``agent``. Sessions of other projects are ignored; folders not named
        here are left alone.
    pool : pathlib.Path
        The pool's folder (it need not exist yet).
    project_key : str
        The project key the pool belongs to (``registry.pool_key``).
    recorded : Collection[str], optional
        Names of the pool's pages that already have a page record; they are
        never taken in again, even if the log is gone.

    Returns
    -------
    dict[str, Any]
        ``moves`` (pages to take in, newest first, with their copy items and page
        record), ``older`` (same-name copies that stay), ``clashes`` (pages that
        stay because a file differs from the pool's), ``skipped`` (what could
        not or must not be taken in), ``unknown`` (folders of unknown sessions),
        and ``stopped`` (why nothing can be done, else None).
    """
    plan: dict[str, Any] = {
        "moves": [],
        "older": [],
        "clashes": [],
        "skipped": [],
        "unknown": [],
        "stopped": None,
        "damaged_log": False,
    }
    if pool.is_symlink():
        plan["stopped"] = f"{pool} is a symbolic link; refused."
        return plan
    try:
        done = set(_read_log(pool)["moved"])
    except _ERRORS:
        plan["stopped"] = f"The migration log in {pool} does not parse."
        plan["damaged_log"] = True
        return plan
    members = _members(known, pool, project_key)
    copies: dict[str, list[tuple[bool, float, str]]] = {}
    settings: dict[str, dict[str, Any]] = {}
    for sid, (info, folder) in sorted(members.items()):
        try:
            settings[sid] = _settings(folder)
        except _ERRORS as error:
            plan["skipped"].append(
                _skip(sid, "session.json", error, os.path.relpath(folder, project_key))
            )
            continue
        for page in _pages(folder, settings[sid]["pages"]):
            entry = settings[sid]["page_meta"].get(page) or {}
            when = _when(entry, folder / page)
            copies.setdefault(page, []).append((not entry.get("archived"), when, sid))
        plan["skipped"] += [
            _skip(
                sid,
                name,
                "a draft stays where it is",
                os.path.relpath(folder, project_key),
            )
            for name in sorted(_top_files(folder))
            if is_draft_name(name)
        ]
    winners = {}
    for page, rows in copies.items():
        live, when, winner = max(rows)
        winners[page] = (when, winner)
        plan["older"] += [
            {
                "page": page,
                "session": sid,
                "kept_in": os.path.relpath(members[sid][1], project_key),
            }
            for _, _, sid in sorted(rows, key=lambda r: r[2])
            if sid != winner
        ]
    # A pool's pages have distinct stems (VIEW-11): the pool's own page, else the
    # copy made first, keeps the stem.
    stems = {Path(name).stem: name for name in [*_pool_pages(pool), *recorded]}
    for page, _ in sorted(winners.items(), key=lambda w: (w[1][0], w[0])):
        stems.setdefault(Path(page).stem, page)
    claimed: dict[str, str] = {}
    for page, (when, sid) in sorted(winners.items(), key=lambda w: (-w[1][0], w[0])):
        if f"{sid}/{page}" in done or page in recorded:
            continue
        info, folder = members[sid]
        if stems[Path(page).stem] != page:
            plan["clashes"].append(
                {
                    "page": page,
                    "session": sid,
                    "file": stems[Path(page).stem],
                    "kept_in": os.path.relpath(folder, project_key),
                }
            )
            continue
        try:
            move = _move(page, sid, info, folder, settings[sid], when)
            move["kept_in"] = os.path.relpath(folder, project_key)
            clash = _first_clash(move["items"], pool, claimed)
            digests = {i["dest"]: i["digest"] for i in move["items"]}
        except _ERRORS as error:
            plan["skipped"].append(
                _skip(sid, page, error, os.path.relpath(folder, project_key))
            )
            continue
        if clash is None:
            claimed.update(digests)
            plan["moves"].append(move)
        else:
            plan["clashes"].append(
                {
                    "page": page,
                    "session": sid,
                    "file": clash,
                    "kept_in": move["kept_in"],
                }
            )
    plan["unknown"], unreadable = _unknown(members, known, pool, project_key)
    plan["skipped"] += unreadable
    return plan


def apply_migration(
    plan: Mapping[str, Any],
    pool: Path,
    write_record: Callable[[str, dict[str, Any]], None],
) -> dict[str, Any]:
    """
    Carry out a plan, page by page; a run that stopped half way can be repeated.

    Parameters
    ----------
    plan : Mapping[str, Any]
        A plan made by :func:`plan_migration`.
    pool : pathlib.Path
        The pool's folder.
    write_record : Callable[[str, dict[str, Any]], None]
        Called with a page name and its page record (a full ``page_meta`` entry
        with ``created_by``, ``updated_by``, ``digest`` and ``sessions``) once
        the page's files are in the pool; it must be safe to call again.

    Returns
    -------
    dict[str, Any]
        The migration log: ``moved``, ``older``, ``clashes``, ``skipped``,
        ``unknown``, ``complete`` (no page failed with an error) and ``stopped``
        (the reason the run did nothing, else None).
        A damaged log is set aside as ``.migration.json.bad`` and the run stops.
    """
    if plan["stopped"]:
        if plan["damaged_log"]:
            set_aside(pool / LOG_NAME)
        return {**_new_log(), "stopped": plan["stopped"]}
    make_private_dirs(pool)
    log = _read_log(pool)
    skipped, clashes = list(plan["skipped"]), list(plan["clashes"])
    failed = False
    for move in plan["moves"]:
        try:
            outcome = _take(move, pool)
            if not isinstance(outcome, tuple):
                write_record(move["page"], _record(move, outcome))
        except _ERRORS as error:
            skipped.append(_skip(move["session"], move["page"], error, move["kept_in"]))
            failed = True
            continue
        if isinstance(outcome, tuple):
            clashes.append(
                {
                    "page": move["page"],
                    "session": move["session"],
                    "file": outcome[0],
                    "kept_in": move["kept_in"],
                }
            )
            continue
        log["moved"] = sorted({*log["moved"], f"{move['session']}/{move['page']}"})
        _write_log(pool, log)
    log["older"] = sorted(plan["older"], key=lambda o: (o["page"], o["session"]))
    log["clashes"] = sorted(clashes, key=lambda c: (c["page"], c["session"]))
    log["skipped"] = sorted(skipped, key=lambda s: (s["session"], s["file"]))
    log["unknown"] = plan["unknown"]
    # Only a run that met no error is complete; another one is planned again.
    log["complete"] = not failed
    _write_log(pool, log)
    return {**log, "stopped": None}


def migrate_project(
    registry: SessionRegistry, project_key: str, apply: bool
) -> dict[str, Any]:
    """
    Plan the migration of one project into this hub's pool, and carry it out.

    Parameters
    ----------
    registry : SessionRegistry
        The hub's sessions; every one of the project but a pool is taken in.
    project_key : str
        The project key (``registry.pool_key`` of a session's project).
    apply : bool
        Carry the plan out. Without it, or with nothing to move into a pool
        that does not exist yet, nothing is written and no pool is made.

    Returns
    -------
    dict[str, Any]
        The plan in short (``moves`` as page, session and number of files, then
        ``older``, ``clashes``, ``skipped``, ``unknown``, ``stopped``), or the
        migration log once applied.
    """
    pool = pool_id(registry.pool_tag, project_key)
    folder = registry.pool_folder(project_key)
    meta = registry.get(pool)
    known = {
        m["id"]: {
            "folder": registry.folder_of(m),
            "project": m["project"],
            "title": registry.effective_title(m),
            "agent": m["agent"],
        }
        for m in registry.list(True, None)
        if not is_project_id(m["id"])
    }
    recorded = set(meta.page_meta) if meta else set()
    plan = plan_migration(known, folder, project_key, recorded)
    if not apply or (meta is None and not plan["moves"]):
        moves = [
            {"page": m["page"], "session": m["session"], "files": len(m["items"])}
            for m in plan["moves"]
        ]
        return {**plan, "moves": moves}
    registry.pool_session(project_key)
    return apply_migration(
        plan, folder, lambda name, record: registry.record_migrated(pool, name, record)
    )


def migrate_at_start(registry: SessionRegistry) -> None:
    """
    Migrate each project of the hub's sessions once, before any pool is watched.

    A project whose pool holds a complete migration log is left alone. An
    error is printed, never raised, so the hub always starts.
    """
    keys = {
        pool_key(m["project"])
        for m in registry.list(True, None)
        if not is_project_id(m["id"])
    }
    for key in sorted(keys):
        try:
            if _complete(registry.pool_folder(key)):
                continue
            done = migrate_project(registry, key, apply=True)
        except Exception as error:  # noqa: BLE001  # the hub must start
            print(
                f"agent-canvas: the migration of {key} failed: {error!r}",
                file=sys.stderr,
            )
            continue
        if "moved" in done and (done["moved"] or done["skipped"] or done["clashes"]):
            print(
                f"agent-canvas: migrated {len(done['moved'])} pages of {key} into its "
                f"pool; {len(done['older']) + len(done['clashes'])} left behind, "
                f"{len(done['skipped'])} skipped (see "
                f"{registry.pool_folder(key) / LOG_NAME})",
                file=sys.stderr,
            )


def left_behind(pool: Path, project_key: str) -> list[dict[str, str]]:
    """
    Return the pages the migration left in old folders (Q3).

    Each row names the ``page``, the old ``session``, ``why`` (``older``: an
    older same-name copy, ``clash``: its ``file`` differs from the pool's, or
    ``skipped``: it could not be moved)
    and the ``folder`` the page stays in. A missing or damaged log gives none.
    """
    try:
        log = json.loads((pool / LOG_NAME).read_text())
        rows = [{**r, "why": "older"} for r in log["older"]]
        rows += [{**r, "why": "clash"} for r in log["clashes"]]
        rows += [
            {
                "page": r["file"],
                "session": r["session"],
                "why": "skipped",
                "kept_in": r["kept_in"],
            }
            for r in log["skipped"]
            if "kept_in" in r
        ]
        return [
            {
                **{k: v for k, v in r.items() if k != "kept_in"},
                "folder": str(Path(project_key) / r["kept_in"]),
            }
            for r in rows
        ]
    except _ERRORS:
        return []


def _complete(pool: Path) -> bool:
    """Tell whether the pool's migration log carries its completion mark."""
    try:
        log = json.loads((pool / LOG_NAME).read_text())
    except _ERRORS:
        return False
    return isinstance(log, dict) and log.get("complete") is True


def _new_log() -> dict[str, Any]:
    return {
        "schema": LOG_SCHEMA,
        "moved": [],
        "older": [],
        "clashes": [],
        "skipped": [],
        "unknown": [],
    }


def _read_log(pool: Path) -> dict[str, Any]:
    try:
        log = json.loads((pool / LOG_NAME).read_text())
    except FileNotFoundError:
        return _new_log()
    return {**_new_log(), "moved": list(log["moved"])}


def _write_log(pool: Path, log: dict[str, Any]) -> None:
    text = json.dumps(log, indent=2) + "\n"
    path = pool / LOG_NAME
    if not path.exists() or path.read_text() != text:
        write_safely(path, text)


def _skip(sid: str, file: str, why: object, kept_in: str = "") -> dict[str, str]:
    row = {"session": sid, "file": file, "why": str(why)}
    return {**row, "kept_in": kept_in} if kept_in else row


def _members(
    known: Mapping[str, Mapping[str, Any]], pool: Path, project_key: str
) -> dict[str, tuple[Mapping[str, Any], Path]]:
    """Return the sessions of this project with their real folders."""
    members = {}
    for sid, info in known.items():
        folder = Path(info["folder"])
        if folder.resolve() != pool.resolve() and (
            pool_key(info["project"]) == project_key
        ):
            members[sid] = (info, folder)
    legacy = pool.parent / LEGACY_FOLDER
    taken = {folder.resolve() for _, folder in members.values()}
    if legacy.is_dir() and not legacy.is_symlink() and legacy.resolve() not in taken:
        # the shared-page session of PROJ-01 (requirement 10)
        members[LEGACY_FOLDER] = (
            {"title": "Project pages", "agent": "project"},
            legacy,
        )
    return members


def _settings(folder: Path) -> dict[str, Any]:
    """Read the page list and the page settings of a session folder."""
    try:
        meta = json.loads((folder / "session.json").read_text())
    except FileNotFoundError:
        return {"pages": [], "page_meta": {}}
    return {
        "pages": list(meta.get("pages", [])),
        "page_meta": dict(meta.get("page_meta", {})),
    }


def _top_files(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return [p.name for p in folder.iterdir() if _plain_file(p)]


def _pool_pages(pool: Path) -> list[str]:
    """Return the pages on disk in the pool, as the registry counts them (VIEW-11)."""
    names = _top_files(pool)
    return [
        n for n in names if n.endswith(".html") and n[0] != "." and not is_draft_name(n)
    ]


def _plain_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _pages(folder: Path, listed: list[str]) -> list[str]:
    """Return the pages of a session: the listed ones and the HTML files on disk."""
    pages = []
    for name in sorted({*listed, *_top_files(folder)}):
        if not isinstance(name, str) or not _plain_file(folder / name):
            continue
        if name not in listed and not is_page_name(name):
            continue
        try:
            validate_page_type(validate_page_name(name))
        except UnsafePathError:
            continue
        if not is_draft_name(name):
            pages.append(name)
    return pages


def _when(entry: Mapping[str, Any], path: Path) -> float:
    """Return when a page last counted as made: its recorded time, else file time."""
    stamps = []
    for key in ("counted_from", "extended"):
        try:
            stamps.append(clock.seconds_of(entry[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return max(stamps) if stamps else path.stat().st_mtime


def _move(
    page: str,
    sid: str,
    info: Mapping[str, Any],
    folder: Path,
    settings: Mapping[str, Any],
    when: float,
) -> dict[str, Any]:
    """Describe the taking in of one page: copy items and page record."""
    time = clock.iso(when)
    who = {
        "session": sid,
        "title": info.get("title"),
        "agent": info.get("agent"),
        "time": time,
    }
    old = settings["page_meta"].get(page) or {}
    entry = {"counted_from": time, **old}
    data = (folder / page).read_bytes()
    return {
        "page": page,
        "session": sid,
        "time": time,
        "items": _items(folder, page, sid, data),
        "record": {**entry, "created_by": who, "updated_by": who},
    }


def _items(folder: Path, page: str, sid: str, data: bytes) -> list[dict[str, Any]]:
    """List what belongs to a page, the page itself last, each with its digest."""
    history = PageHistory(folder)
    paths = [history.path(page, number) for number, _ in history.versions(page)]
    pictures = re.compile(rf"^{re.escape(page)}\.\d+\.png$")
    comments_dir = folder / COMMENTS_DIR
    if comments_dir.is_dir() and not comments_dir.is_symlink():
        paths += sorted(p for p in comments_dir.iterdir() if pictures.match(p.name))
    stores = ((ANSWERS_DIR, None), (COMMENTS_DIR, sid))
    paths_cards = [(folder / s / f"{page}.json", card) for s, card in stores]
    items = [_item(folder, p, None) for p in paths if _plain_file(p)]
    items += [_item(folder, p, card) for p, card in paths_cards if _plain_file(p)]
    text = data.decode("utf-8", "replace")
    items += [_item(folder, p, None) for p in _named_files(folder, text)]
    for item in items:
        item["digest"] = _digest(item)
    page_item = _item(folder, folder / page, None)
    page_item["digest"] = hashlib.sha256(data).hexdigest()
    return [*items, page_item]


def _item(folder: Path, path: Path, card: str | None) -> dict[str, Any]:
    return {"dest": path.relative_to(folder).as_posix(), "src": str(path), "card": card}


def _named_files(folder: Path, text: str) -> list[Path]:
    """Return the files whose path in the folder appears in the text as a reference."""
    found = []
    for root, dirs, names in os.walk(folder):
        top = Path(root) == folder
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".") and not (top and d == "history")
        )
        for name in sorted(names):
            path = Path(root) / name
            if name.startswith(".") or not _plain_file(path):
                continue
            if top and (name in _SESSION_FILES or name.lower().endswith(".html")):
                continue
            relative = re.escape(path.relative_to(folder).as_posix())
            if re.search(rf"(?<![\w.-]){relative}(?![\w-])(?!\.\w)", text):
                found.append(path)
    return found


def _payload(item: Mapping[str, Any]) -> bytes:
    """Return what the pool's copy of an item must contain."""
    data = Path(item["src"]).read_bytes()
    if item["card"] is None:
        return data
    document = json.loads(data)
    for comment in document["comments"]:
        comment.setdefault("card", item["card"])
    return (json.dumps(document, indent=2) + "\n").encode()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(item: Mapping[str, Any]) -> str:
    if item["card"] is None:
        return _file_digest(Path(item["src"]))
    return hashlib.sha256(_payload(item)).hexdigest()


def _first_clash(
    items: list[dict[str, Any]], pool: Path, claimed: Mapping[str, str]
) -> str | None:
    """Return the first item the pool or an earlier page holds differently."""
    for item in items:
        target = pool / item["dest"]
        held = claimed.get(item["dest"])
        if held is None and target.is_file():
            held = _file_digest(target)
        if held is not None and held != item["digest"]:
            return item["dest"]
    return None


def _take(move: Mapping[str, Any], pool: Path) -> str | tuple[str]:
    """
    Copy one page's items into the pool, never over a different file.

    Returns
    -------
    str or tuple[str]
        The SHA-256 of the copied page, or the clashing destination in a tuple.
    """
    clash = _first_clash(move["items"], pool, {})
    if clash is not None:
        return (clash,)
    digest = ""
    for item in move["items"]:
        data = _payload(item)
        digest = hashlib.sha256(data).hexdigest()
        target = pool / item["dest"]
        if not target.parent.resolve().is_relative_to(pool.resolve()):
            raise ValueError(f"{item['dest']} would land outside the pool")
        make_private_dirs(target.parent)
        try:
            write_safely(target, data, new=True)
        except FileExistsError:
            if _file_digest(target) != digest:
                return (item["dest"],)
            continue  # the same file is there: keep it and its dates
        stat = Path(item["src"]).stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return digest


def _record(move: Mapping[str, Any], digest: str) -> dict[str, Any]:
    sid = move["session"]
    return {
        **move["record"],
        "digest": digest,
        "sessions": {sid: {"time": move["time"], "digest": digest}},
    }


def _unknown(
    members: Mapping[str, tuple[Mapping[str, Any], Path]],
    known: Mapping[str, Mapping[str, Any]],
    pool: Path,
    project_key: str,
) -> tuple[list[str], list[dict[str, str]]]:
    """
    List the folders beside the project's sessions that no known session owns.

    Returns
    -------
    tuple[list[str], list[dict[str, str]]]
        Those folders, and a skip row for each folder that could not be listed.
    """
    owned = {Path(info["folder"]).resolve() for info in known.values()}
    owned |= {folder.resolve() for _, folder in members.values()}
    canvases = {pool.parent.resolve(): pool.parent}
    canvases |= {f.parent.resolve(): f.parent for _, f in members.values()}
    found, unreadable = [], []
    for canvas in canvases.values():
        try:
            paths = list(canvas.iterdir()) if canvas.is_dir() else []
        except OSError as error:
            unreadable.append(_skip("", os.path.relpath(canvas, project_key), error))
            continue
        for path in paths:
            if path.name.startswith("pool-") or not path.is_dir() or path.is_symlink():
                continue
            if path.resolve() not in owned:
                found.append(os.path.relpath(path, project_key))
    return sorted(found), unreadable
