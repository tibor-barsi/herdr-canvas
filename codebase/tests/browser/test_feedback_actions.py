"""Action recorder, ``emit``, draft limits, the light and a real click (M6)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.browser


def call(owner, method: str, path: str, **kwargs) -> dict:  # noqa: ANN001
    """Call the hub API while keeping Playwright's event loop running."""
    hub = owner.hub
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            httpx.request,
            method,
            f"{hub.base_url}{path}",
            headers=hub.key_headers,
            timeout=15,
            **kwargs,
        )
        while not future.done():
            owner.page.wait_for_timeout(20)
        return future.result().json()


@pytest.fixture
def make(owner, tmp_path: Path):  # noqa: ANN001, ANN201
    """Create a session and show ``html`` in it; wait for the frame to load."""
    deadline = 100
    while not owner.hub.state.shells and deadline:
        owner.page.wait_for_timeout(50)
        deadline -= 1

    def build(html: str, name: str = "alpha") -> str:
        directory = tmp_path / name
        directory.mkdir(exist_ok=True)
        body = {"project": str(directory), "agent": "claude", "title": "T"}
        sid = call(owner, "POST", "/api/sessions", json=body)["session"]
        folder = owner.hub.state.session_of(sid).folder
        (folder / "page.html").write_text(html)
        call(
            owner,
            "POST",
            f"/api/sessions/{sid}/show",
            json={"project": str(directory), "name": "page.html"},
        )
        owner.visit(sid)
        owner.frame.wait_for_function("document.readyState === 'complete'")
        owner.frame.wait_for_function("window.agentCanvas !== undefined")
        return sid

    return build


def events_of(owner, sid: str) -> list[dict]:  # noqa: ANN001
    return owner.hub.on_loop(lambda: owner.hub.state.events.all(sid))


def wait_events(owner, sid: str, count: int) -> list[dict]:  # noqa: ANN001
    for _ in range(300):
        found = events_of(owner, sid)
        if len(found) >= count:
            return found
        owner.page.wait_for_timeout(20)
    raise AssertionError(f"expected {count} events, got {events_of(owner, sid)}")


def draft_actions(owner, sid: str) -> list[dict]:  # noqa: ANN001
    return owner.page.evaluate(f"(window.__drafts['{sid}'] || {{actions: []}}).actions")


def wait_actions(owner, sid: str, count: int) -> list[dict]:  # noqa: ANN001
    owner.page.wait_for_function(
        f"(window.__drafts['{sid}'] || {{actions: []}}).actions.length >= {count}"
    )
    return draft_actions(owner, sid)


# ---- PAGE-07 ------------------------------------------------------------------


def test_page_07_emit_creates_a_custom_event_and_a_matching_action(owner, make) -> None:
    sid = make("<button id=b onclick=\"agentCanvas.emit('pick', 3)\">pick</button>")
    owner.frame.click("#b")
    [event] = wait_events(owner, sid, 1)
    assert event["kind"] == "custom"
    assert event["value"] == {"name": "pick", "value": 3}
    assert event["delivery"] == "now" and event["state"] == "queued"
    assert event["page"] == "page.html" and event["page_version"] == 1
    actions = wait_actions(owner, sid, 2)
    custom = [a for a in actions if a["kind"] == "custom"]
    assert len(custom) == 1 and custom[0]["value"] == {"name": "pick", "value": 3}
    owner.page.wait_for_function(
        f"window.__drafts['{sid}'].actions.some((a) => a.event)"
    )
    assert [a["event"] for a in draft_actions(owner, sid) if a["kind"] == "custom"] == [
        event["id"]
    ]


def test_page_07_emit_accepts_a_delivery_option_and_structured_values(
    owner, make
) -> None:
    sid = make(
        "<button id=b onclick=\"agentCanvas.emit('later', {a: [1, 2]}, "
        "{delivery: 'next-message'})\">x</button>"
    )
    owner.frame.click("#b")
    [event] = wait_events(owner, sid, 1)
    assert event["delivery"] == "next-message"
    assert event["value"] == {"name": "later", "value": {"a": [1, 2]}}


def test_page_07_a_bad_emit_creates_no_event(owner, make) -> None:
    sid = make("<p>x</p>")
    owner.frame.evaluate("agentCanvas.emit(42, 1)")  # name must be a string
    owner.frame.evaluate("agentCanvas.emit('ok', 1, {delivery: 'bogus'})")
    owner.frame.evaluate("agentCanvas.emit('fine', 2)")
    events = wait_events(owner, sid, 1)
    assert [e["value"]["name"] for e in events] == ["fine"]


# ---- FB-05 --------------------------------------------------------------------


def test_fb_05_a_click_on_a_nested_span_records_the_ancestor_with_an_id(
    owner, make
) -> None:
    sid = make("<section id=a><p><span>hello</span></p></section>")
    owner.frame.click("section span")
    [action] = wait_actions(owner, sid, 1)
    assert action["kind"] == "click"
    assert action["target"]["canvas_id"] == "a"
    assert action["target"]["tag"] == "section"
    assert action["target"]["selector"] == "#a"
    assert action["target"]["text"] == "hello"
    assert action["event"] is None and len(action["at"]) == 2


def test_fb_05_data_canvas_id_wins_over_id(owner, make) -> None:
    sid = make("<div id=x data-canvas-id=spectrum><b>k</b></div>")
    owner.frame.click("b")
    [action] = wait_actions(owner, sid, 1)
    assert action["target"]["canvas_id"] == "spectrum"


def test_fb_05_without_an_id_the_finder_selector_identifies_the_element(
    owner, make
) -> None:
    sid = make("<ul><li>a</li><li class=pick>b</li><li>c</li></ul>")
    owner.frame.wait_for_function("window.agentCanvas.finderReady === true")
    owner.frame.click(".pick")
    [action] = wait_actions(owner, sid, 1)
    target = action["target"]
    assert target["canvas_id"] is None and target["text"] == "b"
    assert owner.frame.evaluate(
        "(s) => [...document.querySelectorAll(s)].map((e) => e.textContent)",
        target["selector"],
    ) == ["b"]


def test_fb_05_long_text_snippets_are_cut_at_80_characters(owner, make) -> None:
    sid = make(f"<p id=p>{'word ' * 60}</p>")
    owner.frame.click("#p")
    [action] = wait_actions(owner, sid, 1)
    assert len(action["target"]["text"]) == 80


def test_fb_05_55_clicks_keep_the_latest_50_and_count_5_dropped(owner, make) -> None:
    buttons = "".join(f"<button data-canvas-id=b{i}>{i}</button>" for i in range(55))
    sid = make(buttons)
    owner.frame.evaluate(
        "document.querySelectorAll('button').forEach((b) => b.click())"
    )
    owner.page.wait_for_function(f"window.__drafts['{sid}'].actions_dropped === 5")
    actions = draft_actions(owner, sid)
    assert len(actions) == 50
    assert [a["target"]["canvas_id"] for a in actions] == [
        f"b{i}" for i in range(5, 55)
    ]


def test_fb_05_a_pressed_button_keeps_its_event_id_in_the_draft(owner, make) -> None:
    sid = make("<button id=go onclick=\"agentCanvas.emit('go', 1)\">go</button>")
    owner.frame.click("#go")
    [event] = wait_events(owner, sid, 1)
    owner.page.wait_for_function(
        f"window.__drafts['{sid}'].actions.some((a) => a.event === '{event['id']}')"
    )
    actions = draft_actions(owner, sid)
    assert [a["kind"] for a in actions] == ["click", "custom"]
    assert actions[0]["event"] is None and actions[1]["event"] == event["id"]


def test_fb_05_links_still_record_one_action_with_the_richer_target(
    owner, make
) -> None:
    sid = make("<a id=ext href='https://example.com/x'>outside</a>")
    owner.frame.click("#ext")
    [action] = wait_actions(owner, sid, 1)
    owner.page.wait_for_timeout(200)
    assert len(draft_actions(owner, sid)) == 1
    assert action["target"]["href"] == "https://example.com/x"
    assert action["target"]["canvas_id"] == "ext"


# ---- FB-06 --------------------------------------------------------------------


def light(owner, sid: str):  # noqa: ANN001, ANN201
    return owner.page.locator(f"[data-session='{sid}'] .light")


# ---- the real click through watch ---------------------------------------------------


def start_cli_watch(hub, sid: str, tmp_path: Path, *args: str):  # noqa: ANN001, ANN201
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AGENT_CANVAS_", "XDG_"))
    }
    env.update(
        HOME=str(tmp_path / "home"),
        AGENT_CANVAS_PORT=str(hub.port),
        AGENT_CANVAS_STATE_DIR=str(hub.state_dir),
        AGENT_CANVAS_CONFIG_DIR=str(hub.config_dir),
        AGENT_CANVAS_WINDOW_COMMAND="true",
    )
    (tmp_path / "home").mkdir(exist_ok=True)
    return subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", "watch", "--session", sid, *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=tmp_path,
    )


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()
    process.stdout.close()
    process.stderr.close()


def test_cli_07_a_real_click_in_a_raw_html_page_reaches_watch(
    owner, make, tmp_path
) -> None:
    sid = make("<button id=go onclick=\"agentCanvas.emit('pick', 3)\">go</button>")
    process = start_cli_watch(owner.hub, sid, tmp_path, "--count", "1")
    try:
        owner.page.wait_for_function(
            f"tabs.find((t) => t.id === '{sid}')?.listening === true", timeout=15000
        )
        owner.frame.click("#go")
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(process.stdout.readline)
            while not first.done():
                owner.page.wait_for_timeout(20)
            line = json.loads(first.result())
            last = pool.submit(process.stdout.readline)
            while not last.done():
                owner.page.wait_for_timeout(20)
            ended = json.loads(last.result())
        assert line["kind"] == "custom" and line["session"] == sid
        assert line["value"] == {"name": "pick", "value": 3}
        assert ended == {"type": "watch-ended", "reason": "count", "renew": False}
        assert process.wait(10) == 0
        for _ in range(100):
            if owner.hub.event_state(sid, line["id"]) == "delivered":
                break
            owner.page.wait_for_timeout(20)
        assert owner.hub.event_state(sid, line["id"]) == "delivered"
    finally:
        stop(process)


# ---- HUB-09 (review finding M5) ---------------------------------------------
