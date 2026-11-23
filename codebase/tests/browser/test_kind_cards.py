# ruff: noqa: E501, F811
"""The card module and the six card frames (KIND-01 to KIND-04, KIND-06, KIND-05 slice).

Fixtures are in ``tests/fixtures/kinds/``. The frames of Ask, Do and Decision have
empty answer areas here; their answers come in later packages.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from helpers import CODEBASE_DIR, decode_png

from .support import block
from .test_comment_kinds import click_at, doc_box, pick, save_box, what
from .test_heavy_blocks import wait_plot
from .test_look_window import headless, look  # noqa: F401

pytestmark = pytest.mark.browser

FIXTURES = CODEBASE_DIR / "tests" / "fixtures" / "kinds"
DASHBOARD = (FIXTURES / "dashboard.html").read_text()
NESTING = (FIXTURES / "nesting.html").read_text()
TAGS = "canvas-ask,canvas-do,canvas-report,canvas-decision,canvas-alert,canvas-live"
IDS = {
    "q-infill", "w-heater", "r-result", "d-mat", "a-bed", "l-job",
    "r-plan", "q-plan", "a-heater", "w-plug", "r-finding",
}  # fmt: skip


def wait_cards(owner, count: int) -> None:  # noqa: ANN001
    """Wait until ``count`` card elements hold a card or an error box."""
    owner.frame.wait_for_function(
        """([tags, n]) => { const all = [...document.querySelectorAll(tags)];
          return all.length === n && all.every((e) => e.renderIdle && e.shadowRoot
            && e.shadowRoot.querySelector('.k, .block-error')); }""",
        arg=[TAGS, count],
    )


def cards(owner) -> dict:  # noqa: ANN001
    """Per card id: head line, words, shape, icon and classes."""
    return owner.frame.evaluate(
        """(tags) => Object.fromEntries([...document.querySelectorAll(tags)].map((e) => {
          const id = e.dataset.canvasId;
          const k = e.shadowRoot.querySelector('.k');
          if (!k) return [id, {error: e.shadowRoot.querySelector('.block-error').textContent}];
          const s = getComputedStyle(k);
          const head = k.querySelector('.kh');
          return [id, {
            tag: e.localName, head: head.querySelector('.kl').textContent,
            words: head.querySelector('.kt').textContent, classes: k.className,
            radius: s.borderTopLeftRadius, edge: s.borderTopStyle,
            hazard: !!k.querySelector('.hazard'), icon: head.querySelector('svg').innerHTML,
            shadow: s.boxShadow, text: k.textContent,
          }];
        }))""",
        TAGS,
    )


def animations(owner) -> dict:  # noqa: ANN001
    """Running animations per part: ``id:card`` for the card, ``id:icon`` for its icon."""
    return owner.frame.evaluate(
        """(tags) => { const out = {};
          for (const e of document.querySelectorAll(tags)) {
            const k = e.shadowRoot.querySelector('.k');
            if (!k) continue;
            const card = k.getAnimations().map((a) => a.animationName);
            const icon = [...k.querySelectorAll('.kh .ic')]
              .flatMap((i) => i.getAnimations().map((a) => a.animationName));
            if (card.length) out[e.dataset.canvasId + ':card'] = card;
            if (icon.length) out[e.dataset.canvasId + ':icon'] = icon;
          }
          return out; }""",
        TAGS,
    )


def set_state(owner, canvas_id: str, **patch) -> None:  # noqa: ANN001, ANN003
    """Set a card's owner state (``answered``, ``later``, ``at``) and wait for the redraw."""
    owner.frame.evaluate(
        "([id, p]) => document.querySelector(`[data-canvas-id=${id}]`).setState(p)",
        [canvas_id, patch],
    )
    owner.frame.wait_for_function(
        "(id) => document.querySelector(`[data-canvas-id=${id}]`).renderIdle",
        arg=canvas_id,
    )


@pytest.fixture
def dashboard(owner, make):  # noqa: ANN001, ANN201
    """The fixture dashboard, shown and drawn."""
    made = make(DASHBOARD)
    wait_cards(owner, len(IDS))
    wait_plot(owner, "r-plot")
    return made


# ---- KIND-01: head line, text, children ---------------------------------------------

HEADS = {
    "q-infill": ("Needs you: Ask", "waits for you"),
    "w-heater": ("Needs you: Do", "waits for you"),
    "r-result": ("Report: result", "from the agent"),
    "r-plan": ("Report: plan", "from the agent"),
    "r-finding": ("Report: finding", "from the agent"),
    "d-mat": ("Decision", "you may change it"),
    "a-bed": ("Alert", "no action needed"),
    "l-job": ("Live", "updating"),
    "q-plan": ("Needs you: Ask", "waits for you"),
    "w-plug": ("Needs you: Do", "waits for you"),
    "a-heater": ("Alert", "needs action"),
}


def test_kind_01_every_kind_draws_its_head_line_and_state_words(dashboard) -> None:  # noqa: ANN001
    found = cards(dashboard.owner)
    assert set(found) == set(HEADS)
    for canvas_id, (head, words) in HEADS.items():
        assert (found[canvas_id]["head"], found[canvas_id]["words"]) == (head, words)
    # no agent name anywhere in a head line (A-102): the session's agent is "claude"
    assert not any("claude" in c["head"].lower() for c in found.values())


def test_kind_01_agent_text_is_drawn_as_text_never_as_html(dashboard) -> None:  # noqa: ANN001
    inside = dashboard.owner.frame.evaluate(
        """() => { const k = document.querySelector('canvas-report[data-canvas-id=r-result]')
          .shadowRoot.querySelector('.k');
          return {text: k.textContent, bold: k.querySelectorAll('b').length}; }"""
    )
    assert "<b>the specimen</b>" in inside["text"]
    assert inside["bold"] == 0


def test_kind_01_lines_with_a_dash_or_a_number_become_list_items(dashboard) -> None:  # noqa: ANN001
    lists = dashboard.owner.frame.evaluate(
        """() => { const k = document.querySelector('canvas-ask[data-canvas-id=q-infill]')
          .shadowRoot.querySelector('.k');
          const items = (sel) => [...k.querySelectorAll(sel)].map((li) => li.textContent);
          return {ul: items('ul > li'), ol: items('ol > li'),
            p: [...k.querySelectorAll('p')].map((p) => p.textContent)}; }"""
    )
    assert lists["ul"] == ["Gyroid is stiffer", "Lines print faster"]
    assert lists["ol"] == ["First choice", "Second choice"]
    assert lists["p"] == [
        "Which infill pattern for the bracket?",
        "Both print in about 4 h.",
    ]


def test_kind_01_a_child_plot_renders_inside_its_card_in_page_order(dashboard) -> None:  # noqa: ANN001
    boxes = dashboard.owner.frame.evaluate(
        """() => { const rect = (e) => { const r = e.getBoundingClientRect();
            return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; };
          const report = document.querySelector('[data-canvas-id=r-result]');
          const plan = document.querySelector('[data-canvas-id=r-plan]');
          return {
            card: rect(report.shadowRoot.querySelector('.k')),
            title: rect(report.shadowRoot.querySelector('.q')),
            plot: rect(report.querySelector('canvas-plot')),
            planText: rect(plan.shadowRoot.querySelector('ol')),
            ask: rect(plan.querySelector('canvas-ask')),
          }; }"""
    )
    card, plot = boxes["card"], boxes["plot"]
    assert card["left"] < plot["left"] and plot["right"] < card["right"]
    assert boxes["title"]["bottom"] <= plot["top"] and plot["bottom"] <= card["bottom"]
    assert boxes["planText"]["bottom"] <= boxes["ask"]["top"]


# ---- KIND-02: the look ----------------------------------------------------------------


def test_kind_02_kinds_differ_by_more_than_colour(dashboard) -> None:  # noqa: ANN001
    found = cards(dashboard.owner)
    one = {kind: found[i] for kind, i in {
        "ask": "q-infill", "do": "w-heater", "report": "r-result", "decision": "d-mat",
        "alert": "a-bed", "live": "l-job"}.items()}  # fmt: skip
    assert len({c["icon"] for c in one.values()}) == 6
    shapes = {
        kind: (c["radius"], c["edge"], c["hazard"])
        for kind, c in one.items()
        if kind != "do"  # Ask and Do are both "Needs you" and differ by icon
    }
    assert len(set(shapes.values())) == 5, shapes
    assert one["ask"]["radius"] == one["do"]["radius"] == "20px"
    assert one["report"]["radius"] == "4px"
    assert one["decision"]["edge"] == "dashed"
    assert one["alert"]["hazard"] and not any(
        c["hazard"] for kind, c in one.items() if kind != "alert"
    )
    assert one["ask"]["radius"] != one["live"]["radius"]


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_kind_02_the_contrast_check_finds_nothing_in_either_mode(
    owner,
    make,
    headless,
    scheme: str,  # noqa: ANN001, F811
) -> None:
    made = make(DASHBOARD)
    wait_cards(owner, len(IDS))
    result = look(owner, made.sid, width=900, height=900, scheme=scheme, full=True)
    assert result["scheme"] == scheme, result
    findings = result["audit"]["findings"]
    assert [f for f in findings if f["rule"] == "contrast"] == [], findings
    # the finished picture of the look (the owner's reference is look-light-full.png)
    if scheme == "light" and os.environ.get("KINDS_LOOK_DIR"):
        target = Path(os.environ["KINDS_LOOK_DIR"])
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(result["png"], target / "look-light-full.png")
    if scheme == "dark" and os.environ.get("KINDS_LOOK_DIR"):
        shutil.copy(
            result["png"], Path(os.environ["KINDS_LOOK_DIR"]) / "look-dark-full.png"
        )


def test_kind_02_the_contrast_check_does_see_a_faint_text_in_a_card_page(
    owner,
    make,  # noqa: ANN001
) -> None:
    """Positive control: the same check, on the same renderer, reports a faint line."""
    faint = '<p id="faint" style="color:#bbb;background:#fff">faint line</p>'
    made = make(DASHBOARD.replace("</div></body>", faint + "</div></body>"))
    wait_cards(owner, len(IDS))
    findings = look(owner, made.sid, width=900, height=900, full=True)["audit"][
        "findings"
    ]
    assert [f["rule"] for f in findings if f["rule"] == "contrast"], findings


# ---- KIND-03: only open needs-you parts animate ---------------------------------------

OPEN = {"q-infill:card", "w-heater:card", "q-plan:card", "w-plug:card"}


def test_kind_03_only_open_asks_and_dos_pulse_and_live_blinks(dashboard) -> None:  # noqa: ANN001
    running = animations(dashboard.owner)
    assert set(running) == OPEN | {"l-job:icon"}, running
    assert all(running[k] == ["kind-glow"] for k in OPEN)
    assert running["l-job:icon"] == ["kind-blink"]
    # an Alert holding an open Do stays still; the Do inside it pulses
    assert "a-heater:card" not in running and "w-plug:card" in running


def test_kind_03_answering_or_putting_off_stops_the_pulse(dashboard) -> None:  # noqa: ANN001
    owner = dashboard.owner
    set_state(owner, "q-infill", answered=True, at="14:02")
    set_state(owner, "w-heater", later=True)
    set_state(owner, "q-plan", answered=True)
    set_state(owner, "w-plug", answered=True, at="14:05")
    assert set(animations(owner)) == {"l-job:icon"}
    found = cards(owner)
    assert (
        found["q-infill"]["words"] == "answered 14:02"
        and "answered" in found["q-infill"]["classes"]
    )
    assert (
        found["w-heater"]["words"] == "later"
        and "answered" not in found["w-heater"]["classes"]
    )
    assert found["w-plug"]["words"] == "done 14:05"


def test_kind_03_with_reduced_motion_nothing_animates_and_open_parts_show_a_mark(
    dashboard,  # noqa: ANN001
) -> None:
    owner = dashboard.owner
    owner.page.emulate_media(reduced_motion="reduce")
    owner.page.wait_for_timeout(200)
    assert animations(owner) == {}
    found = cards(owner)
    for canvas_id in ("q-infill", "w-heater", "q-plan", "w-plug"):
        assert found[canvas_id]["shadow"] != "none", canvas_id
    for canvas_id in ("r-result", "d-mat", "a-bed", "l-job", "a-heater"):
        assert found[canvas_id]["shadow"] == "none", canvas_id
    set_state(owner, "q-infill", answered=True)
    assert cards(owner)["q-infill"]["shadow"] == "none"


# ---- KIND-04: mixing and nesting ------------------------------------------------------


def test_kind_04_a_plot_in_a_card_has_the_same_pixels_as_the_plot_alone(
    owner,
    make,  # noqa: ANN001
) -> None:
    def plot(canvas_id: str) -> str:
        config = {
            "data": [{"x": [0, 1, 2, 3], "y": [0, 3, 1, 4], "mode": "lines+markers"}],
            "layout": {"width": 400, "height": 190},
        }
        return block("canvas-plot", canvas_id, config)

    page = (
        "<style>body{margin:0;padding:10px;font:14px sans-serif}</style>"
        f'<div style="width:400px">{plot("alone")}</div>'
        # 430 px less the card's padding and border: the plot gets the same 400 px
        + '<div style="width:430px">'
        + block("canvas-report", "holder", {"title": "A plot inside"}, plot("inside"))
        + "</div>"
    )
    make(page)
    wait_plot(owner, "alone")
    wait_plot(owner, "inside")
    shots = [
        owner.frame.locator(f"canvas-plot[data-canvas-id={i}]").screenshot()
        for i in ("alone", "inside")
    ]
    # The outermost pixels of the block's rounded corner and border blend with
    # whatever lies behind the block (page or card tint); every pixel inside
    # that 10 px rim must be equal, bar a handful of anti-aliased text pixels.
    (w1, h1, one), (w2, h2, two) = (decode_png(shot) for shot in shots)
    # 281 or 282 high: the frame's fractional offset rounds the clip either way
    assert (w1, h1) == (w2, h2) and w1 == 400 and h1 in (281, 282)
    rim = 10
    unequal = [
        (x, y)
        for y in range(rim, h1 - rim)
        for x in range(rim, w1 - rim)
        if one[y][x] != two[y][x]
    ]
    rects = owner.frame.evaluate(
        "() => [...document.querySelectorAll('canvas-plot')].map((e) => {"
        " const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })"
    )
    # a few text pixels of the axis labels differ with the tile the plot is cut in
    assert len(unequal) <= 12, (unequal, rects)
    assert sum(r1[x] != r2[x] for r1, r2 in zip(one, two) for x in range(w1)) < 600
    # and the card gives the plot no kind visuals
    styles = owner.frame.evaluate(
        """() => ['alone', 'inside'].map((i) => {
          const e = document.querySelector(`canvas-plot[data-canvas-id=${i}]`);
          const s = getComputedStyle(e);
          return [s.color, s.backgroundColor, s.animationName, s.boxShadow, s.fontSize];
        })"""
    )
    assert styles[0] == styles[1]


def test_kind_04_cards_in_cards_show_the_error_box_except_an_ask_or_do_in_a_holder(
    owner,
    make,  # noqa: ANN001
) -> None:
    made = make(NESTING)
    wait_cards(owner, 10)
    found = cards(owner)
    broken = {i for i, c in found.items() if "error" in c}
    assert broken == {
        "n-decision",
        "n-ask-in-decision",
        "n-do-in-ask",
        "n-alert-in-live",
    }, found
    assert "canvas-report" in found["n-decision"]["error"]
    assert "canvas-decision" in found["n-ask-in-decision"]["error"]
    for canvas_id in (
        "n-ask-deep",
        "n-do-in-live",
        "n-report",
        "n-outer-ask",
        "n-live",
    ):
        assert "error" not in found[canvas_id], canvas_id
    listed = {e["canvas_id"] for e in made.shown["errors"] if e["source"] == "block"}
    assert listed == broken


def test_kind_04_a_point_comment_on_a_paragraph_in_a_card_anchors_to_it(studio) -> None:  # noqa: ANN001
    page = (
        "<style>body{margin:0}</style>"
        + block(
            "canvas-report", "rep", {"title": "Findings"},
            '<p id="inner" style="margin:0;padding:20px 0">Text inside the card.</p>',
        )
        + "<div style='height:1500px'></div>"
    )  # fmt: skip
    studio.make(page)
    studio.frame.wait_for_function(
        "document.querySelector('canvas-report').shadowRoot.querySelector('.k')"
    )
    pick(studio, "point")
    box = doc_box(studio, "#inner")
    click_at(studio, box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)
    what(studio)
    saved = save_box(studio, "inside a card")
    assert saved["target"]["selector"] == "#inner", saved["target"]
    assert saved["anchor"]["fx"] == pytest.approx(0.5, abs=0.2)


# ---- KIND-06: Report and Alert ---------------------------------------------------------


def test_kind_06_report_names_its_type_and_defaults_to_result(owner, make) -> None:  # noqa: ANN001
    page = (
        "".join(
            block("canvas-report", f"r-{kind}", {"type": kind, "title": kind})
            for kind in ("plan", "result", "finding")
        )
        + block("canvas-report", "r-none", {"title": "no type"})
        + block("canvas-report", "r-bad", {"type": "essay", "title": "x"})
    )
    make(page)
    wait_cards(owner, 5)
    found = cards(owner)
    assert [found[f"r-{k}"]["head"] for k in ("plan", "result", "finding")] == [
        "Report: plan", "Report: result", "Report: finding",
    ]  # fmt: skip
    assert found["r-none"]["head"] == "Report: result"
    assert all(found[f"r-{k}"]["words"] == "from the agent" for k in ("plan", "none"))
    assert "type" in found["r-bad"]["error"]


def test_kind_06_alert_reads_needs_action_while_a_do_in_it_is_open(dashboard) -> None:  # noqa: ANN001
    owner = dashboard.owner
    assert cards(owner)["a-heater"]["words"] == "needs action"
    assert cards(owner)["a-bed"]["words"] == "no action needed"
    set_state(owner, "w-plug", answered=True, at="14:05")
    owner.frame.wait_for_function(
        """() => document.querySelector('[data-canvas-id=a-heater]').shadowRoot
          .querySelector('.kt').textContent === 'no action needed'"""
    )
    # Later also ends "needs action"
    set_state(owner, "w-plug", answered=False, later=True)
    assert cards(owner)["a-heater"]["words"] == "no action needed"
    set_state(owner, "w-plug", later=False)
    owner.frame.wait_for_function(
        """() => document.querySelector('[data-canvas-id=a-heater]').shadowRoot
          .querySelector('.kt').textContent === 'needs action'"""
    )


# ---- KIND-05 (slice): the module drawn in a shell host page ---------------------------

HOST = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/kit/kit.css"></head><body><div class="page" id="shell"></div>
<div id="element"></div>
<script>window.agentCanvas = {report() {}, blockEvent() {}, blockAction() {}};</script>
<script type="module">
import { drawCard } from "/static/kinds/card.js";
import { kindSheet } from "/static/kinds/style.js";
document.adoptedStyleSheets = [kindSheet()];
const approve = document.createElement("button");
approve.textContent = "Approve";
document.getElementById("shell").append(drawCard({
  kind: "ask", label: "Needs you: Ask", words: "waits for you",
  title: "Approve this plan? <i>text</i>", open: true, answer: approve,
}));
await import("/static/blocks/loader.js");
document.getElementById("element").innerHTML = '<canvas-ask data-canvas-id="q"><script type="application/json">{"question": "Approve this plan?"}<\\/script></canvas-ask>';
window.ready = true;
</script></body></html>"""


def test_kind_05_slice_the_module_draws_the_same_card_in_a_shell_host_page(
    browser,  # noqa: ANN001
) -> None:
    static = CODEBASE_DIR / "src" / "agent_canvas" / "static"
    context = browser.new_context()
    page = context.new_page()

    def serve(route) -> None:  # noqa: ANN001
        path = route.request.url.split("kinds.test", 1)[1]
        if path == "/":
            route.fulfill(body=HOST, content_type="text/html")
        else:
            route.fulfill(
                path=str(static / path.removeprefix("/static/")),
                content_type="text/css" if path.endswith(".css") else "text/javascript",
            )

    context.route("http://kinds.test/**", serve)
    page.goto("http://kinds.test/")
    page.wait_for_function("window.ready === true")
    page.wait_for_function(
        "document.querySelector('canvas-ask').shadowRoot.querySelector('.k')"
    )
    probe = """(root) => { const k = root.querySelector('.k'); const s = getComputedStyle(k);
      const head = k.querySelector('.kh');
      return {head: head.querySelector('.kl').textContent,
        words: head.querySelector('.kt').textContent, radius: s.borderTopLeftRadius,
        strip: getComputedStyle(head).backgroundColor, name: s.animationName,
        text: k.querySelector('.q').textContent,
        buttons: k.querySelectorAll('button').length, bold: k.querySelectorAll('i').length}; }"""
    drawn = page.evaluate("(" + probe + ")(document.getElementById('shell'))")
    element = page.evaluate(
        "(" + probe + ")(document.querySelector('canvas-ask').shadowRoot)"
    )
    context.close()
    assert drawn["text"] == "Approve this plan? <i>text</i>" and drawn["bold"] == 0
    assert drawn["buttons"] == 1
    for key in ("head", "words", "radius", "strip", "name"):
        assert drawn[key] == element[key], key
    assert drawn["name"] == "kind-glow"
