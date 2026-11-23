"""Fixes of the M31 review: Markdown containment, trusted Copy and Open, the PDF window, the form look, the source card (CNT-01, CNT-03, CNT-04, DO-02, ASK-06)."""

# ruff: noqa: E501
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from .pdf_fixtures import text_pdf
from .support import block
from .test_ask_point_fields import FORM, wait_ask
from .test_do_card import DO

pytestmark = pytest.mark.browser

LOOK_DIR = os.environ.get("M31_FIX_LOOK_DIR")
HIDDEN_DO = {**DO, "steps": [{"text": "Run it", "run": "echo HIDDEN-STEP"}]}


def page_of(body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'></head><body>{body}</body></html>"


def requests_to(studio, part: str) -> list[str]:  # noqa: ANN001
    seen: list[str] = []
    studio.page.on("request", lambda r: seen.append(r.url) if part in r.url else None)
    return seen


def clipboard(studio) -> str:  # noqa: ANN001
    return studio.page.evaluate("navigator.clipboard.readText()")


def active_page(studio) -> str:  # noqa: ANN001
    return json.loads((studio.folder / "session.json").read_text())["active_page"]


# ---- F1: Markdown stays in its window -----------------------------------------------

OVERLAY = (
    "# Title\n\n"
    '<div style="position:fixed;inset:0;background:rgba(255,0,0,.15);z-index:99">cover</div>\n\n'
    '<div style="position:absolute;top:-2000px;left:0;width:900px;height:2000px;background:rgba(255,0,0,.15)">up</div>\n'
)


def test_cnt_01_f1_markdown_cannot_paint_outside_its_window_or_catch_clicks_there(
    studio,
) -> None:  # noqa: ANN001
    studio.make(
        page_of(
            block("canvas-document", "d", {"src": "notes.md", "height": 200})
            + '<p id="below" style="margin:20px 0 0;height:40px">below the window</p>'
            + "<script>document.getElementById('below').onclick = () => { window.__hit = true; };</script>"
        ),
        files={"notes.md": OVERLAY},
    )
    studio.frame.wait_for_function(
        "document.querySelector('canvas-document').shadowRoot.querySelector('.doc-scroll .markdown')"
    )
    inside = studio.frame.evaluate(
        """() => {
          const host = document.querySelector('canvas-document');
          const scroll = host.shadowRoot.querySelector('.doc-scroll').getBoundingClientRect();
          const covers = [...host.shadowRoot.querySelectorAll('.markdown div')].map((d) => d.getBoundingClientRect());
          const below = document.getElementById('below').getBoundingClientRect();
          const top = document.elementFromPoint(below.left + 20, below.top + 20);
          return {
            covers: covers.slice(0, 1).map((r) => r.top >= scroll.top - 1 && r.bottom <= scroll.bottom + 1 && r.left >= scroll.left - 1 && r.right <= scroll.right + 1),
            n: covers.length, topId: top && top.id,
          };
        }"""
    )
    assert inside["n"] == 2  # positive control: the overlay elements are there
    assert inside["topId"] == "below", inside
    assert inside["covers"] == [True], inside
    studio.frame.locator("#below").click()
    assert studio.frame.evaluate("window.__hit === true")


# ---- F2, F3: Copy and Open go over the helper's private port ------------------------

SCRIPTED = (
    '<div style="display:none">'
    + block("canvas-do", "hid", HIDDEN_DO)
    + "</div><p id='p'>plain paragraph</p><script>"
    "setInterval(() => { window.focus(); document.body.focus();"
    " parent.postMessage({type: 'copy', id: 'hid', step: 1}, '*');"
    " parent.postMessage({type: 'open-file', path: 'secret-notes.md'}, '*'); }, 600);"
    "</script>"
)


def test_do_02_f2_f3_a_page_script_cannot_copy_or_open_by_postmessage_or_focus(
    studio,
) -> None:  # noqa: ANN001
    studio.owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    copies = requests_to(studio, "/answers/copy")
    opens = requests_to(studio, "/open-file")
    studio.make(page_of(SCRIPTED), files={"secret-notes.md": "# secret\n"})
    studio.page.wait_for_timeout(2500)  # right after the owner's click on the tab
    studio.frame.locator("#p").click()  # and with a real click in the page
    studio.page.wait_for_timeout(2500)
    refused = studio.page.evaluate("window.__guard.dropped.private")
    assert refused >= 4  # positive control: the messages arrived and were refused
    assert copies == [] and opens == []
    assert active_page(studio) == "page.html"
    assert clipboard(studio) != "echo HIDDEN-STEP"


IMITATING = (
    "<script>"
    "const stolen = [];"
    "const nativeSend = MessagePort.prototype.postMessage;"
    "MessagePort.prototype.postMessage = function (...a) { stolen.push(this); return nativeSend.apply(this, a); };"
    "window.__stolen = stolen;"
    "addEventListener('message', (e) => { window.__heard = (window.__heard || 0) + e.ports.length; }, true);"
    "const c = new MessageChannel();"
    "window.__mine = c.port1; c.port1.onmessage = (e) => { window.__got = e.data; };"
    "window.postMessage({type: 'relay-open', token: 'x'}, '*', [c.port2]);"
    "</script>"
)


def test_do_02_f2_a_script_that_imitates_the_shell_gets_no_working_port(
    studio,
) -> None:  # noqa: ANN001
    studio.owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    copies = requests_to(studio, "/answers/copy")
    studio.make(page_of(block("canvas-do", "w1", DO) + IMITATING))
    wait_card(studio)
    # The shell's own second handshake (a new port) must not replace the first port either.
    studio.page.evaluate(
        """() => { const c = new MessageChannel(); window.__second = [];
          c.port1.onmessage = (e) => window.__second.push(e.data);
          document.getElementById('frame').contentWindow.postMessage(
            {type: 'relay-open', token: active.token}, '*', [c.port2]); }"""
    )
    studio.page.wait_for_timeout(300)
    studio.frame.locator("canvas-do .cmd button").click()
    studio.page.wait_for_selector("#copied.visible")
    assert clipboard(studio) == "uv run check\n--port 1"
    assert len(copies) == 1
    assert studio.page.evaluate("window.__second.length") == 0
    # The page's own port got nothing and saw no port of the shell's, even with
    # MessagePort.prototype.postMessage replaced before the click.
    assert studio.frame.evaluate(
        "window.__got === undefined && window.__stolen.length === 0"
    )
    assert (
        studio.frame.evaluate("window.__heard || 0") == 0
    )  # no handshake reached its listener


def do_page(style: str = "") -> str:
    return page_of(f'<div style="{style}">' + block("canvas-do", "w1", DO) + "</div>")


def wait_card(studio) -> None:  # noqa: ANN001
    studio.frame.wait_for_function(
        "(() => { const e = document.querySelector('canvas-do');"
        " return e && e.renderIdle && e.shadowRoot.querySelector('.k, .block-error'); })()"
    )


CLICK_COPY = "document.querySelector('canvas-do').shadowRoot.querySelector('.cmd button').click()"


def test_do_02_f2_a_script_click_on_the_copy_button_copies_nothing(studio) -> None:  # noqa: ANN001
    studio.owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    copies = requests_to(studio, "/answers/copy")
    studio.make(do_page())
    wait_card(studio)
    studio.frame.evaluate(
        CLICK_COPY
    )  # an untrusted click (the evaluate itself is activation)
    studio.page.wait_for_timeout(800)
    assert copies == []
    # Positive control: a real click on the same button copies.
    studio.frame.locator("canvas-do .cmd button").click()
    studio.page.wait_for_selector("#copied.visible")
    assert clipboard(studio) == "uv run check\n--port 1"
    assert len(copies) == 1


def test_do_02_f2_a_real_click_on_an_invisible_copy_button_copies_nothing(
    studio,
) -> None:  # noqa: ANN001
    studio.owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    copies = requests_to(studio, "/answers/copy")
    studio.make(do_page("opacity:0"))
    wait_card(studio)
    studio.frame.locator("canvas-do .cmd button").click(force=True)
    studio.page.wait_for_timeout(800)
    assert copies == []


def test_do_02_f2_a_copy_button_covered_by_another_element_copies_nothing(
    studio,
) -> None:  # noqa: ANN001
    studio.owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    copies = requests_to(studio, "/answers/copy")
    studio.make(do_page())
    wait_card(studio)
    # A click listener of the page's own that forwards a real click is the attack: the
    # button's own click event is trusted, but another element lies on top of it.
    studio.frame.evaluate(
        """() => { const b = document.querySelector('canvas-do').shadowRoot.querySelector('.cmd button');
          const r = b.getBoundingClientRect();
          const cover = document.createElement('div');
          cover.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;z-index:9`;
          cover.id = 'cover';
          cover.addEventListener('click', () => b.dispatchEvent(new MouseEvent('click', {bubbles: true, composed: true})));
          document.body.append(cover); }"""
    )
    studio.frame.locator("#cover").click()
    studio.page.wait_for_timeout(800)
    assert copies == []


def test_do_02_f2_the_notice_shows_the_first_80_characters_of_what_was_copied(
    studio,
) -> None:  # noqa: ANN001
    studio.owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    long_run = "echo " + "x" * 120
    config = {**DO, "steps": [{"text": "Run it", "run": long_run}]}
    studio.make(page_of(block("canvas-do", "w1", config)))
    wait_card(studio)
    studio.frame.locator("canvas-do .cmd button").click()
    studio.page.wait_for_selector("#copied.visible")
    assert studio.page.inner_text("#copied") == "Copied: " + long_run[:80] + "…"
    assert clipboard(studio) == long_run


def test_cnt_03_f3_a_script_click_on_open_opens_nothing_and_a_real_click_does(
    studio,
) -> None:  # noqa: ANN001
    opens = requests_to(studio, "/open-file")
    studio.make(
        page_of(block("canvas-document", "d", {"src": "notes.md", "height": 200})),
        files={"notes.md": "# Note\n"},
    )
    button = 'canvas-document >> button:text-is("Open")'
    studio.frame.locator(button).wait_for()
    studio.frame.evaluate(
        "document.querySelector('canvas-document').shadowRoot.querySelector('.doc-head button').click()"
    )
    studio.page.wait_for_timeout(800)
    assert opens == [] and active_page(studio) == "page.html"
    studio.frame.locator(button).click()
    studio.page.wait_for_function(
        "document.getElementById('frame').src.includes('notes.md')"
    )
    assert active_page(studio) == "notes.md" and len(opens) == 1


# ---- F4: the PDF window stands from the first frame ---------------------------------


def test_cnt_01_f4_the_pdf_window_reserves_its_height_before_the_pages_are_loaded(
    studio,
) -> None:  # noqa: ANN001
    sampler = (
        "<script>window.__tops = new Set(); (function loop() {"
        " const d = document.querySelector('canvas-document');"
        " if (d && d.renderCount > 0) window.__tops.add(Math.round(document.getElementById('below').getBoundingClientRect().top));"
        " if (performance.now() < 4000) requestAnimationFrame(loop); })();</script>"
    )
    studio.make(
        page_of(
            block("canvas-document", "d", {"src": "r.pdf"})
            + "<p id='below'>below</p>"
            + sampler
        ),
        files={"r.pdf": text_pdf(pages=50)},
    )
    studio.frame.wait_for_function("performance.now() > 4100", timeout=15000)
    tops = studio.frame.evaluate("[...window.__tops]")
    assert len(tops) >= 1 and len(set(tops)) == 1 and tops[0] > 400, tops


# ---- F5: the parameter form follows the control look --------------------------------

CONTROLS = """() => {
  const root = document.querySelector('canvas-ask').shadowRoot;
  const style = (e) => { const s = getComputedStyle(e);
    return {font: s.fontFamily, size: s.fontSize, bg: s.backgroundColor, color: s.color,
      border: s.borderTopColor, radius: s.borderTopLeftRadius, height: e.getBoundingClientRect().height,
      accent: s.accentColor}; };
  const gap = (a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().bottom;
  const submit = root.querySelector('button.submit');
  const note = [...root.querySelectorAll('button.link')].find((b) => /note/i.test(b.textContent));
  return {
    select: style(root.querySelector('select')), text: style(root.querySelector('input[type=text]')),
    box: style(root.querySelector('input[type=checkbox]')),
    lastField: gap(root.querySelector('.field[data-field=name]'), submit),
    noteGap: note ? gap(submit, note) : null,
  };
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_ask_06_f5_the_select_and_tick_box_follow_the_control_look(
    studio, scheme: str
) -> None:  # noqa: ANN001
    studio.owner.page.emulate_media(color_scheme=scheme)
    studio.make(page_of(block("canvas-ask", "f", FORM)))
    wait_ask(studio.owner)
    got = studio.frame.evaluate(CONTROLS)
    select, text = got["select"], got["text"]
    for key in ("font", "size", "bg", "color", "border", "radius"):
        assert select[key] == text[key], (key, select, text)
    assert abs(select["height"] - text["height"]) <= 4, got
    assert got["box"]["accent"] != "auto", got["box"]
    assert got["lastField"] >= 12, got
    assert got["noteGap"] is not None and got["noteGap"] >= 6, got
    if LOOK_DIR:
        Path(LOOK_DIR).mkdir(parents=True, exist_ok=True)
        studio.frame.locator("canvas-ask").screenshot(
            path=Path(LOOK_DIR) / f"fields-{scheme}.png"
        )


# ---- F8: the source card's text is at least 12 px ----------------------------------


def test_cnt_04_f8_the_source_card_has_no_text_under_12_px(studio) -> None:  # noqa: ANN001
    config = {
        "claim": "Yield is 240 MPa",
        "source": "Handbook p. 4",
        "status": "verified",
        "quote": "Rp0.2 = 240",
    }
    studio.make(page_of(block("canvas-source", "s", config)))
    studio.frame.wait_for_function(
        "document.querySelector('canvas-source').shadowRoot.querySelector('.src-line button')"
    )
    sizes = studio.frame.evaluate(
        """() => { const r = document.querySelector('canvas-source').shadowRoot;
          return [...r.querySelectorAll('.src-mark, .src-line button, .src-doubt button, .src-text, .src-status, .src-quote')]
            .map((e) => [e.className || e.tagName, parseFloat(getComputedStyle(e).fontSize)]); }"""
    )
    assert len(sizes) >= 5
    assert [s for s in sizes if s[1] < 12] == [], sizes
    if LOOK_DIR:
        Path(LOOK_DIR).mkdir(parents=True, exist_ok=True)
        studio.frame.locator("canvas-source").screenshot(
            path=Path(LOOK_DIR) / "source-card.png"
        )
