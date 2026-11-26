"""The window shows the pool of a project in every card of it (POOL-03, POOL-04, #2)."""

# ruff: noqa: E501

from __future__ import annotations

import copy
import json

import pytest

from .support import call
from .test_hcw_01_herdr_window import pane

pytestmark = pytest.mark.browser

PAGE = "dash.html"
LISTEN = (
    "<p id=t>one</p><script>document.addEventListener('agentcanvas:file-changed',"
    "(e) => { window.changed = (window.changed || []).concat(e.detail.path); });</script>"
)
COMMENT = {
    "page": PAGE, "page_version": 1, "kind": "point", "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
    "target": {"canvas_id": None, "selector": "#t", "text": None},
}  # fmt: skip


class Project:
    """Sessions of one project in one Herdr tab, one card each."""

    def __init__(self, owner, tmp_path, count: int) -> None:  # noqa: ANN001
        while not owner.hub.state.shells:
            owner.page.wait_for_timeout(25)
        self.owner, self.page = owner, owner.page
        self.directory = tmp_path / "proj"
        self.directory.mkdir()
        self.ids = [self.start(f"agent {n}") for n in range(count)]
        self.folder = owner.hub.state.session_of(owner.hub.pool_of(self.ids[0])).folder
        panes = [pane(f"t{n}", sid, n == 0) for n, sid in enumerate(self.ids)]
        self.herdr = {
            "available": True,
            "focus": {"space": "sp1", "tab": "tb1", "pane": "pt0"},
            "spaces": [
                {
                    "id": "sp1", "name": "lab", "color": "#22a99a", "active": True,
                    "tabs": [{"id": "tb1", "name": "rig", "active": True, "panes": panes}],
                }
            ],
            "other": [],
        }  # fmt: skip
        app = owner.hub.app.state.services.herdr_app
        app.snapshot = lambda: copy.deepcopy(self.herdr)
        app.focus = lambda _snapshot, _key, _value: True

    def start(self, title: str) -> str:
        body = {"project": str(self.directory), "agent": "claude", "title": title}
        return call(self.owner, "POST", "/api/sessions", json=body)["session"]

    def show(self, sid: str, name: str, html: str | None = None) -> None:
        if html is not None:
            (self.folder / name).write_text(html)
        body = {"project": str(self.directory), "name": name}
        call(self.owner, "POST", f"/api/sessions/{sid}/show", json=body)

    def owner_post(self, path: str, body: dict) -> int:
        """POST as the owner's window does (its cookie)."""
        return self.page.evaluate(
            """async ([path, body]) => (await fetch(path, {method: "POST",
              headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})).status""",
            [path, body],
        )

    def strip(self, sid: str) -> list[str]:
        return self.page.locator(f'.hv-card[data-session="{sid}"] .hv-pt').evaluate_all(
            "(els) => els.map((e) => e.title)"
        )

    def focus(self, sid: str) -> None:
        self.page.locator(f'.hv-card[data-session="{sid}"] .hv-chead').click()
        self.page.wait_for_function("(id) => activeId === id", arg=sid)


def test_pool_03_a_page_two_sessions_changed_shows_in_both_cards_with_its_comments(
    owner, tmp_path
) -> None:  # noqa: ANN001
    world = Project(owner, tmp_path, 2)
    a, b = world.ids
    world.show(a, PAGE, LISTEN)
    world.show(b, PAGE)
    page = world.page
    page.wait_for_function(
        "([a, b]) => ['.hv-card[data-session=\"' + a + '\"] .hv-pt', '.hv-card[data-session=\"' + b + '\"] .hv-pt']"
        ".every((s) => document.querySelector(s))",
        arg=[a, b],
    )
    assert world.strip(a) == [PAGE] and world.strip(b) == [PAGE]
    # The page is one page of the project: the sidebar counts it once, not once per card.
    assert page.locator(".hv-row.on .hv-cnt").inner_text() == "1"

    # Card B is shown; a comment made in card A's route reaches B's panel by itself.
    world.focus(b)
    page.wait_for_function("(id) => activeId === id", arg=b)
    owner.frame.wait_for_function("window.agentCanvas !== undefined")
    assert page.locator("#comment-panel .ent").count() == 0
    assert world.owner_post(f"/api/sessions/{a}/comments", COMMENT) == 200
    page.locator("#comment-panel .ent").first.wait_for(timeout=5000)
    assert page.locator("#comment-panel .ent").count() == 1

    # A data file of the pool changes: the shown page of card B is told.
    (world.folder / "data.json").write_text(json.dumps({"x": 1}))
    owner.frame.wait_for_function(
        "(window.changed || []).includes('data.json')", timeout=5000
    )

    # The page changes: card A's view-only frame loads the new page too.
    world.focus(b)
    (world.folder / PAGE).write_text(LISTEN.replace("one", "two"))
    inner = (
        page.locator(f'.hv-card[data-session="{a}"] iframe')
        .element_handle()
        .content_frame()
    )
    inner.wait_for_function(
        "document.getElementById('t')?.textContent === 'two'", timeout=8000
    )


def test_pool_04_a_pinned_page_shows_first_with_its_mark_in_a_fresh_sessions_card(
    owner, tmp_path
) -> None:  # noqa: ANN001
    world = Project(owner, tmp_path, 2)
    a, fresh = world.ids
    world.show(a, PAGE, "<p id=t>dash</p>")
    answer = call(
        owner, "POST", f"/api/sessions/{a}/pages", json={"action": "pin", "name": PAGE}
    )
    assert answer["pinned"] is True
    page = world.page
    card = f'.hv-card[data-session="{fresh}"]'
    count = "([card, n]) => document.querySelectorAll(card + ' .hv-pt').length === n"
    # The fresh session has shown nothing: its card shows the pinned page.
    page.wait_for_function(count, arg=[card, 1])
    assert world.strip(fresh) == [PAGE]
    assert page.locator(f"{card} .hv-frame").get_attribute("data-page") == PAGE
    page.locator(f"{card} iframe").wait_for(state="attached", timeout=5000)
    inner = page.locator(f"{card} iframe").element_handle().content_frame()
    inner.wait_for_function(
        "document.getElementById('t')?.textContent === 'dash'", timeout=8000
    )
    world.show(fresh, "mine.html", "<p>mine</p>")
    page.wait_for_function(count, arg=[card, 2])
    assert world.strip(fresh) == [PAGE, "mine.html"]
    marked = page.locator(f"{card} .hv-pt:has(.hv-pin)")
    assert marked.evaluate_all("(els) => els.map((e) => e.title)") == [PAGE]
    assert page.locator(f"{card} .hv-pin").first.is_visible()

    # An older canvas sends no `pinned`: no page counts as pinned and nothing fails.
    marks = page.evaluate(
        """() => {
          const root = document.createElement("div");
          const view = HerdrView.mount(root, {});
          const pane = {pane: "p", terminal: "t", name: "n", app: "claude-code", session: "s", focused: true};
          view.update({available: true, focus: null, other: [], spaces: [{id: "sp", name: "x",
            color: "#fff", active: true, tabs: [{id: "tb", name: "t", active: true, panes: [pane]}]}]},
            [{id: "s", title: "s", pages: ["a.html"], active_page: "a.html", base: "/x/"}]);
          const marks = root.querySelectorAll(".hv-pin").length;
          view.destroy();
          return marks;
        }"""
    )
    assert marks == 0


def test_pool_04_the_pin_key_toggles_and_is_listed_in_the_overview(
    owner, tmp_path
) -> None:  # noqa: ANN001
    world = Project(owner, tmp_path, 2)
    a, b = world.ids
    world.show(a, PAGE, "<p>dash</p>")
    world.show(b, PAGE)
    page = world.page
    world.focus(a)
    page.wait_for_function("keyMap.current('page.pin').length > 0")
    assert page.evaluate("keyMap.current('page.pin')") == ["Alt+p"]
    mark = ".hv-pt:has(.hv-pin)"

    page.keyboard.press("Alt+p")
    for sid in (a, b):
        page.locator(f'.hv-card[data-session="{sid}"] {mark}').wait_for(timeout=5000)
    page.keyboard.press("Alt+p")
    for sid in (a, b):
        page.locator(f'.hv-card[data-session="{sid}"] {mark}').wait_for(
            state="detached", timeout=5000
        )

    page.keyboard.press("?")
    page.wait_for_selector("#key-help")
    row = page.locator('#key-help dt[data-action="page.pin"]')
    assert row.count() == 1
    assert row.inner_text() == "Alt+p"


def test_pool_03_an_agent_reply_marks_only_the_cards_that_list_its_page(
    owner, tmp_path
) -> None:  # noqa: ANN001
    world = Project(owner, tmp_path, 3)
    a, b, c = world.ids
    world.show(a, PAGE, LISTEN)
    world.show(b, PAGE)
    world.show(c, "other.html", "<p>other</p>")
    page = world.page
    page.wait_for_function(
        "(id) => tabs.find((t) => t.id === id)?.pages.includes('other.html')", arg=c
    )
    assert page.evaluate("() => activeId") == a
    assert world.owner_post(f"/api/sessions/{a}/comments", COMMENT) == 200
    send = {
        "delivery": "next-message", "message": "", "page": PAGE,
        "viewport": {"width": 10, "height": 10, "scroll_x": 0, "scroll_y": 0},
        "screenshot": None, "screenshot_error": "none",
    }  # fmt: skip
    assert call(owner, "POST", f"/api/sessions/{a}/send", json=send)["event"]
    page.wait_for_timeout(300)
    # The shows marked the cards; start from no mark.
    page.evaluate("() => tabs.forEach((t) => { t.updated = false; })")
    reply = {"page": PAGE, "n": 1, "text": "fixed"}
    replied = call(owner, "POST", f"/api/sessions/{a}/comments/reply", json=reply)
    assert replied["n"] == 1
    page.wait_for_function("(id) => tabs.find((t) => t.id === id).updated", arg=b)
    page.wait_for_timeout(300)
    assert not page.evaluate("(id) => tabs.find((t) => t.id === id).updated", c)
