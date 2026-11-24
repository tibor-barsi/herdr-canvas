"""Private drafts of pages (DRAFT-01, DRAFT-03, POOL-11).

A session's draft of ``NAME.html`` is ``NAME.TAG.draft.html`` in the same pool
folder, TAG being the session's draft tag, so that relative asset paths are the
same for both and two sessions never share a draft. The owner never sees a
draft: the hub does not treat it as a page. Only the standard library is
imported, so that the command line and the hub can share these helpers.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agent_canvas.files_safe import write_safely

DRAFT_SUFFIX = ".draft.html"
# A page name never ends in this, so a draft's tag is never part of a name (A-1006).
TAG_ENDING = re.compile(r"\.[0-9a-f]{8}$", re.IGNORECASE)


class DraftError(ValueError):
    """A draft that cannot be published; the message names the file."""


def is_draft_name(name: str) -> bool:
    """
    Tell whether a file name is the name of a draft (DRAFT-01).

    Parameters
    ----------
    name : str
        File name without directories.

    Returns
    -------
    bool
        True for ``<stem>.draft.html`` with a non-empty stem that does not
        start with a dot; the comparison ignores case.
    """
    lowered = name.lower()
    return (
        lowered.endswith(DRAFT_SUFFIX)
        and len(lowered) > len(DRAFT_SUFFIX)
        and not name.startswith(".")
    )


def session_tag(session_id: str) -> str:
    """Return a session's draft tag: 8 hexadecimal characters of SHA-256 (A-1016)."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:8]


def published_name_for(name: str) -> str:
    """
    Return the page name a draft is published as.

    Parameters
    ----------
    name : str
        ``NAME.TAG.draft.html``, ``NAME.draft.html``, or a page name with or
        without ``.html``.

    Returns
    -------
    str
        ``NAME.html``.
    """
    if is_draft_name(name):
        return f"{TAG_ENDING.sub('', name[: -len(DRAFT_SUFFIX)])}.html"
    return name if name.lower().endswith(".html") else f"{name}.html"


def draft_name_for(name: str, tag: str | None = None) -> str:
    """
    Return the draft file name of a page.

    Parameters
    ----------
    name : str
        A page name with or without ``.html``, or a draft name.
    tag : str | None, optional
        The session's draft tag; without it the untagged name.

    Returns
    -------
    str
        ``NAME.TAG.draft.html``, or ``NAME.draft.html`` without a tag.
    """
    stem = published_name_for(name)[:-5]
    return f"{stem}.{tag}{DRAFT_SUFFIX}" if tag else f"{stem}{DRAFT_SUFFIX}"


def publish_draft(folder: Path, page: str, tag: str | None = None) -> Path:
    """
    Copy the session's draft over ``NAME.html`` atomically (DRAFT-03, POOL-11).

    The copy goes to a temporary dotfile in the same folder and is renamed
    over the page, so that a reader (the page watcher, a browser) sees the old
    or the new content completely. The draft stays in place.

    Parameters
    ----------
    folder : pathlib.Path
        Pool or session folder.
    page : str
        Page name (``NAME.html``) or the draft's name.
    tag : str | None, optional
        The session's draft tag; without it the untagged draft is used.

    Returns
    -------
    pathlib.Path
        The published page.

    Raises
    ------
    DraftError
        If the draft does not exist or cannot be copied.
    """
    target = folder / published_name_for(page)
    draft = folder / draft_name_for(page, tag)
    if not draft.is_file():
        untagged = folder / draft_name_for(page)
        if tag and untagged.is_file():
            raise DraftError(
                f"No draft {draft.name} in {folder}. Drafts carry your tag: "
                f"rename {untagged.name} to {draft.name}, then publish again."
            )
        raise DraftError(f"No draft {draft.name} in {folder}; write it first.")
    try:
        write_safely(target, draft.read_bytes(), 0o644, exact=True)
    except OSError as error:
        raise DraftError(f"Could not publish {draft.name}: {error}") from error
    return target
