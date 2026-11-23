"""Cookie-authenticated requests that change state (review finding M1).

Browsers treat other ports of 127.0.0.1 as the same site, and cookies ignore
ports, so a page on another local port must not be able to act as the owner.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    """An HTTP client logged in as the owner window (cookie only, no key)."""
    client = httpx.Client(base_url=hub.base_url)
    client.get(hub.login_url(), follow_redirects=False)
    assert client.cookies, "login did not set a cookie"
    return client


def post(owner, headers: dict[str, str], content=b"{}"):  # noqa: ANN001, ANN201
    return owner.post("/api/open", content=content, headers=headers)


def test_sec_10_the_cookie_name_carries_the_port(hub, owner) -> None:  # noqa: ANN001
    assert list(owner.cookies.keys()) == [f"agent_canvas_session_{hub.port}"]


def test_sec_10_foreign_origin_on_another_local_port_is_refused(hub, owner) -> None:  # noqa: ANN001
    headers = {"Origin": "http://127.0.0.1:3000", "Content-Type": "application/json"}
    assert post(owner, headers).status_code == 403


def test_sec_10_cross_port_form_post_with_text_plain_is_refused(hub, owner) -> None:  # noqa: ANN001
    headers = {"Origin": "http://127.0.0.1:3000", "Content-Type": "text/plain"}
    body = b'{"older_than":"1s","yes":true,"force":true}'
    answer = owner.post("/api/cleanup", content=body, headers=headers)
    assert answer.status_code == 403


def test_sec_10_the_hub_origin_with_json_is_accepted(hub, owner) -> None:  # noqa: ANN001
    headers = {"Origin": hub.base_url, "Content-Type": "application/json"}
    assert post(owner, headers).status_code == 200


def test_sec_10_same_origin_fetch_metadata_replaces_the_origin(hub, owner) -> None:  # noqa: ANN001
    headers = {"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}
    assert post(owner, headers).status_code == 200
    headers["Sec-Fetch-Site"] = "same-site"
    assert post(owner, headers).status_code == 403


def test_sec_10_neither_origin_nor_fetch_metadata_is_refused(hub, owner) -> None:  # noqa: ANN001
    assert post(owner, {"Content-Type": "application/json"}).status_code == 403


def test_sec_10_the_right_origin_with_another_content_type_is_refused(
    hub, owner
) -> None:  # noqa: ANN001
    headers = {"Origin": hub.base_url, "Content-Type": "text/plain"}
    assert post(owner, headers).status_code == 415


def test_sec_10_key_header_requests_and_reads_are_not_affected(hub, owner) -> None:  # noqa: ANN001
    cli_style = httpx.post(
        f"{hub.base_url}/api/open", content=b"{}", headers=hub.key_headers
    )
    assert cli_style.status_code == 200
    headers = {"Origin": "http://127.0.0.1:3000"}
    assert owner.get("/api/status", headers=headers).status_code == 200
