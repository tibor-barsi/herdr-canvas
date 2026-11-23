"""Serving session files to the sandboxed frame (PAGE-02, PAGE-03, SEC-06)."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

from agent_canvas.files_safe import EVENTS_FILE

HELPER_TAG = '<script src="/static/helper.js" data-agent-canvas-helper></script>'
# Defines the block elements (BLK-08); a module, so it runs after parsing.
BLOCK_LOADER_TAG = (
    '<script type="module" src="/static/blocks/loader.js"'
    " data-agent-canvas-helper></script>"
)
INJECTED_TAGS = HELPER_TAG + BLOCK_LOADER_TAG

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("model/stl", ".stl")
mimetypes.add_type("model/step", ".step")
mimetypes.add_type("model/step", ".stp")
mimetypes.add_type("application/json", ".json")

_HEAD_OPEN = re.compile(rb"<head(?:\s[^>]*)?>", re.IGNORECASE)
_HTML_OPEN = re.compile(rb"<html(?:\s[^>]*)?>", re.IGNORECASE)


def frame_csp(port: int, token: str) -> str:
    """
    Build the Content-Security-Policy of a frame response (SEC-06).

    Parameters
    ----------
    port : int
        Hub port.
    token : str
        Page token of the session.

    Returns
    -------
    str
        The header value.
    """
    f = f"http://localhost:{port}"
    t = token
    return (
        "default-src 'none'; "
        f"script-src {f}/static/ {f}/s/{t}/ 'unsafe-inline' 'unsafe-eval' "
        "'wasm-unsafe-eval'; "
        f"style-src {f}/static/ {f}/s/{t}/ 'unsafe-inline'; "
        f"img-src {f}/s/{t}/ {f}/static/ data: blob:; "
        f"font-src {f}/static/ data:; "
        f"media-src {f}/s/{t}/ data: blob:; "
        f"connect-src {f}/s/{t}/ {f}/static/ data: blob:; "
        "worker-src blob:; form-action 'none'; frame-src 'none'; base-uri 'none'"
    )


# Files the hub keeps in the session folder; a page (untrusted) must not read them.
HUB_FILES = frozenset({EVENTS_FILE, "session.json"})


def resolve_session_file(folder: Path, relative: str) -> Path | None:
    """
    Resolve ``relative`` inside ``folder`` or return None (PAGE-03).

    Rejects parent segments, absolute paths, backslashes, NUL bytes, anything
    under ``history/``, dotfiles, the hub's own top-level files
    (``events.jsonl``, ``session.json``) and symlinks that leave the folder.

    Parameters
    ----------
    folder : pathlib.Path
        Resolved session folder.
    relative : str
        Request path below the page token, already percent-decoded.

    Returns
    -------
    pathlib.Path | None
        An existing regular file inside ``folder``, otherwise None.
    """
    if not relative or "\x00" in relative or "\\" in relative:
        return None
    parts = relative.split("/")
    if relative.startswith("/") or any(p in ("", ".", "..") for p in parts):
        return None
    if parts[0] == "history" or any(p.startswith(".") for p in parts):
        return None
    if len(parts) == 1 and parts[0] in HUB_FILES:
        return None
    candidate = (folder / relative).resolve()
    if not candidate.is_relative_to(folder) or not candidate.is_file():
        return None
    return candidate


def source_digest(content: bytes) -> str:
    """Return a short digest of a page source (PAGE-13)."""
    return hashlib.sha256(content).hexdigest()[:16]


def inject_helper(html: bytes, digest: str | None = None) -> bytes:
    """
    Put the helper and block loader tags first in ``<head>`` (PAGE-02).

    A fragment is wrapped in a minimal document first.

    Parameters
    ----------
    html : bytes
        The agent's HTML, a full document or a fragment.
    digest : str, optional
        ``source_digest`` of ``html``, given to the helper as ``data-source``.

    Returns
    -------
    bytes
        HTML whose ``<head>`` starts with the helper and block loader tags.
    """
    tag = INJECTED_TAGS
    if digest is not None:
        tag = tag.replace(
            " data-agent-canvas-helper",
            f' data-source="{digest}" data-agent-canvas-helper',
            1,
        )
    tag = tag.encode()
    if match := _HEAD_OPEN.search(html):
        return html[: match.end()] + tag + html[match.end() :]
    if match := _HTML_OPEN.search(html):
        head = b"<head><meta charset=utf-8>" + tag + b"</head>"
        return html[: match.end()] + head + html[match.end() :]
    return (
        b"<!doctype html><html><head><meta charset=utf-8>"
        + tag
        + b"</head><body>"
        + html
        + b"</body></html>"
    )


def content_type(path: Path) -> str:
    """Return the Content-Type for ``path``."""
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed in ("application/json",):
        return f"{guessed}; charset=utf-8"
    return guessed
