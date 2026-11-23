"""Stars on pages, set only by the owner (STAR-01 to STAR-06, #36)."""

from __future__ import annotations

import json
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


def shifted(monkeypatch, days: float) -> None:  # noqa: ANN001
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(days * DAY_SECONDS))


def pages_api(hub, sid: str, **body):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/pages", json=body, headers=hub.key_headers
    )


def listing(hub, sid: str) -> dict:  # noqa: ANN001
    rows = httpx.get(
        f"{hub.base_url}/api/sessions/{sid}/pages", headers=hub.key_headers
    ).json()["pages"]
    return {r["name"]: r for r in rows}


def tab_pages(hub, sid: str) -> tuple[list[str], list[str]]:  # noqa: ANN001
    tab = next(t for t in hub.app.state.registry.tabs() if t["id"] == sid)
    return tab["pages"], tab["starred"]


def test_star_01_the_owner_sets_and_clears_a_star(hub, owner) -> None:  # noqa: ANN001
    make_session(hub, "a")
    answer = post(hub, owner, session="a", page="two.html", star=True)
    assert answer.status_code == 200 and answer.json()["starred"] is True
    assert listing(hub, "a")["two.html"]["starred"] is True
    assert listing(hub, "a")["one.html"]["starred"] is False
    post(hub, owner, session="a", page="two.html", star=False)
    assert listing(hub, "a")["two.html"]["starred"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"page": "one.html", "star": "yes"},
        {"page": "one.html", "star": 1},
        {"page": "one.html", "star": True, "kind": "long-term"},
        {"page": "nope.html", "star": True},
    ],
)
def test_star_01_bad_star_bodies_are_refused(hub, owner, body) -> None:  # noqa: ANN001
    make_session(hub, "a")
    assert post(hub, owner, session="a", **body).status_code in (400, 422)
    assert not any(r["starred"] for r in listing(hub, "a").values())


def test_star_02_starred_pages_come_first_in_the_tab(
    hub,
    owner,
) -> None:  # noqa: ANN001
    make_session(hub, "a")
    post(hub, owner, session="a", page="three.html", star=True)
    post(hub, owner, session="a", page="two.html", star=True)
    assert tab_pages(hub, "a") == (
        ["two.html", "three.html", "one.html"],
        ["two.html", "three.html"],
    )
    post(hub, owner, session="a", page="two.html", star=False)
    post(hub, owner, session="a", page="three.html", star=False)
    assert tab_pages(hub, "a")[0] == NAMES


def test_star_03_a_starred_page_does_not_expire(hub, owner, monkeypatch) -> None:  # noqa: ANN001
    make_session(hub, "a", ["keep.html", "lose.html"])
    shifted(monkeypatch, 31)
    assert listing(hub, "a")["keep.html"]["expired"] is True
    post(hub, owner, session="a", page="keep.html", star=True)
    kept, lost = listing(hub, "a")["keep.html"], listing(hub, "a")["lose.html"]
    assert (kept["expired"], kept["expires"]) == (False, None)
    assert lost["expired"] is True
    reminders = httpx.post(
        f"{hub.base_url}/api/sessions/a/pending",
        json={"peek": True},
        headers=hub.key_headers,
    ).json()["reminders"]
    assert [r["page"] for r in reminders] == ["lose.html"]
    post(hub, owner, session="a", page="keep.html", star=False)
    assert listing(hub, "a")["keep.html"]["expired"] is True


def test_star_04_an_agent_cannot_archive_a_starred_page(hub, owner) -> None:  # noqa: ANN001
    make_session(hub, "a")
    post(hub, owner, session="a", page="one.html", star=True)
    refused = pages_api(hub, "a", action="archive", name="one.html")
    assert refused.status_code == 422 and "starred" in refused.json()["message"]
    assert "one.html" in listing(hub, "a")
    post(hub, owner, session="a", page="one.html", star=False)
    assert pages_api(hub, "a", action="archive", name="one.html").status_code == 200


def test_star_04_the_owner_can_archive_a_starred_page(hub, owner) -> None:  # noqa: ANN001
    make_session(hub, "a")
    post(hub, owner, session="a", page="one.html", star=True)
    answer = post(hub, owner, session="a", page="one.html", archive=True)
    assert answer.status_code == 200 and answer.json()["archived"]
    assert "one.html" not in listing(hub, "a")


def test_star_05_an_agent_cannot_set_or_clear_a_star(hub, owner) -> None:  # noqa: ANN001
    make_session(hub, "a")
    forged = {"session": "a", "page": "one.html", "star": True}
    keyed = httpx.post(
        f"{hub.base_url}/api/home/pages", json=forged, headers=hub.key_headers
    )
    assert keyed.status_code == 403
    assert listing(hub, "a")["one.html"]["starred"] is False
    # Every path of the agent's page route, with a star smuggled in.
    for body in (
        {"action": "star", "name": "one.html", "star": True},
        {"action": "kind", "name": "one.html", "kind": "long-term", "starred": True},
        {"action": "extend", "name": "one.html", "starred": True, "star": True},
    ):
        pages_api(hub, "a", **body)
    assert not any(r["starred"] for r in listing(hub, "a").values())
    post(hub, owner, session="a", page="one.html", star=True)
    clear = {**forged, "star": False}
    keyed = httpx.post(
        f"{hub.base_url}/api/home/pages", json=clear, headers=hub.key_headers
    )
    assert keyed.status_code == 403
    assert listing(hub, "a")["one.html"]["starred"] is True


def test_star_06_the_agent_listing_shows_the_star(hub, owner) -> None:  # noqa: ANN001
    folder = make_session(hub, "a")
    assert listing(hub, "a")["one.html"]["starred"] is False
    post(hub, owner, session="a", page="one.html", star=True)
    assert listing(hub, "a")["one.html"]["starred"] is True
    entry = json.loads((folder / "session.json").read_text())["page_meta"]["one.html"]
    assert entry["starred"] is True
