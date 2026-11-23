"""Build identity of the shell: the version and the served static files (SHELL-01).

A shell tab that stays open while the hub is reinstalled keeps running the old
JavaScript. Both sides know the identity: the hub computes it at start-up, the
shell page records the one it was loaded with, and they are compared on every
(re)connect.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

VENDOR_DIR = "vendor"
VENDOR_MANIFEST = "MANIFEST.json"
BUILD_ID_LENGTH = 12


def compute_build_id(static_dir: Path, version: str) -> str:
    """
    Hash the package version and the files below ``static_dir``.

    Vendored libraries are large and never edited by hand, so they count
    through ``vendor/MANIFEST.json`` (a SHA-256 per file) instead of their
    bytes.

    Parameters
    ----------
    static_dir : pathlib.Path
        The directory the hub serves below ``/static``.
    version : str
        The package version.

    Returns
    -------
    str
        A short hexadecimal identity that changes when the version, a file
        name or a file's content changes.
    """
    digest = hashlib.sha256(f"version:{version}\0".encode())
    for path in sorted(p for p in static_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(static_dir)
        in_vendor = relative.parts[0] == VENDOR_DIR
        if in_vendor and relative.name != VENDOR_MANIFEST:
            continue
        digest.update(f"{relative.as_posix()}\0".encode())
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:BUILD_ID_LENGTH]
