"""KMAP-02, KMAP-05: ``/api/keys`` answers the profiles and changes, and saves them."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_kmap_02_the_route_reads_the_file_on_each_request(hub) -> None:  # noqa: ANN001
    url = hub.base_url + "/api/keys"
    first = httpx.get(url, headers=hub.key_headers).json()
    assert (
        first["profile"] == "herdr" and first["keys"] == {} and first["problems"] == []
    )
    (Path(os.environ["AGENT_CANVAS_CONFIG_DIR"]) / "keys.toml").write_text(
        '[keys]\n"tab.next" = "n"\n'
    )
    assert httpx.get(url, headers=hub.key_headers).json()["keys"] == {"tab.next": "n"}


def test_kmap_02_the_route_needs_the_key(hub) -> None:  # noqa: ANN001
    assert httpx.get(hub.base_url + "/api/keys").status_code in (401, 403)
    assert httpx.post(hub.base_url + "/api/keys", json={"keys": {}}).status_code in (
        401,
        403,
    )


def test_kmap_05_a_post_saves_profile_and_changes(hub) -> None:  # noqa: ANN001
    url = hub.base_url + "/api/keys"
    answer = httpx.post(
        url,
        headers=hub.key_headers,
        json={"profile": "vim", "keys": {"tab.next": ["n"]}},
    )
    assert answer.status_code == 200
    assert answer.json()["profile"] == "vim"
    saved = httpx.get(url, headers=hub.key_headers).json()
    assert saved["profile"] == "vim" and saved["keys"] == {"tab.next": ["n"]}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"other": 1},
        {"profile": "nope"},
        {"keys": "x"},
        {"keys": {"Bad Name": ["n"]}},
        {"keys": {"tab.next": "n"}},
        {"keys": {"tab.next": [3]}},
        {"keys": {"tab.next": ["n"] * 13}},
    ],
)
def test_kmap_05_a_bad_post_is_refused_and_nothing_is_written(hub, body) -> None:  # noqa: ANN001
    url = hub.base_url + "/api/keys"
    assert httpx.post(url, headers=hub.key_headers, json=body).status_code == 400
    assert not (Path(os.environ["AGENT_CANVAS_CONFIG_DIR"]) / "keys.toml").exists()
