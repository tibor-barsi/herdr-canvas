"""PAGE-12: the sandboxed frame can fetch, import, run WASM and use snapdom."""

from __future__ import annotations

import base64

import pytest

from helpers import FIXTURE_DIR

pytestmark = pytest.mark.browser

# 1x1 transparent PNG.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)


def capability_files() -> dict[str, bytes | str]:
    """Files of the PAGE-12 session: fixture page, data and image."""
    return {
        "capability.html": (FIXTURE_DIR / "capability.html").read_text(),
        "data.json": '{"answer": 42}',
        "pixel.png": PIXEL_PNG,
    }


def test_page_12_fetch_import_wasm_and_snapdom_work_in_sandboxed_frame(owner) -> None:
    hub = owner.hub
    hub.add_session("cap", capability_files())
    owner.show("cap", "capability.html")
    results = owner.wait_report("capability")
    assert results == {
        "fetch": "ok",
        "import": "ok",
        "wasm": "ok",
        "snapdom": "ok",
        "api_blocked": "ok",
    }
