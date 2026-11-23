"""Static checks of ``canvas-scene``: vendored files, guide, wiring, ids (SCN)."""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from helpers import PACKAGE_DIR, VENDOR_DIR

pytestmark = pytest.mark.unit

BLOCKS = PACKAGE_DIR / "static" / "blocks"
GUIDE = PACKAGE_DIR / "guide" / "blocks.md"
PART_KEYS = {"src", "name", "group", "colour", "opacity", "visible", "split"}


def test_scn_05_gltf_loader_is_vendored_with_everything_it_imports() -> None:
    manifest = json.loads((VENDOR_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    three = next(lib for lib in manifest["libraries"] if lib["name"] == "three")
    listed = {entry["path"]: entry["sha256"] for entry in three["files"]}
    loader = "three/addons/GLTFLoader.js"
    assert loader in listed and three["version"] == "0.186.1"
    for path, digest in listed.items():
        assert hashlib.sha256((VENDOR_DIR / path).read_bytes()).hexdigest() == digest
    source = (VENDOR_DIR / loader).read_text(encoding="utf-8")
    for relative in re.findall(r"from '(\.\./[^']+)'", source):
        target = (VENDOR_DIR / "three" / "addons" / relative).resolve()
        assert target.is_file(), relative
        assert f"three/{target.relative_to(VENDOR_DIR / 'three').as_posix()}" in listed


def test_scn_01_the_guide_example_manifest_is_valid_json_with_known_keys() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    section = text.split("## `canvas-scene`", 1)[1].split("\n## ", 1)[0]
    manifest = json.loads(re.search(r"`(\{\"units\".*?\]\})`", section, re.S).group(1))
    assert manifest["up"] == "z" and len(manifest["parts"]) == 3
    for part in manifest["parts"]:
        assert set(part) <= PART_KEYS
        assert part["src"].rsplit(".", 1)[1] in {"stl", "step", "stp", "glb"}
    assert any(part.get("split") for part in manifest["parts"])
    tag = re.search(r"Example: `(<canvas-scene.*?)`", section).group(1)
    assert 'data-canvas-id="asm"' in tag and json.loads(
        re.search(r">(\{.*?\})<", tag).group(1)
    ) == {"src": "asm.json"}


def test_scn_wiring_the_block_is_defined_and_its_action_is_known() -> None:
    loader = (BLOCKS / "loader.js").read_text(encoding="utf-8")
    assert '"canvas-scene": CanvasScene' in loader
    for script in ("helper.js", "shell.js"):
        text = (PACKAGE_DIR / "static" / script).read_text(encoding="utf-8")
        assert '"scene-mark"' in text, script
