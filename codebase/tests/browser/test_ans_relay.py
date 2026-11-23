# ruff: noqa: E501
"""The answer relay in the owner's window (ANS-02, SEC-09).

A test-only element, ``x-answerer``, posts answers for a card the way the real
answer areas will (P26.6 to P26.8); the cards themselves are the real Ask and Do.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from .support import block

pytestmark = pytest.mark.browser

FIXTURE_ELEMENT = """
<script>
window.__log = [];
document.addEventListener("agentcanvas:answers", (e) => window.__log.push(Object.keys(e.detail.items)));
customElements.define("x-answerer", class extends HTMLElement {
  connectedCallback() {
    const target = () => document.querySelector(`[data-canvas-id="${this.getAttribute("for")}"]`);
    const post = document.createElement("button");
    post.id = "post-" + this.getAttribute("for");
    post.onclick = () => window.agentCanvas.answer(target(), JSON.parse(this.dataset.value));
    const tick = document.createElement("button");
    tick.id = "tick-" + this.getAttribute("for");
    tick.onclick = () => window.agentCanvas.tick(target(), [1]);
    this.output = document.createElement("output");
    this.append(post, tick, this.output);
    const show = (items) => {
      const item = (items || {})[this.getAttribute("for")];
      this.output.textContent = item ? item.state : "open";
    };
    show(window.agentCanvas.answerItems);
    document.addEventListener("agentcanvas:answers", (e) => show(e.detail.items));
  }
});
</script>
"""
ASK = {"question": "Keep layout A?", "options": ["keep", "change"]}
DO = {
    "title": "Plug it in",
    "steps": [{"text": "plug", "run": "echo hi"}],
    "where": "bench",
}


def page(
    extra: str = "", question: str = ASK["question"], ids: tuple = ("q1", "w1")
) -> str:
    ask_id, do_id = ids
    value = json.dumps({"answer": ["keep"], "note": "ok"}).replace('"', "&quot;")
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        + extra
        + block("canvas-ask", ask_id, {**ASK, "question": question})
        + block("canvas-do", do_id, DO)
        + f'<x-answerer for="{ask_id}" data-value="{value}"></x-answerer>'
        + FIXTURE_ELEMENT
        + "</body></html>"
    )


def card_text(owner, card_id: str, selector: str) -> str:  # noqa: ANN001
    return owner.frame.evaluate(
        "([id, s]) => document.querySelector(`[data-canvas-id=${id}]`)"
        ".shadowRoot.querySelector(s).textContent",
        [card_id, selector],
    )


def pulsing(owner, card_id: str) -> bool:  # noqa: ANN001
    return owner.frame.evaluate(
        "(id) => document.querySelector(`[data-canvas-id=${id}]`)"
        ".shadowRoot.querySelector('.k').classList.contains('pulse')",
        card_id,
    )


def wait_ready(owner, fixture: bool = True) -> None:  # noqa: ANN001
    """Wait for the cards, and for the fixture element unless a morph removed its output."""
    owner.frame.wait_for_function(
        """(fixture) => [...document.querySelectorAll('canvas-ask,canvas-do')].every(
          (e) => e.renderIdle && e.shadowRoot && e.shadowRoot.querySelector('.k'))
          && (!fixture || document.querySelector('x-answerer output'))""",
        arg=fixture,
    )


def wait_words(owner, card_id: str, start: str) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        """([id, start]) => document.querySelector(`[data-canvas-id=${id}]`)
          .shadowRoot.querySelector('.kt').textContent.startsWith(start)""",
        arg=[card_id, start],
    )


@pytest.fixture
def made(owner, make):  # noqa: ANN001, ANN201
    shown = make(page())
    wait_ready(owner)
    return shown


def store_events(made) -> list[dict]:  # noqa: ANN001
    return [e for e in made.events if e["kind"] in ("answer", "todo", "change")]


# ---- ANS-02: from the frame to the hub and back ------------------------------------------


def test_ans_02_an_answer_from_the_frame_reaches_the_hub_and_the_card_shows_it(
    owner,
    made,  # noqa: ANN001
) -> None:
    assert pulsing(owner, "q1") and card_text(owner, "q1", ".kt") == "waits for you"
    owner.frame.click("#post-q1")
    [event] = made.wait_events(1)
    assert (event["kind"], event["target"]["canvas_id"]) == ("answer", "q1")
    assert event["value"]["answer"] == ["keep"] and event["page"] == "page.html"
    wait_words(owner, "q1", "answered ")
    assert not pulsing(owner, "q1")
    assert pulsing(owner, "w1")  # nothing else changed
    assert owner.frame.inner_text("x-answerer output") == "answered"


def test_ans_01_an_answer_carries_the_config_the_card_showed(owner, made) -> None:  # noqa: ANN001
    with owner.page.expect_request(lambda r: r.url.endswith("/answers/answer")) as sent:
        owner.frame.click("#post-q1")
    seen = json.loads(sent.value.post_data)["seen"]
    assert seen["question"] == ASK["question"] and seen["options"] == ASK["options"]
    made.wait_events(1)


def test_ans_02_after_a_reload_of_the_window_the_answered_line_shows_at_once(
    owner,
    made,  # noqa: ANN001
) -> None:
    owner.frame.click("#post-q1")
    made.wait_events(1)
    wait_words(owner, "q1", "answered ")
    words = card_text(owner, "q1", ".kt")
    owner.page.reload()
    owner.visit(made.sid)
    wait_ready(owner)
    wait_words(owner, "q1", "answered ")
    assert card_text(owner, "q1", ".kt") == words
    assert not pulsing(owner, "q1")
    assert owner.frame.inner_text("x-answerer output") == "answered"
    assert len(store_events(made)) == 1  # the reload made no second answer


def test_ans_02_a_rewrite_of_the_page_never_shows_an_answered_card_open(
    owner,
    made,  # noqa: ANN001
) -> None:
    owner.frame.click("#post-q1")
    made.wait_events(1)
    wait_words(owner, "q1", "answered ")
    made.rewrite(page(extra="<p id='added'>new text</p>"))
    owner.frame.wait_for_selector("#added", state="attached")
    wait_ready(owner, fixture=False)
    assert card_text(owner, "q1", ".kt").startswith("answered ")
    made.rewrite(page(extra="<p id='added'>new text</p>", question="Keep layout B?"))
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=q1]').shadowRoot.textContent"
        ".includes('layout B')"
    )
    wait_words(owner, "q1", "waits")
    assert pulsing(owner, "q1")


def test_ans_02_ticks_travel_to_the_store_without_an_event(owner, made) -> None:  # noqa: ANN001
    owner.frame.evaluate(
        "window.agentCanvas.tick(document.querySelector('[data-canvas-id=w1]'), [1])"
    )
    folder = made.folder / ".answers" / "page.html.json"
    deadline = time.monotonic() + 5
    while not folder.exists() and time.monotonic() < deadline:
        owner.page.wait_for_timeout(50)
    assert json.loads(folder.read_text())["items"]["w1"]["ticked"] == [1]
    assert store_events(made) == []


def test_ans_02_a_second_pages_frame_never_receives_the_first_pages_items(
    owner,
    made,  # noqa: ANN001
) -> None:
    owner.frame.click("#post-q1")
    made.wait_events(1)
    wait_words(owner, "q1", "answered ")
    (made.folder / "other.html").write_text(page(ids=("o1", "o2")))
    owner.page.wait_for_timeout(800)  # the watcher takes the new page
    owner.hub.show(made.sid, "other.html")
    owner.frame.wait_for_function("document.querySelector('[data-canvas-id=o1]')")
    wait_ready(owner)
    owner.frame.click("#post-o1")
    made.wait_events(2)
    owner.frame.wait_for_function("window.__log.length > 0")
    seen = {name for names in owner.frame.evaluate("window.__log") for name in names}
    assert seen == {"o1"}  # never q1
    items = owner.frame.evaluate("Object.keys(window.agentCanvas.answerItems)")
    assert items == ["o1"]


# ---- SEC-09: what a page can forge ---------------------------------------------------------


def forge(owner, message: dict) -> None:  # noqa: ANN001
    owner.frame.evaluate("(m) => window.parent.postMessage(m, '*')", message)
    owner.page.wait_for_timeout(500)


def test_sec_09_a_forged_answer_touches_only_the_items_of_the_shown_page(
    owner,
    made,  # noqa: ANN001
) -> None:
    (made.folder / "other.html").write_text(page(ids=("o1", "o2")))
    owner.page.wait_for_timeout(800)
    forge(owner, {"type": "answer", "id": "o1", "value": {"answer": ["keep"]}})
    assert store_events(made) == []  # o1 is on other.html, not on the shown page
    forge(owner, {"type": "answer", "id": "q1", "value": {"answer": ["keep"]}})
    assert [e["target"]["canvas_id"] for e in store_events(made)] == ["q1"]
    assert not (made.folder / ".answers" / "other.html.json").exists()


@pytest.mark.parametrize(
    "message",
    [
        {"type": "answer", "id": 7, "value": {"answer": ["keep"]}},
        {"type": "answer", "id": "q1", "value": ["keep"]},
        {"type": "answer", "id": "q1"},
        {"type": "answer", "id": "x" * 201, "value": {"answer": ["keep"]}},
        {"type": "tick", "id": "w1", "ticked": ["1"]},
        {"type": "tick", "id": "w1", "ticked": list(range(60))},
        {"type": "tick", "id": "q1", "ticked": [1]},
    ],
)
def test_sec_09_a_malformed_answer_or_tick_changes_nothing(
    owner,
    made,
    message,  # noqa: ANN001
) -> None:
    forge(owner, message)
    assert store_events(made) == []
    assert not (made.folder / ".answers").exists()


def test_sec_09_an_oversized_answer_is_dropped_by_the_guard(owner, made) -> None:  # noqa: ANN001
    before = owner.page.evaluate("window.__guard.dropped.size")
    huge = {"answer": ["x" * 300_000]}
    forge(owner, {"type": "answer", "id": "q1", "value": huge})
    assert owner.page.evaluate("window.__guard.dropped.size") == before + 1
    assert store_events(made) == []


# ---- ANS-02, SEC-09: the page that is leaving the frame -----------------------------------

FORGER = """
<script>
window.addEventListener("message", (e) => {
  if (e.data && e.data.type === "answers") {
    window.parent.postMessage({type: "report", name: "got-items", data: Object.keys(e.data.items)}, "*");
  }
});
window.startForging = () => setInterval(() => {
  window.parent.postMessage({type: "ready"}, "*");
  window.parent.postMessage({type: "answer", id: "o1", value: {answer: ["keep"]}}, "*");
}, 50);
</script>
"""


def test_ans_02_the_page_leaving_the_frame_gets_no_items_and_its_answers_are_not_stored(
    owner,
    make,  # noqa: ANN001
) -> None:
    made = make(page(extra=FORGER))
    wait_ready(owner)
    (made.folder / "other.html").write_text(page(ids=("o1", "o2")))
    owner.page.wait_for_timeout(800)  # the watcher takes the new page
    owner.hub.show(made.sid, "other.html")
    owner.frame.wait_for_function("document.querySelector('[data-canvas-id=o1]')")
    wait_ready(owner)
    owner.frame.click("#post-o1")  # o1 now holds the owner's answer
    made.wait_events(1)
    owner.hub.show(made.sid, "page.html")
    owner.frame.wait_for_function("window.startForging")
    wait_ready(owner)
    owner.page.wait_for_timeout(300)
    before = len(owner.reports_of("got-items"))
    held: list = []
    owner.context.route(re.compile(r"/other\.html"), lambda route: held.append(route))
    owner.frame.evaluate("window.startForging()")
    # SES-15: other.html's kept frame is dropped, as the frame cap does, so it loads again.
    owner.page.evaluate(
        "for (const r of liveFrames.values()) if (r !== active) dropFrame(r)"
    )
    owner.hub.show(made.sid, "other.html")
    for _ in range(100):
        if held:
            break
        owner.page.wait_for_timeout(50)
    assert held, "the next page was never requested"
    owner.page.wait_for_timeout(1500)  # the old page is still in the frame and forging
    assert (
        len(owner.reports_of("got-items")) == before
    )  # read in the shell: the frame is busy
    assert len(store_events(made)) == 1
    held[0].continue_()
    owner.frame.wait_for_function("document.querySelector('[data-canvas-id=o1]')")
    wait_ready(owner)
    owner.frame.wait_for_function("window.agentCanvas.answerItems")  # sent after load
    assert owner.frame.evaluate("Object.keys(window.agentCanvas.answerItems)") == ["o1"]
    owner.frame.click("#post-o1")  # the new page's own answer still counts
    [_, event] = made.wait_events(2)
    assert event["target"]["canvas_id"] == "o1" and event["page"] == "other.html"
    assert len(store_events(made)) == 2
