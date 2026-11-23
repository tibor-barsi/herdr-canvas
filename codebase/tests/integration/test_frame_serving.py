"""Serving of session files on the frame site (PAGE-02, PAGE-03, SEC-06, SEC-07)."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import httpx
import pytest

from helpers import raw_get

pytestmark = pytest.mark.integration

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)
HELPER = (
    '<script src="/static/helper.js" data-agent-canvas-helper></script>'
    '<script type="module" src="/static/blocks/loader.js"'
    " data-agent-canvas-helper></script>"
)


@pytest.fixture
def session(hub):
    return hub.add_session(
        "s1",
        {
            "page.html": "<!doctype html><html><head><title>t</title></head>"
            "<body>full</body></html>",
            "fragment.html": "<h1 id=a>Fragment</h1>",
            "style.css": "body{}",
            "app.js": "1",
            "data.json": "{}",
            "pic.png": PNG,
            "pic.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>",
            "notes.txt": "n",
            "model.stl": "solid x",
            "sub/inner.json": "[]",
            "history/pages/page.0001.html": "old",
        },
    )


def url(hub, session, name: str) -> str:
    return f"{hub.frame_origin}/s/{session.page_token}/{name}"


def test_page_02_full_document_and_fragment_start_head_with_helper_once(
    hub, session
) -> None:
    full = httpx.get(url(hub, session, "page.html")).text
    fragment = httpx.get(url(hub, session, "fragment.html")).text
    full, fragment = (
        re.sub(r' data-source="[0-9a-f]{16}"', "", t) for t in (full, fragment)
    )
    assert full.count(HELPER) == 1
    assert "<head>" + HELPER + "<title>t</title>" in full
    assert fragment.count(HELPER) == 1
    assert "<head>" in fragment and fragment.index(HELPER) > fragment.index("<head>")
    assert "<h1 id=a>Fragment</h1>" in fragment and "<body>" in fragment


@pytest.mark.parametrize(
    ("name", "content_type"),
    [
        ("page.html", "text/html"),
        ("style.css", "text/css"),
        ("app.js", "text/javascript"),
        ("data.json", "application/json"),
        ("pic.png", "image/png"),
        ("pic.svg", "image/svg+xml"),
        ("notes.txt", "text/plain"),
        ("model.stl", "model/stl"),
        ("sub/inner.json", "application/json"),
    ],
)
def test_page_03_content_types(hub, session, name: str, content_type: str) -> None:
    answer = httpx.get(url(hub, session, name))
    assert answer.status_code == 200
    assert answer.headers["content-type"].split(";")[0] == content_type


def test_page_03_static_wasm_and_woff2_content_types(hub) -> None:
    wasm = httpx.get(
        f"{hub.frame_origin}/static/vendor/occt-import-js/occt-import-js.wasm"
    )
    font = httpx.get(
        f"{hub.frame_origin}/static/vendor/katex/fonts/KaTeX_Main-Regular.woff2"
    )
    assert wasm.headers["content-type"] == "application/wasm"
    assert font.headers["content-type"] == "font/woff2"


def test_page_03_head_request_is_allowed_and_other_methods_give_405(
    hub, session
) -> None:
    target = url(hub, session, "page.html")
    assert httpx.head(target).status_code == 200
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert httpx.request(method, target).status_code == 405


def test_page_03_traversal_encoded_absolute_and_symlink_requests_give_404(
    hub, tmp_path: Path
) -> None:
    secret = "TOP-SECRET-CONTENT"
    a = hub.add_session("a", {"page.html": "a"})
    hub.add_session("b", {"secret.txt": secret})
    outside = tmp_path / "outside.txt"
    outside.write_text(secret)
    (hub.sessions["a"].folder / "escape.txt").symlink_to(outside)
    (hub.sessions["a"].folder / "escape_dir").symlink_to(tmp_path)
    token = a.page_token
    secret_path = hub.sessions["b"].folder / "secret.txt"
    paths = [
        f"/s/{token}/../b/secret.txt",
        f"/s/{token}/%2e%2e/b/secret.txt",
        f"/s/{token}/%2e%2e%2fb/secret.txt",
        f"/s/{token}/..%2fb%2fsecret.txt",
        f"/s/{token}/{secret_path}",
        f"/s/{token}/%2F{str(secret_path).lstrip('/')}",
        f"/s/{token}//{str(secret_path).lstrip('/')}",
        f"/s/{token}/escape.txt",
        f"/s/{token}/escape_dir/outside.txt",
        f"/s/{token}/%5C..%5Cb%5Csecret.txt",
    ]
    for path in paths:
        status, _, body = raw_get(hub.port, path)
        assert status == 404, path
        assert secret.encode() not in body, path


def test_page_03_history_folder_is_not_served(hub, session) -> None:
    assert (
        httpx.get(url(hub, session, "history/pages/page.0001.html")).status_code == 404
    )


@pytest.mark.parametrize(
    "name", ["events.jsonl", "session.json", ".secret", "sub/.hidden.json"]
)
def test_page_03_hub_internal_files_and_dotfiles_are_not_served(
    hub, session, name
) -> None:
    target = session.folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("private")
    assert httpx.get(url(hub, session, name)).status_code == 404


def test_page_03_a_data_file_named_like_an_internal_one_in_a_subfolder_is_served(
    hub, session
) -> None:
    (session.folder / "sub" / "session.json").write_text("{}")
    assert httpx.get(url(hub, session, "sub/session.json")).status_code == 200


def test_sec_07_token_grants_only_its_own_session(hub) -> None:
    a = hub.add_session("a", {"a.txt": "from-a"})
    b = hub.add_session("b", {"b.txt": "from-b"})
    ok = httpx.get(f"{hub.frame_origin}/s/{b.page_token}/b.txt")
    assert (ok.status_code, ok.text) == (200, "from-b")
    assert httpx.get(f"{hub.frame_origin}/s/{a.page_token}/b.txt").status_code == 404
    assert httpx.get(f"{hub.frame_origin}/s/{a.page_token}/a.txt").text == "from-a"
    assert httpx.get(f"{hub.frame_origin}/s/not-a-token/a.txt").status_code == 404


def expected_csp(port: int, token: str) -> str:
    f = f"http://localhost:{port}"
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src {f}/static/ {f}/s/{token}/ 'unsafe-inline' 'unsafe-eval' "
            "'wasm-unsafe-eval'",
            f"style-src {f}/static/ {f}/s/{token}/ 'unsafe-inline'",
            f"img-src {f}/s/{token}/ {f}/static/ data: blob:",
            f"font-src {f}/static/ data:",
            f"media-src {f}/s/{token}/ data: blob:",
            f"connect-src {f}/s/{token}/ {f}/static/ data: blob:",
            "worker-src blob:",
            "form-action 'none'",
            "frame-src 'none'",
            "base-uri 'none'",
        ]
    )


@pytest.mark.parametrize("name", ["page.html", "data.json", "pic.png", "missing.txt"])
def test_sec_06_csp_header_on_every_frame_response(hub, session, name: str) -> None:
    answer = httpx.get(url(hub, session, name))
    if name == "missing.txt":
        assert answer.status_code == 404
        return
    assert answer.headers["content-security-policy"] == expected_csp(
        hub.port, session.page_token
    )


def test_sec_06_cors_header_on_static_and_frame_get_and_head(hub, session) -> None:
    targets = [url(hub, session, "data.json"), f"{hub.frame_origin}/static/helper.js"]
    for target in targets:
        for method in ("GET", "HEAD"):
            answer = httpx.request(method, target)
            assert answer.headers["access-control-allow-origin"] == "*", (
                method,
                target,
            )


def test_sec_06_no_cors_header_on_api_ws_and_login(hub) -> None:
    api = httpx.get(hub.base_url + "/api/sessions", headers=hub.key_headers)
    login = httpx.get(hub.login_url(), follow_redirects=False)
    denied = httpx.get(hub.base_url + "/api/sessions")
    ws = httpx.get(hub.base_url + "/ws/shell", headers=hub.key_headers)
    for answer in (api, login, denied, ws):
        assert "access-control-allow-origin" not in answer.headers


@pytest.mark.parametrize(
    "name", ["loader", "base", "style", "choices", "buttons", "textbox", "table",
             "progress", "markdown"]
)  # fmt: skip
def test_blk_08_block_modules_are_served_as_javascript(hub, name: str) -> None:
    response = httpx.get(
        f"{hub.base_url}/static/blocks/{name}.js", headers=hub.key_headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
