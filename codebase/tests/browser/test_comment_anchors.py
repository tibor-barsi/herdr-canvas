"""Markers, finding anchors again and report tokens on HTML pages (M22 P22.3).

COM-05, ANC-06, ANC-07 and COM-18 are owned here; SEC-09's list of the comment
layer's messages closes here (its selection and picture vectors are in the earlier
comment test files).
"""

# ruff: noqa: E501  (the scripts run in the frame are one-line strings)
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from agent_canvas.hub import comments
from helpers import PACKAGE_DIR, decode_png

from .support import block, call
from .test_com_10_multi_page import go_to, open_other_page
from .test_comment_kinds import (
    HOST,
    click_at,
    doc_box,
    mouse_path,
    save_box,
    select_words,
    what,
)
from .test_comment_kinds import (
    pick as pick_kind,
)
from .test_comment_layer import all_rects, comment_file, drag, wait_saved
from .test_comment_panel import steady_layout

pytestmark = pytest.mark.browser


def pick(studio, kind: str) -> None:  # noqa: ANN001
    """Pick a kind and wait for the layer, which the first message loads."""
    pick_kind(studio, kind)
    studio.frame.wait_for_function("Boolean(window.agentCanvas.commentLayer)")


ANCHOR_JS = PACKAGE_DIR / "static" / "anchor.js"

# ---- ANC-07: findQuote as a pure function in a test host page ------------------------

TEXT = (
    "Intro paragraph about beams. The beam deflects under load. "
    "Closing remarks follow here."
)
QUOTE = "The beam deflects under load."


def anchor_of(text: str, quote: str, nth: int = 0) -> dict:
    """The anchor ANC-01 would hold for the ``nth`` occurrence of ``quote``."""
    start = -1
    for _ in range(nth + 1):
        start = text.index(quote, start + 1)
    end = start + len(quote)
    letters = lambda part: "".join(c for c in part if c.isalnum())  # noqa: E731
    return {
        "quote": quote,
        "before": letters(text[:start])[-120:],
        "after": letters(text[end:])[:120],
        "start": start,
        "end": end,
    }


@pytest.fixture
def host(page):  # noqa: ANN001, ANN201
    """A plain page with ``anchor.js`` loaded: nothing of the hub around it."""
    page.set_content("<!doctype html><html><body></body></html>")
    page.add_script_tag(path=str(ANCHOR_JS))
    return page


def find(host, text: str, anchor: dict):  # noqa: ANN001, ANN201
    return host.evaluate(
        "([t, a]) => window.agentCanvas.anchor.findQuote(t, a)", [text, anchor]
    )


def test_anc_07_unchanged_gives_the_same_offsets(host) -> None:  # noqa: ANN001
    anchor = anchor_of(TEXT, QUOTE)
    assert find(host, TEXT, anchor) == {"start": anchor["start"], "end": anchor["end"]}


def test_anc_07_a_moved_paragraph_is_found_at_its_new_place(host) -> None:  # noqa: ANN001
    anchor = anchor_of(TEXT, QUOTE)
    moved = (
        "Closing remarks follow here. Extra section words. Intro paragraph about beams. "
        + QUOTE
    )
    found = find(host, moved, anchor)
    assert found["start"] == moved.index(QUOTE) != anchor["start"]
    assert moved[found["start"] : found["end"]] == QUOTE


def test_anc_07_a_changed_neighbour_does_not_hide_the_quote(host) -> None:  # noqa: ANN001
    anchor = anchor_of(TEXT, QUOTE)
    changed = TEXT.replace("Intro paragraph about beams.", "A different opening.")
    found = find(host, changed, anchor)
    assert changed[found["start"] : found["end"]] == QUOTE


def test_anc_07_of_a_duplicate_quote_the_one_with_the_matching_context_wins(
    host,  # noqa: ANN001
) -> None:
    text = (
        "Alpha beta. See table 3. Result A. Gamma delta. See table 3. Result B. Omega."
    )
    anchor = anchor_of(text, "See table 3.", nth=1)
    # The two blocks swapped places: the occurrence nearest the old start is the
    # wrong one, the one whose text after it agrees is the right one.
    swapped = (
        "See table 3. Result B. Omega. Padding words here and there. "
        "See table 3. Result A. Closing."
    )
    found = find(host, swapped, anchor)
    assert found["start"] == 0
    assert abs(swapped.rindex("See table 3.") - anchor["start"]) < anchor["start"]


def test_anc_07_of_equal_contexts_the_nearest_start_wins_and_a_dead_heat_is_lost(
    host,  # noqa: ANN001
) -> None:
    text = "one two. same words. three four. same words. five six."
    first, second = (anchor_of(text, "same words.", n) for n in (0, 1))
    blind = {"quote": "same words.", "before": "", "after": ""}
    assert (
        find(host, text, blind | {"start": first["start"]})["start"] == first["start"]
    )
    assert (
        find(host, text, blind | {"start": second["start"] + 1})["start"]
        == (second["start"])
    )
    middle = (first["start"] + second["start"]) / 2
    assert find(host, text, blind | {"start": middle}) is None  # unclear: not guessed


def test_anc_07_a_removed_quote_gives_null(host) -> None:  # noqa: ANN001
    anchor = anchor_of(TEXT, QUOTE)
    assert find(host, TEXT.replace(QUOTE, "Something else."), anchor) is None
    assert find(host, TEXT, {**anchor, "quote": ""}) is None


def test_anc_07_changed_white_space_only_still_finds_the_quote(host) -> None:  # noqa: ANN001
    anchor = anchor_of(TEXT, QUOTE)
    spaced = TEXT.replace("The beam deflects", "The  beam\n  deflects").replace(
        "Closing", "\n\nClosing"
    )
    found = find(host, spaced, anchor)
    taken = re.sub(r"\s+", " ", spaced[found["start"] : found["end"]])
    assert taken == QUOTE


@pytest.mark.timing
def test_anc_07_the_index_is_built_once_per_text_for_200_anchors_within_100_ms(
    host,  # noqa: ANN001
) -> None:
    lines = [
        f"Line {i} holds words number {i * 7} about topic {i % 50}."
        for i in range(2000)
    ]
    text = " ".join(lines)
    anchors = [anchor_of(text, lines[i * 9][5:45]) for i in range(200)]
    result = host.evaluate(
        """([text, anchors]) => {
          const {findQuote} = window.agentCanvas.anchor;
          const before = findQuote.builds;
          const t0 = performance.now();
          const found = anchors.map((a) => findQuote(text, a));
          return {ms: performance.now() - t0, builds: findQuote.builds - before,
                  hits: found.filter((f) => f).length};
        }""",
        [text, anchors],
    )
    assert result["hits"] == 200
    assert result["builds"] == 1
    assert result["ms"] < 100, result


# ---- helpers for the layer in the live frame -----------------------------------------

INTRO = "Intro paragraph about beams and their loads."
MOVED = "The moved paragraph says something unique about damping."
STYLE = "<style>body{margin:0;font:16px/24px sans-serif} p{margin:0 0 8px;width:640px}</style>"
ANCHOR_PAGE = (
    STYLE
    + f"<p id='intro'>{INTRO}</p>"
    + f"<section id='a'><p id='mv'>{MOVED}</p></section>"
    + "<section id='b'><p>Another section with other words entirely.</p></section>"
    + "<div id='fig' style='width:200px;height:100px;background:#ddd'></div>"
    + "<div style='height:1200px'></div>"
)


def morph_to(studio, html: str) -> None:  # noqa: ANN001
    """Write a new version of the page and wait until the helper has morphed it."""
    studio.frame.evaluate(
        "if (!window.__hooked) { window.__hooked = true; window.__morphs = 0;"
        " document.addEventListener('agentcanvas:updated', () => window.__morphs++); }"
    )
    seen = studio.frame.evaluate("window.__morphs")
    (studio.folder / "page.html").write_text(html)
    studio.frame.wait_for_function(f"window.__morphs > {seen}")


def stored(studio) -> dict:  # noqa: ANN001
    """The stored ``lost`` flag per comment number."""
    return {c["n"]: c["lost"] for c in comment_file(studio)["comments"]}


def wait_stored(studio, expected: dict, timeout: float = 8) -> None:  # noqa: ANN001
    end = time.monotonic() + timeout
    while time.monotonic() < end and stored(studio) != expected:
        studio.page.wait_for_timeout(50)
    assert stored(studio) == expected


def marks(studio) -> dict:  # noqa: ANN001
    """The frame's markers by number: their class and the top of their first shape."""
    return studio.frame.evaluate(
        """() => {
          const root = document.querySelector('[data-ac-comment-host]').shadowRoot;
          const out = {};
          for (const m of root.querySelectorAll('[data-n]')) {
            const shape = m.matches('.box') ? m : m.querySelector('.hl, .pin, svg.outline polygon');
            const r = shape.getBoundingClientRect();
            out[m.dataset.n] = {cls: m.className, y: r.top + scrollY, x: r.left + scrollX};
          }
          return out;
        }"""
    )


def marker_count(studio) -> int:  # noqa: ANN001
    return studio.frame.evaluate(
        "(() => { const h = document.querySelector('[data-ac-comment-host]');"
        " return h ? h.shadowRoot.querySelectorAll('[data-n]').length : 0; })()"
    )


def wait_marks(studio, numbers: set) -> dict:  # noqa: ANN001
    end = time.monotonic() + 8
    found = {}
    while time.monotonic() < end:
        found = marks(studio) if marker_count(studio) else {}
        if {int(n) for n in found} == numbers:
            return found
        studio.page.wait_for_timeout(50)
    raise AssertionError(f"markers {sorted(found)} instead of {sorted(numbers)}")


def page_y(studio, selector: str) -> float:  # noqa: ANN001
    return studio.frame.evaluate(
        "(s) => document.querySelector(s).getBoundingClientRect().top + scrollY",
        selector,
    )


def drag_over(studio, selector: str) -> None:  # noqa: ANN001
    """Select the text of the element with a drag along its first line."""
    box = studio.frame.evaluate(
        """(s) => { const e = document.querySelector(s); e.scrollIntoView({block: 'nearest'});
          const r = document.createRange(); r.selectNodeContents(e);
          const b = r.getBoundingClientRect(); return {x: b.x, y: b.y, w: b.width, h: b.height}; }""",
        selector,
    )
    drag(
        studio,
        (box["x"] + 1, box["y"] + box["h"] / 2),
        (box["x"] + box["w"] - 1, box["y"] + box["h"] / 2),
    )


def comment_on_text(studio, selector: str) -> None:  # noqa: ANN001
    pick(studio, "text")
    drag_over(studio, selector)
    what(studio)
    save_box(studio, "note on " + selector)


def comment_on_rect(studio, selector: str) -> None:  # noqa: ANN001
    pick(studio, "rect")
    box = doc_box(studio, selector)
    drag(
        studio,
        (box["x"] + 5, box["y"] + 5),
        (box["x"] + box["w"] - 5, box["y"] + box["h"] - 5),
    )
    what(studio)
    save_box(studio, "note on " + selector)


# ---- ANC-06: finding anchors again after a change ------------------------------------


def test_anc_06_a_paragraph_moved_below_another_section_its_text_comment_follows(
    studio,
) -> None:
    studio.make(ANCHOR_PAGE)
    comment_on_text(studio, "#mv")
    before = wait_marks(studio, {1})["1"]["y"]
    assert abs(before - page_y(studio, "#mv")) < 30
    moved = (
        STYLE
        + f"<p id='intro'>{INTRO}</p>"
        + "<section id='b'><p>Another section with other words entirely.</p></section>"
        + "<div style='height:300px'></div>"
        + f"<section id='a'><p id='mv'>{MOVED}</p></section>"
        + "<div style='height:1200px'></div>"
    )
    morph_to(studio, moved)
    after = wait_marks(studio, {1})["1"]["y"]
    assert after > before + 250
    assert abs(after - page_y(studio, "#mv")) < 30
    studio.page.wait_for_timeout(600)
    assert stored(studio) == {1: False}  # found again: nothing to report


def block_words(studio, first: str, last: str) -> None:  # noqa: ANN001
    """Drag a selection from ``first`` to ``last`` inside the page's one markdown block."""
    box = studio.frame.evaluate(
        """([first, last]) => {
          const root = document.querySelector('canvas-markdown').shadowRoot;
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          let node = walker.nextNode();
          while (!node.data.includes(first)) node = walker.nextNode();
          const at = (word, end) => {
            const i = node.data.indexOf(word);
            const r = document.createRange();
            r.setStart(node, i); r.setEnd(node, i + word.length);
            const b = r.getBoundingClientRect();
            return [end ? b.right - 1 : b.left + 1, b.top + b.height / 2];
          };
          node.parentElement.scrollIntoView({block: 'nearest'});
          return [at(first, false), at(last, true)];
        }""",
        [first, last],
    )
    drag(studio, tuple(box[0]), tuple(box[1]))


def test_anc_06_a_comment_in_a_block_stays_on_the_blocks_phrase_not_the_pages(
    studio,
) -> None:
    page = (
        STYLE
        + "<p id='light'>Notes: the damping ratio is shown below.</p>"
        + block(
            "canvas-markdown",
            "md1",
            {"text": "Results: the damping ratio is 0.8 for mode one."},
        )
        + "<div style='height:1200px'></div>"
    )
    studio.make(page)
    studio.frame.locator("canvas-markdown p").first.wait_for()
    pick(studio, "text")
    block_words(studio, "damping", "ratio")
    what(studio)
    save_box(studio, "in block")
    assert comment_file(studio)["comments"][0]["anchor"]["quote"] == "damping ratio"
    inside = studio.frame.evaluate(
        "(() => { const b = document.querySelector('canvas-markdown').getBoundingClientRect();"
        " return [b.top + scrollY, b.bottom + scrollY]; })()"
    )
    y = wait_marks(studio, {1})["1"]["y"]
    assert inside[0] - 2 <= y <= inside[1], (y, inside)
    studio.page.wait_for_timeout(600)
    assert stored(studio) == {1: False}


def test_anc_01_white_space_between_two_inline_elements_stays_in_the_quote(
    studio,
) -> None:
    studio.make(
        STYLE
        + "<p id='s'><b>Damping</b> <i>ratio</i>\n<span>holds</span></p>"
        + "<div style='height:1200px'></div>"
    )
    comment_on_text(studio, "#s")
    anchor = comment_file(studio)["comments"][0]["anchor"]
    assert anchor["quote"] == "Damping ratio holds"
    morph_to(studio, (studio.folder / "page.html").read_text() + "<!-- v2 -->")
    wait_marks(studio, {1})
    studio.page.wait_for_timeout(600)
    assert stored(studio) == {1: False}


def test_anc_06_of_two_equal_quotes_the_one_with_the_matching_after_text_is_chosen(
    studio,
) -> None:
    twice = (
        STYLE
        + "<p id='x1'>See table three.</p><p>Result A holds under all loads.</p>"
        + "<p>Some words between the two.</p>"
        + "<p id='x2'>See table three.</p><p>Result B holds only when dry.</p>"
        + "<div style='height:1200px'></div>"
    )
    studio.make(twice)
    comment_on_text(studio, "#x2")
    first = wait_marks(studio, {1})["1"]["y"]
    assert abs(first - page_y(studio, "#x2")) < 30
    # The blocks swap places: the occurrence at the old place is the wrong one.
    changed = (
        STYLE
        + "<p id='x2'>See table three.</p><p>Result B holds only when dry.</p>"
        + "<p>Other filler text here.</p>"
        + "<p id='x1'>See table three.</p><p>Result A holds under all loads.</p>"
        + "<div style='height:1200px'></div>"
    )
    morph_to(studio, changed)
    now = wait_marks(studio, {1})["1"]["y"]
    assert abs(now - page_y(studio, "#x2")) < 30
    assert abs(now - page_y(studio, "#x1")) > 60


def test_anc_06_a_deleted_quote_is_lost_and_found_again_when_restored(studio) -> None:
    studio.make(ANCHOR_PAGE)
    comment_on_text(studio, "#mv")
    wait_marks(studio, {1})
    gone = ANCHOR_PAGE.replace(MOVED, "Something else entirely.")
    morph_to(studio, gone)
    wait_marks(studio, set())  # no marker
    wait_stored(studio, {1: True})
    [record] = comment_file(studio)["comments"]
    assert record["anchored_version"] == 2  # the version it was looked for in
    folder = studio.folder
    comments.take_unsent(folder, "page.html", "now", "evt_1")
    [listed] = comments.listing(folder, "page.html", mark_seen=False, include_all=True)
    assert listed["lost"] is True
    studio.page.evaluate("requestComments()")
    studio.page.wait_for_function(
        "[...document.querySelectorAll('#comment-panel .ent')].length === 1"
    )
    morph_to(studio, ANCHOR_PAGE)
    wait_marks(studio, {1})
    wait_stored(studio, {1: False})


def test_anc_06_a_rectangle_follows_its_element_and_is_lost_when_it_is_removed(
    studio,
) -> None:
    studio.make(ANCHOR_PAGE)
    comment_on_rect(studio, "#fig")
    start = wait_marks(studio, {1})["1"]["y"]
    fig_before = page_y(studio, "#fig")
    lower = ANCHOR_PAGE.replace(
        "<div id='fig'", "<div style='height:200px'></div><div id='fig'"
    )
    morph_to(studio, lower)
    moved = wait_marks(studio, {1})["1"]["y"]
    assert moved == pytest.approx(start + 200, abs=2)
    offset = start - fig_before  # the rectangle sits a little inside the element
    assert moved - page_y(studio, "#fig") == pytest.approx(offset, abs=2)
    morph_to(studio, ANCHOR_PAGE.replace("<div id='fig'", "<div id='other'"))
    wait_marks(studio, set())
    wait_stored(studio, {1: True})


def test_anc_06_point_and_lasso_follow_their_element_too(studio) -> None:
    studio.make(ANCHOR_PAGE)
    box = doc_box(studio, "#fig")
    pick(studio, "point")
    click_at(studio, box["x"] + 100, box["y"] + 50)
    what(studio)
    save_box(studio, "point")
    pick(studio, "lasso")
    mouse_path(
        studio,
        [
            (box["x"] + 20, box["y"] + 20),
            (box["x"] + 120, box["y"] + 20),
            (box["x"] + 120, box["y"] + 80),
            (box["x"] + 20, box["y"] + 80),
        ],
    )
    what(studio)
    save_box(studio, "lasso")
    start = wait_marks(studio, {1, 2})
    lower = ANCHOR_PAGE.replace(
        "<div id='fig'", "<div style='height:200px'></div><div id='fig'"
    )
    morph_to(studio, lower)
    after = wait_marks(studio, {1, 2})
    for number in ("1", "2"):
        assert after[number]["y"] == pytest.approx(start[number]["y"] + 200, abs=3)
    morph_to(studio, ANCHOR_PAGE.replace("id='fig'", "id='fig2'"))
    wait_marks(studio, set())
    wait_stored(studio, {1: True, 2: True})


def test_anc_06_after_a_frame_reload_the_markers_come_back_and_nothing_is_reported(
    studio,
) -> None:
    studio.make(ANCHOR_PAGE)
    comment_on_text(studio, "#mv")
    comment_on_rect(studio, "#fig")
    wait_marks(studio, {1, 2})
    studio.page.evaluate("beginLoad(active)")
    studio.frame.wait_for_function("document.readyState === 'complete'")
    wait_marks(studio, {1, 2})
    studio.page.wait_for_timeout(600)
    assert stored(studio) == {1: False, 2: False}


# ---- the 200-anchor limit (ANC-06, ANC-07, check 14: the normal variant) -----------------

PHRASE = "shared phrase of the second kind"


def line(i: int, edited: bool = False) -> str:
    if edited:
        return (
            f"<p data-i='{i}'>Edited line {i} with nothing of the old words at all.</p>"
        )
    extra = f" {PHRASE} closing {i}" if i % 17 == 0 else ""
    return f"<p data-i='{i}'>Line {i} holds words number {i * 7} about topic {i % 50}.{extra}</p>"


def letters(text: str) -> str:
    return "".join(c for c in text if c.isalnum())


@pytest.mark.timing
def test_anc_06_200_anchors_are_found_again_within_100_ms_after_a_morph(studio) -> None:
    morph_with_200_anchors(studio, budgets=True)


def test_anc_06_200_anchors_are_found_again_after_a_morph(studio) -> None:
    morph_with_200_anchors(studio, budgets=False)


def morph_with_200_anchors(studio, budgets: bool) -> None:  # noqa: ANN001
    """Check which of 200 anchors are found after a morph; ``budgets`` adds the ANC-06 times."""
    studio.make(STYLE + "<p>start</p>")
    lines = [line(i) for i in range(2000)]
    (studio.folder / "page.html").write_text(STYLE + "".join(lines))
    studio.frame.wait_for_function("document.querySelectorAll('p').length === 2000")
    document = " ".join(re.sub(r"<[^>]+>", "", p) for p in lines)
    # 100 comments on unique quotes of 40 characters, 100 on the phrase that 118
    # lines hold; each with the context ANC-01 stores.
    unique = [i for i in range(2000) if i % 17 and i % 10 == 3][:100]
    shared = [i for i in range(2000) if i % 17 == 0][:100]
    quotes = {
        i: f"Line {i} holds words number {i * 7} about topic {i % 50}."[:40]
        for i in unique
    }
    quotes |= {i: PHRASE for i in shared}
    numbers = {}
    for i, quote in quotes.items():
        start = document.index(quote, document.index(f"Line {i} holds"))
        anchor = {"space": "page-px", "x": 1, "y": 1, "w": 1, "h": 1}
        anchor |= {"fx": 0, "fy": 0, "fw": 1, "fh": 1, "quote": quote, "start": start}
        anchor |= {"end": start + len(quote)}
        anchor |= {"before": letters(document[:start])[-120:]}
        anchor |= {"after": letters(document[start + len(quote) :])[:120]}
        fields = {"kind": "text", "text": "n", "anchor": anchor, "page_version": 1}
        numbers[i] = comments.create(studio.folder, "page.html", fields)["n"]
    studio.page.evaluate("requestComments()")
    wait_marks_count(studio, 200)
    studio.frame.evaluate(
        """() => {
          window.__t = {}; window.__morphs = 0; window.__hooked = true;
          const morph = Idiomorph.morph;
          Idiomorph.morph = (...args) => {
            const done = morph.apply(Idiomorph, args);
            window.__t.morphed = performance.now();
            return done;
          };
          document.addEventListener('agentcanvas:updated', () => {
            window.__t.drawn = performance.now(); window.__morphs++;
          });
        }"""
    )
    # Five lines inserted at the top shift every offset. Every 100th line from 3
    # on is deleted (every 200th) or rewritten without its old words: the unique
    # quotes on them are gone. A shared phrase of a changed line stays on other
    # lines, so its comment goes to the occurrence that agrees most (ANC-06).
    changed = set(range(3, 2000, 100))
    version = ["<p>top</p>"] * 5
    for i in range(2000):
        if i in changed and i % 200 == 3:
            continue
        version.append(line(i, edited=True) if i in changed else lines[i])
    (studio.folder / "page.html").write_text(STYLE + "".join(version))
    studio.frame.wait_for_function("window.__morphs >= 1")
    timing = studio.frame.evaluate(
        "({morph_to_drawn: __t.drawn - __t.morphed,"
        " find: agentCanvas.commentLayer.stats.reanchorMs,"
        " text: agentCanvas.commentLayer.stats.textMs})"
    )
    print("P22.3 200 anchors, ms:", timing)
    if budgets:
        assert timing["find"] < 100, timing  # the finding itself, ANC-06
        assert timing["morph_to_drawn"] < 250, timing  # with drawing; 70 ms alone
    gone = [i for i in unique if i in changed]
    assert 0 < len(gone) < 40  # something is lost, most is found: not a vacuous pass
    found = wait_marks_count(studio, 200 - len(gone))
    for i in [*unique, *shared]:
        if i not in changed:  # an unchanged line's marker stands on its own line
            own = page_y(studio, f"p[data-i='{i}']")
            assert abs(found[str(numbers[i])]["y"] - own) < 30, i
    wait_stored(studio, {n: i in gone for i, n in numbers.items()}, timeout=15)


def wait_marks_count(studio, count: int) -> dict:  # noqa: ANN001
    end = time.monotonic() + 20
    found = 0
    while time.monotonic() < end:
        found = marker_count(studio)
        if found == count:
            return marks(studio)
        studio.page.wait_for_timeout(100)
    drawn = {int(n) for n in marks(studio)}
    missing = [
        c["anchor"]["quote"]
        for c in comment_file(studio)["comments"]
        if c["n"] not in drawn
    ]
    raise AssertionError(f"{found} markers instead of {count}; without: {missing}")


# ---- COM-05: the markers of four kinds and five statuses -----------------------------

FOUR_PAGE = (
    STYLE
    + "<p id='t'>alpha beta gamma delta epsilon</p>"
    + "<div id='fig' style='position:absolute;left:100px;top:200px;width:220px;height:120px;"
    + "background:#eee'></div>"
    + "<div style='height:1500px'></div>"
)


def four_comments(studio) -> None:  # noqa: ANN001
    pick(studio, "text")
    select_words(studio, "beta", "gamma")
    what(studio)
    save_box(studio, "text")
    pick(studio, "point")
    click_at(studio, 150, 240)
    what(studio)
    save_box(studio, "point")
    pick(studio, "rect")
    drag(studio, (200, 230), (300, 290))
    what(studio)
    save_box(studio, "rect")
    pick(studio, "lasso")
    mouse_path(studio, [(130, 280), (180, 280), (180, 310), (130, 310)])
    what(studio)
    save_box(studio, "lasso")


def style_of(studio, n: int) -> dict:  # noqa: ANN001
    return studio.frame.evaluate(
        """(n) => {
          const root = document.querySelector('[data-ac-comment-host]').shadowRoot;
          const m = root.querySelector(`[data-n="${n}"]`);
          const shape = m.matches('.box') ? m : m.querySelector('.hl, .pin, svg.outline polygon');
          const s = getComputedStyle(shape); const b = getComputedStyle(m.querySelector('.badge'));
          return {border: s.borderTopStyle, dash: s.strokeDasharray, bg: s.backgroundColor,
                  stroke: s.stroke, pin: s.backgroundColor, badge: b.backgroundColor,
                  opacity: getComputedStyle(m).opacity};
        }""",
        n,
    )


def test_com_05_each_kind_has_its_marker_with_the_number_where_the_text_says(
    studio,
) -> None:
    studio.make(FOUR_PAGE)
    four_comments(studio)
    found = wait_marks(studio, {1, 2, 3, 4})
    assert "mk" in found["1"]["cls"] and "box" in found["3"]["cls"]
    details = studio.frame.evaluate(
        """() => {
          const root = document.querySelector('[data-ac-comment-host]').shadowRoot;
          const rect = (e) => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
          const get = (n) => root.querySelector(`[data-n="${n}"]`);
          const text = get(1);
          return {
            lines: text.querySelectorAll('.hl').length,
            textBadge: rect(text.querySelector('.badge')), textFirst: rect(text.querySelector('.hl')),
            pin: get(2).querySelectorAll('.pin').length, pinBadge: rect(get(2).querySelector('.badge')),
            pinAt: rect(get(2).querySelector('.pin')),
            rectBadge: rect(get(3).querySelector('.badge')), rectBox: rect(get(3)),
            lasso: get(4).querySelector('svg.outline polygon').getAttribute('points'),
            lassoBadge: rect(get(4).querySelector('.badge')),
            labels: [1, 2, 3, 4].map((n) => get(n).querySelector('.badge').textContent),
          };
        }"""
    )
    assert details["labels"] == ["1", "2", "3", "4"]
    assert details["lines"] == 1
    # text: the number in a circle left of the first line; point: over the pin
    assert (
        details["textBadge"][0] + details["textBadge"][2] <= details["textFirst"][0] + 2
    )
    assert (
        abs(
            details["textBadge"][1]
            + 10
            - (details["textFirst"][1] + details["textFirst"][3] / 2)
        )
        < 4
    )
    assert details["pin"] == 1
    assert abs(details["pinBadge"][0] + 10 - (details["pinAt"][0] + 6)) < 3
    assert details["pinBadge"][1] < details["pinAt"][1]
    # rectangle: on the top edge; lasso: at the path's point nearest the top left
    assert abs(details["rectBadge"][1] + 10 - details["rectBox"][1]) < 4
    points = [[float(v) for v in p.split(",")] for p in details["lasso"].split(" ")]
    corner = min(points, key=lambda p: p[0] + p[1])
    box = details["lassoBadge"]
    assert abs(box[0] + 10 - corner[0]) < 3 and abs(box[1] + 10 - corner[1]) < 3


def test_com_05_drafts_are_dashed_with_an_open_circle(studio) -> None:
    studio.make(FOUR_PAGE)
    four_comments(studio)
    wait_marks(studio, {1, 2, 3, 4})
    text, point, rect, lasso = (style_of(studio, n) for n in (1, 2, 3, 4))
    assert text["border"] == "dashed" and rect["border"] == "dashed"
    assert lasso["dash"] != "none"
    assert point["pin"] == "rgb(255, 255, 255)"  # an open pin
    for style in (text, point, rect, lasso):
        assert style["badge"] == "rgb(255, 255, 255)"  # an open circle


def test_com_05_sent_answered_and_done_markers_look_as_the_text_says(studio) -> None:
    sid = studio.make(FOUR_PAGE)
    four_comments(studio)
    wait_marks(studio, {1, 2, 3, 4})
    studio.queue_action()
    studio.page.click("#send-button")
    studio.wait_events(sid, 1)
    wait_status(studio, "sent")
    text, point, rect, lasso = (style_of(studio, n) for n in (1, 2, 3, 4))
    assert text["border"] == "none" and rect["border"] == "solid"  # not dashed
    assert lasso["dash"] == "none"
    assert point["pin"] == "rgb(194, 65, 12)"
    for style in (text, point, rect, lasso):
        assert style["badge"] == "rgb(194, 65, 12)" and style["opacity"] == "1"
    comments.reply(studio.folder, "page.html", 3, "fixed it", "claude")
    comments.set_done(studio.folder, "page.html", 4, "agent")
    studio.page.evaluate("requestComments()")
    studio.page.locator('#comment-panel [data-filter="all"]').click()  # COM-22
    wait_status(studio, "answered", 3)
    wait_status(studio, "done", 4)
    answered, done = style_of(studio, 3), style_of(studio, 4)
    assert answered["badge"] == "rgb(27, 127, 75)" and answered["border"] == "solid"
    assert float(done["opacity"]) < 1  # faint
    assert done["badge"] == "rgb(107, 116, 128)"


def wait_status(studio, status: str, n: int = 1) -> None:  # noqa: ANN001
    studio.frame.wait_for_function(
        """([n, s]) => { const h = document.querySelector('[data-ac-comment-host]');
          const m = h && h.shadowRoot.querySelector(`[data-n="${n}"]`);
          return Boolean(m) && m.classList.contains(s); }""",
        arg=[n, status],
    )


def test_com_05_markers_take_pointer_input_on_their_number_only(studio) -> None:
    studio.make(FOUR_PAGE)
    four_comments(studio)
    wait_marks(studio, {1, 2, 3, 4})
    studio.page.keyboard.press("Escape")  # mode off: the page gets its pointer back
    result = studio.frame.evaluate(
        """() => {
          const host = document.querySelector('[data-ac-comment-host]');
          const root = host.shadowRoot;
          const others = [...root.querySelectorAll('*')].filter((e) =>
            !e.matches('.badge, style, .layer') && getComputedStyle(e).pointerEvents !== 'none'
            && !e.closest('.badge'));
          const centre = (e) => { const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; };
          const under = (e) => { const [x, y] = centre(e); return document.elementFromPoint(x, y); };
          const hl = root.querySelector('.hl');
          const rect = root.querySelector('.box[data-n="3"]');
          return {others: others.map((e) => e.className.baseVal ?? e.className), hl: under(hl) === host,
                  rect: under(rect) === host,
                  badges: [...root.querySelectorAll('.badge')].map((b) => under(b) === host),
                  hostEvents: getComputedStyle(host).pointerEvents};
        }"""
    )
    assert result["others"] == []
    assert result["hostEvents"] == "none"
    assert result["hl"] is False and result["rect"] is False
    assert result["badges"] == [True, True, True, True]


def test_com_05_a_click_on_a_number_reports_it_and_a_page_click_elsewhere_does_not(
    studio,
) -> None:
    studio.make(FOUR_PAGE)
    four_comments(studio)
    wait_marks(studio, {1, 2, 3, 4})
    studio.page.keyboard.press("Escape")
    before = studio.page.evaluate("window.__guard.accepted['comment-marker'] || 0")
    studio.frame.locator(f"{HOST} .box[data-n='3'] .badge").click()
    studio.page.wait_for_function(
        f"(window.__guard.accepted['comment-marker'] || 0) > {before}"
    )
    studio.frame.wait_for_selector(f"{HOST} >> .box[data-n='3'].hot")  # now selected
    assert studio.frame.locator(f"{HOST} >> .hot").count() == 1


def test_com_05_the_markers_move_no_element_and_the_host_is_kept_once_by_a_morph(
    studio,
) -> None:
    studio.make(FOUR_PAGE)
    steady_layout(studio)
    pick(studio, "rect")  # the panel opens and narrows the frame: measure after it
    before = all_rects(studio)
    four_comments(studio)
    wait_marks(studio, {1, 2, 3, 4})
    assert all_rects(studio) == before
    studio.frame.evaluate(
        "window.__host = document.querySelector('[data-ac-comment-host]')"
    )
    morph_to(studio, FOUR_PAGE.replace("alpha", "ALPHA"))
    assert studio.frame.evaluate(
        "[document.querySelectorAll('[data-ac-comment-host]').length,"
        " document.querySelector('[data-ac-comment-host]') === window.__host]"
    ) == [1, True]
    wait_marks(studio, {1, 2, 3, 4})
    assert marker_count(studio) == 4


def reddish(rows) -> bool:  # noqa: ANN001
    """True when a pixel is the orange of a marker or the yellow of a highlight."""
    orange, yellow = (194, 65, 12), (253, 236, 166)

    def near(pixel, colour) -> bool:  # noqa: ANN001
        return all(abs(a - b) <= 8 for a, b in zip(pixel[:3], colour, strict=True))

    return any(near(p, orange) or near(p, yellow) for row in rows for p in row)


def test_com_05_markers_are_in_the_live_window_but_not_in_the_send_screenshot(
    studio,
) -> None:
    sid = studio.make(FOUR_PAGE)
    four_comments(studio)
    wait_marks(studio, {1, 2, 3, 4})
    studio.page.keyboard.press("Escape")
    _, _, live = decode_png(studio.page.screenshot())
    assert reddish(live), "positive control: the markers show in the window"
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    _, _, rows = decode_png(studio.screenshot(event))
    assert not reddish(rows)


def test_com_05_markers_are_not_in_a_look_nor_in_the_page_checks(studio) -> None:
    sid = studio.make(FOUR_PAGE)
    four_comments(studio)
    wait_marks(studio, {1, 2, 3, 4})
    answer = call(
        studio.owner,
        "POST",
        f"/api/sessions/{sid}/look",
        json={"width": 700, "height": 500},
    )
    _, _, rows = decode_png(Path(answer["png"]).read_bytes())
    assert not reddish(rows), "no marker in the picture of a look"
    audit = studio.frame.evaluate(
        "async () => JSON.stringify(await window.agentCanvas.runPageAudit({}))"
    )
    assert "data-ac-comment-host" not in audit and "badge" not in audit
    print("P22.3 audit:", audit[:300])


# ---- COM-18, SEC-09: tokens on lost reports and the list of messages -------------------

CAPTURE = (
    "window.__tokens = []; window.addEventListener('message', (e) => {"
    " if (e.data && e.data.type === 'comment-markers') window.__tokens.push(...e.data.markers.map((m) => m.token)); });"
)


def forge_lost(studio, token: str, lost: bool = True) -> None:  # noqa: ANN001
    message = json.dumps(
        {"type": "comment-lost", "items": [{"token": token, "lost": lost}]}
    )
    studio.frame.evaluate(f"parent.postMessage({message}, '*')")


def test_com_18_a_lost_report_with_a_wrong_token_is_dropped_and_logged(studio) -> None:
    studio.make(ANCHOR_PAGE)
    studio.frame.evaluate(CAPTURE)
    comment_on_text(studio, "#mv")
    wait_marks(studio, {1})
    before = studio.page.evaluate("window.__guard.dropped.token")
    forge_lost(studio, "guessed")
    studio.page.wait_for_function(f"window.__guard.dropped.token > {before}")
    studio.page.wait_for_timeout(300)
    assert stored(studio) == {1: False}
    # Positive control: the token the shell gave this comment is accepted.
    token = studio.frame.evaluate("window.__tokens[window.__tokens.length - 1]")
    forge_lost(studio, token)
    wait_stored(studio, {1: True})


def test_com_18_a_token_is_void_once_the_page_has_a_new_version(studio) -> None:
    studio.make(ANCHOR_PAGE)
    studio.frame.evaluate(CAPTURE)
    comment_on_text(studio, "#mv")
    wait_marks(studio, {1})
    old = studio.frame.evaluate("window.__tokens[window.__tokens.length - 1]")
    morph_to(studio, ANCHOR_PAGE.replace("Another section", "Another part"))
    studio.frame.wait_for_function(
        f"window.__tokens[window.__tokens.length - 1] !== '{old}'"
    )
    before = studio.page.evaluate("window.__guard.dropped.token")
    forge_lost(studio, old)
    studio.page.wait_for_function(f"window.__guard.dropped.token > {before}")
    studio.page.wait_for_timeout(300)
    assert stored(studio) == {1: False}


def test_com_18_a_lost_report_for_a_comment_of_another_page_changes_nothing(
    studio,
) -> None:
    sid = studio.make(ANCHOR_PAGE)
    studio.frame.evaluate(CAPTURE)
    comment_on_text(studio, "#mv")
    wait_marks(studio, {1})
    token = studio.frame.evaluate("window.__tokens[window.__tokens.length - 1]")
    open_other_page(studio, sid)
    go_to(studio, "other.html")
    before = studio.page.evaluate("window.__guard.dropped.token")
    forge_lost(studio, token)
    studio.page.wait_for_function(f"window.__guard.dropped.token > {before}")
    studio.page.wait_for_timeout(300)
    assert stored(studio) == {1: False}
    # Positive control: back on the first page its own token is accepted.
    go_to(studio, "page.html")
    studio.frame.evaluate(CAPTURE)
    studio.frame.evaluate("window.__tokens = []")
    morph_to(studio, ANCHOR_PAGE + "<!-- again -->")
    studio.frame.wait_for_function("window.__tokens.length > 0")
    forge_lost(
        studio, studio.frame.evaluate("window.__tokens[window.__tokens.length - 1]")
    )
    wait_stored(studio, {1: True})


def test_com_04_a_saved_comment_carries_the_page_version_it_was_made_on(
    studio,
) -> None:
    studio.make(ANCHOR_PAGE)
    morph_to(studio, ANCHOR_PAGE.replace("Another section", "Another part"))
    comment_on_text(studio, "#mv")
    record = comment_file(studio)["comments"][0]
    assert record["page_version"] == 2 == record["anchored_version"]


def test_com_18_each_selection_gets_a_fresh_token(studio) -> None:
    studio.make(ANCHOR_PAGE)
    studio.frame.evaluate(
        "window.__crops = []; window.addEventListener('message', (e) => {"
        " if (e.data && e.data.type === 'comment-crop') window.__crops.push(e.data.token); });"
    )
    pick(studio, "rect")
    for _ in range(2):
        drag(studio, (50, 300), (150, 360))
        what(studio)
        studio.page.keyboard.press("Escape")
        studio.page.wait_for_selector(".cbox", state="detached")
        pick(studio, "rect")
    crops = studio.frame.evaluate("window.__crops")
    assert len(crops) == 2 and crops[0] != crops[1]
    assert all(re.fullmatch(r"[0-9a-f]{24}", token) for token in crops)


def test_sec_09_the_lost_report_is_on_the_list_and_has_the_size_limit(studio) -> None:
    studio.make(ANCHOR_PAGE)
    before = studio.page.evaluate("window.__guard.accepted['comment-lost'] || 0")
    forge_lost(studio, "x")
    studio.page.wait_for_function(
        f"(window.__guard.accepted['comment-lost'] || 0) > {before}"
    )
    size = studio.page.evaluate("window.__guard.dropped.size")
    big = json.dumps({"type": "comment-lost", "items": [], "pad": "x" * 1_100_000})
    studio.frame.evaluate(f"parent.postMessage({big}, '*')")
    studio.page.wait_for_function(f"window.__guard.dropped.size > {size}")
    kind = studio.page.evaluate("window.__guard.dropped.type")
    studio.frame.evaluate("parent.postMessage({type: 'comment-hover'}, '*')")
    studio.page.wait_for_function(f"window.__guard.dropped.type > {kind}")


def test_com_15_markers_carry_the_page_quote_but_never_a_comment_or_reply_text(
    studio,
) -> None:
    sid = studio.make(ANCHOR_PAGE)
    studio.frame.evaluate(
        "window.__rec = []; window.addEventListener('message', "
        "(e) => window.__rec.push(JSON.stringify(e.data)));"
    )
    pick(studio, "text")
    drag_over(studio, "#mv")
    what(studio)
    studio.page.fill(".cbox textarea", "SECRET-comment-text")
    studio.page.keyboard.press("Enter")
    wait_saved(studio, 1)
    studio.queue_action()
    studio.page.click("#send-button")
    studio.wait_events(sid, 1)
    comments.reply(studio.folder, "page.html", 1, "SECRET-agent-reply", "claude")
    studio.page.evaluate("requestComments()")
    studio.page.wait_for_function(
        "[...commentPages.values()].some((p) => p.comments.some((c) => c.replies.length))"
    )
    studio.page.wait_for_timeout(300)
    records = studio.frame.evaluate("window.__rec")
    quoted = [r for r in records if '"comment-markers"' in r and MOVED[:20] in r]
    assert quoted, "positive control: the quote travelled"
    assert not [r for r in records if "SECRET" in r]


def test_anc_06_keys_outside_comment_mode_still_reach_the_page_with_markers_shown(
    studio,
) -> None:
    studio.make(ANCHOR_PAGE)
    studio.frame.evaluate(
        "window.__keys = []; window.addEventListener('keydown', (e) => window.__keys.push(e.key));"
    )
    comment_on_text(studio, "#mv")
    wait_marks(studio, {1})
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_function("!document.body.classList.contains('commenting')")
    studio.frame.evaluate("document.body.tabIndex = 0; document.body.focus()")
    studio.page.keyboard.press("t")
    studio.page.keyboard.press("l")
    assert studio.frame.evaluate(
        "window.__keys.filter((k) => k === 't' || k === 'l')"
    ) == ["t", "l"]
