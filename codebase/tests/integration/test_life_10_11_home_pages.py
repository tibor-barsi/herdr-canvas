"""The owner's page route and the archive lists (LIFE-10, LIFE-11, LIFE-12 data)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import clock
from agent_canvas.hub.lifetime import DAY_SECONDS

pytestmark = pytest.mark.integration

NAMES = ["one.html", "two.html", "three.html"]


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    """An HTTP client logged in as the owner window (cookie only, no key)."""
    client = httpx.Client(base_url=hub.base_url)
    client.get(hub.login_url(), follow_redirects=False)
    return client


def make_session(hub, sid: str, names=NAMES) -> Path:  # noqa: ANN001, ANN201
    """Create session ``sid`` with ``names`` shown in that order; return its folder."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    folder = Path(answer.json()["folder"])
    for name in names:
        (folder / name).write_text(f"<title>{name} title</title><p>{name}</p>")
        httpx.post(
            f"{hub.base_url}/api/sessions/{sid}/show",
            json={"name": name, "audit": False},
            headers=hub.key_headers,
        ).raise_for_status()
    return folder


def post(hub, owner, **body):  # noqa: ANN001, ANN003, ANN201
    return owner.post("/api/home/pages", json=body, headers={"Origin": hub.base_url})


def agent_kind(hub, sid: str, name: str, kind: str):  # noqa: ANN001, ANN201
    body = {"action": "kind", "name": name, "kind": kind}
    return httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/pages", json=body, headers=hub.key_headers
    )


def end(hub, sid: str) -> None:  # noqa: ANN001
    httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/end", json={}, headers=hub.key_headers
    )


def archive_view(owner) -> dict:  # noqa: ANN001
    return owner.get("/api/home/archive").json()


def snapshot(hub) -> dict:  # noqa: ANN001
    return httpx.get(f"{hub.base_url}/api/home", headers=hub.key_headers).json()


def shifted(monkeypatch, days: float) -> None:  # noqa: ANN001
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(days * DAY_SECONDS))


def test_life_10_the_route_is_for_the_owner_window_only(hub) -> None:  # noqa: ANN001
    make_session(hub, "a")
    body = {"session": "a", "page": "one.html", "kind": "long-term"}
    keyed = httpx.post(
        f"{hub.base_url}/api/home/pages", json=body, headers=hub.key_headers
    )
    assert keyed.status_code == 403
    assert agent_kind(hub, "a", "one.html", "single-use").json()["set_by"] == "agent"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"session": "a", "page": "one.html"}, 400),
        ({"session": "a", "page": "one.html", "kind": "x"}, 422),
        (
            {"session": "a", "page": "one.html", "kind": "long-term", "archive": True},
            400,
        ),
        ({"session": "a", "page": "one.html", "archive": 1}, 400),
        ({"session": "a", "page": "nope.html", "archive": True}, 422),
        ({"session": "zz", "page": "one.html", "archive": True}, 404),
        ({"session": "a", "kind": "long-term"}, 400),
        ({"session": "a", "page": "one.html", "kind": "long-term", "x": 1}, 400),
    ],
)
def test_life_10_bad_bodies_are_refused(hub, owner, body, status) -> None:  # noqa: ANN001
    make_session(hub, "a")
    assert post(hub, owner, **body).status_code == status


def test_life_11_the_archive_route_needs_credentials(hub) -> None:  # noqa: ANN001
    assert httpx.get(f"{hub.base_url}/api/home/archive").status_code == 401
