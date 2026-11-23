"""Unit tests: key handling, constant-time compare, helper injection, CSP."""

from __future__ import annotations

import hmac
import re
import stat
from pathlib import Path

import pytest

from agent_canvas.hub import auth
from agent_canvas.hub.auth import Credentials, KeyFileError, load_or_create_key
from agent_canvas.hub.serve import (
    BLOCK_LOADER_TAG,
    HELPER_TAG,
    frame_csp,
    inject_helper,
    resolve_session_file,
    source_digest,
)

pytestmark = pytest.mark.unit


def test_sec_02_key_is_32_random_bytes_urlsafe_with_private_modes(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    key = load_or_create_key(state)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", key)  # 32 bytes, unpadded base64
    assert stat.S_IMODE((state / "key").stat().st_mode) == 0o600
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert load_or_create_key(state) == key


@pytest.mark.parametrize("mode", [0o640, 0o644, 0o604, 0o660])
def test_sec_02_group_or_world_accessible_key_refuses(
    tmp_path: Path, mode: int
) -> None:
    state = tmp_path / "state"
    load_or_create_key(state)
    (state / "key").chmod(mode)
    with pytest.raises(KeyFileError, match=str(state / "key")):
        load_or_create_key(state)


def test_sec_03_keys_are_compared_with_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    credentials = Credentials("secret", lambda: 0.0)
    assert credentials.key_ok("secret")
    assert not credentials.key_ok("wrong")
    assert not credentials.key_ok(None)
    assert credentials.cookie_ok(credentials.cookie_value)
    assert len(calls) >= 3


def test_sec_04_login_token_is_single_use_and_expires_after_60_seconds() -> None:
    now = [0.0]
    credentials = Credentials("k", lambda: now[0])
    token = credentials.new_login_token()
    assert credentials.consume_login_token(token)
    assert not credentials.consume_login_token(token)
    late = credentials.new_login_token()
    now[0] = 60.5
    assert not credentials.consume_login_token(late)
    assert not credentials.consume_login_token(None)
    assert not credentials.consume_login_token("made-up")


def test_page_02_full_document_gets_helper_first_in_head() -> None:
    html = b"<!doctype html><HTML lang=en><HEAD><title>t</title></HEAD><body>x</body>"
    out = inject_helper(html)
    assert out.count(HELPER_TAG.encode()) == 1
    head_start = out.index(b"<HEAD>") + len(b"<HEAD>")
    assert out[head_start:].startswith(HELPER_TAG.encode() + BLOCK_LOADER_TAG.encode())
    assert out.count(BLOCK_LOADER_TAG.encode()) == 1
    assert out.replace(HELPER_TAG.encode() + BLOCK_LOADER_TAG.encode(), b"") == html


def test_page_13_helper_tag_carries_the_source_digest() -> None:
    html = b"<html><head></head><body>x</body></html>"
    out = inject_helper(html, source_digest(html))
    assert (
        f'data-source="{source_digest(html)}" data-agent-canvas-helper'.encode() in out
    )
    assert source_digest(html) != source_digest(html + b" ")


def test_page_02_fragment_is_wrapped_with_helper_first() -> None:
    out = inject_helper(b"<h1 id=a>Hello</h1>")
    assert re.search(rb"<head>(<meta[^>]*>)?" + re.escape(HELPER_TAG.encode()), out)
    assert b"<body><h1 id=a>Hello</h1></body>" in out
    assert out.count(HELPER_TAG.encode()) == 1


def test_page_02_header_element_is_not_mistaken_for_head() -> None:
    out = inject_helper(b"<html><body><header>x</header></body></html>")
    assert out.count(HELPER_TAG.encode()) == 1
    assert out.index(HELPER_TAG.encode()) < out.index(b"<body>")


def test_sec_06_csp_matches_requirement_text() -> None:
    port, token = 27463, "TOK"
    expected = (
        "default-src 'none'; "
        "script-src http://localhost:27463/static/ http://localhost:27463/s/TOK/ "
        "'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'; "
        "style-src http://localhost:27463/static/ http://localhost:27463/s/TOK/ "
        "'unsafe-inline'; "
        "img-src http://localhost:27463/s/TOK/ http://localhost:27463/static/ "
        "data: blob:; "
        "font-src http://localhost:27463/static/ data:; "
        "media-src http://localhost:27463/s/TOK/ data: blob:; "
        "connect-src http://localhost:27463/s/TOK/ http://localhost:27463/static/ "
        "data: blob:; "
        "worker-src blob:; form-action 'none'; frame-src 'none'; base-uri 'none'"
    )
    assert frame_csp(port, token) == expected


@pytest.mark.parametrize(
    "relative",
    [
        "../x",
        "a/../../x",
        "/etc/passwd",
        "",
        "a//b",
        "a\\b",
        "a\x00b",
        "./a",
        "history/x",
    ],
)
def test_sec_08_page_03_resolver_rejects_unsafe_paths(
    tmp_path: Path, relative: str
) -> None:
    folder = tmp_path.resolve()
    (folder / "a").write_text("x")
    assert resolve_session_file(folder, relative) is None


def test_page_03_resolver_rejects_symlink_escape(tmp_path: Path) -> None:
    folder = (tmp_path / "s").resolve()
    folder.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (folder / "link.txt").symlink_to(outside)
    (folder / "ok.txt").write_text("fine")
    assert resolve_session_file(folder, "link.txt") is None
    assert resolve_session_file(folder, "ok.txt") == folder / "ok.txt"
