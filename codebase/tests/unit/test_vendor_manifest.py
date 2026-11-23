"""Tests for the vendored-asset manifest (OPS-03, OPS-06) and CDN freedom."""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from helpers import PACKAGE_DIR, VENDOR_DIR

pytestmark = pytest.mark.unit

REQUIRED_LIBRARIES = {
    "idiomorph",
    "@zumer/snapdom",
    "@medv/finder",
    "plotly.js-dist-min",
    "three",
    "occt-import-js",
    "marked",
    "katex",
    "pdfjs-dist",
}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((VENDOR_DIR / "MANIFEST.json").read_text(encoding="utf-8"))


def test_ops_03_manifest_lists_every_required_library(manifest: dict) -> None:
    names = {lib["name"] for lib in manifest["libraries"]}
    assert names == REQUIRED_LIBRARIES


def test_ops_03_entries_have_metadata(manifest: dict) -> None:
    for lib in manifest["libraries"]:
        for key in ("name", "version", "license", "source_url"):
            assert lib[key], f"{lib['name']}: empty {key}"
        assert lib["source_url"].startswith("https://registry.npmjs.org/")


def test_ops_03_every_file_and_licence_exists(manifest: dict) -> None:
    for lib in manifest["libraries"]:
        assert lib["license_files"], f"{lib['name']}: no licence file"
        assert lib["files"], f"{lib['name']}: no files"
        for rel in lib["license_files"]:
            assert (VENDOR_DIR / rel).is_file(), rel
            assert rel.startswith("licenses/")
        for entry in lib["files"]:
            assert (VENDOR_DIR / entry["path"]).is_file(), entry["path"]


def test_ops_03_occt_is_shipped_as_separate_files(manifest: dict) -> None:
    occt = next(lib for lib in manifest["libraries"] if lib["name"] == "occt-import-js")
    paths = {entry["path"] for entry in occt["files"]}
    assert "occt-import-js/occt-import-js.js" in paths
    assert "occt-import-js/occt-import-js.wasm" in paths


def test_ops_06_every_sha256_matches(manifest: dict) -> None:
    for lib in manifest["libraries"]:
        for entry in lib["files"]:
            digest = hashlib.sha256((VENDOR_DIR / entry["path"]).read_bytes())
            assert digest.hexdigest() == entry["sha256"], entry["path"]


def test_ops_06_no_unlisted_files_in_vendor_dir(manifest: dict) -> None:
    listed = {"MANIFEST.json"}
    for lib in manifest["libraries"]:
        listed.update(lib["license_files"])
        listed.update(entry["path"] for entry in lib["files"])
    on_disk = {
        p.relative_to(VENDOR_DIR).as_posix()
        for p in VENDOR_DIR.rglob("*")
        if p.is_file()
    }
    assert on_disk == listed


def test_ops_01_no_cdn_urls_outside_manifest() -> None:
    # Vendored third-party code may mention URLs in comments; only our own
    # html/js files are checked, plus any html in the package.
    own = [
        p
        for p in PACKAGE_DIR.rglob("*")
        if p.suffix in {".html", ".js"} and VENDOR_DIR not in p.parents
    ]
    url = re.compile(r"https?://|//cdn\.|cdnjs|unpkg|jsdelivr", re.IGNORECASE)
    offenders = [str(p) for p in own if url.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_ops_01_manifest_urls_are_not_referenced_by_pages(manifest: dict) -> None:
    urls = [lib["source_url"] for lib in manifest["libraries"]]
    pages = [
        p
        for p in PACKAGE_DIR.rglob("*")
        if p.suffix in {".html", ".js"} and VENDOR_DIR not in p.parents
    ]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert not any(url in text for url in urls), page


def test_pdf_01_pdfjs_ships_worker_fonts_cmaps_and_licence(manifest: dict) -> None:
    lib = next(lib for lib in manifest["libraries"] if lib["name"] == "pdfjs-dist")
    assert lib["version"] == "4.10.38"
    assert lib["license"] == "Apache-2.0"
    paths = {entry["path"] for entry in lib["files"]}
    assert "pdfjs-dist/pdf.min.mjs" in paths
    assert "pdfjs-dist/pdf.worker.min.mjs" in paths
    assert any(p.startswith("pdfjs-dist/standard_fonts/") for p in paths)
    assert any(p.startswith("pdfjs-dist/cmaps/") for p in paths)
    assert "licenses/pdfjs-dist.LICENSE" in lib["license_files"]
