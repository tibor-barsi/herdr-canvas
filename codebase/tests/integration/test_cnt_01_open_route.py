"""The owner's Open route, ``POST /api/sessions/<id>/open-file`` (CNT-01, A-100)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    """An HTTP client logged in as the owner window (cookie only, no key)."""
    client = httpx.Client(base_url=hub.base_url)
    client.get(hub.login_url(), follow_redirects=False)
    return client


@pytest.fixture
def folder(hub) -> Path:  # noqa: ANN001
    """Create the session ``a`` through the key route and return its folder."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    return Path(answer.json()["folder"])


def open_file(hub, owner, body, session: str = "a", **headers):  # noqa: ANN001, ANN201
    return owner.post(
        f"/api/sessions/{session}/open-file",
        json=body,
        headers={"Origin": hub.base_url, **headers},
    )


def pages(folder: Path) -> dict:
    meta = json.loads((folder / "session.json").read_text())
    return {"pages": meta["pages"], "active": meta["active_page"]}


def test_cnt_01_a_session_file_becomes_the_active_page(hub, owner, folder) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("# x")
    (folder / "r.pdf").write_bytes(b"%PDF-1")
    first = open_file(hub, owner, {"name": "notes.md"})
    assert first.status_code == 200, first.text
    assert first.json() == {
        "session": "a",
        "page": "notes.md",
        "path": str(folder / "notes.md"),
        "version": 1,
    }
    assert pages(folder) == {"pages": ["notes.md"], "active": "notes.md"}
    assert open_file(hub, owner, {"name": "r.pdf"}).status_code == 200
    assert pages(folder) == {"pages": ["notes.md", "r.pdf"], "active": "r.pdf"}
    again = open_file(hub, owner, {"name": "notes.md"})  # already a page: shown again
    assert again.status_code == 200
    assert pages(folder) == {"pages": ["notes.md", "r.pdf"], "active": "notes.md"}


@pytest.mark.parametrize(
    "name",
    [
        "../outside.md",
        "sub/inner.md",
        "/etc/passwd",
        "..",
        "",
        "page.html",
        "tool.py",
        "page.draft.html",
        "missing.md",
        "bad\u0000.md",
        "a\\b.md",
    ],
)
def test_cnt_01_a_forged_name_opens_nothing(hub, owner, folder, name: str) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    (folder / "tool.py").write_text("x = 1")
    (folder.parent / "outside.md").write_text("# outside")
    answer = open_file(hub, owner, {"name": name})
    assert answer.status_code == 400, answer.text
    assert pages(folder)["pages"] == []


@pytest.mark.parametrize("body", [{}, {"name": 5}, {"name": None}, {"name": ["a.md"]}])
def test_cnt_01_a_body_without_a_file_name_opens_nothing(
    hub, owner, folder, body
) -> None:  # noqa: ANN001
    assert open_file(hub, owner, body).status_code == 400
    assert pages(folder)["pages"] == []


def test_cnt_01_a_link_to_a_file_outside_the_folder_opens_nothing(
    hub, owner, folder
) -> None:  # noqa: ANN001
    secret = folder.parent / "secret.md"
    secret.write_text("# secret")
    (folder / "link.md").symlink_to(secret)
    assert open_file(hub, owner, {"name": "link.md"}).status_code == 400
    assert pages(folder)["pages"] == []


def test_cnt_01_a_key_request_answers_403(hub, owner, folder) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("# x")
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/open-file",
        json={"name": "notes.md"},
        headers=hub.key_headers,
    )
    assert answer.status_code == 403
    assert pages(folder)["pages"] == []


def test_cnt_01_no_credentials_answer_401(hub, folder) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("# x")
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/open-file",
        json={"name": "notes.md"},
        headers={"Origin": hub.base_url},
    )
    assert answer.status_code == 401


def test_cnt_01_an_unknown_session_answers_404(hub, owner, folder) -> None:  # noqa: ANN001
    assert open_file(hub, owner, {"name": "n.md"}, session="nope").status_code == 404
