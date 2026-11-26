"""Question cards and awaited blocks in the shell (CLI-04, CLI-05, CLI-06, SES-07).

A real ``agent-canvas ask`` process runs against the test hub and Playwright is
the owner who clicks the card.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from .support import card_events

pytestmark = pytest.mark.browser

BLOCK_PAGE = """<!doctype html><title>t</title>
<div id="d" data-canvas-id="design"><p>Designs</p>
<button id="ok"
 onclick="agentCanvas.blockEvent('choice', document.getElementById('d'), ['b'])"
 >Use b</button></div>
<div id="other" data-canvas-id="other">other</div>"""


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


class Asking:
    """A running ``agent-canvas ask`` the owner answers through the browser."""

    def __init__(self, owner, tmp_path: Path, *args: str) -> None:  # noqa: ANN001
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("AGENT_CANVAS_", "XDG_"))
        }
        env.update(
            HOME=str(home),
            AGENT_CANVAS_PORT=str(owner.hub.port),
            AGENT_CANVAS_STATE_DIR=str(owner.hub.state_dir),
            AGENT_CANVAS_CONFIG_DIR=str(owner.hub.config_dir),
            AGENT_CANVAS_WINDOW_COMMAND="true",
        )
        self.owner = owner
        self.process = subprocess.Popen(
            [sys.executable, "-m", "agent_canvas.cli", "ask", *args],
            cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )  # fmt: skip

    def finish(self, seconds: float = 20) -> tuple[int, dict]:
        """Pump the browser until the process ends; return exit code and JSON."""
        for _ in range(int(seconds * 50)):
            if self.process.poll() is not None:
                break
            self.owner.page.wait_for_timeout(20)
        else:
            self.process.kill()
            raise AssertionError("ask did not end in time")
        out, err = self.process.communicate()
        return self.process.returncode, json.loads(out or err)


@pytest.fixture
def make(owner, tmp_path: Path):  # noqa: ANN001, ANN201
    """Create a session showing ``html``; return its id."""
    deadline = 100
    while not owner.hub.state.shells and deadline:
        owner.page.wait_for_timeout(50)
        deadline -= 1
    made: list[Asking] = []

    def build(html: str = "<p>page</p>", name: str = "alpha") -> str:
        directory = tmp_path / name
        directory.mkdir(exist_ok=True)
        body = {"project": str(directory), "agent": "claude", "title": name}
        sid = call(owner, "POST", "/api/sessions", json=body)["session"]
        (
            owner.hub.state.session_of(owner.hub.pool_of(sid)).folder / "page.html"
        ).write_text(html)
        call(owner, "POST", f"/api/sessions/{sid}/show",
             json={"project": str(directory), "name": "page.html"})  # fmt: skip
        # A later session does not take over the window: visit it as the owner would.
        owner.visit(sid)
        owner.frame.wait_for_function("window.agentCanvas !== undefined")
        return sid

    build.asking = lambda *args: made.append(Asking(owner, tmp_path, *args)) or made[-1]  # type: ignore[attr-defined]
    yield build
    for ask in made:
        if ask.process.poll() is None:
            ask.process.kill()
        ask.process.wait()
        ask.process.stdout.close()
        ask.process.stderr.close()


def card_of(owner):  # noqa: ANN001, ANN201
    return owner.page.locator("#ask-bar .ask-card")


# ---- CLI-04 -----------------------------------------------------------------------


def test_cli_04_the_card_sits_above_the_page_and_a_click_answers(owner, make) -> None:  # noqa: ANN001
    sid = make()
    ask = make.asking(
        "Which layout?", "--choice", "A", "--choice", "B", "--session", sid
    )
    card = card_of(owner)
    card.wait_for()
    assert "Which layout?" in card.inner_text()
    card_box = card.bounding_box()
    frame_box = owner.page.locator("#frame").bounding_box()
    assert card_box["y"] + card_box["height"] <= frame_box["y"] + 1  # above the page
    assert card.get_by_role("button", name="A").is_visible()
    card.get_by_role("button", name="B").click()
    code, body = ask.finish()
    assert code == 0 and body["status"] == "answered"
    assert body["event"]["kind"] == "answer" and body["event"]["value"] == ["B"]
    assert body["event"]["delivery"] == "ask" and body["event"]["state"] == "delivered"
    owner.page.wait_for_function("document.querySelectorAll('.ask-card').length === 0")


def test_cli_04_multi_selection_is_submitted_as_a_label_list(owner, make) -> None:  # noqa: ANN001
    sid = make()
    ask = make.asking("Which?", "--choice", "A", "--choice", "B", "--choice", "C",
                      "--multi", "--session", sid)  # fmt: skip
    card = card_of(owner)
    card.wait_for()
    card.get_by_label("A").check()
    card.get_by_label("C").check()
    card.get_by_role("button", name="Submit").click()
    code, body = ask.finish()
    assert code == 0 and body["event"]["value"] == ["A", "C"]


def test_cli_04_a_text_card_sends_the_typed_text(owner, make) -> None:  # noqa: ANN001
    sid = make()
    ask = make.asking("Part name?", "--session", sid)
    card = card_of(owner)
    card.wait_for()
    card.get_by_label("Your answer").fill("bracket-7")
    card.get_by_role("button", name="Send").click()
    code, body = ask.finish()
    assert code == 0 and body["event"]["value"] == "bracket-7"


def test_cli_04_enter_sends_the_text_and_choices_with_text_offer_both(
    owner,
    make,  # noqa: ANN001
) -> None:
    sid = make()
    ask = make.asking("Pick or type", "--choice", "A", "--text", "--session", sid)
    card = card_of(owner)
    card.wait_for()
    assert card.get_by_role("button", name="A").is_visible()
    field = card.get_by_label("Your answer")
    field.fill("something else")
    field.press("Enter")
    code, body = ask.finish()
    assert code == 0 and body["event"]["value"] == "something else"


# ---- CLI-05 -----------------------------------------------------------------------


def test_cli_05_the_dismiss_button_ends_the_ask_with_exit_7(owner, make) -> None:  # noqa: ANN001
    sid = make()
    ask = make.asking("Dismiss?", "--choice", "A", "--session", sid)
    card = card_of(owner)
    card.wait_for()
    card.get_by_role("button", name="Dismiss question").click()
    code, body = ask.finish()
    assert code == 7 and body["status"] == "dismissed" and body["reason"] == "owner"
    owner.page.wait_for_function("document.querySelectorAll('.ask-card').length === 0")


def test_cli_05_a_timed_out_card_stays_and_a_late_answer_is_queued(owner, make) -> None:  # noqa: ANN001
    sid = make()
    ask = make.asking("Late?", "--choice", "A", "--choice", "B", "--timeout", "1",
                      "--session", sid)  # fmt: skip
    code, body = ask.finish()
    assert code == 6 and body["status"] == "timeout"
    card = card_of(owner)
    card.wait_for()  # still there
    owner.page.wait_for_function(
        "document.querySelector('.ask-note') && "
        "document.querySelector('.ask-note').textContent.length > 0"
    )
    card.get_by_role("button", name="B").click()
    owner.page.wait_for_function("document.querySelectorAll('.ask-card').length === 0")
    events = card_events(owner.hub, sid)
    [answer] = [e for e in events if e["kind"] == "answer"]
    assert answer["value"] == ["B"] and answer["delivery"] == "now"
    assert answer["state"] == "queued"


# ---- CLI-06 -----------------------------------------------------------------------


def test_cli_06_the_awaited_block_is_highlighted_until_it_answers(owner, make) -> None:  # noqa: ANN001
    sid = make(BLOCK_PAGE)
    block = owner.frame.locator('[data-canvas-id="design"]')
    assert block.get_attribute("data-canvas-waiting") is None
    ask = make.asking("Which design?", "--block", "design", "--session", sid)
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=design]')"
        ".hasAttribute('data-canvas-waiting')"
    )
    assert (
        owner.frame.locator('[data-canvas-id="other"]').get_attribute(
            "data-canvas-waiting"
        )
        is None
    )
    card = card_of(owner)
    card.wait_for()
    assert "Which design?" in card.inner_text()
    assert card.locator("button.ask-choice").count() == 0  # no inputs on the card
    owner.frame.click("#ok")
    code, body = ask.finish()
    assert code == 0 and body["event"]["kind"] == "choice"
    assert body["event"]["value"] == ["b"] and body["event"]["delivery"] == "ask"
    assert body["event"]["target"]["canvas_id"] == "design"
    owner.frame.wait_for_function(
        "!document.querySelector('[data-canvas-id=design]')"
        ".hasAttribute('data-canvas-waiting')"
    )
    owner.page.wait_for_function("document.querySelectorAll('.ask-card').length === 0")


def test_cli_06_the_highlight_survives_a_page_update(owner, make) -> None:  # noqa: ANN001
    sid = make(BLOCK_PAGE)
    ask = make.asking("Which design?", "--block", "design", "--session", sid)
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=design]')"
        ".hasAttribute('data-canvas-waiting')"
    )
    folder = owner.hub.state.session_of(owner.hub.pool_of(sid)).folder
    (folder / "page.html").write_text(BLOCK_PAGE.replace("Designs", "Designs v2"))
    owner.frame.wait_for_function("document.body.innerText.includes('Designs v2')")
    assert (
        owner.frame.locator('[data-canvas-id="design"]').get_attribute(
            "data-canvas-waiting"
        )
        is not None
    )
    owner.page.locator("#ask-bar").get_by_role(
        "button", name="Dismiss question"
    ).click()
    assert ask.finish()[0] == 7


def test_cli_06_block_event_helper_records_a_choice_action_with_its_event(
    owner,
    make,  # noqa: ANN001
) -> None:
    sid = make(BLOCK_PAGE)
    owner.frame.click("#ok")
    owner.page.wait_for_function(
        f"(window.__drafts['{sid}'] || {{actions: []}}).actions.some("
        "(a) => a.kind === 'choice' && a.event)"
    )
    [event] = card_events(owner.hub, sid)
    assert event["kind"] == "choice" and event["value"] == ["b"]
    assert event["target"]["canvas_id"] == "design" and event["delivery"] == "now"


# ---- SES-07 and CLI-10 ---------------------------------------------------------------


def test_cli_10_the_card_comes_back_after_a_hub_restart_and_still_answers(
    owner,
    make,  # noqa: ANN001
) -> None:
    sid = make()
    ask = make.asking("Survive?", "--choice", "yes", "--choice", "no", "--session", sid)
    card_of(owner).wait_for()
    owner.hub.restart()
    owner.page.wait_for_timeout(2500)  # the shell reconnects after a second
    card = card_of(owner)
    card.wait_for()
    owner.hub.wait_for(
        lambda: any(a["waiting"] for a in owner.hub.open_asks(sid)), timeout=15
    )
    card.get_by_role("button", name="yes").click()
    code, body = ask.finish()
    assert code == 0 and body["event"]["value"] == ["yes"]
