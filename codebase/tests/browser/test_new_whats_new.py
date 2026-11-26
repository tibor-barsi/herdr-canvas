"""What's new since the owner last looked, in the owner's window (NEW-01, NEW-03)."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from agent_canvas.hub.headless import HeadlessRenderer
from agent_canvas.hub.watcher import PageHistory

from .conftest import _launch_env
from .support import call, until
from .test_look_window import look

pytestmark = pytest.mark.browser

PAGE = (
    "<!doctype html><title>t</title><body style='margin:0'>"
    "<section data-canvas-id='a' style='height:80px'>Alpha</section>"
    "<section data-canvas-id='b' style='height:80px'>Beta</section></body>"
)
SECOND = PAGE.replace("Beta", "Beta two")
THIRD = SECOND.replace(
    "<section data-canvas-id='a'",
    "<section data-canvas-id='c' style='height:120px'>Gamma</section>"
    "<section data-canvas-id='a'",
)
SIGNS = (
    "() => { const host = document.querySelector('[data-ac-comment-host]');"
    " return host ? [...host.shadowRoot.querySelectorAll('.sign-box')].map((e) => ({"
    "sign: e.classList.contains('new') ? 'new' : 'changed', text: e.textContent,"
    " top: e.getBoundingClientRect().top + scrollY})) : []; }"
)


def set_visible(owner, visible: bool) -> None:  # noqa: ANN001
    """Make the shell's document report ``visible`` or ``hidden``."""
    owner.page.evaluate(
        "(v) => { Object.defineProperty(document, 'visibilityState',"
        " {get: () => (v ? 'visible' : 'hidden'), configurable: true});"
        " document.dispatchEvent(new Event('visibilitychange')); }",
        visible,
    )


def seen_of(made, name: str = "page.html"):  # noqa: ANN001, ANN201
    meta = json.loads((made.folder / "session.json").read_text())["page_meta"]
    return meta[name].get("seen_version")


def wait_until(owner, check, timeout: float = 8.0):  # noqa: ANN001, ANN201
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if value := check():
            return value
        owner.page.wait_for_timeout(50)
    raise AssertionError("condition not met in time")


def write_version(owner, made, name: str, html: str, number: int) -> None:  # noqa: ANN001
    """Write the page and wait until the hub has saved version ``number``."""
    (made.folder / name).write_text(html)

    def saved() -> bool:
        latest = PageHistory(made.folder).latest(name)
        return latest is not None and latest[0] >= number

    wait_until(owner, saved)


def leave_and_return(owner, made, make) -> None:  # noqa: ANN001
    make("<p>other</p>", name="beta")
    owner.visit(made.sid)
    owner.frame.wait_for_function("window.agentCanvas !== undefined")


def seen_first(owner, make, html: str = PAGE):  # noqa: ANN001, ANN201
    """Open version 1 and wait until it is seen; the window is then on the page."""
    made = make(html)
    wait_until(owner, lambda: seen_of(made) == 1)
    return made


def sign_list(owner) -> list:  # noqa: ANN001
    return owner.frame.evaluate(SIGNS)


def test_new_01_a_version_shown_2_s_in_a_visible_window_is_seen(owner, make) -> None:  # noqa: ANN001
    set_visible(owner, False)
    made = make(PAGE)
    set_visible(owner, True)
    owner.page.wait_for_timeout(1000)
    assert seen_of(made) is None
    wait_until(owner, lambda: seen_of(made) == 1)


def test_new_01_with_the_window_hidden_nothing_is_seen(owner, make) -> None:  # noqa: ANN001
    set_visible(owner, False)
    made = make(PAGE)
    owner.page.wait_for_timeout(2600)
    assert seen_of(made) is None
    set_visible(owner, True)
    wait_until(owner, lambda: seen_of(made) == 1)


def test_new_01_shown_1_s_and_then_another_page_is_not_seen(owner, make) -> None:  # noqa: ANN001
    set_visible(owner, False)
    made = make(PAGE)
    set_visible(owner, True)
    owner.page.wait_for_timeout(1000)
    set_visible(owner, False)
    owner.page.wait_for_timeout(2600)
    assert seen_of(made) is None


def test_new_01_a_page_cannot_report_a_version_as_seen(owner, make) -> None:  # noqa: ANN001
    set_visible(owner, False)
    made = make(PAGE)
    dropped = owner.page.evaluate("window.__guard.dropped.type")
    owner.frame.evaluate(
        "(sid) => parent.postMessage({type: 'seen', session: sid, page: 'page.html',"
        " version: 1}, '*')",
        made.sid,
    )
    owner.page.wait_for_function(
        "(n) => window.__guard.dropped.type > n", arg=dropped, timeout=5000
    )
    owner.page.wait_for_timeout(2600)
    assert seen_of(made) is None


def test_new_01_a_look_through_the_window_never_counts_as_seen(owner, make) -> None:  # noqa: ANN001
    set_visible(owner, False)
    made = make(PAGE)
    assert look(owner, made.sid)["source"] == "window"
    owner.page.wait_for_timeout(2600)
    assert seen_of(made) is None


def test_new_01_a_headless_show_and_look_never_count_as_seen(
    hub,  # noqa: ANN001
    tmp_path,
) -> None:
    hub.app.state.looks.headless = HeadlessRenderer(launch_env=_launch_env())
    source = tmp_path / "tall.html"
    source.write_text(PAGE)
    shown = httpx.post(
        hub.base_url + "/api/sessions/t1/show",
        json={"project": str(hub.project_dir), "agent": "x", "copy": str(source)},
        headers=hub.key_headers,
        timeout=90,
    )
    assert shown.status_code == 200, shown.text
    looked = httpx.post(
        hub.base_url + "/api/sessions/t1/look",
        json={},
        headers=hub.key_headers,
        timeout=90,
    )
    assert looked.json()["source"] == "headless"
    folder = hub.state.session_of(hub.pool_of("t1")).folder
    meta = json.loads((folder / "session.json").read_text())["page_meta"]["tall.html"]
    assert (meta["seen_version"], meta["seen_at"]) == (None, None)


def test_new_03_one_changed_block_gives_the_line_and_the_sign_then_nothing_after_return(
    owner,
    make,  # noqa: ANN001
) -> None:
    made = seen_first(owner, make)
    set_visible(owner, False)
    write_version(owner, made, "page.html", SECOND, 2)
    set_visible(owner, True)
    owner.visit(made.sid)
    owner.page.wait_for_selector("#changes-bar.visible")
    assert owner.page.inner_text("#changes-text").startswith("1 change since ")
    owner.frame.wait_for_function(f"({SIGNS})().length === 1")
    [sign] = sign_list(owner)
    assert (sign["sign"], sign["text"]) == ("changed", "changed")
    beta = owner.frame.evaluate(
        "document.querySelector('[data-canvas-id=b]').offsetTop"
    )
    assert sign["top"] == beta
    wait_until(owner, lambda: seen_of(made) == 2)
    leave_and_return(owner, made, make)
    owner.page.wait_for_timeout(500)
    assert not owner.page.is_visible("#changes-bar")
    assert sign_list(owner) == []


def test_new_03_the_signs_stay_while_the_owner_stays_even_when_the_version_is_seen(
    owner,
    make,  # noqa: ANN001
) -> None:
    made = seen_first(owner, make)
    set_visible(owner, False)
    write_version(owner, made, "page.html", SECOND, 2)
    set_visible(owner, True)
    owner.visit(made.sid)
    owner.frame.wait_for_function(f"({SIGNS})().length === 1")
    wait_until(owner, lambda: seen_of(made) == 2)
    until(
        owner.page,
        lambda: owner.page.is_visible("#changes-bar") and len(sign_list(owner)) == 1,
    )


def test_new_03_the_signs_are_not_in_the_page_and_survive_a_morph(owner, make) -> None:  # noqa: ANN001
    made = seen_first(owner, make)
    set_visible(owner, False)
    write_version(owner, made, "page.html", SECOND, 2)
    set_visible(owner, True)
    owner.visit(made.sid)
    owner.frame.wait_for_function(f"({SIGNS})().length === 1")
    owner.frame.evaluate(
        "() => { window.__morphs = 0; document.addEventListener("
        "'agentcanvas:updated', () => window.__morphs++); }"
    )
    before = owner.frame.evaluate("document.documentElement.outerHTML")
    assert "sign-box" not in before and "sign-tag" not in before
    (made.folder / "page.html").write_text(THIRD)
    owner.frame.wait_for_function("window.__morphs > 0")
    owner.frame.wait_for_function(f"({SIGNS})().length === 2")
    by = {s["sign"]: s for s in sign_list(owner)}
    top = owner.frame.evaluate
    assert by["changed"]["top"] == top(
        "document.querySelector('[data-canvas-id=b]').offsetTop"
    )
    assert by["new"]["top"] == top(
        "document.querySelector('[data-canvas-id=c]').offsetTop"
    )
    assert (
        owner.frame.evaluate(
            "document.querySelectorAll('[data-ac-comment-host]').length"
        )
        == 1
    )
    assert (
        owner.frame.evaluate(
            "document.body.querySelectorAll('.sign-box, .sign-tag').length"
            " + document.querySelectorAll('.sign-box').length"
        )
        == 0
    )
    assert owner.page.inner_text("#changes-text").startswith("2 changes since ")


def test_new_03_a_page_never_seen_shows_nothing(owner, make) -> None:  # noqa: ANN001
    set_visible(owner, False)
    made = make(PAGE)
    set_visible(owner, False)
    write_version(owner, made, "page.html", SECOND, 2)
    set_visible(owner, True)
    owner.visit(made.sid)
    owner.frame.wait_for_function("window.agentCanvas !== undefined")
    owner.page.wait_for_timeout(800)
    assert not owner.page.is_visible("#changes-bar")
    assert sign_list(owner) == []


def test_new_03_a_viewer_page_gets_the_line_and_no_signs(owner) -> None:  # noqa: ANN001
    directory = owner.hub.project_dir / "viewer"
    directory.mkdir()
    body = {"project": str(directory), "agent": "claude", "title": "v"}
    sid = call(owner, "POST", "/api/sessions", json=body)["session"]
    folder = owner.hub.state.session_of(owner.hub.pool_of(sid)).folder
    (folder / "notes.md").write_text("# One\n")
    owner.visit(sid)
    call(owner, "POST", f"/api/sessions/{sid}/show", json={"name": "notes.md"})
    made = type("Made", (), {"folder": folder, "sid": sid})
    wait_until(owner, lambda: seen_of(made, "notes.md") == 1)
    set_visible(owner, False)
    write_version(owner, made, "notes.md", "# Two\n", 2)
    set_visible(owner, True)
    owner.visit(sid)
    owner.page.wait_for_selector("#changes-bar.visible")
    assert owner.page.inner_text("#changes-text").startswith("1 change since ")
    owner.frame.wait_for_function("document.readyState === 'complete'")
    assert owner.frame.evaluate(SIGNS) == []


def test_new_03_the_signs_are_sent_only_after_the_load_answered_its_token(
    owner, make
) -> None:  # noqa: ANN001
    owner.context.add_init_script(
        "window.addEventListener('message', (e) => {"
        " if (e.source === window.parent && e.data && typeof e.data.type === 'string')"
        " (window.__got = window.__got || []).push(e.data.type); });"
    )
    made = seen_first(owner, make)
    set_visible(owner, False)
    write_version(owner, made, "page.html", SECOND, 2)
    set_visible(owner, True)
    owner.visit(made.sid)
    owner.frame.wait_for_function(f"({SIGNS})().length === 1")
    got = owner.frame.evaluate("window.__got")
    assert "relay-open" in got and "change-signs" in got
    assert got.index("relay-open") < got.index("change-signs")
