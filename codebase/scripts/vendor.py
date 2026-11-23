"""Download and lay out the vendored browser libraries (run by hand).

Usage: ``uv run python scripts/vendor.py [LIBRARY ...]`` (with names, only those
libraries are refreshed)

Every library is fetched from the npm registry at a pinned version, the
tarball is verified against a pinned sha512 integrity string, and the listed
files are copied unmodified into ``src/agent_canvas/static/vendor``. The result
is described by ``MANIFEST.json`` (with a SHA-256 per file). Tests never call
this script; they only verify its committed output.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

VENDOR_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "agent_canvas" / "static" / "vendor"
)
REGISTRY = "https://registry.npmjs.org"


@dataclass(frozen=True)
class Library:
    """One npm package and the files taken from it.

    ``files`` maps a path inside the tarball (without the leading ``package/``)
    to a path relative to the vendor directory; a source ending in ``/*``
    stands for every file below that folder. ``licenses`` maps tarball paths
    to file names below ``licenses/``.
    """

    name: str
    version: str
    license: str
    integrity: str
    files: dict[str, str]
    licenses: dict[str, str]

    @property
    def tarball_url(self) -> str:
        """Registry URL of the tarball."""
        base = self.name.rsplit("/", 1)[-1]
        return f"{REGISTRY}/{self.name}/-/{base}-{self.version}.tgz"


def _katex_fonts() -> dict[str, str]:
    """Map the KaTeX woff2 fonts (the only format modern Chromium needs)."""
    names = (
        "AMS-Regular Caligraphic-Bold Caligraphic-Regular Fraktur-Bold "
        "Fraktur-Regular Main-Bold Main-BoldItalic Main-Italic Main-Regular "
        "Math-BoldItalic Math-Italic SansSerif-Bold SansSerif-Italic "
        "SansSerif-Regular Script-Regular Size1-Regular Size2-Regular "
        "Size3-Regular Size4-Regular Typewriter-Regular"
    ).split()
    return {
        f"dist/fonts/KaTeX_{n}.woff2": f"katex/fonts/KaTeX_{n}.woff2" for n in names
    }


def _pdfjs_data(folder: str) -> dict[str, str]:
    """Map a pdfjs-dist data folder; ``build_entry`` expands the ``/*`` ending."""
    return {f"{folder}/*": f"pdfjs-dist/{folder}/*"}


LIBRARIES = [
    Library(
        "idiomorph",
        "0.8.0",
        "0BSD",
        "sha512-R47JBL+6jHDQvcnbppIUtXXcxi5h6+wuCEEZXnRhUltsgzPFKzThL5PuHppP9ypJuy+7WawcY1TsSBD/iQbMhw==",
        {"dist/idiomorph.min.js": "idiomorph/idiomorph.min.js"},
        {"LICENSE": "idiomorph.LICENSE"},
    ),
    Library(
        "@zumer/snapdom",
        "3.3.6",
        "MIT",
        "sha512-Ynxm2UJz6/diX/M2Xi9R5xqAgg/MrfsiEVJqAjUzcDI1kwnlfK+3F2tiP3BQJWgRouuYjT07cxeSYs31zgR2GA==",
        {"dist/snapdom.mjs": "snapdom/snapdom.mjs"},
        {"LICENSE": "snapdom.LICENSE"},
    ),
    Library(
        "@medv/finder",
        "4.0.2",
        "MIT",
        "sha512-RraNY9SCcx4KZV0Dh6BEW6XEW2swkqYca74pkFFRw6hHItSHiy+O/xMnpbofjYbzXj0tSpBGthUF1hHTsr3vIQ==",
        {"finder.js": "finder/finder.js"},
        {"LICENSE": "finder.LICENSE"},
    ),
    Library(
        "plotly.js-dist-min",
        "4.1.2",
        "MIT",
        "sha512-VSmS9KVNun16S8qFYYp9LlL/XBby4ueeGqB+K9AqRCVsup8dSpGULap4UyR1f2mz4pV3qjWp1sR5chwLgIKPoQ==",
        {"plotly.min.js": "plotly.js-dist-min/plotly.min.js"},
        {"LICENSE": "plotly.LICENSE"},
    ),
    Library(
        "three",
        "0.186.1",
        "MIT",
        "sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA==",
        {
            "build/three.module.js": "three/three.module.js",
            "build/three.core.js": "three/three.core.js",
            "examples/jsm/loaders/STLLoader.js": "three/addons/STLLoader.js",
            "examples/jsm/controls/OrbitControls.js": "three/addons/OrbitControls.js",
            "examples/jsm/loaders/GLTFLoader.js": "three/addons/GLTFLoader.js",
            # GLTFLoader imports these two as ../utils/ (three/utils/)
            "examples/jsm/utils/BufferGeometryUtils.js": (
                "three/utils/BufferGeometryUtils.js"
            ),
            "examples/jsm/utils/SkeletonUtils.js": "three/utils/SkeletonUtils.js",
        },
        {"LICENSE": "three.LICENSE"},
    ),
    Library(
        "occt-import-js",
        "0.0.23",
        "LGPL-2.1",
        "sha512-RFfYQXYFX5C1mB1Aywm0ShcUKzXOr/VzTnlzhBSDJOR6YCAPt1HYCzeXWg1vwwjn/cUxwqRNhhtf1dlewoZYCQ==",
        {
            "dist/occt-import-js.js": "occt-import-js/occt-import-js.js",
            "dist/occt-import-js.wasm": "occt-import-js/occt-import-js.wasm",
        },
        {
            "LICENSE.md": "occt-import-js.LICENSE.md",
            "dist/license.occt-import-js.txt": "occt-import-js.license.txt",
            "dist/license.occt.txt": "occt.license.txt",
        },
    ),
    Library(
        "marked",
        "18.1.1",
        "MIT",
        "sha512-zEGgrtUG8crk+TrMacJSVABU4DYDDkS8uqgU3ohrn/2fW9C2AEfUrO3m6IhpIpQpl7YcVpiXXC9cSMWDANT3dg==",
        {"lib/marked.esm.js": "marked/marked.esm.js"},
        {"LICENSE": "marked.LICENSE"},
    ),
    Library(
        "katex",
        "0.19.0",
        "MIT",
        "sha512-v6Tznz3zJ7u3niRCoDTsumM2+HA2XXcCu+WAacCeHD2z3p9A9Ks987o5FzfTGBN0e8A0vjEgIDvLbICrXpdw/Q==",
        {
            "dist/katex.min.js": "katex/katex.min.js",
            "dist/katex.min.css": "katex/katex.min.css",
            **_katex_fonts(),
        },
        {"LICENSE": "katex.LICENSE"},
    ),
    # pdfjs-dist: the modern build (not legacy/): it runs as plain ES modules in
    # current Chromium without a bundler or polyfills. Only the minified
    # library and worker are taken (no source maps, no sandbox build).
    Library(
        "pdfjs-dist",
        "4.10.38",
        "Apache-2.0",
        "sha512-/Y3fcFrXEAsMjJXeL9J8+ZG9U01LbuWaYypvDW2ycW1jL269L3js3DVBjDJ0Up9Np1uqDXsDrRihHANhZOlwdQ==",
        {
            "build/pdf.min.mjs": "pdfjs-dist/pdf.min.mjs",
            "build/pdf.worker.min.mjs": "pdfjs-dist/pdf.worker.min.mjs",
            **_pdfjs_data("cmaps"),
            **_pdfjs_data("standard_fonts"),
        },
        {"LICENSE": "pdfjs-dist.LICENSE"},
    ),
]


def fetch_verified(library: Library) -> dict[str, bytes]:
    """
    Download a tarball, verify its integrity and return its members.

    Parameters
    ----------
    library : Library
        The package to fetch.

    Returns
    -------
    dict[str, bytes]
        File contents keyed by path inside the tarball (``package/`` removed).

    Raises
    ------
    RuntimeError
        If the tarball does not match the pinned integrity string.
    """
    with urllib.request.urlopen(library.tarball_url, timeout=120) as response:
        data = response.read()
    algorithm, _, expected = library.integrity.partition("-")
    actual = base64.b64encode(hashlib.new(algorithm, data).digest()).decode()
    if actual != expected:
        raise RuntimeError(f"Integrity mismatch for {library.name}@{library.version}")
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if member.isfile() and (handle := archive.extractfile(member)):
                members[member.name.removeprefix("package/")] = handle.read()
    return members


def build_entry(library: Library, members: dict[str, bytes]) -> dict:
    """Write one library's files below the vendor directory; return its entry."""
    files = []
    wanted: dict[str, str] = {}
    for source, target in library.files.items():
        if source.endswith("/*"):
            folder = source[:-1]
            wanted.update(
                {
                    m: target[:-1] + m[len(folder) :]
                    for m in members
                    if m.startswith(folder)
                }
            )
        else:
            wanted[source] = target
    for source, target in sorted(wanted.items(), key=lambda kv: kv[1]):
        content = members[source]
        _write(VENDOR_DIR / target, content)
        files.append({"path": target, "sha256": hashlib.sha256(content).hexdigest()})
    license_files = []
    for source, name in sorted(library.licenses.items(), key=lambda kv: kv[1]):
        _write(VENDOR_DIR / "licenses" / name, members[source])
        license_files.append(f"licenses/{name}")
    return {
        "name": library.name,
        "version": library.version,
        "license": library.license,
        "source_url": library.tarball_url,
        "integrity": library.integrity,
        "license_files": license_files,
        "files": files,
    }


def _write(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def main(only: list[str] | None = None) -> int:
    """
    Rebuild the vendor directory and manifest.

    Parameters
    ----------
    only : list[str] | None, optional
        Names of libraries to refresh. The other libraries and their
        manifest entries stay as they are. Default is None (everything is
        rebuilt from scratch).

    Returns
    -------
    int
        Process exit code.
    """
    kept: dict[str, dict] = {}
    if only:
        manifest_file = VENDOR_DIR / "MANIFEST.json"
        old = json.loads(manifest_file.read_text(encoding="utf-8"))
        kept = {entry["name"]: entry for entry in old["libraries"]}
        for name in only:
            shutil.rmtree(VENDOR_DIR / name, ignore_errors=True)
    elif VENDOR_DIR.exists():
        shutil.rmtree(VENDOR_DIR)
    entries = []
    for library in LIBRARIES:
        if only and library.name not in only:
            entries.append(kept[library.name])
            continue
        print(f"fetching {library.name}@{library.version}", file=sys.stderr)
        entries.append(build_entry(library, fetch_verified(library)))
    manifest = {"generated_by": "scripts/vendor.py", "libraries": entries}
    _write(
        VENDOR_DIR / "MANIFEST.json", (json.dumps(manifest, indent=2) + "\n").encode()
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
