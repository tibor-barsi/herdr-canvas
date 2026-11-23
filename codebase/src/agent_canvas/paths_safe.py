"""Validation of session ids, page names and paths (SEC-08, SES-02, SES-03).

Every value that reaches the file system comes through one of these functions,
so that no operation can read or write outside the session folder or the state
directory.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
SESSION_ENV_VARIABLE = "AGENT_CANVAS_SESSION"
MAX_NAME_LENGTH = 255
# Page types besides HTML, each shown by a viewer document (VIEW-01).
VIEWER_EXTENSIONS = (
    ".md", ".markdown", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
)  # fmt: skip


class UnsafePathError(ValueError):
    """Raised when a path or name could leave its permitted directory."""


class InvalidSessionId(ValueError):
    """Raised when a session id is missing or malformed."""


def validate_session_id(value: str) -> str:
    """
    Check a session id against ``^[A-Za-z0-9_-]{1,64}$``.

    Parameters
    ----------
    value : str
        Candidate id.

    Returns
    -------
    str
        The same id.

    Raises
    ------
    InvalidSessionId
        If the id does not match the pattern.
    """
    if not SESSION_ID_PATTERN.match(value):
        raise InvalidSessionId(
            f"Invalid session id {value!r}: use 1-64 letters, digits, '_' or '-'."
        )
    return value


def resolve_session_id(option: str | None, environ: Mapping[str, str]) -> str:
    """
    Resolve the session id: ``--session``, else ``AGENT_CANVAS_SESSION`` (SES-02).

    Parameters
    ----------
    option : str | None
        Value of ``--session``, if given.
    environ : Mapping[str, str]
        Environment variables.

    Returns
    -------
    str
        A valid session id.

    Raises
    ------
    InvalidSessionId
        If neither source gives an id, or the id is malformed.
    """
    value = option or environ.get(SESSION_ENV_VARIABLE)
    if not value:
        raise InvalidSessionId(
            "No session id. Pass --session or set AGENT_CANVAS_SESSION; "
            "agents without hooks run `agent-canvas session start`."
        )
    return validate_session_id(value)


def validate_page_name(name: str) -> str:
    """
    Check that ``name`` is one plain file name at the top of a session folder.

    Parameters
    ----------
    name : str
        Page name such as ``page.html``.

    Returns
    -------
    str
        The same name.

    Raises
    ------
    UnsafePathError
        For empty names, separators, ``.``/``..``, NUL bytes, over-long names
        and the reserved name ``history``.
    """
    if not name or len(name) > MAX_NAME_LENGTH:
        raise UnsafePathError("Page name is empty or too long.")
    if "\x00" in name or "/" in name or "\\" in name or name in (".", ".."):
        raise UnsafePathError(
            f"Invalid page name {name!r}: pages are plain file names in the "
            "session folder."
        )
    if name == "history":
        raise UnsafePathError("The name 'history' is reserved.")
    return name


def validate_page_type(name: str) -> str:
    """
    Check that a page name has a type the hub can show (VIEW-01).

    Parameters
    ----------
    name : str
        A validated page name.

    Returns
    -------
    str
        The same name.

    Raises
    ------
    UnsafePathError
        For a type other than HTML, Markdown, PDF and the picture types, and
        for dotfiles; the message lists the allowed extensions.
    """
    extension = Path(name).suffix.lower()
    if name.startswith(".") or (
        extension != ".html" and extension not in VIEWER_EXTENSIONS
    ):
        allowed = ", ".join([".html", *VIEWER_EXTENSIONS])
        raise UnsafePathError(
            f"{name!r} cannot be a page: allowed types are {allowed}."
        )
    return name


def ensure_inside(base: Path, candidate: Path) -> Path:
    """
    Resolve ``candidate`` (following symlinks) and require it to lie in ``base``.

    Parameters
    ----------
    base : pathlib.Path
        Permitted directory.
    candidate : pathlib.Path
        Path to check; it need not exist.

    Returns
    -------
    pathlib.Path
        The resolved candidate.

    Raises
    ------
    UnsafePathError
        If the resolved path is outside ``base``.
    """
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise UnsafePathError(f"Path {candidate} is outside {base}.")
    return resolved


def resolve_page(folder: Path, name: str) -> tuple[str, Path]:
    """
    Resolve a page argument of ``show`` to its name and real path (CLI-02).

    Parameters
    ----------
    folder : pathlib.Path
        The session folder.
    name : str
        A plain page name, or an absolute path of a file directly inside
        ``folder``.

    Returns
    -------
    tuple[str, pathlib.Path]
        The page name and its resolved path (which may not exist).

    Raises
    ------
    UnsafePathError
        If the name is unsafe or an absolute path lies outside the folder
        (the message then suggests ``--copy``).
    """
    if "\x00" in name:
        raise UnsafePathError("Page name contains a NUL byte.")
    folder = folder.resolve()
    if name.startswith("/"):
        resolved = Path(name).resolve()
        if resolved.parent != folder:
            raise UnsafePathError(
                f"{name} is not a page directly inside the session folder "
                f"{folder}; use --copy to copy an external file."
            )
        name = resolved.name
    validate_page_name(name)
    return name, ensure_inside(folder, folder / name)


def validate_project(value: str, home: Path) -> Path:
    """
    Check a project directory (SES-03).

    Parameters
    ----------
    value : str
        Absolute path of the project directory.
    home : pathlib.Path
        The user's home directory.

    Returns
    -------
    pathlib.Path
        The resolved project directory.

    Raises
    ------
    UnsafePathError
        If the path is not an absolute existing directory, or is ``home`` or
        one of its ancestors (the message asks for ``--project``).
    """
    if not value or "\x00" in value or not value.startswith("/"):
        raise UnsafePathError(f"Project path {value!r} must be an absolute path.")
    project = Path(value).resolve()
    if not project.is_dir():
        raise UnsafePathError(f"Project directory {project} does not exist.")
    resolved_home = home.resolve()
    if project == resolved_home or project in resolved_home.parents:
        raise UnsafePathError(
            f"Project {project} is the home directory or contains it; "
            "pass --project with the project directory."
        )
    return project
