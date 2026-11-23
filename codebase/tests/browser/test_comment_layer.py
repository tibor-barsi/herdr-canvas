"""Comment mode, rectangle, box, marker and picture (M21 P21.3).

COM-01, COM-03, COM-15, SES-11 (changed) are owned here; COM-02, COM-05, COM-06,
COM-12, COM-13, ANC-03, COM-18 and SEC-09 are slices: rectangle comments on HTML
pages (``# slice of COM-xx, closed in P2x.y``).
"""

from __future__ import annotations

import json

import pytest

from helpers import decode_png

from .support import SCROLL_PAGE, block, until

pytestmark = pytest.mark.browser

BUTTONS = {"buttons": [{"id": "go", "label": "Go"}]}

# Counts clicks that reach page scripts; a long page that scrolls.
CLICK_PAGE = (
    "<script>window.__clicks = 0;"
    "window.addEventListener('click', () => window.__clicks++, true);</script>"
    + block("canvas-buttons", "ctl", BUTTONS)
    + "<p id='plain' tabindex='0'>plain</p><input id='t' type='text'>"
    + "<div style='height:2400px'></div>"
)

# Known colours at known page coordinates: a red block at x 300..500, y 1100..1200.
PICTURE_PAGE = """<!doctype html><html><head><style>
body { margin: 0; background: #ffffff; }
#red { position: absolute; left: 300px; top: 1100px; width: 200px; height: 100px;
       background: rgb(229, 72, 77); }
#tall { height: 2600px; }
</style></head><body><div id="tall"></div><div id="red"></div></body></html>"""


def near(pixel, colour, tolerance: int = 12) -> bool:  # noqa: ANN001
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


def comment_file(studio) -> dict:  # noqa: ANN001
    path = studio.folder / ".comments" / "page.html.json"
    return json.loads(path.read_text()) if path.exists() else {"comments": []}


def comment_mode(studio, on: bool = True) -> None:  # noqa: ANN001
    """Press ``C`` in the shell until comment mode is as wanted."""
    if studio.page.evaluate("document.body.classList.contains('commenting')") != on:
        studio.page.locator("body").press("c")
    studio.page.wait_for_function(
        f"document.body.classList.contains('commenting') === {str(on).lower()}"
    )
    studio.frame.wait_for_function(
        f"document.documentElement.hasAttribute('data-ac-commenting') "
        f"=== {str(on).lower()}"
    )
    if on:
        # The helper swallows the page's pointer events from the attribute on, but
        # the layer that turns them into a comment loads only after the message.
        studio.frame.wait_for_function("!!window.agentCanvas.commentLayer")


def drag(studio, start, end, steps: int = 6) -> None:  # noqa: ANN001
    """Drag in frame coordinates, as the owner does."""
    left, top = studio.origin()
    mouse = studio.page.mouse
    mouse.move(left + start[0], top + start[1])
    mouse.down()
    mouse.move(left + end[0], top + end[1], steps=steps)
    mouse.up()


def write_comment(studio, start, end, text: str, enter: bool = True) -> None:  # noqa: ANN001
    drag(studio, start, end)
    studio.page.wait_for_selector(".cbox textarea")
    studio.page.fill(".cbox textarea", text)
    if enter:
        studio.page.press(".cbox textarea", "Enter")


def box_count(studio) -> int:  # noqa: ANN001
    return studio.page.locator(".cbox").count()


def marker(studio, n: int):  # noqa: ANN001, ANN201
    return studio.frame.locator(f'[data-ac-comment-host] .box[data-n="{n}"]')


def wait_saved(studio, count: int) -> None:  # noqa: ANN001
    studio.page.wait_for_function(
        f"document.querySelectorAll('#comment-panel .ent').length >= {count}"
    )
    studio.page.wait_for_selector(".cbox", state="detached")


# ---- COM-01: the toggle, the keys and what the page does not get ---------------------


def test_com_01_c_in_a_text_field_does_not_toggle_but_c_in_the_frame_does(
    studio,
) -> None:
    studio.make(CLICK_PAGE)
    studio.frame.evaluate("document.getElementById('t').focus()")
    studio.page.keyboard.type("c")
    assert studio.frame.locator("#t").input_value() == "c"
    assert not studio.page.evaluate("document.body.classList.contains('commenting')")
    studio.frame.evaluate("document.getElementById('t').blur()")
    studio.frame.evaluate("document.getElementById('plain').focus()")
    studio.page.keyboard.press("c")  # forwarded by the helper from inside the frame
    studio.page.wait_for_function("document.body.classList.contains('commenting')")


def test_com_01_esc_without_a_box_leaves_the_mode(studio) -> None:
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_function("!document.body.classList.contains('commenting')")
    comment_mode(studio)
    studio.frame.evaluate("document.getElementById('plain').focus()")
    studio.page.keyboard.press("Escape")  # forwarded from the frame as well
    studio.page.wait_for_function("!document.body.classList.contains('commenting')")


def test_com_01_in_comment_mode_page_input_is_stopped_before_page_scripts_see_it(
    studio,
) -> None:
    sid = studio.make(CLICK_PAGE)
    button = studio.frame.locator("canvas-buttons button")
    comment_mode(studio)
    button.click()
    button.click(click_count=2)
    studio.page.wait_for_timeout(300)
    assert studio.frame.evaluate("window.__clicks") == 0
    assert studio.events(sid) == []
    assert studio.page.evaluate(f"window.__drafts['{sid}'].actions") == []
    # Positive control: with the mode off the same click reaches the page.
    comment_mode(studio, False)
    button.click()
    studio.wait_events(sid, 1)
    assert studio.frame.evaluate("window.__clicks") >= 1
    assert len(studio.page.evaluate(f"window.__drafts['{sid}'].actions")) >= 1


def test_com_01_the_wheel_still_scrolls_the_page_in_comment_mode(studio) -> None:
    studio.make(CLICK_PAGE)
    comment_mode(studio)
    left, top = studio.origin()
    studio.page.mouse.move(left + 200, top + 200)
    studio.page.mouse.wheel(0, 300)
    studio.frame.wait_for_function("window.scrollY > 100")


# ---- COM-02 (slice): the rectangle gesture -------------------------------------------


def test_com_02_a_3_px_drag_opens_nothing_and_a_4_px_drag_opens_the_box(studio) -> None:
    # slice of COM-02, closed in P22.2 (the other kinds)
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    drag(studio, (200, 200), (203, 203))
    drag(studio, (200, 200), (204, 190))  # 4 px across, 10 px up
    until(studio.page, lambda: box_count(studio) == 1)
    assert "Rectangle" in studio.page.locator(".cbox .what").inner_text()
    studio.page.keyboard.press("Escape")
    drag(studio, (200, 200), (200, 260))  # no width
    studio.page.wait_for_timeout(200)
    assert box_count(studio) == 0


def test_com_01_a_drag_right_after_c_gives_a_box_although_the_layer_loads_late(
    studio,
) -> None:
    """The mode shows (attribute set) only once the layer can take the drag."""

    def slow(route) -> None:  # noqa: ANN001
        studio.page.wait_for_timeout(700)
        route.continue_()

    studio.page.context.route("**/static/comments-layer.js*", slow)
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    drag(studio, (200, 200), (300, 260))
    studio.page.wait_for_selector(".cbox textarea", timeout=3000)
    assert box_count(studio) == 1


def test_com_02_r_picks_the_rectangle_in_comment_mode_and_is_ignored_outside_it(
    studio,
) -> None:
    # slice of COM-02, closed in P22.2
    studio.make(CLICK_PAGE)
    studio.frame.evaluate("document.getElementById('plain').focus()")
    studio.frame.evaluate(
        "window.__keys = []; "
        "window.addEventListener('keydown', e => __keys.push(e.key))"
    )
    studio.page.keyboard.press("r")
    assert studio.frame.evaluate("window.__keys") == ["r"]  # reaches the page
    assert not studio.page.evaluate("document.body.classList.contains('commenting')")
    comment_mode(studio)
    studio.page.keyboard.press("r")
    studio.frame.wait_for_function(
        "document.documentElement.getAttribute('data-ac-commenting') === 'rect'"
    )


# ---- COM-03: the box -----------------------------------------------------------------


def test_com_03_enter_saves_shift_enter_adds_a_line_empty_enter_saves_nothing(
    studio,
) -> None:
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    drag(studio, (150, 120), (260, 200))
    studio.page.wait_for_selector(".cbox textarea")
    assert studio.page.evaluate("document.activeElement.tagName") == "TEXTAREA"
    studio.page.keyboard.press("Enter")  # empty: nothing happens
    studio.page.wait_for_timeout(300)
    assert box_count(studio) == 1 and comment_file(studio)["comments"] == []
    studio.page.keyboard.type("first line")
    studio.page.keyboard.press("Shift+Enter")
    studio.page.keyboard.type("second line")
    studio.page.keyboard.press("Enter")
    wait_saved(studio, 1)
    [saved] = comment_file(studio)["comments"]
    assert saved["text"] == "first line\nsecond line" and saved["n"] == 1
    assert studio.page.evaluate("document.body.classList.contains('commenting')")


def test_com_03_esc_closes_only_the_box_the_other_comments_and_the_mode_stay(
    studio,
) -> None:
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    write_comment(studio, (120, 100), (220, 160), "one")
    wait_saved(studio, 1)
    write_comment(studio, (260, 100), (360, 160), "two")
    wait_saved(studio, 2)
    drag(studio, (400, 100), (500, 160))
    studio.page.wait_for_selector(".cbox textarea")
    studio.page.keyboard.type("never stored")
    studio.page.keyboard.press("Escape")
    studio.page.wait_for_selector(".cbox", state="detached")
    studio.page.wait_for_timeout(300)
    assert [c["n"] for c in comment_file(studio)["comments"]] == [1, 2]
    assert studio.page.locator("#comment-panel .ent").count() == 2
    assert marker(studio, 1).count() == 1 and marker(studio, 2).count() == 1
    assert studio.frame.locator("[data-ac-comment-host] .box.temp").count() == 0
    assert studio.page.evaluate("document.body.classList.contains('commenting')")
    studio.page.keyboard.press("Escape")  # no box: now the mode ends
    studio.page.wait_for_function("!document.body.classList.contains('commenting')")


def test_com_03_the_box_is_headed_by_number_kind_and_target_and_lies_inside_the_frame(
    studio,
) -> None:
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    area = studio.page.locator("main").bounding_box()
    width, height = area["width"], area["height"]
    corners = {
        "top-left": ((6, 6), (40, 40)),
        "top-right": ((width - 40, 6), (width - 6, 40)),
        "bottom-left": ((6, height - 40), (40, height - 6)),
        "bottom-right": ((width - 40, height - 40), (width - 6, height - 6)),
    }
    for name, (start, end) in corners.items():
        drag(studio, start, end)
        studio.page.wait_for_selector(".cbox textarea")
        box = studio.page.locator(".cbox").bounding_box()
        assert box["x"] >= area["x"] and box["y"] >= area["y"], name
        assert box["x"] + box["width"] <= area["x"] + area["width"] + 0.5, name
        assert box["y"] + box["height"] <= area["y"] + area["height"] + 0.5, name
        head = studio.page.locator(".cbox .h").inner_text()
        assert "#1" in head and "Rectangle" in head, head
        studio.page.keyboard.press("Escape")
        studio.page.wait_for_selector(".cbox", state="detached")


def test_com_03_the_box_next_to_a_shape_in_the_middle_stands_beside_it(studio) -> None:
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    drag(studio, (150, 200), (260, 280))
    studio.page.wait_for_selector(".cbox textarea")
    box = studio.page.locator(".cbox").bounding_box()
    left, top = studio.origin()
    assert box["x"] >= left + 260  # right of the shape, not on it
    assert studio.page.locator(".cbox button.primary").inner_text() == "Save"
    assert "Enter" in studio.page.locator(".cbox .keys").inner_text()


# ---- COM-15 (and COM-18): the text never enters the frame ----------------------------

RECORDER = (
    "window.__rec = []; window.addEventListener('message', "
    "(e) => window.__rec.push(JSON.stringify(e.data)));"
)


def test_com_15_no_message_to_the_frame_ever_carries_the_comment_text(studio) -> None:
    studio.make(SCROLL_PAGE)
    studio.frame.evaluate(RECORDER)
    comment_mode(studio)
    secret = "SECRET-units-missing-q7"
    write_comment(studio, (120, 100), (260, 180), secret)
    wait_saved(studio, 1)
    until(
        studio.page,
        lambda: all(
            any(kind in r for r in studio.frame.evaluate("window.__rec"))
            for kind in ('"comment-markers"', '"comment-mode"')
        ),
    )
    studio.page.wait_for_timeout(300)  # a leak of the text, if any, has arrived
    records = studio.frame.evaluate("window.__rec")
    assert any('"comment-markers"' in r for r in records), records  # not a vacuous pass
    assert any('"comment-mode"' in r for r in records)
    assert not [r for r in records if "SECRET" in r], records
    markers = [json.loads(r) for r in records if '"comment-markers"' in r]
    assert markers[-1]["markers"][0]["n"] == 1
    assert markers[-1]["markers"][0]["status"] == "draft"
    assert comment_file(studio)["comments"][0]["text"] == secret  # it did reach the hub


# ---- COM-05, COM-13, ANC-03 (slices): markers and anchors ----------------------------


def all_rects(studio) -> list:  # noqa: ANN001
    return studio.frame.evaluate(
        "Array.from(document.body.querySelectorAll('*')).map((e) => {"
        " const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })"
    )


def test_com_05_a_rectangle_marker_is_dashed_while_draft_and_moves_no_element(
    studio,
) -> None:
    # slice of COM-05, closed in P22.3 (the other kinds, the other statuses)
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    write_comment(studio, (300, 100), (380, 180), "first")
    wait_saved(studio, 1)  # the panel opens and narrows the frame: measure after it
    before = all_rects(studio)
    write_comment(studio, (120, 100), (260, 180), "units?")
    wait_saved(studio, 2)
    assert all_rects(studio) == before  # the layer changes no element's position
    box = marker(studio, 2)
    box.wait_for()
    assert (
        studio.frame.evaluate(
            "getComputedStyle(document.querySelector('[data-ac-comment-host]').shadowRoot"
            ".querySelector('.box[data-n=\"1\"]')).borderStyle"
        )
        == "dashed"
    )
    assert marker(studio, 1).locator(".badge").inner_text() == "1"
    # One host, a child of <html> after <body>, not taking pointer input.
    assert studio.frame.evaluate(
        "(() => { const h = document.querySelectorAll('[data-ac-comment-host]');"
        " return [h.length, h[0].parentNode === document.documentElement,"
        " h[0].previousElementSibling === document.body,"
        " getComputedStyle(h[0]).pointerEvents]; })()"
    ) == [1, True, True, "none"]


def test_com_13_the_anchor_is_in_page_coordinates_and_the_marker_follows_a_scroll(
    studio,
) -> None:
    # slice of COM-13, closed in P22.2 (resize and the other kinds)
    studio.make(SCROLL_PAGE)
    comment_mode(studio)
    studio.frame.evaluate("window.scrollTo(0, 340)")
    studio.frame.wait_for_function("window.scrollY === 340")
    write_comment(studio, (100, 60), (300, 180), "scrolled")  # the teal target
    wait_saved(studio, 1)
    anchor = comment_file(studio)["comments"][0]["anchor"]
    assert anchor["space"] == "page-px"
    assert (anchor["x"], anchor["y"], anchor["w"], anchor["h"]) == (100, 400, 200, 120)
    before = marker(studio, 1).bounding_box()
    studio.frame.evaluate("window.scrollTo(0, 940)")  # 600 px further
    studio.frame.wait_for_function("window.scrollY === 940")
    after = marker(studio, 1).bounding_box()
    assert (
        abs(before["y"] - after["y"] - 600) <= 1 and abs(before["x"] - after["x"]) <= 1
    )
    teal = studio.frame.locator("#target").bounding_box()
    assert (
        abs(after["y"] - teal["y"]) <= 1 and abs(after["height"] - teal["height"]) <= 1
    )


def test_anc_03_a_rectangle_anchor_has_target_fractions_and_text_inside(studio) -> None:
    # slice of ANC-03, closed in P22.2 (the viewers' coordinate spaces)
    page = (
        "<style>body{margin:0;font:16px/24px sans-serif}"
        "#a{position:absolute;left:40px;top:50px;width:400px}</style>"
        "<div id='a'><p>alpha beta</p><p>gamma delta</p><p>far below</p></div>"
        "<div style='height:1500px'></div>"
    )
    studio.make(page)
    comment_mode(studio)
    drag(studio, (50, 55), (200, 125))  # the first two paragraphs' lines
    studio.page.wait_for_selector(".cbox textarea")
    studio.page.fill(".cbox textarea", "units")
    studio.page.keyboard.press("Enter")
    wait_saved(studio, 1)
    [saved] = comment_file(studio)["comments"]
    anchor = saved["anchor"]
    assert saved["kind"] == "rect"
    assert (anchor["x"], anchor["y"], anchor["w"], anchor["h"]) == (50, 55, 150, 70)
    box = studio.frame.evaluate(
        "(() => { const r = document.getElementById('a').getBoundingClientRect();"
        " return {x: r.x, y: r.y, width: r.width, height: r.height}; })()"
    )
    assert saved["target"]["selector"] == "#a"
    assert anchor["fx"] == pytest.approx((50 - box["x"]) / box["width"], abs=1e-3)
    assert anchor["fy"] == pytest.approx((55 - box["y"]) / box["height"], abs=1e-3)
    assert anchor["fw"] == pytest.approx(150 / box["width"], abs=1e-3)
    assert anchor["fh"] == pytest.approx(70 / box["height"], abs=1e-3)
    assert saved["text_inside"] == "alpha beta gamma delta"
    assert "far below" not in saved["text_inside"]


def test_com_05_the_host_is_kept_once_by_a_morph_that_replaces_the_body(studio) -> None:
    # slice of COM-05, closed in P22.3
    first = (
        "<body class='v1'><h1 id='v1'>one</h1><div style='height:1500px'></div></body>"
    )
    studio.make(first)
    comment_mode(studio)
    write_comment(studio, (100, 100), (200, 160), "kept")
    wait_saved(studio, 1)
    studio.frame.evaluate(
        "window.__host = document.querySelector('[data-ac-comment-host]');"
        "window.__morphs = 0;"
        "document.addEventListener('agentcanvas:updated', () => window.__morphs++)"
    )
    second = (
        "<body class='v2'><h1 id='v2'>two, replaced</h1><p>new</p>"
        "<div style='height:1500px'></div></body>"
    )
    (studio.folder / "page.html").write_text(second)
    studio.frame.wait_for_function("window.__morphs >= 1")
    assert studio.frame.evaluate("document.body.className") == "v2"
    studio.frame.wait_for_function(
        "document.querySelectorAll('[data-ac-comment-host]').length === 1"
    )
    assert studio.frame.evaluate(
        "document.querySelector('[data-ac-comment-host]') === window.__host"
    )
    assert studio.frame.locator("[data-ac-comment-host] .box").count() == 1
    assert (
        studio.frame.evaluate("document.body.querySelector('[data-ac-comment-host]')")
        is None
    )


# ---- COM-06 (slice): the plain entry list --------------------------------------------


def test_com_06_the_panel_lists_entries_with_chip_and_buttons_and_deletes_a_draft(
    studio,
) -> None:
    # slice of COM-06, closed in P22.4 (filters by status, replies, lost, strip rules)
    sid = studio.make(SCROLL_PAGE)
    comment_mode(studio)
    write_comment(studio, (120, 100), (260, 180), "first")
    wait_saved(studio, 1)
    assert studio.page.locator("#comment-panel .ph").inner_text().startswith("Comments")
    write_comment(studio, (300, 100), (380, 180), "second")
    wait_saved(studio, 2)
    entries = studio.page.locator("#comment-panel .ent")
    assert [e.locator(".cn").inner_text() for e in entries.all()] == ["1", "2"]
    first = entries.nth(0)
    assert first.locator(".chip").inner_text() == "draft"
    assert first.locator(".tx").inner_text() == "first"
    assert first.locator("button").all_inner_texts() == ["Edit", "Delete"]
    assert [b.inner_text() for b in studio.page.locator(".filters button").all()] == [
        "Open 2",
        "Done 0",
        "All 2",
    ]
    first.locator("button", has_text="Delete").click()
    studio.page.wait_for_function(
        "document.querySelectorAll('#comment-panel .ent').length === 1"
    )
    marker(studio, 1).wait_for(state="detached")
    assert [c["n"] for c in comment_file(studio)["comments"]] == [2]
    # A reload of the window keeps the draft (COM-04) and numbers go on from 3.
    studio.page.reload()
    studio.page.wait_for_selector(f'.hv-pill[data-session="{sid}"]')
    studio.owner.visit(sid)
    studio.page.wait_for_selector("#comment-panel .ent")
    comment_mode(studio)
    studio.frame.wait_for_function(
        "Boolean(window.agentCanvas && window.agentCanvas.commentLayer)"
    )
    drag(studio, (120, 100), (260, 180))
    studio.page.wait_for_selector(".cbox textarea")
    assert "#3" in studio.page.locator(".cbox .h").inner_text()


# ---- COM-12 (slice): the picture -----------------------------------------------------


def test_com_12_a_200_by_100_rectangle_at_scroll_900_gives_a_232_by_132_picture(
    studio,
) -> None:
    # slice of COM-12, closed in P25.2 (text, point, lasso, PDF and pictures)
    studio.make(PICTURE_PAGE)
    studio.frame.evaluate("window.scrollTo(0, 900)")
    studio.frame.wait_for_function("window.scrollY === 900")
    comment_mode(studio)
    drag(studio, (300, 200), (500, 300))  # exactly the red block (page y 1100..1200)
    studio.page.wait_for_selector(".cbox textarea")
    studio.page.fill(".cbox textarea", "the red block")
    studio.page.keyboard.press("Enter")
    wait_saved(studio, 1)
    [saved] = comment_file(studio)["comments"]
    assert saved["picture_error"] is None
    assert saved["picture"] == ".comments/page.html.1.png"
    width, height, rows = decode_png((studio.folder / saved["picture"]).read_bytes())
    assert (width, height) == (232, 132)
    white = (255, 255, 255)
    red = (229, 72, 77)
    assert (
        near(rows[66][116], red)
        and near(rows[17][17], red)
        and near(rows[114][214], red)
    )
    assert (
        near(rows[10][116], white)
        and near(rows[66][8], white)
        and near(rows[120][116], white)
    )
    assert near(rows[14][14], white) and near(rows[117][217], white)


def test_com_12_a_failing_picture_saves_the_comment_with_the_reason(studio) -> None:
    studio.make(PICTURE_PAGE)
    studio.frame.evaluate("agentCanvas.captureFailure = 'snapdom exploded'")
    comment_mode(studio)
    write_comment(studio, (100, 100), (200, 180), "no picture")
    wait_saved(studio, 1)
    [saved] = comment_file(studio)["comments"]
    assert saved["picture"] is None
    assert "snapdom exploded" in saved["picture_error"]
    assert saved["text"] == "no picture"


def test_com_12_a_picture_that_takes_too_long_is_given_up_after_the_limit(
    studio,
) -> None:
    studio.make(PICTURE_PAGE)
    studio.page.evaluate("window.__pictureTimeoutMs = 400")
    studio.frame.evaluate("agentCanvas.captureHang = true")
    comment_mode(studio)
    write_comment(studio, (100, 100), (200, 180), "late")
    wait_saved(studio, 1)
    [saved] = comment_file(studio)["comments"]
    assert saved["picture"] is None and "timed out" in saved["picture_error"]


def test_com_12_the_send_screenshot_and_the_picture_show_no_marker(studio) -> None:
    sid = studio.make(PICTURE_PAGE)
    comment_mode(studio)
    write_comment(studio, (300, 200), (500, 300), "a marker")
    wait_saved(studio, 1)
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    _, _, rows = decode_png(studio.screenshot(event))
    # The marker's dashed outline is orange-red (194, 65, 12) and would sit at the
    # rectangle's top edge, page y 300..302 => none in the screenshot.
    orange = (194, 65, 12)
    assert not any(near(pixel, orange, 6) for row in rows for pixel in row[290:520:3])


# ---- COM-18, SEC-09: tokens and the message list -------------------------------------


def test_com_18_a_picture_with_another_token_is_dropped_and_logged(studio) -> None:
    # slice of COM-18, closed in P22.3 (lost reports)
    studio.make(PICTURE_PAGE)
    comment_mode(studio)
    drag(studio, (300, 200), (400, 260))
    studio.page.wait_for_selector(".cbox textarea")
    before = studio.page.evaluate("window.__guard.dropped.token")
    forged = (
        "{type: 'comment-picture', token: 'guessed', ok: true, "
        "png: 'data:image/png;base64,AAAA'}"
    )
    studio.frame.evaluate(f"window.parent.postMessage({forged}, '*')")
    studio.page.wait_for_function(f"window.__guard.dropped.token > {before}")
    studio.page.fill(".cbox textarea", "real picture")
    studio.page.keyboard.press("Enter")
    wait_saved(studio, 1)
    [saved] = comment_file(studio)["comments"]
    assert saved["picture"]  # the layer's own, not the forged one
    data = (studio.folder / saved["picture"]).read_bytes()
    assert data.startswith(b"\x89PNG") and len(data) > 100


def test_com_18_a_picture_without_an_open_box_is_dropped(studio) -> None:
    studio.make(SCROLL_PAGE)
    before = studio.page.evaluate("window.__guard.dropped.token")
    studio.frame.evaluate(
        "window.parent.postMessage({type: 'comment-picture', "
        "token: 'x', ok: false}, '*')"
    )
    studio.page.wait_for_function(f"window.__guard.dropped.token > {before}")


def test_sec_09_a_forged_selection_can_only_open_the_box_and_only_in_comment_mode(
    studio,
) -> None:
    # slice of SEC-09, closed in P22.3 (the other report types)
    studio.make(SCROLL_PAGE)
    selection = (
        "{type: 'comment-selection', kind: 'rect', rect: {x: 50, y: 50, w: 80, h: 60},"
        " anchor: {x: 50, y: 50, w: 80, h: 60, fx: 0, fy: 0, fw: 1, fh: 1},"
        " target: {canvas_id: null, selector: 'body', text: 'forged'}}"
    )
    studio.frame.evaluate(f"window.parent.postMessage({selection}, '*')")
    studio.page.wait_for_timeout(300)
    assert box_count(studio) == 0  # the mode is off: nothing opens
    comment_mode(studio)
    studio.frame.evaluate(f"window.parent.postMessage({selection}, '*')")
    studio.page.wait_for_selector(".cbox textarea")
    studio.page.wait_for_timeout(300)
    assert comment_file(studio)["comments"] == []  # only the owner's Enter saves
    # Message types the frame may not send are dropped.
    dropped = studio.page.evaluate("window.__guard.dropped.type")
    studio.frame.evaluate(
        "window.parent.postMessage({type: 'comment-markers', markers: []}, '*');"
        "window.parent.postMessage({type: 'comment-crop', token: 'x'}, '*')"
    )
    studio.page.wait_for_function(f"window.__guard.dropped.type >= {dropped + 2}")
