"""Viewer documents for Markdown, PDF and picture pages (VIEW-01, VIEW-02)."""

from __future__ import annotations

import html
from pathlib import Path

from agent_canvas.hub.serve import inject_helper

# One viewer script per type; the extensions come from the page-name rule.
_TYPE_OF_EXTENSION = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
}


def viewer_type(name: str) -> str | None:
    """
    Return the viewer type of a page name.

    Parameters
    ----------
    name : str
        Page file name.

    Returns
    -------
    str | None
        ``markdown``, ``pdf`` or ``image``; None for HTML and other files.
    """
    return _TYPE_OF_EXTENSION.get(Path(name).suffix.lower())


def viewer_document(name: str) -> bytes:
    """
    Build the HTML document the frame loads for a viewer page (VIEW-02).

    The helper and block loader are injected as for HTML pages (PAGE-02), then
    the one script of the page's type. The script reads the page's own URL to
    find the file and the version.

    Parameters
    ----------
    name : str
        Page file name with a viewer extension.

    Returns
    -------
    bytes
        The document.

    Raises
    ------
    ValueError
        If ``name`` is not a viewer page.
    """
    kind = viewer_type(name)
    if kind is None:
        raise ValueError(f"{name!r} is not a viewer page.")
    document = (
        "<!doctype html><html><head><meta charset=utf-8>"
        f"<title>{html.escape(name)}</title></head><body>"
        f'<script src="/static/viewer/{kind}.js"></script></body></html>'
    )
    return inject_helper(document.encode())
