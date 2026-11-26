"""The owner's file upload: ``POST /api/sessions/<id>/files`` (VIEW-10, SEC-10)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

OCTET = "application/octet-stream"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40


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


def upload(hub, owner, name: str, body=PNG, session: str = "a", **headers):  # noqa: ANN001, ANN201
    headers = {"Origin": hub.base_url, "Content-Type": OCTET, **headers}
    return owner.post(
        f"/api/sessions/{session}/files", params={"name": name}, content=body,
        headers=headers,
    )  # fmt: skip


def test_view_10_the_body_is_stored_and_the_answer_has_its_shape(
    hub, owner, folder
) -> None:  # noqa: ANN001
    answer = upload(hub, owner, "photo.png")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body == {
        "session": "a",
        "page": "photo.png",
        "path": str(folder / "photo.png"),
        "version": 1,
    }
    assert (folder / "photo.png").read_bytes() == PNG
    meta = json.loads((folder / "session.json").read_text())
    assert meta["pages"] == ["photo.png"] and meta["active_page"] == "photo.png"
    assert not list(folder.glob(".upload-*"))


def test_view_10_a_name_in_use_gets_a_number(hub, owner, folder) -> None:  # noqa: ANN001
    names = [upload(hub, owner, "r.pdf", b"%PDF-1").json()["page"] for _ in range(3)]
    assert names == ["r.pdf", "r-2.pdf", "r-3.pdf"]
    assert (folder / "r-2.pdf").read_bytes() == b"%PDF-1"


def test_view_10_a_stem_taken_by_another_page_is_renamed(hub, owner, folder) -> None:  # noqa: ANN001
    (folder / "report.html").write_text("<p>x</p>")
    httpx.post(
        f"{hub.base_url}/api/sessions/a/show",
        json={"name": "report.html", "audit": False},
        headers=hub.key_headers,
    )
    assert upload(hub, owner, "report.md", b"# x").json()["page"] == "report-2.md"


def test_view_10_a_key_request_answers_403(hub, owner, folder) -> None:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/files",
        params={"name": "k.png"},
        content=PNG,
        headers={**hub.key_headers, "Content-Type": OCTET},
    )
    assert answer.status_code == 403
    assert not (folder / "k.png").exists()


def test_view_10_no_credentials_answer_401(hub, folder) -> None:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/files?name=n.png",
        content=PNG,
        headers={"Origin": hub.base_url, "Content-Type": OCTET},
    )
    assert answer.status_code == 401


def test_view_10_more_than_64_mb_answers_413(hub, owner, folder) -> None:  # noqa: ANN001
    big = b"\0" * (64 * 1024 * 1024 + 1)
    assert upload(hub, owner, "big.pdf", big).status_code == 413
    assert sorted(p.name for p in folder.iterdir()) == ["session.json"]


def test_view_10_streaming_body_over_the_limit_answers_413_and_leaves_no_file(
    hub, owner, folder
) -> None:  # noqa: ANN001
    """F4: a body with no Content-Length is cut off while it streams."""
    chunk = b"\0" * (1024 * 1024)

    def body(chunks: int):  # noqa: ANN202
        for _ in range(chunks):
            yield chunk

    sent = owner.build_request(
        "POST", "/api/sessions/a/files", params={"name": "s.pdf"}, content=body(65),
        headers={"Origin": hub.base_url, "Content-Type": OCTET},
    )  # fmt: skip
    assert "content-length" not in sent.headers  # a generator is sent chunked
    assert owner.send(sent).status_code == 413
    assert sorted(p.name for p in folder.iterdir()) == ["session.json"]
    # Positive control: the same route takes a streamed body within the limit.
    ok = owner.post(
        "/api/sessions/a/files", params={"name": "s.pdf"}, content=body(2),
        headers={"Origin": hub.base_url, "Content-Type": OCTET},
    )  # fmt: skip
    assert ok.status_code == 200 and (folder / "s.pdf").stat().st_size == 2 * len(chunk)


def test_view_10_a_failed_show_removes_the_stored_file(
    hub, owner, folder, monkeypatch
) -> None:  # noqa: ANN001
    """F8: the file is not left in the folder when opening it fails."""
    from agent_canvas.hub.registry import RegistryError, SessionRegistry

    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RegistryError("failed", "cannot open")

    with monkeypatch.context() as patch:
        patch.setattr(SessionRegistry, "show", refuse)
        answer = upload(hub, owner, "late.png")
    assert answer.status_code == 400 and answer.json()["message"] == "cannot open"
    assert sorted(p.name for p in folder.iterdir()) == ["session.json"]
    assert upload(hub, owner, "late.png").json()["page"] == "late.png"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "a/b.png",
        "..",
        "data.zip",
        ".hidden.png",
        "x.draft.html",
        "history",
        "a\\b.pdf",
    ],
)
def test_view_10_a_bad_name_or_type_answers_400(hub, owner, folder, name) -> None:  # noqa: ANN001
    answer = upload(hub, owner, name)
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"] == "invalid-file"
    assert sorted(p.name for p in folder.iterdir()) == ["session.json"]


def test_view_10_an_empty_file_answers_400(hub, owner, folder) -> None:  # noqa: ANN001
    assert upload(hub, owner, "e.png", b"").status_code == 400


def test_view_10_an_unknown_session_answers_404(hub, owner) -> None:  # noqa: ANN001
    assert upload(hub, owner, "a.png", session="nope").status_code == 404


def test_view_10_a_reserved_session_gets_its_folder(hub, owner) -> None:  # noqa: ANN001
    httpx.post(
        f"{hub.base_url}/api/sessions/rsv/reserve",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    folder = hub.project_dir / hub.project_dir_name / "rsv"
    assert not folder.exists()
    answer = upload(hub, owner, "first.png", session="rsv")
    assert answer.status_code == 200, answer.text
    pool = hub.pool_of("rsv")  # the upload is a page of the project's pool
    assert pool != "rsv"
    assert (hub.state.session_of(pool).folder / "first.png").read_bytes() == PNG
    listed = httpx.get(f"{hub.base_url}/api/sessions/{pool}", headers=hub.key_headers)
    assert listed.json()["pages"] == ["first.png"]


def test_view_10_the_session_page_serves_the_stored_file(hub, owner, folder) -> None:  # noqa: ANN001
    upload(hub, owner, "p.png")
    token = hub.state.session_of(hub.pool_of("a")).page_token
    served = httpx.get(f"{hub.frame_origin}/s/{token}/p.png")
    assert served.content == PNG


def test_sec_10_a_cross_site_octet_stream_upload_is_refused(hub, owner, folder) -> None:  # noqa: ANN001
    for headers in (
        {"Origin": "http://127.0.0.1:3000"},
        {"Origin": "http://evil.example"},
        {"Origin": "null"},
    ):
        answer = owner.post(
            "/api/sessions/a/files",
            params={"name": "x.png"},
            content=PNG,
            headers={"Content-Type": OCTET, **headers},
        )
        assert answer.status_code == 403, headers
    no_origin = owner.post(
        "/api/sessions/a/files",
        params={"name": "x.png"},
        content=PNG,
        headers={"Content-Type": OCTET, "Sec-Fetch-Site": "cross-site"},
    )
    assert no_origin.status_code == 403
    assert sorted(p.name for p in folder.iterdir()) == ["session.json"]


def test_sec_10_same_origin_without_origin_header_is_accepted(
    hub, owner, folder
) -> None:  # noqa: ANN001
    answer = owner.post(
        "/api/sessions/a/files",
        params={"name": "s.png"},
        content=PNG,
        headers={"Content-Type": OCTET, "Sec-Fetch-Site": "same-origin"},
    )
    assert answer.status_code == 200


def test_sec_10_octet_stream_is_accepted_on_the_upload_route_only(
    hub, owner, folder
) -> None:  # noqa: ANN001
    json_to_upload = upload(
        hub, owner, "j.png", b"{}", **{"Content-Type": "application/json"}
    )
    assert json_to_upload.status_code == 415
    other = owner.post(
        "/api/open",
        content=b"{}",
        headers={"Origin": hub.base_url, "Content-Type": OCTET},
    )
    assert other.status_code == 415


def test_sec_10_the_hub_never_grants_cors_on_the_upload_route(
    hub, owner, folder
) -> None:  # noqa: ANN001
    preflight = owner.options(
        "/api/sessions/a/files?name=x.png",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    answer = upload(hub, owner, "c.png")
    for response in (preflight, answer):
        assert not any(k.lower().startswith("access-control") for k in response.headers)
    assert preflight.status_code in (401, 403, 405)
