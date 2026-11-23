# ruff: noqa: E501
"""canvas-document: a Markdown or PDF file in a scrolling window inside a page (CNT-01, A-100).

The shell's side of Open (its message list and the call to the relay) belongs to the
package that owns ``shell.js``; here the block's message and the relay are tested on their own.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from helpers import decode_png

from .pdf_fixtures import text_pdf
from .support import block
from .test_comment_kinds import pick, save_box, select_words, what
from .test_look_window import look

pytestmark = pytest.mark.browser

SHOTS = os.environ.get("AC_P311_SHOTS")
MARKDOWN = (
    "# Document title\n\n"
    + "\n\n".join(
        f"Paragraph {i} has several plain words and some more text."
        for i in range(1, 60)
    )
    + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode block\n```\n\n"
    "Inline math $x^2$ here.\n\n"
    "<script>window.__ran = 'script'</script>\n\n"
    '<img src="x" onerror="window.__ran = \'onerror\'">\n\n'
    '<a href="javascript:window.__ran = \'href\'" id="bad">bad link</a>\n'
)
PDF = text_pdf(pages=50)
FILES = {"notes.md": MARKDOWN, "r.pdf": PDF}


def document(canvas_id: str = "d", src: str = "notes.md", **config) -> str:  # noqa: ANN003
    return block("canvas-document", canvas_id, {"src": src, **config})


def wait_ready(owner, count: int = 1) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        """(n) => { const all = [...document.querySelectorAll('canvas-document')];
          return all.length === n && all.every((e) => e.renderIdle && e.shadowRoot
            && e.shadowRoot.querySelector('.doc-scroll.text .markdown, .doc-page canvas, .block-error')); }""",
        arg=count,
    )


def box(owner, canvas_id: str = "d") -> dict:  # noqa: ANN001
    return owner.frame.evaluate(
        """(id) => { const e = document.querySelector(`[data-canvas-id="${id}"]`);
          const s = e.shadowRoot.querySelector('.doc-scroll') || document.body;
          const r = s.getBoundingClientRect();
          return {height: r.height, scrollHeight: s.scrollHeight, clientHeight: s.clientHeight,
            page: document.documentElement.scrollHeight,
            canvases: e.shadowRoot.querySelectorAll('.doc-page canvas').length,
            pages: e.shadowRoot.querySelectorAll('.doc-page').length,
            frames: e.shadowRoot.querySelectorAll('iframe, object, embed, frame').length,
            error: e.shadowRoot.querySelector('.block-error') ? e.shadowRoot.querySelector('.block-error').textContent : null}; }""",
        canvas_id,
    )


def settle_text(owner, canvas_id: str = "d") -> None:  # noqa: ANN001
    """Wait until the first text-layer span stays where it is (the layout has settled)."""
    owner.frame.wait_for_function(
        """(id) => { const s = document.querySelector(`[data-canvas-id="${id}"]`)
            .shadowRoot.querySelector('.textLayer span');
          const r = s && JSON.stringify(s.getBoundingClientRect());
          const same = r && window.__last === r;
          window.__last = r;
          return same; }""",
        arg=canvas_id,
        polling="raf",
    )


def pdf_state(owner, canvas_id: str = "d") -> dict:  # noqa: ANN001
    return owner.frame.evaluate(
        """(id) => { const e = document.querySelector(`[data-canvas-id="${id}"]`);
          const drawn = [...e.shadowRoot.querySelectorAll('.doc-page')]
            .filter((p) => p.querySelector('canvas')).map((p) => Number(p.dataset.page));
          return {drawn, thread: e.session && e.session.thread,
            width: e.shadowRoot.querySelector('.doc-page').getBoundingClientRect().width,
            scroll: e.shadowRoot.querySelector('.doc-scroll').clientWidth,
            where: e.shadowRoot.querySelectorAll('.doc-head output')[1].textContent,
            percent: e.shadowRoot.querySelectorAll('.doc-head output')[0].textContent}; }""",
        canvas_id,
    )


def wait_drawn(owner, number: int, canvas_id: str = "d") -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        """([id, n]) => { const p = document.querySelector(`[data-canvas-id="${id}"]`)
          .shadowRoot.querySelector(`.doc-page[data-page="${n}"]`);
          return p && p.querySelector('canvas') && p.querySelector('.textLayer span'); }""",
        arg=[canvas_id, number],
    )


def press(owner, label: str, canvas_id: str = "d") -> None:  # noqa: ANN001
    owner.frame.locator(
        f'[data-canvas-id="{canvas_id}"] >> button[aria-label="{label}"]'
    ).click()


# ---- CNT-01: Markdown ---------------------------------------------------------------------


def test_cnt_01_markdown_shows_in_a_480_px_window_and_the_page_does_not_grow(
    owner,
    make,  # noqa: ANN001
) -> None:
    made = make("<p>before</p>" + document() + "<p>after</p>", files=FILES)
    wait_ready(owner)
    shown = box(owner)
    assert shown["height"] == 480 and shown["clientHeight"] <= 480
    assert shown["scrollHeight"] > 3 * 480  # long file: it scrolls inside the window
    assert shown["page"] < 480 + 400  # the page holds the window, not the file
    text = owner.frame.evaluate(
        "document.querySelector('canvas-document').shadowRoot.querySelector('.markdown').textContent"
    )
    assert "Document title" in text and "code block" in text
    rendered = owner.frame.evaluate(
        "(() => { const m = document.querySelector('canvas-document').shadowRoot.querySelector('.markdown');"
        " return [!!m.querySelector('table'), !!m.querySelector('pre'), !!m.querySelector('.katex')]; })()"
    )
    assert rendered == [True, True, True]
    assert made.sid


def test_cnt_01_height_is_set_by_the_config(owner, make) -> None:  # noqa: ANN001
    make(document(height=200), files=FILES)
    wait_ready(owner)
    assert box(owner)["height"] == 200


def test_cnt_01_a_script_in_the_markdown_does_not_run(owner, make) -> None:  # noqa: ANN001
    make(document(), files=FILES)
    wait_ready(owner)
    owner.page.wait_for_timeout(500)  # an image error handler would fire by now
    state = owner.frame.evaluate(
        """() => { const m = document.querySelector('canvas-document').shadowRoot.querySelector('.markdown');
          return {ran: window.__ran === undefined ? null : window.__ran,
            scripts: m.querySelectorAll('script').length,
            on: [...m.querySelectorAll('*')].filter((e) => [...e.attributes].some((a) => a.name.startsWith('on'))).length,
            href: m.querySelector('#bad').getAttribute('href')}; }"""
    )
    assert state == {"ran": None, "scripts": 0, "on": 0, "href": None}


@pytest.mark.parametrize("name", ["notes.md", "r.pdf"])
def test_cnt_01_no_frame_is_nested(owner, make, name: str) -> None:  # noqa: ANN001
    make(document(src=name), files=FILES)
    wait_ready(owner)
    assert box(owner)["frames"] == 0
    assert (
        owner.frame.evaluate(
            "document.querySelectorAll('iframe, object, embed').length"
        )
        == 0
    )
    assert owner.frame.evaluate("window.frames.length") == 0


# ---- CNT-01: PDF --------------------------------------------------------------------------


def test_cnt_01_the_50_page_pdf_renders_lazily_in_the_window(owner, make) -> None:  # noqa: ANN001
    make("<p>before</p>" + document(src="r.pdf") + "<p>after</p>", files=FILES)
    wait_ready(owner)
    wait_drawn(owner, 1)
    shown, state = box(owner), pdf_state(owner)
    assert shown["height"] == 480 and shown["pages"] == 50
    assert shown["page"] < 480 + 400  # fifty pages did not grow the page
    assert (
        1 <= shown["canvases"] <= 10
        and 1 in state["drawn"]
        and 50 not in state["drawn"]
    )
    assert state["thread"] == "worker"
    # fitted to the width of the window
    assert abs(state["width"] - (state["scroll"] - 16)) < 2
    assert state["where"] == "1 / 50"


def test_cnt_01_scrolling_draws_the_pages_in_view_and_keeps_at_most_ten(
    owner, make
) -> None:  # noqa: ANN001
    make(document(src="r.pdf"), files=FILES)
    wait_ready(owner)
    for target in (20, 40, 50):
        owner.frame.evaluate(
            """(n) => { const s = document.querySelector('canvas-document').shadowRoot;
              const p = s.querySelector(`.doc-page[data-page="${n}"]`);
              s.querySelector('.doc-scroll').scrollTop += p.getBoundingClientRect().top
                - s.querySelector('.doc-scroll').getBoundingClientRect().top; }""",
            target,
        )
        wait_drawn(owner, target)
        state = pdf_state(owner)
        assert target in state["drawn"] and 1 not in state["drawn"]
        assert len(state["drawn"]) <= 10
        assert state["where"] == f"{target} / 50"


def test_cnt_01_the_zoom_buttons_change_the_page_size(owner, make) -> None:  # noqa: ANN001
    make(document(src="r.pdf"), files=FILES)
    wait_ready(owner)
    wait_drawn(owner, 1)
    fitted = pdf_state(owner)
    press(owner, "Zoom in")
    bigger = pdf_state(owner)
    assert bigger["width"] > fitted["width"] and bigger["percent"] != fitted["percent"]
    press(owner, "Zoom out")
    press(owner, "Zoom out")
    smaller = pdf_state(owner)
    assert smaller["width"] < fitted["width"]
    press(owner, "Fit width")
    assert abs(pdf_state(owner)["width"] - fitted["width"]) < 1
    wait_drawn(owner, 1)  # the page is drawn again at the new zoom


def test_cnt_01_a_pdf_script_does_not_run(owner, make) -> None:  # noqa: ANN001
    from .pdf_fixtures import script_pdf

    seen: list[str] = []
    owner.page.on("dialog", lambda d: (seen.append(d.message), d.dismiss()))
    make(document(src="s.pdf"), files={"s.pdf": script_pdf()})
    wait_ready(owner)
    owner.page.wait_for_timeout(400)
    assert seen == [] and not box(owner)["error"]
    assert owner.frame.evaluate(
        "import(new URL('/static/pdf-core.js', location.href).href).then((m) => m.OPTIONS)"
    ) == {"useSystemFonts": False, "isEvalSupported": False, "enableScripting": False}


def test_cnt_01_a_missing_file_shows_the_block_error(owner, make) -> None:  # noqa: ANN001
    make(document(src="gone.md"), files=FILES)
    wait_ready(owner)
    assert box(owner)["error"]


@pytest.mark.parametrize(
    "src", ["../x.md", "/etc/x.md", "http://example.com/x.md", "notes.html", "a\\b.md"]
)
def test_cnt_01_a_src_that_is_not_a_session_file_of_a_viewer_type_is_refused(
    owner,
    make,
    src: str,  # noqa: ANN001
) -> None:
    make(document(src=src), files=FILES)
    wait_ready(owner)
    assert box(owner)["error"]
    assert owner.frame.evaluate("window.__ran === undefined")


# ---- CNT-01: Open ----------------------------------------------------------------------


@pytest.mark.parametrize(("canvas_id", "src"), [("d", "notes.md"), ("p", "r.pdf")])
def test_cnt_01_open_sends_only_the_file_name(
    owner, make, canvas_id: str, src: str
) -> None:  # noqa: ANN001
    make(document(canvas_id, src=src), files=FILES)
    wait_ready(owner)
    owner.page.evaluate(
        "window.__opens = []; const seen = privateMessage; privateMessage = (m) => {"
        " if (m && m.type === 'open-file') window.__opens.push(m); return seen(m); };"
    )
    owner.frame.locator(
        f'[data-canvas-id="{canvas_id}"] >> button:text-is("Open")'
    ).click()
    assert owner.page.evaluate("window.__opens") == [{"type": "open-file", "path": src}]


def test_cnt_01_a_file_in_a_subfolder_has_no_open_button(owner, make) -> None:  # noqa: ANN001
    made = make("<p>first</p>")
    (made.folder / "sub").mkdir()
    (made.folder / "sub" / "inner.md").write_text("# inner\n")
    made.rewrite(document(src="sub/inner.md"))
    owner.frame.wait_for_function(
        "(document.querySelector('canvas-document') || {}).shadowRoot"
        " && document.querySelector('canvas-document').shadowRoot.querySelector('.markdown')"
    )
    assert owner.frame.locator('canvas-document >> button:text-is("Open")').count() == 0
    assert (
        owner.frame.locator("canvas-document >> .doc-name").inner_text()
        == "sub/inner.md"
    )


RELAY = """async (paths) => {
  const calls = [];
  const original = window.fetch;
  window.fetch = (url, init) => {
    calls.push({url: String(url), body: init && init.body, method: init && init.method});
    return Promise.resolve(new Response('{}', {status: 200}));
  };
  const relay = window.createAnswerRelay({
    activeTab: () => ({id: 'sid', page: 'page.html'}), postToFrame() {}, requestItems() {},
    isOldVersion: () => false, notify() {}, submit() {}, showCopied() {},
  });
  relay.onFrameReady(true);  // a document that opened the relay (ANS-02)
  for (const path of paths) await relay.onFrameOpen({type: 'open-file', path});
  window.fetch = original;
  return calls;
}"""


def test_cnt_01_the_relay_forwards_a_plain_viewer_file_name_only(owner, make) -> None:  # noqa: ANN001
    make("<p>x</p>")
    forged = [
        "../x.md", "a/b.md", "/etc/passwd", "x.html", "x.py", "x.md/", "..\\x.md",
        "", "x" * 300 + ".md", 5, None, {"a": 1}, ["x.md"], "x\u0000.md",
    ]  # fmt: skip
    assert owner.page.evaluate(RELAY, forged) == []
    sent = owner.page.evaluate(RELAY, ["notes.md", "r.PDF", "p.png"])
    assert [c["url"] for c in sent] == ["/api/sessions/sid/open-file"] * 3
    assert [c["method"] for c in sent] == ["POST"] * 3
    assert [c["body"] for c in sent] == [
        '{"name":"notes.md"}', '{"name":"r.PDF"}', '{"name":"p.png"}',
    ]  # fmt: skip


# ---- COM-17: text inside the block ---------------------------------------------------------


def test_com_17_text_in_a_document_markdown_gives_a_text_comment_on_that_block(
    studio,
) -> None:  # noqa: ANN001
    studio.make(document(), files=FILES)
    wait_ready(studio.owner)
    pick(studio, "text")
    select_words(studio, "several", "words")
    assert "Text" in what(studio)
    saved = save_box(studio, "in document")
    assert saved["target"]["canvas_id"] == "d"
    assert saved["anchor"]["quote"] == "several plain words"


def test_com_17_text_in_a_document_pdf_gives_a_text_comment_on_that_block(
    studio,
) -> None:  # noqa: ANN001
    studio.make(document(src="r.pdf"), files=FILES)
    wait_ready(studio.owner)
    wait_drawn(studio.owner, 1)
    settle_text(studio.owner)
    pick(studio, "text")
    select_words(studio, "quick", "fox")
    assert "Text" in what(studio)
    saved = save_box(studio, "in pdf")
    assert saved["target"]["canvas_id"] == "d"
    assert "quick" in saved["anchor"]["quote"] and "fox" in saved["anchor"]["quote"]


# ---- looks: light and dark, outside and inside a card ----------------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_cnt_01_looks_the_same_inside_and_outside_a_card_and_passes_contrast(
    owner,
    make,
    scheme: str,  # noqa: ANN001
) -> None:
    inside = block(
        "canvas-report",
        "r",
        {"type": "result", "title": "Results"},
        document("m2") + document("p2", src="r.pdf"),
    )
    made = make(document("m") + document("p", src="r.pdf") + inside, files=FILES)
    wait_ready(owner, 4)
    wait_drawn(owner, 1, "p")
    wait_drawn(owner, 1, "p2")
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.wait_for_timeout(300)
    result = look(owner, made.sid, width=900, height=2400, scheme=scheme)
    assert [f for f in result["audit"]["findings"] if f["rule"] == "contrast"] == []
    sizes = owner.frame.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('canvas-document')].map((e) => {
          const s = e.shadowRoot;
          const head = s.querySelector('.doc-head').getBoundingClientRect();
          return [e.dataset.canvasId, [Math.round(head.height), Math.round(s.querySelector('.doc-scroll').getBoundingClientRect().height),
            getComputedStyle(s.querySelector('.doc-scroll')).backgroundColor,
            getComputedStyle(s.querySelector('.doc-name')).fontSize]];
        }))"""
    )
    assert sizes["m"] == sizes["m2"] and sizes["p"] == sizes["p2"]
    if SHOTS:
        shutil.copy(result["png"], Path(SHOTS) / f"look-{scheme}.png")


def test_cnt_01_the_send_screenshot_shows_the_pdf_pages_inside_and_outside_a_card(
    studio,
) -> None:  # noqa: ANN001
    studio.page.set_viewport_size({"width": 1000, "height": 1200})
    card = block(
        "canvas-report",
        "r",
        {"type": "result", "title": "Results"},
        document("p2", src="r.pdf", height=200),
    )
    sid = studio.make(document("p", src="r.pdf", height=200) + card, files=FILES)
    wait_ready(studio.owner, 2)
    wait_drawn(studio.owner, 1, "p")
    wait_drawn(studio.owner, 1, "p2")
    studio.frame.evaluate("window.scrollTo(0, 0)")
    areas = studio.frame.evaluate(
        """() => ['p', 'p2'].map((id) => {
          const r = document.querySelector(`[data-canvas-id="${id}"]`).shadowRoot
            .querySelector('.doc-scroll').getBoundingClientRect();
          return [r.left, r.top, r.right, r.bottom].map(Math.round); })"""
    )
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    assert event["screenshot_error"] is None, event
    _, _, rows = decode_png(studio.screenshot(event))
    for left, top, right, bottom in areas:
        dark = sum(
            1
            for row in rows[top + 4 : bottom - 4]
            for r, g, b, *_ in row[left + 4 : right - 20]
            if r + g + b < 3 * 90
        )
        assert dark > 300, (left, top, dark)  # the text of page 1, not a blank page


def test_cnt_01_the_controls_work_inside_a_card(owner, make) -> None:  # noqa: ANN001
    make(
        block(
            "canvas-report",
            "r",
            {"type": "result", "title": "Results"},
            document("p2", src="r.pdf"),
        ),
        files=FILES,
    )
    wait_ready(owner)
    wait_drawn(owner, 1, "p2")
    before = pdf_state(owner, "p2")
    press(owner, "Zoom in", "p2")
    assert pdf_state(owner, "p2")["width"] > before["width"]
