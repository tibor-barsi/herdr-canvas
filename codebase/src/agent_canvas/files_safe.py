"""Safe file writes, set-asides and the session-folder names, in one place."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

EVENTS_FILE = "events.jsonl"
COMMENTS_DIR = ".comments"
ANSWERS_DIR = ".answers"
HISTORY_PAGES = Path("history") / "pages"


def write_safely(
    path: Path,
    content: str | bytes,
    mode: int | None = None,
    exact: bool = False,
    new: bool = False,
) -> None:
    """
    Write ``content`` to ``path`` through a temporary file and an atomic rename.

    The temporary file has a unique, short name in the same folder (a long target
    name must not make it too long), so a stale one never lends its permissions.
    Any error removes it and leaves the old file.

    Parameters
    ----------
    path : pathlib.Path
        Target file; its folder must exist.
    content : str or bytes
        Text is written as UTF-8.
    mode : int, optional
        Permissions of the new file, reduced by the process umask like
        ``os.open``. None leaves the default (0o666 under the umask).
    exact : bool, optional
        Set ``mode`` exactly, whatever the umask (needs ``mode``).
    new : bool, optional
        Never replace a file: raise ``FileExistsError`` if ``path`` exists, even
        one made after the call began (the rename is a hard link then).
    """
    data = content.encode() if isinstance(content, str) else content
    temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            if exact:
                os.fchmod(handle.fileno(), mode)
            handle.write(data)
        if new:
            os.link(temporary, path)
            temporary.unlink()
        else:
            os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def set_aside(path: Path) -> None:
    """Rename a damaged file to ``<name>.bad``; never raises (a failure is logged)."""
    bad = path.with_name(path.name + ".bad")
    try:
        os.replace(path, bad)
    except OSError as error:
        logger.warning("%s does not parse and cannot be set aside: %s", path, error)
    else:
        logger.warning("%s does not parse; renamed to %s", path, bad.name)
