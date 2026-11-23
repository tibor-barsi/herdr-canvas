"""The four selection kinds and their anchors on HTML pages (M22 P22.2).

COM-02, COM-13, ANC-02, ANC-04, ANC-05, COM-17 and SES-13 (changed) are owned
here; ANC-01 and ANC-03 are owned in their HTML vectors (the viewers' vectors
close in P24.4, P25.2 and P25.3). Markers for the new kinds are drawn in P22.3:
these tests look at the shape shown while a box is open.
"""

from __future__ import annotations

import json
import math

import pytest

from .support import SCROLL_PAGE, block, until
from .test_comment_layer import (
    box_count,
    comment_file,
    comment_mode,
    drag,
    wait_saved,
)
from .test_comment_panel import steady_layout
from .test_heavy_blocks import data_to_page, plot_config, wait_plot

pytestmark = pytest.mark.browser

HOST = "[data-ac-comment-host]"

TEXT_PAGE = (
    "<style>body{margin:0;font:16px/24px sans-serif}"
    "#a{position:absolute;left:40px;top:50px;width:260px}</style>"
    "<div id='a'><p id='p1'>alpha beta gamma delta epsilon zeta eta theta iota kappa "
    "lambda</p>"
    "<p id='p2'>second paragraph</p></div><div style='height:1500px'></div>"
)

FIG_PAGE = (
    "<style>body{margin:0}#fig{position:absolute;left:100px;top:100px;width:200px;"
    "height:100px;background:#ddd}</style><div id='fig'></div>"
    "<div style='height:2400px'></div>"
)


# ---- helpers -----------------------------------------------------------------------


def words(studio, word: str) -> dict:  # noqa: ANN001
    """Scroll the first ``word`` into view; return its frame-viewport rectangle.

    Looks inside shadow roots too.
    """
    return studio.frame.evaluate(
        """(word) => {
          const scan = (root) => {
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            for (let n = walker.nextNode(); n; n = walker.nextNode()) {
              const at = n.data.indexOf(word);
              const tag = n.parentElement ? n.parentElement.tagName : '';
              if (at < 0 || tag === 'SCRIPT' || tag === 'STYLE') continue;
              if (n.parentElement) n.parentElement.scrollIntoView({block: 'nearest'});
              const r = document.createRange();
              r.setStart(n, at); r.setEnd(n, at + word.length);
              const b = r.getBoundingClientRect();
              return {x: b.x, y: b.y, w: b.width, h: b.height};
            }
            for (const e of root.querySelectorAll('*')) {
              if (e.shadowRoot) { const f = scan(e.shadowRoot); if (f) return f; }
            }
            return null;
          };
          return scan(document.body);
        }""",
        word,
    )


def select_words(studio, first: str, last: str) -> None:  # noqa: ANN001
    """Drag a text selection from the start of ``first`` to the end of ``last``."""
    # At the frame's edge a held mouse autoscrolls the page, more on a slow machine.
    studio.frame.evaluate(
        "y => window.scrollBy(0, y - innerHeight / 2)", words(studio, first)["y"]
    )
    a, b = words(studio, first), words(studio, last)
    drag(
        studio,
        (a["x"] + 1, a["y"] + a["h"] / 2),
        (b["x"] + b["w"] - 1, b["y"] + b["h"] / 2),
    )


def mouse_path(studio, points: list[tuple[float, float]]) -> None:  # noqa: ANN001
    """Press at the first point, move through the others, release at the last."""
    left, top = studio.origin()
    mouse = studio.page.mouse
    mouse.move(left + points[0][0], top + points[0][1])
    mouse.down()
    for x, y in points[1:]:
        mouse.move(left + x, top + y)
    mouse.up()


def click_at(studio, x: float, y: float) -> None:  # noqa: ANN001
    left, top = studio.origin()
    studio.page.mouse.click(left + x, top + y)


def ellipse(cx: float, cy: float, rx: float, ry: float, count: int) -> list:
    return [
        (
            cx + rx * math.cos(2 * math.pi * i / count),
            cy + ry * math.sin(2 * math.pi * i / count),
        )
        for i in range(count)
    ]


def pick(studio, kind: str) -> None:  # noqa: ANN001
    """Turn comment mode on with ``C``, press the kind's key and wait for both."""
    body = studio.page.locator("body")
    if not studio.page.evaluate("document.body.classList.contains('commenting')"):
        body.press("c")
    studio.page.wait_for_function("document.body.classList.contains('commenting')")
    body.press(kind[0])  # t, p, r, l
    studio.frame.wait_for_function(
        f"document.documentElement.getAttribute('data-ac-commenting') === '{kind}'"
    )
    # The layer that handles the gesture loads only after the mode message.
    studio.frame.wait_for_function("!!window.agentCanvas.commentLayer")


def what(studio) -> str:  # noqa: ANN001
    studio.page.wait_for_selector(".cbox textarea")
    return studio.page.locator(".cbox .what").inner_text()


def save_box(studio, text: str = "note") -> dict:  # noqa: ANN001
    """Type into the open box, save, and return the newest stored comment."""
    studio.page.fill(".cbox textarea", text)
    studio.page.keyboard.press("Enter")
    count = len(comment_file(studio)["comments"]) + 1
    wait_saved(studio, count)
    return comment_file(studio)["comments"][-1]


def focus_page(studio) -> None:  # noqa: ANN001
    studio.frame.evaluate("document.body.tabIndex = 0; document.body.focus()")


def host_count(studio, selector: str) -> int:  # noqa: ANN001
    return studio.frame.evaluate(
        "(s) => document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelectorAll(s).length",
        selector,
    )


def marker_and_bar(studio) -> dict | None:  # noqa: ANN001
    """Frame boxes of comment mark 1 and ``#bar`` from one read, or None."""
    return studio.frame.evaluate(
        "() => { const host = document.querySelector('[data-ac-comment-host]');"
        " const m = host && host.shadowRoot.querySelector('.box[data-n=\\'1\\']');"
        " if (!m) return null;"
        " const box = (r) => ({x: r.x, y: r.y, w: r.width, h: r.height});"
        " return {mark: box(m.getBoundingClientRect()),"
        " bar: box(document.querySelector('#bar').getBoundingClientRect())}; }"
    )


def doc_box(studio, selector: str) -> dict:  # noqa: ANN001
    return studio.frame.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
        " return {x: r.x, y: r.y, w: r.width, h: r.height}; }",
        selector,
    )


# ---- COM-02: keys and gestures -----------------------------------------


def test_com_02_the_keys_pick_the_kind_in_comment_mode_only_and_reach_the_page_outside(
    studio,
) -> None:
    studio.make(SCROLL_PAGE)
    studio.frame.evaluate(
        "window.__keys = [];"
        "window.addEventListener('keydown',"
        " e => __keys.push([e.key, e.defaultPrevented]))"
    )
    focus_page(studio)
    for key in "tprlx":
        studio.page.keyboard.press(key)
    # They reached the page; only x is taken (it marks a comment done, KEY).
    assert studio.frame.evaluate("window.__keys") == [
        [k, k == "x"] for k in "tprlx"
    ]
    assert not studio.page.evaluate("document.body.classList.contains('commenting')")
    comment_mode(studio)
    for key, kind in [("t", "text"), ("p", "point"), ("l", "lasso"), ("r", "rect")]:
        studio.page.keyboard.press(key)
        studio.frame.wait_for_function(
            f"document.documentElement.getAttribute('data-ac-commenting') === '{kind}'"
        )


def test_com_02_the_last_kind_is_kept_across_a_reload(studio) -> None:
    sid = studio.make(SCROLL_PAGE)
    pick(studio, "lasso")
    studio.page.reload()
    studio.page.wait_for_selector(f'.hv-pill[data-session="{sid}"]')
    studio.owner.visit(sid)
    assert not commenting(studio)
    comment_mode(studio)
    studio.frame.wait_for_function(
        "document.documentElement.getAttribute('data-ac-commenting') === 'lasso'"
    )


def test_com_02_text_drag_double_click_and_triple_click_open_the_box_on_release(
    studio,
) -> None:
    studio.make(TEXT_PAGE)
    pick(studio, "text")
    select_words(studio, "beta", "gamma")
    assert "Text" in what(studio)
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_selector(".cbox", state="detached")
    box = words(studio, "epsilon")
    left, top = studio.origin()
    studio.page.mouse.dblclick(left + box["x"] + 5, top + box["y"] + 8)
    studio.page.wait_for_selector(".cbox textarea")
    assert studio.page.locator(".cbox .what").inner_text().endswith("epsilon")
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_selector(".cbox", state="detached")
    studio.page.mouse.click(left + box["x"] + 5, top + box["y"] + 8, click_count=3)
    studio.page.wait_for_selector(".cbox textarea")
    assert (
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
        in studio.page.locator(".cbox .what").inner_text()
    )


def test_com_02_a_text_click_without_a_selection_opens_nothing_and_page_clicks_stay_out(
    studio,
) -> None:
    studio.make(TEXT_PAGE)
    studio.frame.evaluate(
        "window.__clicks = 0; window.addEventListener('click', () => __clicks++)"
    )
    pick(studio, "text")
    box = words(studio, "iota")
    click_at(studio, box["x"] + 5, box["y"] + 8)
    studio.page.wait_for_timeout(300)
    assert box_count(studio) == 0
    assert studio.frame.evaluate("window.__clicks") == 0


def test_com_02_a_point_is_a_click_and_a_drag_in_point_kind_opens_nothing(
    studio,
) -> None:
    studio.make(FIG_PAGE)
    pick(studio, "point")
    drag(studio, (150, 120), (190, 160))
    studio.page.wait_for_timeout(300)
    assert box_count(studio) == 0
    click_at(studio, 150, 120)
    assert "Point" in what(studio)
    assert host_count(studio, ".dot") == 1


def test_com_02_a_lasso_needs_three_points_and_64_px_squared_and_shows_while_dragging(
    studio,
) -> None:
    studio.make(FIG_PAGE)
    pick(studio, "lasso")
    mouse_path(studio, [(200, 400), (260, 440)])  # two points
    studio.page.wait_for_timeout(200)
    assert box_count(studio) == 0
    mouse_path(studio, [(200, 400), (260, 400), (330, 400)])  # three points, no area
    studio.page.wait_for_timeout(200)
    assert box_count(studio) == 0
    mouse_path(
        studio, [(200, 400), (207, 400), (207, 407), (200, 407)]
    )  # 49 px squared
    studio.page.wait_for_timeout(200)
    assert box_count(studio) == 0
    left, top = studio.origin()
    studio.page.mouse.move(left + 200, top + 400)
    studio.page.mouse.down()
    for x, y in [(260, 400), (260, 460), (200, 440)]:
        studio.page.mouse.move(left + x, top + y)
    assert (
        host_count(studio, "svg.lasso polygon") == 1
    )  # drawn while the button is held
    studio.page.mouse.up()
    assert "Lasso" in what(studio)
    assert host_count(studio, "svg.lasso polygon") == 1  # and while the box is open
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_selector(".cbox", state="detached")
    assert host_count(studio, "svg.lasso polygon") == 0


def test_com_02_each_kind_stores_a_comment_with_its_kind(studio) -> None:
    studio.make(TEXT_PAGE)
    pick(studio, "text")
    select_words(studio, "beta", "gamma")
    assert "Text" in what(studio)
    save_box(studio, "t")
    pick(studio, "point")
    click_at(studio, 400, 300)
    assert "Point" in what(studio)
    save_box(studio, "p")
    pick(studio, "rect")
    drag(studio, (400, 400), (480, 460))
    assert "Rectangle" in what(studio)
    save_box(studio, "r")
    pick(studio, "lasso")
    mouse_path(studio, [(400, 500), (500, 500), (500, 560), (400, 560)])
    assert "Lasso" in what(studio)
    save_box(studio, "l")
    assert [c["kind"] for c in comment_file(studio)["comments"]] == [
        "text",
        "point",
        "rect",
        "lasso",
    ]


# ---- COM-13: page coordinates, scrolling and resize ----------------------------------


def test_com_13_two_points_either_side_of_a_scroll_are_stored_in_page_coordinates(
    studio,
) -> None:
    studio.make(FIG_PAGE)
    pick(studio, "point")
    click_at(studio, 400, 200)
    what(studio)
    first = save_box(studio, "top")["anchor"]
    studio.frame.evaluate("window.scrollTo(0, 700)")
    studio.frame.wait_for_function("window.scrollY === 700")
    click_at(studio, 400, 200)
    what(studio)
    second = save_box(studio, "scrolled")["anchor"]
    assert (first["x"], first["y"]) == (400, 200)
    assert (second["x"], second["y"]) == (400, 900)
    assert first["space"] == second["space"] == "page-px"


RESIZE_PAGE = (
    "<style>body{margin:0;font:16px/24px sans-serif}"
    "#bar{position:absolute;left:10%;top:120px;width:50%;height:100px;background:#eee}"
    "#txt{position:absolute;left:10%;top:300px;width:40%}</style>"
    "<div id='bar'></div>"
    "<p id='txt'>one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen</p>"
    "<div style='height:1800px'></div>"
)


def test_com_13_markers_and_the_open_shape_are_placed_again_after_a_resize(
    studio,
) -> None:
    studio.make(RESIZE_PAGE)
    studio.page.set_viewport_size({"width": 1280, "height": 800})
    steady_layout(studio)
    comment_mode(studio)
    bar = doc_box(studio, "#bar")
    drag(studio, (bar["x"], bar["y"]), (bar["x"] + bar["w"], bar["y"] + bar["h"]))
    what(studio)
    save_box(studio, "bar")
    marker = studio.frame.locator(f'{HOST} .box[data-n="1"]')
    before = marker.bounding_box()
    assert abs(before["width"] - bar["w"]) <= 2
    # A point on the bar: its open shape follows the bar's fractions.
    pick(studio, "point")
    click_at(studio, bar["x"] + bar["w"] * 0.25, bar["y"] + bar["h"] * 0.5)
    what(studio)
    studio.page.set_viewport_size({"width": 600, "height": 700})
    studio.frame.wait_for_function(f"window.innerWidth < {bar['x'] + bar['w']}")
    # The layer redraws by replacing its marks: measure mark and bar in one go.
    both = until(
        studio.page,
        lambda: (
            (m := marker_and_bar(studio))
            and m["bar"]["w"] < bar["w"] - 50
            and abs(m["mark"]["w"] - m["bar"]["w"]) <= 2
            and m
        ),
    )
    narrow, after = both["bar"], both["mark"]
    assert narrow["w"] < bar["w"] - 50
    assert abs(after["w"] - narrow["w"]) <= 2
    assert abs(after["x"] - narrow["x"]) <= 2
    dot = studio.frame.evaluate(
        "(() => { const r = document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelector('.dot').getBoundingClientRect();"
        " return [r.x + r.width / 2, r.y + r.height / 2]; })()"
    )
    assert dot[0] == pytest.approx(narrow["x"] + narrow["w"] * 0.25, abs=2)
    assert dot[1] == pytest.approx(narrow["y"] + narrow["h"] * 0.5, abs=2)


def test_com_13_a_lasso_and_a_text_selection_follow_their_page_after_a_resize(
    studio,
) -> None:
    studio.make(RESIZE_PAGE)
    studio.page.set_viewport_size({"width": 1280, "height": 800})
    pick(studio, "lasso")
    bar = doc_box(studio, "#bar")
    x0, y0 = bar["x"] + bar["w"] * 0.2, bar["y"] + 10
    mouse_path(studio, [(x0, y0), (x0 + 120, y0), (x0 + 120, y0 + 60), (x0, y0 + 60)])
    what(studio)
    first = host_polygon(studio)
    studio.page.set_viewport_size({"width": 600, "height": 700})
    studio.frame.wait_for_function(f"window.innerWidth < {bar['x'] + bar['w']}")
    until(studio.page, lambda: doc_box(studio, "#bar")["w"] < bar["w"] - 50)
    narrow = doc_box(studio, "#bar")
    until(
        studio.page,
        lambda: (
            host_polygon(studio)[0][0]
            == pytest.approx(
                narrow["x"] + (first[0][0] - bar["x"]) / bar["w"] * narrow["w"], abs=2
            )
        ),
    )
    after = host_polygon(studio)
    assert after[0][0] == pytest.approx(
        narrow["x"] + (first[0][0] - bar["x"]) / bar["w"] * narrow["w"], abs=2
    )
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_selector(".cbox", state="detached")
    pick(studio, "text")
    select_words(studio, "five", "six")
    what(studio)
    studio.page.set_viewport_size({"width": 700, "height": 700})

    def temp_box() -> list:
        return studio.frame.evaluate(
            "(() => { const r = document.querySelector('[data-ac-comment-host]')"
            ".shadowRoot.querySelector('.box.temp').getBoundingClientRect();"
            " return [r.x, r.y]; })()"
        )

    until(
        studio.page,
        lambda: temp_box()[0] == pytest.approx(words(studio, "five")["x"], abs=2),
    )
    word = words(studio, "five")
    temp = temp_box()
    assert temp[0] == pytest.approx(word["x"], abs=2)
    assert temp[1] == pytest.approx(word["y"], abs=2)


def host_polygon(studio) -> list:  # noqa: ANN001
    return studio.frame.evaluate(
        "(() => { const p = document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelector('svg.lasso polygon'); return p.getAttribute('points')"
        ".split(' ').map(s => s.split(',').map(Number)); })()"
    )


# ---- ANC-01: text anchor -------------------------------------------------------------

SENTENCES = [
    f"Sentence number {i} says something plain about topic {i * 7}." for i in range(40)
]
LONG_PAGE = (
    "<style>body{margin:0;font:16px/22px sans-serif}p{margin:0 0 10px;width:600px}"
    "</style>"
    + "".join(f"<p>{s}</p>" for s in SENTENCES)
    + "<p id='target'>The TARGETWORD sits here.</p><p>After one two three.</p>"
    + "<p id='wrap'>uno dos tres<br>cuatro cinco seis</p>"
    + "<p id='spaced'>alpha   beta\n     gamma</p>"
    + f"<p id='long'>{'word ' * 400}</p>"
)
DOC = " ".join(
    [
        *SENTENCES,
        "The TARGETWORD sits here.",
        "After one two three.",
        "uno dos tres cuatro cinco seis",
        "alpha beta gamma",
        ("word " * 400).strip(),
    ]
)


def test_anc_01_a_word_has_quote_context_offsets_one_rect_and_its_paragraph_as_target(
    studio,
) -> None:
    studio.make(LONG_PAGE)
    pick(studio, "text")
    box = words(studio, "TARGETWORD")
    left, top = studio.origin()
    studio.page.mouse.dblclick(left + box["x"] + 10, top + box["y"] + 8)
    what(studio)
    saved = save_box(studio, "word")
    anchor = saved["anchor"]
    start = DOC.index("TARGETWORD")
    letters = "".join(c for c in DOC[:start] if c.isalnum())
    assert anchor["quote"] == "TARGETWORD" and anchor["cut"] is False
    assert (anchor["start"], anchor["end"]) == (start, start + len("TARGETWORD"))
    assert anchor["before"] == letters[-120:] and len(anchor["before"]) == 120
    after = "".join(c for c in DOC[start + 10 :] if c.isalnum())
    assert anchor["after"] == after[:120]
    assert anchor["space"] == "page-px" and len(anchor["rects"]) == 1
    rect = anchor["rects"][0]
    scroll = studio.frame.evaluate("window.scrollY")
    assert rect["y"] == pytest.approx(box["y"] + scroll, abs=1)
    assert rect["x"] == pytest.approx(box["x"], abs=1)
    assert saved["target"]["selector"] == "#target"


def test_anc_01_a_selection_over_two_lines_gives_two_rects_that_quote_and_context(
    studio,
) -> None:
    studio.make(LONG_PAGE)
    pick(studio, "text")
    studio.page.wait_for_timeout(200)
    select_words(studio, "dos", "cinco")  # inside #wrap: line 1 to line 2
    what(studio)
    saved = save_box(studio, "two lines")
    anchor = saved["anchor"]
    assert anchor["quote"] == "dos tres cuatro cinco"
    assert len(anchor["rects"]) == 2
    assert anchor["rects"][0]["y"] < anchor["rects"][1]["y"]
    start = DOC.index("uno dos tres cuatro cinco seis") + 4
    assert DOC[start : start + 21] == "dos tres cuatro cinco"
    assert (anchor["start"], anchor["end"]) == (start, start + 21)
    assert anchor["before"].endswith("uno")
    assert anchor["after"].startswith("seis")
    assert saved["target"]["selector"] == "#wrap"


def test_anc_01_white_space_is_collapsed_in_the_quote_and_the_offsets(studio) -> None:
    studio.make(LONG_PAGE)
    pick(studio, "text")
    studio.page.wait_for_timeout(200)
    box = words(studio, "beta")
    left, top = studio.origin()
    studio.page.mouse.click(left + box["x"] + 4, top + box["y"] + 8, click_count=3)
    what(studio)
    anchor = save_box(studio, "spaced")["anchor"]
    start = DOC.index("alpha beta gamma")
    assert anchor["quote"] == "alpha beta gamma"
    assert (anchor["start"], anchor["end"]) == (start, start + 16)


def test_anc_01_a_1500_character_selection_gives_1000_characters_and_cut_true(
    studio,
) -> None:
    studio.make(LONG_PAGE)
    pick(studio, "text")
    studio.page.wait_for_timeout(200)
    box = studio.frame.evaluate(
        "(() => { const e = document.getElementById('long'); e.scrollIntoView();"
        " const r = e.getBoundingClientRect();"
        " return {x: r.x, y: r.y}; })()"
    )
    left, top = studio.origin()
    studio.page.mouse.click(left + box["x"] + 20, top + box["y"] + 8, click_count=3)
    what(studio)
    anchor = save_box(studio, "long")["anchor"]
    assert len(anchor["quote"]) == 1000 and anchor["cut"] is True
    assert anchor["end"] - anchor["start"] == 1999  # the whole paragraph, uncut


# ---- ANC-02 and ANC-03: point and rectangle ------------------------------------------


def test_anc_02_a_click_at_the_centre_of_fig_gives_target_fig_and_fractions_one_half(
    studio,
) -> None:
    studio.make(FIG_PAGE)
    pick(studio, "point")
    click_at(studio, 200, 150)
    what(studio)
    saved = save_box(studio, "centre")
    anchor = saved["anchor"]
    assert saved["kind"] == "point" and anchor["space"] == "page-px"
    assert (anchor["x"], anchor["y"]) == (200, 150)
    assert saved["target"]["selector"] == "#fig"
    assert anchor["fx"] == pytest.approx(0.5, abs=0.01)
    assert anchor["fy"] == pytest.approx(0.5, abs=0.01)


# ---- ANC-04: lasso -------------------------------------------------------------------

TABLE_PAGE = (
    "<style>body{margin:0;font:16px/24px sans-serif}"
    "table{position:absolute;left:40px;top:50px;border-collapse:collapse}"
    "td{padding:1px 8px}</style>"
    "<table><tr id='r1'><td>row one</td><td>alpha</td></tr>"
    "<tr id='r2'><td>row two</td><td>beta</td></tr></table>"
    "<div style='height:1500px'></div>"
)


def test_anc_04_a_lasso_around_one_of_two_adjacent_rows_gives_that_rows_text_only(
    studio,
) -> None:
    studio.make(TABLE_PAGE)
    steady_layout(studio)
    pick(studio, "lasso")
    row = doc_box(studio, "#r1")
    path = ellipse(
        row["x"] + row["w"] / 2, row["y"] + row["h"] / 2, row["w"] / 2 + 6, 17, 300
    )
    mouse_path(studio, path)
    what(studio)
    saved = save_box(studio, "row")
    anchor = saved["anchor"]
    assert saved["text_inside"] == "row one alpha"
    assert 3 <= len(anchor["points"]) <= 200
    assert len(anchor["fpoints"]) == len(anchor["points"])
    target = doc_box(studio, saved["target"]["selector"])
    for (x, y), (fx, fy) in zip(anchor["points"], anchor["fpoints"], strict=True):
        assert x == pytest.approx(target["x"] + fx * target["w"], abs=1)
        assert y == pytest.approx(target["y"] + fy * target["h"], abs=1)
    box = anchor["bbox"]
    assert box["w"] == pytest.approx(
        max(p[0] for p in anchor["points"]) - box["x"], abs=1
    )


def test_anc_04_a_wiggly_path_of_1200_points_is_cut_to_at_most_200(studio) -> None:
    studio.make(FIG_PAGE)
    pick(studio, "lasso")
    path = [
        (
            350 + (150 + 10 * math.sin(150 * t)) * math.cos(t),
            420 + (150 + 10 * math.sin(150 * t)) * math.sin(t),
        )
        for t in (2 * math.pi * i / 1200 for i in range(1200))
    ]
    mouse_path(studio, path)
    what(studio)
    anchor = save_box(studio, "wiggly")["anchor"]
    assert 10 <= len(anchor["points"]) <= 200  # 2 px alone keeps hundreds more
    assert anchor["bbox"]["w"] > 300 and anchor["bbox"]["h"] > 300


EVEN_ODD_PAGE = (
    "<style>body{margin:0;font:16px/24px sans-serif}"
    "#tri{position:absolute;left:40px;top:50px;width:260px;margin:0}</style>"
    "<p id='tri'>aaa one<br>bbb two<br>ccc three</p><div style='height:1500px'></div>"
)


def test_anc_04_text_covered_twice_by_a_self_crossing_path_is_outside_by_even_odd(
    studio,
) -> None:
    studio.make(EVEN_ODD_PAGE)
    pick(studio, "lasso")
    box = doc_box(studio, "#tri")
    x0, y0, x1, y1 = box["x"] - 5, box["y"] - 5, box["x"] + 200, box["y"] + 77
    # The outer loop, then an inner loop around the middle line, both clockwise:
    # the middle line is wound twice, which the even-odd rule counts as outside.
    outer = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0 + 1)]
    ya, yb = box["y"] + 28, box["y"] + 46
    inner = [(x0 + 4, ya), (x1 - 4, ya), (x1 - 4, yb), (x0 + 4, yb), (x0 + 4, ya + 1)]
    mouse_path(studio, outer + inner)
    what(studio)
    assert save_box(studio, "ring")["text_inside"] == "aaa one ccc three"


# ---- check 13: the hit test over 2000 lines ------------------------------------------

KIT_PAGE = (
    "<style>body{margin:0;font:16px/24px sans-serif}p{margin:0;padding:0 20px}"
    "section{border:1px solid #ccc}</style>"
    + "".join(
        "<section>"
        + "".join(f"<p>Line {c * 50 + i} of the kit page</p>" for i in range(50))
        + "</section>"
        for c in range(40)
    )
)


@pytest.mark.timing
def test_anc_04_a_200_point_lasso_over_2000_lines_is_found_within_check_13s_time(
    studio,
) -> None:
    studio.make(KIT_PAGE)
    pick(studio, "lasso")  # loads the comment layer into the frame
    counts = studio.frame.evaluate("document.querySelectorAll('p').length")
    assert counts == 2000
    result = studio.frame.evaluate(
        """() => {
          const polygon = [];
          for (let i = 0; i < 200; i++) {
            const a = 2 * Math.PI * i / 200;
            polygon.push([400 + 350 * Math.cos(a), 300 + 250 * Math.sin(a)]);
          }
          const rect = {x: 50, y: 50, w: 700, h: 500};
          const times = [];
          let inside = null;
          for (let k = 0; k < 25; k++) {
            const t0 = performance.now();
            inside = window.agentCanvas.commentLayer.textInside(rect, polygon);
            times.push(performance.now() - t0);
          }
          return {best: Math.min(...times), times, inside};
        }"""
    )
    print("lasso 2000 lines, ms:", result["times"])
    assert result["inside"] and "Line 10 " in result["inside"]
    assert (
        result["best"] <= 16
    )  # early check 13: 4 to 16 ms (110 ms without the prefilter)


# ---- ANC-05: data coordinates over a plot --------------------------------------------


def plot_page(studio, layout: dict | None = None) -> None:  # noqa: ANN001
    config = plot_config()
    if layout:
        config["layout"].update(layout)
    studio.make(block("canvas-plot", "spectrum", config))
    wait_plot(studio.owner, "spectrum")


def test_anc_05_a_rectangle_over_a_plot_gives_data_ranges_within_2_percent(
    studio,
) -> None:
    plot_page(studio)
    pick(studio, "rect")
    x0, y0 = data_to_page(studio.frame, "spectrum", 2, 60)
    x1, y1 = data_to_page(studio.frame, "spectrum", 6, 20)
    drag(studio, (x0, y0), (x1, y1))
    what(studio)
    saved = save_box(studio, "region")
    data = saved["data"]
    assert data["canvas_id"] == "spectrum"
    assert data["x"] == pytest.approx([2, 6], abs=0.2)  # 2 % of the range 0..10
    assert data["y"] == pytest.approx([20, 60], abs=2)  # 2 % of 0..100


def test_anc_05_a_point_on_the_peak_gives_its_x_within_2_percent(studio) -> None:
    plot_page(studio)
    pick(studio, "point")
    x, y = data_to_page(studio.frame, "spectrum", 5, 90)
    click_at(studio, x, y)
    what(studio)
    saved = save_box(studio, "peak")
    data = saved["data"]
    assert data["canvas_id"] == "spectrum"
    assert data["x"] == pytest.approx(5, abs=0.2)
    assert data["y"] == pytest.approx(90, abs=2)


def test_anc_05_a_lasso_over_a_plot_gives_the_ranges_of_its_bounding_box(
    studio,
) -> None:
    plot_page(studio)
    pick(studio, "lasso")
    a = data_to_page(studio.frame, "spectrum", 3, 80)
    b = data_to_page(studio.frame, "spectrum", 7, 80)
    c = data_to_page(studio.frame, "spectrum", 5, 30)
    mouse_path(studio, [a, b, c])
    what(studio)
    data = save_box(studio, "tri")["data"]
    assert data["x"] == pytest.approx([3, 7], abs=0.2)
    assert data["y"] == pytest.approx([30, 80], abs=2)


def test_anc_05_log_axes_give_data_values_not_exponents(studio) -> None:
    plot_page(studio, {"yaxis": {"type": "log", "range": [0, 3]}})
    pick(studio, "point")
    box = studio.frame.evaluate(
        "(() => { const r = document.querySelector('canvas-plot').shadowRoot"
        ".querySelector('.plot').getBoundingClientRect(); return [r.left, r.top]; })()"
    )
    left, top, width, height = 60, 20, 520, 330  # the fixed layout of plot_config
    # y = 100 is 2 of 3 decades up; x = 5 is half way.
    px = box[0] + left + width / 2
    py = box[1] + top + (3 - 2) / 3 * height
    click_at(studio, px, py)
    what(studio)
    data = save_box(studio, "log")["data"]
    assert data["x"] == pytest.approx(5, abs=0.2)
    assert data["y"] == pytest.approx(100, rel=0.02)


def test_anc_05_a_shape_away_from_any_plot_has_no_data(studio) -> None:
    studio.make(block("canvas-plot", "spectrum", plot_config()) + FIG_PAGE)
    wait_plot(studio.owner, "spectrum")
    pick(studio, "point")
    click_at(studio, 450, 560)
    what(studio)
    saved = save_box(studio, "elsewhere")
    assert saved["data"] is None


# ---- COM-17: text inside a block's shadow root ---------------------------------------

BLOCKS_PAGE = (
    "<style>body{margin:0;font:16px/24px sans-serif}"
    "p.light{margin:10px;width:400px}</style>"
    "<p class='light'>Light paragraph before the first block.</p>"
    + block(
        "canvas-markdown",
        "md1",
        {
            "text": "First block paragraph with several plain words."
            "\n\nSecond paragraph."
        },
    )
    + block("canvas-markdown", "md2", {"text": "Other block with its own words."})
    + "<p class='light'>Light paragraph after the blocks.</p>"
    "<div style='height:1500px'></div>"
)


def show_blocks(studio) -> None:  # noqa: ANN001
    studio.make(BLOCKS_PAGE)
    studio.frame.locator("canvas-markdown p").first.wait_for()


def test_com_17_a_selection_inside_one_block_gives_a_text_comment_on_that_block(
    studio,
) -> None:
    show_blocks(studio)
    pick(studio, "text")
    select_words(studio, "several", "words")
    assert "Text" in what(studio)
    saved = save_box(studio, "in block")
    assert saved["anchor"]["quote"] == "several plain words"
    assert saved["target"]["canvas_id"] == "md1"
    assert len(saved["anchor"]["rects"]) >= 1


@pytest.mark.parametrize(
    ("first", "last"),
    [("before", "several"), ("several", "Other"), ("plain", "after")],
)
def test_com_17_a_selection_across_a_block_boundary_shows_the_notice_and_opens_no_box(
    studio, first, last
) -> None:
    show_blocks(studio)
    pick(studio, "text")
    select_words(studio, first, last)
    studio.page.wait_for_function(
        "document.getElementById('notice').classList.contains('visible')"
    )
    assert (
        "Text inside this block cannot be selected; use a point, rectangle or lasso"
        in studio.page.locator("#notice").inner_text()
    )
    assert box_count(studio) == 0


# ---- COM-15, COM-18, SEC-09: what the frame may say ----------------------------------


def test_sec_09_a_forged_selection_of_another_kind_or_with_a_bad_anchor_opens_nothing(
    studio,
) -> None:
    studio.make(FIG_PAGE)
    pick(studio, "rect")
    forged = {"x": 10, "y": 10, "w": 50, "h": 50, "fx": 0, "fy": 0, "fw": 1, "fh": 1}
    for message in [
        {
            "type": "comment-selection",
            "kind": "lasso",
            "anchor": forged,
            "rect": forged,
        },
        {
            "type": "comment-selection",
            "kind": "rect",
            "anchor": {"x": 1},
            "rect": forged,
        },
        {"type": "comment-selection", "kind": "text", "notice": "block-boundary"},
    ]:
        studio.frame.evaluate(f"parent.postMessage({json.dumps(message)}, '*')")
    studio.page.wait_for_timeout(300)
    assert box_count(studio) == 0
    assert not studio.page.locator("#notice.visible").count()
    # Positive control: the same shape with the right kind opens the box, nothing more.
    studio.frame.evaluate(
        "parent.postMessage("
        + json.dumps(
            {
                "type": "comment-selection",
                "kind": "rect",
                "anchor": forged,
                "rect": forged,
            }
        )
        + ", '*')"
    )
    studio.page.wait_for_selector(".cbox textarea")
    assert comment_file(studio)["comments"] == []


def test_com_15_the_mode_message_carries_the_kind_and_no_message_carries_the_text(
    studio,
) -> None:
    studio.make(TEXT_PAGE)
    studio.frame.evaluate(
        "window.__rec = []; window.addEventListener('message', "
        "(e) => window.__rec.push(JSON.stringify(e.data)));"
    )
    pick(studio, "text")
    select_words(studio, "beta", "gamma")
    what(studio)
    save_box(studio, "SECRET-kind-text")
    studio.page.wait_for_timeout(300)
    records = studio.frame.evaluate("window.__rec")
    assert any('"kind":"text"' in r and '"comment-mode"' in r for r in records)
    assert not [r for r in records if "SECRET" in r]


# ---- COM-02 (#43, D-64): C starts comment mode with the last kind --------------------


def commenting(studio) -> bool:  # noqa: ANN001
    return studio.page.evaluate("document.body.classList.contains('commenting')")


def pressed(studio) -> list[str]:  # noqa: ANN001
    """The kind comment mode is on with in the page, as a list (empty when off)."""
    kind = studio.frame.evaluate(
        "document.documentElement.getAttribute('data-ac-commenting')"
    )
    return [kind] if kind else []


def test_com_02_esc_leaves_comment_mode(studio) -> None:
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_function("!document.body.classList.contains('commenting')")


def test_com_02_c_starts_with_the_last_kind_and_c_again_leaves(studio) -> None:
    studio.make(SCROLL_PAGE)
    pick(studio, "point")
    comment_mode(studio, False)  # leaves; the kind stays the last used
    comment_mode(studio)
    assert pressed(studio) == ["point"]
    studio.page.keyboard.press("t")
    studio.frame.wait_for_function(
        "document.documentElement.getAttribute('data-ac-commenting') === 'text'"
    )
    comment_mode(studio, False)
    assert pressed(studio) == []
    comment_mode(studio)
    assert pressed(studio) == ["text"]
