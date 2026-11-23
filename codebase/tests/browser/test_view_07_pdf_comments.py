"""Comments on PDFs (P25.2) and the per-type test of VIEW-07.

VIEW-07, VIEW-08, ANC-01, ANC-03, ANC-08 and COM-12 are closed here for the PDF
(the HTML, Markdown and picture vectors run in their own files and in the per-type
test below). A PDF's anchors are in ``pdf-pt``: points from the top-left of page ``p``,
pages from 1.
"""

# ruff: noqa: E501  (the scripts run in the frame are one-line strings)
from __future__ import annotations

import pytest

from .pdf_fixtures import text_pdf
from .test_comment_anchors import wait_marks
from .test_comment_kinds import mouse_path, select_words, what
from .test_comment_layer import comment_mode, drag
from .test_comment_panel import steady_layout
from .test_view_04_pdf_viewer import PAGE, click, settle, span_of, wait_text
from .test_viewer_comments import (
    DOC,
    ORANGE,
    at,
    comments_of,
    full_size,
    lost_posts,
    md_box,
    near,
    pick,
    save,
    saved_picture,
    settled,
    show_file,
    show_markdown,
    show_picture,
    wait_lost,
    watch_lost_reports,
)

pytestmark = pytest.mark.browser

PAGE_W, PAGE_H = 595, 842  # the fixture's page, points


def open_doc(studio, data: bytes | None = None, name: str = "doc.pdf") -> None:  # noqa: ANN001
    """Show a PDF and wait until page 1 has its text layer and the text is read."""
    show_file(studio, name, data or text_pdf(3))
    wait_text(studio.owner, 1)
    studio.frame.wait_for_function("window.acViewer.index !== null")
    studio.page.wait_for_timeout(100)


def go(studio, page: int, top: float = 0) -> None:  # noqa: ANN001
    """Scroll page ``page`` so that its top lies ``top`` px below the frame's top."""
    studio.frame.evaluate(
        f"(() => {{ const e = {PAGE.format(n=page)}; const s = document.querySelector('[data-scroller]');"
        f" s.scrollTop += e.getBoundingClientRect().top - {top}; }})()"
    )
    wait_text(studio.owner, page)
    settle(studio.owner)


def pt(studio, page: int, x: float, y: float) -> tuple[float, float]:  # noqa: ANN001
    """The frame point of (x, y) points on ``page`` now."""
    spot = studio.frame.evaluate(f"acViewer.fromSpace({page}, {x}, {y})")
    return spot["x"], spot["y"]


def scale(studio) -> float:  # noqa: ANN001
    return studio.frame.evaluate("acViewer.scale")


def comment_picture(studio, index: int = -1) -> tuple:  # noqa: ANN001
    return saved_picture(studio, "doc.pdf", index)


def reveal(studio, page: int, box: tuple) -> None:  # noqa: ANN001
    """Scroll so that the points ``(x0, y0, x1, y1)`` of ``page`` are in view."""
    studio.frame.evaluate(
        f"acViewer.reveal({{p: {page}, x: {box[0]}, y: {box[1]}, w: {box[2] - box[0]}, h: {box[3] - box[1]}}})"
    )
    settled(studio)


def rect_on_page(studio, page: int, box: tuple, text: str = "note") -> None:  # noqa: ANN001
    """Drag over points ``(x0, y0, x1, y1)`` of ``page`` and save the comment."""
    reveal(studio, page, box)
    pick(studio, "rect")
    drag(studio, pt(studio, page, box[0], box[1]), pt(studio, page, box[2], box[3]))
    what(studio)
    save(studio, text)


def point_on_page(studio, page: int, x: float, y: float, text: str = "note") -> None:  # noqa: ANN001
    reveal(studio, page, (x - 5, y - 5, x + 5, y + 5))
    pick(studio, "point")
    left, top = studio.origin()
    px, py = pt(studio, page, x, y)
    studio.page.mouse.click(left + px, top + py)
    what(studio)
    save(studio, text)


def text_on_page(studio, first: str, last: str, text: str = "note") -> None:  # noqa: ANN001
    pick(studio, "text")
    select_words(studio, first, last)
    what(studio)
    save(studio, text)


# ---- 4.2: the interface of the PDF viewer ---------------------------------------------------


def test_view_07_a_pdf_converts_for_a_given_page_and_reveals_a_box(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 1)
    # A point below page 1, asked for as a point of page 3, lies far beyond page 3's top.
    spot = studio.frame.evaluate("acViewer.toSpace(100, 100, 3)")
    assert spot["p"] == 3 and spot["y"] < -PAGE_H
    studio.frame.evaluate("acViewer.reveal({p: 3, x: 50, y: 400, w: 100, h: 40})")
    settle(studio.owner)
    x, y = pt(studio, 3, 100, 420)
    size = studio.frame.evaluate("[innerWidth, innerHeight]")
    assert 0 <= x <= size[0] and 0 <= y <= size[1]
    assert studio.frame.evaluate("acViewer.page") == 3
    # A box that is in view does not move the view.
    before = studio.frame.evaluate(
        "document.querySelector('[data-scroller]').scrollTop"
    )
    studio.frame.evaluate("acViewer.reveal({p: 3, x: 90, y: 410, w: 20, h: 20})")
    assert (
        studio.frame.evaluate("document.querySelector('[data-scroller]').scrollTop")
        == before
    )


# ---- ANC-01: the text anchor ------------------------------------------------------------------

LINE = "Line {i} of page {n}: the quick brown fox jumps over the lazy dog"


def test_anc_01_a_pdf_text_anchor_has_quote_context_offsets_and_rects_with_the_page(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 3)
    first = "Line 5 of page 3"
    text_on_page(studio, first, "Line 5 of page 3: the quick brown")
    [comment] = comments_of(studio, "doc.pdf")
    anchor = comment["anchor"]
    assert anchor["space"] == "pdf-pt"
    assert (
        anchor["quote"] == "Line 5 of page 3: the quick brown"
        and anchor["cut"] is False
    )
    assert anchor["before"].endswith("Line4ofpage3thequickbrownfoxjumpsoverthelazydog")
    assert anchor["after"].startswith("foxjumpsoverthelazydogLine6ofpage3")
    text = studio.frame.evaluate("acViewer.index.text")
    assert text[anchor["start"] : anchor["end"]] == anchor["quote"]
    [rect] = anchor["rects"]
    assert rect["p"] == 3
    # The rectangle is where the text layer draws the words (points from the page's top-left).
    span = span_of(studio.owner, first)
    top_left = studio.frame.evaluate(f"acViewer.toSpace({span['x']}, {span['y']}, 3)")
    assert rect["x"] == pytest.approx(top_left["x"], abs=3)
    assert rect["y"] == pytest.approx(top_left["y"], abs=4)
    assert rect["h"] == pytest.approx(span["h"] / scale(studio), abs=3)
    assert 100 < rect["w"] < 200
    assert comment["target"]["selector"]
    assert comment["text_inside"] is None
    assert comment["picture_error"] is None and comment["picture"]


def test_anc_01_a_pdf_selection_over_two_lines_has_one_rect_per_line(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 2)
    text_on_page(studio, "Line 7 of page 2: the quick", "Line 8 of page 2: the quick")
    [comment] = comments_of(studio, "doc.pdf")
    rects = comment["anchor"]["rects"]
    assert [r["p"] for r in rects] == [2, 2]
    assert rects[1]["y"] == pytest.approx(rects[0]["y"] + 17, abs=1.5)
    assert (
        rects[0]["w"] > rects[1]["w"]
    )  # the first line to its end, the second to "quick"


def test_anc_01_a_selection_from_page_2_into_page_3_has_rects_on_both_pages(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 2, top=-300)
    studio.frame.evaluate(
        "document.querySelector('[data-scroller]').scrollTop += 600; null"
    )
    settle(studio.owner)
    text_on_page(studio, "Line 29 of page 2: the quick", "Line 2 of page 3: the quick")
    [comment] = comments_of(studio, "doc.pdf")
    pages = [r["p"] for r in comment["anchor"]["rects"]]
    assert pages[0] == 2 and pages[-1] == 3 and set(pages) == {2, 3}
    assert comment["picture_error"] is None


# ---- ANC-03: rectangle, point and lasso --------------------------------------------------------


def test_anc_03_a_pdf_rectangle_is_in_points_from_the_page_top_left_with_the_text_inside(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 2)
    rect_on_page(studio, 2, (100, 180, 300, 250))
    [comment] = comments_of(studio, "doc.pdf")
    anchor = comment["anchor"]
    assert anchor["space"] == "pdf-pt" and anchor["p"] == 2
    assert "nw" not in anchor and "fx" not in anchor
    for name, value in zip("xywh", (100, 180, 200, 70), strict=True):
        assert anchor[name] == pytest.approx(value, abs=1.5), name
    inside = comment["text_inside"]
    assert LINE.format(i=5, n=2) in inside and LINE.format(i=8, n=2) in inside
    assert "Line 3 of page 2" not in inside and "page 1" not in inside
    assert len(inside) <= 500
    assert comment["target"]["selector"]
    assert wait_marks(studio, {1})


def test_anc_03_a_rectangle_with_no_text_under_it_has_text_inside_null(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 1)
    rect_on_page(studio, 1, (400, 130, 500, 170))
    assert comments_of(studio, "doc.pdf")[0]["text_inside"] is None


def test_anc_03_a_pdf_point_has_its_page_and_points(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 3)
    point_on_page(studio, 3, 300, 400)
    [comment] = comments_of(studio, "doc.pdf")
    anchor = comment["anchor"]
    assert anchor["space"] == "pdf-pt" and anchor["p"] == 3
    assert (anchor["x"], anchor["y"]) == (
        pytest.approx(300, abs=1),
        pytest.approx(400, abs=1),
    )
    assert comment["text_inside"] is None


def test_anc_04_a_pdf_lasso_has_points_bbox_and_the_text_inside(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 2)
    pick(studio, "lasso")
    path = [pt(studio, 2, 100, 175), pt(studio, 2, 350, 175), pt(studio, 2, 225, 260)]
    mouse_path(studio, path)
    what(studio)
    save(studio, "loop")
    [comment] = comments_of(studio, "doc.pdf")
    anchor = comment["anchor"]
    assert anchor["space"] == "pdf-pt" and anchor["p"] == 2
    assert len(anchor["points"]) == 3
    assert anchor["points"][0] == [
        pytest.approx(100, abs=1.5),
        pytest.approx(175, abs=1.5),
    ]
    assert anchor["bbox"]["w"] == pytest.approx(250, abs=2)
    assert (
        LINE.format(i=5, n=2) in comment["text_inside"]
    )  # centre (216, 182) is inside
    assert (
        LINE.format(i=9, n=2) not in comment["text_inside"]
    )  # centre (216, 250) is outside


def test_anc_03_a_pdf_gesture_in_the_gap_below_a_page_selects_nothing(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    steady_layout(studio)
    go(studio, 1, top=-(PAGE_H * 0.9))
    left, top = studio.origin()
    pick(studio, "point")
    bottom = studio.frame.evaluate(f"{PAGE.format(n=1)}.getBoundingClientRect().bottom")
    # Positive control: the same click a few pixels higher, on the page, opens the box.
    studio.page.mouse.click(left + 200, top + bottom - 6)
    studio.page.wait_for_selector(".cbox textarea")
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_selector(".cbox", state="detached")
    studio.page.mouse.click(left + 200, top + bottom + 4)
    studio.page.wait_for_timeout(300)
    assert studio.page.locator(".cbox").count() == 0


# ---- COM-12: the pictures of PDF comments --------------------------------------------------------


def test_com_12_a_pdf_rectangle_is_cut_from_the_page_canvas_with_16_px_padding(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio)
    steady_layout(studio)
    go(studio, 1)
    rect_on_page(studio, 1, (400, 130, 500, 170))
    anchor = comments_of(studio, "doc.pdf")[0]["anchor"]
    width, height, rows = comment_picture(studio)
    css = scale(studio)
    assert width == pytest.approx(anchor["w"] * css + 32, abs=3)
    assert height == pytest.approx(anchor["h"] * css + 32, abs=3)
    assert near(rows[height // 2][width // 2], (255, 255, 255))  # a white page


def test_com_12_a_pdf_picture_shows_the_selected_text(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 1)
    rect_on_page(studio, 1, (50, 160, 350, 200))
    width, height, rows = comment_picture(studio)
    dark = sum(1 for row in rows for pixel in row if sum(pixel[:3]) < 300)
    assert dark > 100  # the glyphs of the lines are in it


@pytest.mark.parametrize("presses", [0, 3, 6])
def test_com_12_a_pdf_crop_has_at_least_one_image_pixel_per_css_pixel_and_is_not_enlarged(
    studio, presses
) -> None:  # noqa: ANN001
    """At fit, 175 %, and 400 %: the crop has the canvas's pixels, 1 per CSS px at 1x."""
    open_doc(studio)
    steady_layout(studio)
    for _ in range(presses):
        click(studio.owner, "Zoom in")
    settle(studio.owner)
    go(studio, 1)
    box = (60, 130, 90, 150)
    rect_on_page(studio, 1, box)
    css = scale(studio)
    anchor = comments_of(studio, "doc.pdf")[0]["anchor"]
    width, _, rows = comment_picture(studio)
    expected = anchor["w"] * css + 32
    assert width >= expected - 3  # not below one image px per CSS px
    assert width <= expected + 3  # and not enlarged
    assert rows


def test_com_12_a_crop_taken_right_after_a_zoom_is_drawn_at_the_new_zoom_first(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 1)
    script = """async () => {
      for (let i = 0; i < 3; i++) document.querySelector('[aria-label="Zoom in"]').click();
      const css = acViewer.scale;
      const got = await acViewer.crop(1, {x: 0, y: 0, w: 100, h: 50});
      return [got.canvas.width, got.canvas.height, got.k, css];
    }"""
    width, height, k, css = studio.frame.evaluate(script)
    assert k >= css - 1e-6
    assert width >= 100 * css - 2 and height >= 50 * css - 2


def test_com_12_a_pdf_point_is_320_by_200_css_px_with_the_pin_on_it(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 2)
    point_on_page(studio, 2, 300, 450)
    width, height, rows = comment_picture(studio)
    assert (width, height) == (320, 200)
    assert near(rows[100][160], ORANGE, 30)


def test_com_12_a_pdf_lasso_is_its_bounding_box_with_the_path_drawn(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    steady_layout(studio)
    go(studio, 2)
    pick(studio, "lasso")
    path = [pt(studio, 2, 100, 175), pt(studio, 2, 350, 175), pt(studio, 2, 225, 260)]
    mouse_path(studio, path)
    what(studio)
    save(studio, "loop")
    anchor = comments_of(studio, "doc.pdf")[0]["anchor"]
    css = scale(studio)
    width, height, rows = comment_picture(studio)
    assert width == pytest.approx(anchor["bbox"]["w"] * css + 32, abs=3)
    assert height == pytest.approx(anchor["bbox"]["h"] * css + 32, abs=3)
    assert near(rows[16][width // 2], ORANGE, 60), rows[16][width // 2]


def test_com_12_a_pdf_text_picture_is_the_quotes_box(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    steady_layout(studio)
    go(studio, 3)
    text_on_page(studio, "Line 5 of page 3", "Line 5 of page 3: the quick brown")
    anchor = comments_of(studio, "doc.pdf")[0]["anchor"]
    css = scale(studio)
    width, height, _ = comment_picture(studio)
    assert width == pytest.approx(anchor["rects"][0]["w"] * css + 32, abs=3)
    assert height == pytest.approx(anchor["rects"][0]["h"] * css + 32, abs=3)


# ---- ANC-08, VIEW-08: a new version -------------------------------------------------------------


def new_version(
    studio, data: bytes, pages: int, mark: str, name: str = "doc.pdf"
) -> None:  # noqa: ANN001
    """Write a new version; wait until the viewer shows its pages and has read its text."""
    (studio.folder / name).write_bytes(data)
    studio.frame.wait_for_function(
        f"acViewer.pageCount === {pages} && acViewer.index !== null && acViewer.index.text.includes({mark!r})"
    )
    settled(studio)


def item_spot(studio, text: str) -> dict:  # noqa: ANN001
    """The frame point of the top-left of the first text item that starts with ``text``."""
    return studio.frame.evaluate(
        """(t) => { const i = acViewer.index.items.find((e) => e.str.startsWith(t));
          const f = acViewer.fromSpace(i.p, i.x, i.y); return {p: i.p, x: f.x, y: f.y}; }""",
        text,
    )


def marker_y(studio, number: int) -> float:  # noqa: ANN001
    return wait_marks(studio, set(range(1, number + 1)))[str(number)]["y"]


def test_anc_08_pdf_text_is_found_again_and_shapes_keep_their_page_or_are_lost_with_it(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio, text_pdf(3))
    go(studio, 3)
    text_on_page(
        studio, "Line 5 of page 3", "Line 5 of page 3: the quick brown", "text"
    )
    rect_on_page(studio, 3, (100, 180, 300, 250), "rect")
    go(studio, 1)
    point_on_page(studio, 1, 300, 400, "point")
    wait_marks(studio, {1, 2, 3})
    assert [c["lost"] for c in comments_of(studio, "doc.pdf")] == [False] * 3

    # Every text moves one page on: the quote is on page 4 now, the shapes stay on their pages.
    new_version(studio, text_pdf(4, first=0), 4, "Line 5 of page 0")
    assert item_spot(studio, "Line 5 of page 3")["p"] == 4
    studio.frame.evaluate(
        "acViewer.reveal({p: 4, x: 0, y: 150, w: 100, h: 100})"
    )  # the marker of a page that is drawn
    settle(studio.owner)
    expected = item_spot(studio, "Line 5 of page 3")
    found = wait_marks(studio, {1, 2, 3})
    assert found["1"]["y"] == pytest.approx(expected["y"], abs=3)
    rect_spot = pt(studio, 3, 100, 180)
    assert found["2"]["y"] == pytest.approx(rect_spot[1], abs=3)
    assert [c["lost"] for c in comments_of(studio, "doc.pdf")] == [False] * 3

    # Two pages: the quote is gone and so is page 3, the point on page 1 stays.
    new_version(studio, text_pdf(2), 2, "Line 5 of page 2")
    wait_lost(studio, [True, True, False], "doc.pdf")
    assert set(wait_marks(studio, {3})) == {"3"}

    # Three pages as before: all found again.
    new_version(studio, text_pdf(3), 3, "Line 5 of page 3")
    wait_lost(studio, [False, False, False], "doc.pdf")
    wait_marks(studio, {1, 2, 3})


def test_anc_08_nothing_is_reported_lost_while_the_new_text_is_being_read(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio, text_pdf(3))
    go(studio, 2)
    text_on_page(
        studio, "Line 5 of page 2", "Line 5 of page 2: the quick brown", "text"
    )
    rect_on_page(studio, 2, (100, 180, 300, 250), "rect")
    wait_marks(studio, {1, 2})
    settled(studio)  # a report timer from saving the comments has run out
    watch_lost_reports(studio)
    # A long document: its text is read for longer than the layer's 300 ms report delay.
    new_version(studio, text_pdf(150, lines=300), 150, "Line 5 of page 150")
    studio.frame.wait_for_function("window.__lostChecks > 0")
    studio.page.wait_for_timeout(600)
    assert lost_posts(studio) == 0
    assert [c["lost"] for c in comments_of(studio, "doc.pdf")] == [False, False]
    wait_marks(studio, {1, 2})


def test_anc_08_a_quote_that_stands_twice_with_the_same_surroundings_is_lost(
    studio,
) -> None:  # noqa: ANN001
    """The rule of ANC-06 holds for a PDF: an unclear match is lost, never guessed."""
    open_doc(studio, text_pdf(3, tag=" x"))
    go(studio, 3)
    text_on_page(studio, "Line 5 of page 3", "Line 5 of page 3: the quick")
    new_version(studio, text_pdf(3, tag=" x", first=3), 3, "Line 5 of page 5")
    # Page numbers 3, 4, 5: the quote "Line 5 of page 3: the quick" now stands on page 1 only.
    wait_lost(studio, [False], "doc.pdf")
    assert item_spot(studio, "Line 5 of page 3")["p"] == 1


def test_view_08_a_new_pdf_version_is_pushed_and_keeps_the_page_offset_and_zoom(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio, text_pdf(8))
    for _ in range(2):
        click(studio.owner, "Zoom in")
    settle(studio.owner)
    go(studio, 4)
    studio.frame.evaluate("document.querySelector('[data-scroller]').scrollTop += 300")
    settle(studio.owner)
    studio.frame.evaluate("window.__same = document.querySelector('[data-scroller]')")
    zoom = "document.querySelector('[data-bar] output').textContent"
    before = studio.frame.evaluate(f"({{zoom: {zoom}, spot: acViewer.toSpace(10, 0)}})")
    new_version(
        studio,
        text_pdf(9, tag=" v2"),
        9,
        "page 4: the quick brown fox jumps over the lazy dog v2",
    )
    after = studio.frame.evaluate(f"({{zoom: {zoom}, spot: acViewer.toSpace(10, 0)}})")
    assert after["zoom"] == before["zoom"]
    assert after["spot"]["p"] == before["spot"]["p"] == 4
    assert after["spot"]["y"] == pytest.approx(before["spot"]["y"], abs=2)
    assert studio.frame.evaluate(
        "window.__same === document.querySelector('[data-scroller]')"
    )


def test_anc_08_a_marker_click_in_the_panel_scrolls_the_pdf_to_it(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 3)
    rect_on_page(studio, 3, (100, 180, 300, 250))
    comment_mode(studio, False)
    studio.frame.evaluate("document.querySelector('[data-scroller]').scrollTop = 0")
    settle(studio.owner)
    assert studio.frame.evaluate("acViewer.page") == 1
    studio.page.locator("#comment-panel .ent").first.click()
    studio.frame.wait_for_function("acViewer.page === 3")
    x, y = pt(studio, 3, 150, 200)
    assert 0 <= y <= studio.frame.evaluate("innerHeight")


# ---- VIEW-07: the same workflow on the four kinds of page -----------------------------------------

HTML = (
    "<body style='margin:0'><p style='position:absolute;left:40px;top:40px;margin:0;"
    "font:20px sans-serif'>alpha beta gamma delta epsilon</p>"
    "<div style='height:1200px'></div></body>"
)


def prepare(studio, kind: str) -> tuple:  # noqa: ANN001
    """Show a page of ``kind``; return (name, space, words or None, area in the frame)."""
    if kind == "html":
        studio.make(HTML)
        studio.frame.wait_for_function("document.readyState === 'complete'")
        return "page.html", "page-px", ("alpha", "delta"), (30, 30, 400, 100)
    if kind == "markdown":
        show_markdown(studio, DOC)
        box = md_box(studio, "main.markdown p")
        return "notes.md", "page-px", ("beta", "delta"), (box["x"], box["y"], 400, 60)
    if kind == "pdf":
        open_doc(studio)
        go(studio, 1)
        x, y = pt(studio, 1, 56, 330)
        return (
            "doc.pdf",
            "pdf-pt",
            ("Line 3 of page 1", "Line 3 of page 1: the quick"),
            (x, y, 400, 60),
        )
    show_picture(studio)
    full_size(studio)
    x, y = at(studio, 900, 700)
    return "pic.png", "image-px", None, (x, y, 200, 100)


@pytest.mark.parametrize("kind", ["html", "markdown", "pdf", "picture"])
def test_view_07_the_four_kinds_work_the_same_on_html_markdown_pdf_and_picture(
    studio, kind
) -> None:  # noqa: ANN001
    name, space, words, (x, y, w, h) = prepare(studio, kind)
    expected = []
    if words:
        pick(studio, "text")
        select_words(studio, *words)
        what(studio)
        save(studio, "text")
        expected.append("text")
    pick(studio, "point")
    studio.page.mouse.click(studio.origin()[0] + x + 20, studio.origin()[1] + y + 15)
    what(studio)
    save(studio, "point")
    pick(studio, "rect")
    drag(studio, (x + 5, y + 2), (x + 105, y + 40))
    what(studio)
    save(studio, "rect")
    pick(studio, "lasso")
    mouse_path(studio, [(x + 5, y + 2), (x + 90, y + 2), (x + 50, y + 45)])
    what(studio)
    save(studio, "lasso")
    expected += ["point", "rect", "lasso"]

    saved = comments_of(studio, name)
    assert [c["kind"] for c in saved] == expected
    assert {c["anchor"]["space"] for c in saved} == {space}
    assert all(c["target"]["selector"] for c in saved)
    assert all(c["lost"] is False for c in saved)
    for index, comment in enumerate(saved):
        assert comment["picture_error"] is None and comment["picture"], comment["kind"]
        width, height, _ = saved_picture(studio, name, index)
        assert width > 20 and height > 20
    assert set(wait_marks(studio, set(range(1, len(saved) + 1)))) == {
        str(n) for n in range(1, len(saved) + 1)
    }
    if kind == "pdf":
        assert [c["anchor"]["p"] for c in saved[1:]] == [1, 1, 1]
        assert saved[0]["anchor"]["rects"][0]["p"] == 1


def test_view_07_a_pdf_marker_stays_on_its_words_at_another_zoom(studio) -> None:  # noqa: ANN001
    open_doc(studio)
    go(studio, 2)
    text_on_page(studio, "Line 5 of page 2", "Line 5 of page 2: the quick brown")
    comment_mode(studio, False)
    click(studio.owner, "Zoom in")
    click(studio.owner, "Zoom in")
    settle(studio.owner)
    go(studio, 2)
    settled(studio)
    spot = item_spot(studio, "Line 5 of page 2")
    found = wait_marks(studio, {1})["1"]
    assert found["y"] == pytest.approx(spot["y"], abs=3)
    assert found["x"] == pytest.approx(spot["x"], abs=3)
