"""History cleanup (CLI-11): plan what to delete, then optionally delete it.

``plan_session`` only looks; ``apply_plan`` deletes. The hub route calls both
(a dry run stops after the plan) so that the listed paths and the deleted
paths come from the same plan. Only the standard library is imported here, so
the command line can use :func:`parse_age` without loading the hub.

What is deleted:

* ``--older-than``: files under ``history/`` older than the age (by modification
  time) and lines of ``events.jsonl`` older than the age (by their ``time``).
  Pages and other files of the session folder are never touched.
* ``--session``: everything under ``history/``, ``.comments/`` and ``.answers/``
  and ``events.jsonl``. ``--older-than`` never touches the last two (current
  state, not history). If the session has ended, the whole session folder goes
  as well, and the session is forgotten.
* An event that is still queued is kept, with its ``history/sends`` files,
  unless ``force`` is set; its id is listed as ``kept_queued``. A session that
  keeps such an event is not removed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_canvas.files_safe import ANSWERS_DIR, COMMENTS_DIR, EVENTS_FILE, write_safely

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

AGE = re.compile(r"^(\d+)([smhdw])$")
AGE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
SEND_FILE = re.compile(r"^(\d{4,})\.(json|png)$")
RESERVED_DEFAULT_AGE = 7 * 24 * 3600  # seconds; unused reserved ids (SES-10)
HISTORY = "history"
STATE_DIRECTORIES = (COMMENTS_DIR, ANSWERS_DIR)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class CleanupError(ValueError):
    """
    A cleanup request that cannot be carried out.

    Parameters
    ----------
    message : str
        Human-readable text.
    code : str, optional
        CLI error code: ``failed`` (default) or ``no-session``.
    """

    def __init__(self, message: str, code: str = "failed") -> None:
        super().__init__(message)
        self.code = code


def parse_age(text: str) -> int:
    """
    Parse an age such as ``30d`` or ``12h`` into seconds.

    Parameters
    ----------
    text : str
        A positive whole number and one unit: ``s``, ``m``, ``h``, ``d``, ``w``.

    Returns
    -------
    int
        The age in seconds.

    Raises
    ------
    CleanupError
        If ``text`` is not of that form or is zero.
    """
    match = AGE.match(text) if isinstance(text, str) else None
    seconds = int(match[1]) * AGE_UNITS[match[2]] if match else 0
    if seconds <= 0:
        raise CleanupError(
            f"Invalid age {text!r}: use a positive number and s, m, h, d or w, "
            "for example 30d or 12h."
        )
    return seconds


@dataclass
class SessionPlan:
    """
    What cleanup would do in one session.

    Attributes
    ----------
    session_id : str
        Session id.
    folder : pathlib.Path
        Session folder.
    files : list[pathlib.Path]
        Files (and symlinks) to delete.
    bytes : int
        Size of the files plus the event lines to be cut.
    kept_queued : list[str]
        Queued events that were spared.
    events_keep : list[str] | None
        Lines that stay in ``events.jsonl``; None if the file is not changed.
    remove_folder : bool
        Delete the whole session folder and forget the session.
    """

    session_id: str
    folder: Path
    files: list[Path] = field(default_factory=list)
    bytes: int = 0
    kept_queued: list[str] = field(default_factory=list)
    events_keep: list[str] | None = None
    remove_folder: bool = False

    def listed(self) -> list[str]:
        """Return the paths this plan deletes or cuts, as strings."""
        paths = [str(path) for path in self.files]
        if self.events_keep is not None:
            paths.append(str(self.folder / EVENTS_FILE))
        if self.remove_folder:
            paths.append(str(self.folder))
        return paths


def plan_session(
    session_id: str,
    folder: Path,
    queued: set[str],
    *,
    cutoff: float | None,
    force: bool,
    ended: bool,
) -> SessionPlan:
    """
    Decide what to delete in one session.

    Parameters
    ----------
    session_id : str
        Session id.
    folder : pathlib.Path
        Session folder (never followed through symbolic links).
    queued : set[str]
        Ids of the session's events that are still queued.
    cutoff : float | None
        Delete what is older than this time (seconds since the epoch); None
        deletes all history (``--session``).
    force : bool
        Also delete queued events.
    ended : bool
        The session has ended; with ``cutoff`` None the whole folder may go.

    Returns
    -------
    SessionPlan
        The plan; nothing has been changed yet.
    """
    plan = SessionPlan(session_id, folder)
    protected = set() if force else queued
    if cutoff is None and ended and not protected and not folder.is_symlink():
        plan.remove_folder = True
        plan.files = sorted(_files_below(folder))
        plan.bytes = sum(_size(path) for path in plan.files)
        return plan
    spared: set[str] = set()
    _plan_history(plan, cutoff, protected, spared)
    _plan_events(plan, cutoff, protected, spared)
    if cutoff is None:
        _plan_state(plan)
    plan.kept_queued = sorted(spared)
    return plan


def apply_plan(plan: SessionPlan) -> None:
    """
    Carry out a plan: delete the files, cut ``events.jsonl`` or the folder.

    Parameters
    ----------
    plan : SessionPlan
        A plan from :func:`plan_session`.
    """
    if plan.remove_folder:
        if plan.folder.exists() or plan.folder.is_symlink():
            shutil.rmtree(plan.folder)
        return
    for path in plan.files:
        path.unlink(missing_ok=True)
    if plan.events_keep is None:
        return
    target = plan.folder / EVENTS_FILE
    if not plan.events_keep:
        target.unlink(missing_ok=True)
        return
    write_safely(target, "".join(line + "\n" for line in plan.events_keep))


# ---- planning helpers -----------------------------------------------------


def _files_below(directory: Path) -> Iterator[Path]:
    """Yield files and symlinks below ``directory`` without following links."""
    for root, names, files in os.walk(directory, followlinks=False):
        base = Path(root)
        for name in files:
            yield base / name
        for name in list(names):
            if (base / name).is_symlink():
                names.remove(name)
                yield base / name


def _size(path: Path) -> int:
    """Return the size of a file; a symbolic link counts as zero."""
    try:
        return path.lstat().st_size if not path.is_symlink() else 0
    except OSError:
        return 0


def _is_old(path: Path, cutoff: float | None) -> bool:
    """Tell whether a file is older than the cutoff (always, if no cutoff)."""
    if cutoff is None:
        return True
    try:
        return path.lstat().st_mtime < cutoff
    except OSError:
        return False


def _send_event_ids(directory: Path) -> dict[str, str]:
    """Map send numbers (``0003``) to the event id in their ``.json`` record."""
    found: dict[str, str] = {}
    for path in directory.glob("*.json"):
        match = SEND_FILE.match(path.name)
        if match is None or path.is_symlink():
            continue
        try:
            event_id = json.loads(path.read_text()).get("event")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(event_id, str):
            found[match[1]] = event_id
    return found


def _plan_history(
    plan: SessionPlan, cutoff: float | None, protected: set[str], spared: set[str]
) -> None:
    """Add the old files of ``history/`` to the plan."""
    history = plan.folder / HISTORY
    if history.is_symlink() or not history.is_dir():
        return
    sends = history / "sends"
    owners = _send_event_ids(sends) if sends.is_dir() else {}
    for path in sorted(_files_below(history)):
        if not _is_old(path, cutoff):
            continue
        match = SEND_FILE.match(path.name) if path.parent == sends else None
        owner = owners.get(match[1]) if match else None
        if owner in protected:
            spared.add(owner)
            continue
        plan.files.append(path)
        plan.bytes += _size(path)


def _plan_state(plan: SessionPlan) -> None:
    """Add every file of ``.comments/`` and ``.answers/`` to the plan."""
    for name in STATE_DIRECTORIES:
        directory = plan.folder / name
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in sorted(_files_below(directory)):
            plan.files.append(path)
            plan.bytes += _size(path)


def _record_time(record: Any) -> float | None:
    """Return the epoch time of an event-log record, or None if unreadable."""
    if not isinstance(record, dict) or not isinstance(record.get("time"), str):
        return None
    try:
        stamp = datetime.strptime(record["time"], TIME_FORMAT)
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC).timestamp()


def _plan_events(
    plan: SessionPlan, cutoff: float | None, protected: set[str], spared: set[str]
) -> None:
    """Decide which lines of ``events.jsonl`` stay."""
    path = plan.folder / EVENTS_FILE
    if path.is_symlink() or not path.is_file():
        return
    keep: list[str] = []
    cut = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        moment = _record_time(record)
        # A line whose time cannot be read is only cut when everything goes.
        old = cutoff is None or (moment is not None and moment < cutoff)
        is_queued = (
            isinstance(record, dict)
            and record.get("record") == "event"
            and record.get("id") in protected
        )
        if is_queued and old:
            spared.add(record["id"])
        if old and not is_queued:
            cut += len(line.encode()) + 1
        else:
            keep.append(line)
    if cut:
        plan.events_keep = keep
        plan.bytes += cut


# ---- the request ------------------------------------------------------------


@dataclass(frozen=True)
class CleanupRequest:
    """
    A validated ``POST /api/cleanup`` body.

    Attributes
    ----------
    older_than : int | None
        Age in seconds (``--older-than``).
    session : str | None
        Session id (``--session``).
    project : str | None
        Absolute project directory limiting the scope.
    yes : bool
        Really delete; otherwise a dry run.
    force : bool
        Also delete queued events.
    """

    older_than: int | None
    session: str | None
    project: str | None
    yes: bool
    force: bool

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> CleanupRequest:
        """
        Validate a request body.

        Parameters
        ----------
        body : dict[str, Any]
            Keys ``older_than``, ``session``, ``project``, ``yes``, ``force``.

        Returns
        -------
        CleanupRequest
            The request.

        Raises
        ------
        CleanupError
            If not exactly one of ``older_than`` and ``session`` is given, or a
            value has the wrong type or form.
        """
        age, session = body.get("older_than"), body.get("session")
        project = body.get("project")
        if (age is None) == (session is None):
            raise CleanupError("Give exactly one of older_than and session.")
        if session is not None and not isinstance(session, str):
            raise CleanupError("session must be a string.")
        if project is not None and not isinstance(project, str):
            raise CleanupError("project must be a string.")
        return cls(
            None if age is None else parse_age(age),
            session,
            str(Path(project).resolve()) if project else None,
            body.get("yes") is True,
            body.get("force") is True,
        )


def run_cleanup(
    registry: Any,
    state: Any,
    events: Any,
    request: CleanupRequest,
    running: Callable[[str], bool] | None = None,
) -> dict:
    """
    Plan and (with ``yes``) carry out a cleanup over the registered sessions.

    Parameters
    ----------
    registry : SessionRegistry
        Session registry; sessions it forgets disappear from ``sessions.json``.
    state : HubState
        Hub state; removed sessions are unregistered.
    events : EventService
        Event service; logs are reloaded after their file changed.
    request : CleanupRequest
        What to clean.
    running : Callable[[str], bool] | None, optional
        True for a session the agent table holds as running; its reserved id
        is never pruned (SES-10).

    Returns
    -------
    dict
        ``{"dry_run", "deleted", "bytes", "kept_queued"}`` (requirements 5.7).

    Raises
    ------
    CleanupError
        ``no-session`` if the session is unknown or in another project.
    """
    cutoff = None if request.older_than is None else time.time() - request.older_than
    result: dict[str, Any] = {
        "dry_run": not request.yes,
        "deleted": [],
        "bytes": 0,
        "kept_queued": [],
    }
    if request.yes and request.session is None:
        # Reserved ids (SES-10) have no files; this only forgets old ones.
        registry.prune_reserved(
            RESERVED_DEFAULT_AGE if request.older_than is None else request.older_than,
            keep=running,
        )
    for meta in _scope(registry, request):
        queued = {
            e["id"] for e in events.log(meta["id"]).all() if e["state"] == "queued"
        }
        plan = plan_session(
            meta["id"],
            registry.folder_of(meta),
            queued,
            cutoff=cutoff,
            force=request.force,
            ended=meta["state"] == "ended",
        )
        result["deleted"] += plan.listed()
        result["bytes"] += plan.bytes
        result["kept_queued"] += plan.kept_queued
        if request.yes:
            apply_plan(plan)
            _forget(registry, state, events, plan)
    return result


def _scope(registry: Any, request: CleanupRequest) -> list[dict[str, Any]]:
    """Return the ``session.json`` contents of the sessions to clean."""
    if request.session is None:
        return registry.list(True, request.project)
    from agent_canvas.hub.registry import (
        RegistryError,
        is_project_id,
        validate_or_raise,
    )

    try:
        meta = registry.get(validate_or_raise(request.session))
    except RegistryError as error:
        raise CleanupError(str(error), "no-session") from error
    if meta is None or request.project not in (None, meta.project):
        raise CleanupError(f"Unknown session {request.session}.", "no-session")
    if is_project_id(meta.id):
        raise CleanupError("The project pages session is never cleaned.")
    return [dict(meta.raw)]


def _forget(registry: Any, state: Any, events: Any, plan: SessionPlan) -> None:
    """Bring the in-memory hub in line with the files after a deletion."""
    if plan.remove_folder:
        registry.forget(plan.session_id)
        state.unregister_session(plan.session_id)
        events.drop(plan.session_id)
    elif plan.events_keep is not None:
        events.log(plan.session_id).reload()
