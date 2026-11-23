"""The card modules are served as JavaScript and loaded by the loader (KIND-01)."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration

MODULES = [
    "blocks/ask", "blocks/do", "blocks/report", "blocks/decision", "blocks/alert",
    "blocks/live", "kinds/card", "kinds/style",
]  # fmt: skip


@pytest.mark.parametrize("name", MODULES)
def test_kind_01_card_modules_are_served_as_javascript(hub, name: str) -> None:  # noqa: ANN001
    response = httpx.get(f"{hub.base_url}/static/{name}.js", headers=hub.key_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


def test_kind_01_the_loader_defines_the_six_card_elements(hub) -> None:  # noqa: ANN001
    loader = httpx.get(
        f"{hub.base_url}/static/blocks/loader.js", headers=hub.key_headers
    ).text
    for tag in ("ask", "do", "report", "decision", "alert", "live"):
        assert f'"canvas-{tag}"' in loader, tag
