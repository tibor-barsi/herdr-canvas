"""Comments in the Markdown and picture viewers (M24 P24.4).

VIEW-06 is closed here (its comment vector). VIEW-07, VIEW-08, ANC-08 and COM-12 are
slices: their Markdown and picture vectors run here, PDF in P25.2. The viewers'
common interface (4.2) is ``window.acViewer``.
"""

# ruff: noqa: E501  (the scripts run in the frame are one-line strings)
from __future__ import annotations

import json
import struct
import time
import zlib

import pytest

from helpers import decode_png

from .support import call
from .test_comment_anchors import pick as pick_kind
from .test_comment_anchors import wait_marks
from .test_comment_kinds import mouse_path, select_words, what
from .test_comment_layer import comment_mode, drag, wait_saved
from .test_comment_panel import steady_layout

pytestmark = pytest.mark.browser

RED = (229, 72, 77)
WHITE = (255, 255, 255)
ORANGE = (194, 65, 12)


def rgb_png(width: int, height: int, blocks: list, background=WHITE) -> bytes:  # noqa: ANN001
    """A PNG of one background colour with ``(x0, y0, x1, y1, colour)`` blocks."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    rows = []
    for y in range(height):
        row = bytearray(bytes(background) * width)
        for x0, y0, x1, y1, colour in blocks:
            if y0 <= y < y1:
                row[x0 * 3 : x1 * 3] = bytes(colour) * (x1 - x0)
        rows.append(b"\x00" + bytes(row))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


BLOCK = [(900, 700, 1100, 800, RED)]
BIG = rgb_png(2000, 1500, BLOCK)
BIG_OTHER = rgb_png(2000, 1500, [(900, 700, 1100, 800, (20, 20, 220))])
SMALL = rgb_png(300, 300, [(100, 100, 200, 200, RED)])


def near(pixel, colour, tolerance: int = 12) -> bool:  # noqa: ANN001
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


def show_file(studio, name: str, data: bytes | str) -> str:  # noqa: ANN001
    """Open ``name`` as the shown page of a new session; return the session id."""
    sid = studio.make("<p>first</p>")
    raw = data.encode() if isinstance(data, str) else data
    (studio.folder / name).write_bytes(raw)
    call(
        studio.owner,
        "POST",
        f"/api/sessions/{sid}/show",
        json={"project": str(studio.tmp_path / "alpha"), "name": name},
    )
    studio.frame.wait_for_function("window.acViewer && window.acViewer.mounted")
    return sid


def show_picture(studio, data: bytes = BIG, name: str = "pic.png") -> str:  # noqa: ANN001
    sid = show_file(studio, name, data)
    studio.frame.wait_for_function("document.querySelector('img').complete")
    return sid


def show_markdown(studio, text: str, name: str = "notes.md") -> str:  # noqa: ANN001
    sid = show_file(studio, name, text)
    studio.frame.wait_for_selector("main.markdown")
    return sid


def comments_of(studio, name: str) -> list:  # noqa: ANN001
    path = studio.folder / ".comments" / f"{name}.json"
    return json.loads(path.read_text())["comments"] if path.exists() else []


def view(studio) -> dict:  # noqa: ANN001
    return studio.frame.evaluate("window.acImageView()")


def at(studio, u: float, v: float) -> tuple[float, float]:  # noqa: ANN001
    """Frame point of picture pixel (u, v) now."""
    state = view(studio)
    return state["x"] + u * state["scale"], state["y"] + v * state["scale"]


def full_size(studio) -> None:  # noqa: ANN001
    studio.frame.get_by_role("button", name="100 %", exact=True).click()
    studio.frame.wait_for_function("window.acImageView().scale === 1")


def settled(studio) -> None:  # noqa: ANN001
    """Wait until the frame keeps its size (the panel opens and narrows it)."""
    studio.page.wait_for_timeout(300)
    studio.frame.evaluate("new Promise(requestAnimationFrame)")


def pick(studio, kind: str) -> None:  # noqa: ANN001
    pick_kind(studio, kind)
    settled(studio)


def save(studio, text: str = "note") -> None:  # noqa: ANN001
    """Type into the open box and save it; wait until the panel lists it."""
    count = studio.page.locator("#comment-panel .ent").count() + 1
    studio.page.fill(".cbox textarea", text)
    studio.page.keyboard.press("Enter")
    wait_saved(studio, count)


def rect_on_picture(studio, box: tuple, text: str = "note") -> None:  # noqa: ANN001
    """Drag over picture pixels ``(u0, v0, u1, v1)`` and save the comment."""
    pick(studio, "rect")
    a, b = at(studio, box[0], box[1]), at(studio, box[2], box[3])
    drag(studio, a, b)
    what(studio)
    save(studio, text)


def hook_updates(studio) -> int:  # noqa: ANN001
    studio.frame.evaluate(
        "if (!window.__hooked) { window.__hooked = true; window.__updates = 0;"
        " document.addEventListener('agentcanvas:updated', () => window.__updates++); }"
    )
    return studio.frame.evaluate("window.__updates")


def rewrite(studio, name: str, data: bytes | str) -> None:  # noqa: ANN001
    """Write a new version and wait until the viewer has replaced its content."""
    seen = hook_updates(studio)
    raw = data.encode() if isinstance(data, str) else data
    (studio.folder / name).write_bytes(raw)
    studio.frame.wait_for_function(f"window.__updates > {seen}")


# ---- 4.2: one interface for the viewers ------------------------------------------------


def test_view_07_both_viewers_mount_and_return_their_text_root(studio) -> None:  # noqa: ANN001
    show_markdown(studio, "# Title\n\nsome words\n")
    script = """async () => {
      const holder = document.createElement('div');
      const url = location.pathname;
      const root = await window.acViewer.mount(holder, url);
      return [window.acViewer.kind, window.acViewer.space, root === holder.firstElementChild,
              root.tagName, root.textContent.includes('some words')];
    }"""
    assert studio.frame.evaluate(script) == ["markdown", "page-px", True, "MAIN", True]
    show_picture(studio, SMALL, "small.png")
    script = """async () => {
      const holder = document.createElement('div');
      const root = await window.acViewer.mount(holder, location.pathname);
      return [window.acViewer.kind, window.acViewer.space, root, holder.children.length];
    }"""
    assert studio.frame.evaluate(script) == ["image", "image-px", None, 2]


def test_view_07_a_picture_converts_between_frame_and_picture_pixels(studio) -> None:  # noqa: ANN001
    show_picture(studio)
    state = view(studio)
    script = """([cx, cy]) => {
      const u = window.acViewer.toSpace(cx, cy);
      const back = window.acViewer.fromSpace(u.x, u.y);
      return [u.x, u.y, back.x, back.y];
    }"""
    u, v, bx, by = studio.frame.evaluate(script, [state["x"] + 50, state["y"] + 80])
    assert (u, v) == (
        pytest.approx(50 / state["scale"]),
        pytest.approx(80 / state["scale"]),
    )
    assert (bx, by) == (pytest.approx(state["x"] + 50), pytest.approx(state["y"] + 80))


# ---- VIEW-06: the comment vector ----------------------------------------------------------


def test_view_06_a_comment_made_at_100_percent_stays_on_the_same_image_pixels_at_fit(
    studio,
) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    rect_on_picture(studio, (900, 700, 1100, 800))
    [stored_comment] = comments_of(studio, "pic.png")
    anchor = stored_comment["anchor"]
    assert anchor["space"] == "image-px" and (anchor["nw"], anchor["nh"]) == (
        2000,
        1500,
    )
    assert anchor["x"] == pytest.approx(900, abs=1) and anchor["w"] == pytest.approx(
        200, abs=1
    )
    assert anchor["y"] == pytest.approx(700, abs=1) and anchor["h"] == pytest.approx(
        100, abs=1
    )
    comment_mode(studio, False)
    studio.frame.get_by_role("button", name="Fit", exact=True).click()
    studio.frame.wait_for_function("window.acImageView().scale < 0.9")
    settled(studio)
    state = view(studio)
    found = wait_marks(studio, {1})["1"]
    assert found["x"] == pytest.approx(
        state["x"] + anchor["x"] * state["scale"], abs=1.5
    )
    assert found["y"] == pytest.approx(
        state["y"] + anchor["y"] * state["scale"], abs=1.5
    )
    width = studio.frame.evaluate(
        "document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelector('[data-n]').getBoundingClientRect().width"
    )
    assert width == pytest.approx(anchor["w"] * state["scale"], abs=1.5)


def test_view_06_markers_follow_the_zoom_around_the_pointer_and_the_scroll(
    studio,
) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    rect_on_picture(studio, (900, 700, 1100, 800))
    anchor = comments_of(studio, "pic.png")[0]["anchor"]
    pick(studio, "rect")
    left, top = studio.origin()
    px, py = at(studio, 1000, 750)
    studio.page.mouse.move(left + px, top + py)
    studio.page.keyboard.down("Control")
    studio.page.mouse.wheel(0, -300)
    studio.page.keyboard.up("Control")
    studio.frame.wait_for_function("window.acImageView().scale > 1.2")
    settled(studio)
    state = view(studio)
    found = wait_marks(studio, {1})["1"]
    assert found["x"] == pytest.approx(
        state["x"] + anchor["x"] * state["scale"], abs=1.5
    )
    assert found["y"] == pytest.approx(
        state["y"] + anchor["y"] * state["scale"], abs=1.5
    )
    studio.frame.evaluate("document.querySelector('[data-scroller]').scrollBy(30, 20)")
    settled(studio)
    state = view(studio)
    found = wait_marks(studio, {1})["1"]
    assert found["x"] == pytest.approx(
        state["x"] + anchor["x"] * state["scale"], abs=1.5
    )
    assert found["y"] == pytest.approx(
        state["y"] + anchor["y"] * state["scale"], abs=1.5
    )


# ---- VIEW-07: the four kinds on a picture -------------------------------------------------


def test_view_07_point_rectangle_and_lasso_on_a_picture_keep_their_image_pixels(
    studio,
) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    pick(studio, "point")
    studio.page.mouse.click(
        *[sum(p) for p in zip(studio.origin(), at(studio, 950, 720), strict=True)]
    )
    what(studio)
    save(studio, "point")
    rect_on_picture(studio, (900, 700, 1100, 800), "rect")
    pick(studio, "lasso")
    path = [at(studio, 920, 720), at(studio, 1000, 720), at(studio, 960, 790)]
    mouse_path(studio, path)
    what(studio)
    save(studio, "lasso")
    point, rect, lasso = (c["anchor"] for c in comments_of(studio, "pic.png"))
    assert point["space"] == rect["space"] == lasso["space"] == "image-px"
    assert (point["x"], point["y"]) == (
        pytest.approx(950, abs=1),
        pytest.approx(720, abs=1),
    )
    assert "fx" not in point and "fx" not in rect
    assert len(lasso["points"]) == 3
    assert lasso["points"][0] == [pytest.approx(920, abs=1), pytest.approx(720, abs=1)]
    assert lasso["bbox"]["w"] == pytest.approx(80, abs=2)
    assert all(c["target"]["selector"] for c in comments_of(studio, "pic.png"))
    assert all(c["text_inside"] is None for c in comments_of(studio, "pic.png"))
    assert set(wait_marks(studio, {1, 2, 3})) == {"1", "2", "3"}


def test_view_07_a_gesture_outside_the_picture_selects_nothing_and_text_mode_finds_none(
    studio,
) -> None:  # noqa: ANN001
    show_picture(studio, SMALL, "small.png")
    pick(studio, "point")
    state = view(studio)
    studio.page.mouse.click(
        *[sum(p) for p in zip(studio.origin(), (state["x"] - 40, 30), strict=True)]
    )
    studio.page.wait_for_timeout(300)
    assert studio.page.locator(".cbox").count() == 0
    pick(studio, "text")
    drag(
        studio, (state["x"] + 10, state["y"] + 10), (state["x"] + 200, state["y"] + 200)
    )
    studio.page.wait_for_timeout(300)
    assert studio.page.locator(".cbox").count() == 0


# ---- ANC-08: a picture of another size loses all its comments -------------------------------


def test_anc_08_a_picture_with_another_natural_size_loses_all_its_comments(
    studio,
) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    rect_on_picture(studio, (900, 700, 1100, 800), "one")
    pick(studio, "point")
    studio.page.mouse.click(
        *[sum(p) for p in zip(studio.origin(), at(studio, 950, 720), strict=True)]
    )
    what(studio)
    save(studio, "two")
    wait_marks(studio, {1, 2})
    settled(studio)  # a report timer from saving the comments has run out
    watch_lost_reports(studio)
    rewrite(studio, "pic.png", BIG_OTHER)  # same size, other content
    # The layer's report timer runs once the new version is mounted and stays quiet.
    studio.frame.wait_for_function("window.__lostChecks > 0")
    assert lost_posts(studio) == 0
    assert [c["lost"] for c in comments_of(studio, "pic.png")] == [False, False]
    wait_marks(studio, {1, 2})
    rewrite(studio, "pic.png", SMALL)
    wait_marks_none(studio)
    wait_lost(studio, [True, True])
    # Positive control: the same spy does see a report when there is one.
    assert lost_posts(studio) == 1
    rewrite(studio, "pic.png", BIG)
    wait_lost(studio, [False, False])
    wait_marks(studio, {1, 2})


def watch_lost_reports(studio) -> None:  # noqa: ANN001
    """Count, in the shell, the lost reports the frame posts."""
    studio.page.evaluate(
        """() => {
      window.__lostPosts = 0;
      window.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'comment-lost') window.__lostPosts++;
      });
    }"""
    )
    studio.frame.evaluate(
        """() => {
      window.__lostChecks = 0;
      const timer = window.setTimeout.bind(window);
      window.setTimeout = (fn, ms, ...rest) => ms !== 300 ? timer(fn, ms, ...rest) : timer(() => {
        fn(...rest);
        if (document.readyState === 'complete' && window.acViewer.mounted) window.__lostChecks++;
      }, ms);
    }"""
    )


def lost_posts(studio) -> int:  # noqa: ANN001
    return studio.page.evaluate("window.__lostPosts")


def wait_marks_none(studio) -> None:  # noqa: ANN001
    studio.frame.wait_for_function(
        "(() => { const h = document.querySelector('[data-ac-comment-host]');"
        " return !h || h.shadowRoot.querySelectorAll('[data-n]').length === 0; })()"
    )


def wait_lost(studio, expected: list, name: str = "pic.png") -> None:  # noqa: ANN001
    end = time.monotonic() + 8
    while time.monotonic() < end:
        if [c["lost"] for c in comments_of(studio, name)] == expected:
            return
        studio.page.wait_for_timeout(50)
    assert [c["lost"] for c in comments_of(studio, name)] == expected


# ---- VIEW-08: the reading place -------------------------------------------------------------


def test_view_08_a_new_picture_version_keeps_zoom_and_centre(studio) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    studio.frame.evaluate(
        "document.querySelector('[data-scroller]').scrollTo(700, 500)"
    )
    settled(studio)
    studio.frame.evaluate("window.__same = document.querySelector('[data-scroller]')")
    before = view(studio)
    centre = studio.frame.evaluate(
        "(() => { const u = window.acViewer.toSpace(innerWidth / 2, innerHeight / 2);"
        " return [u.x, u.y]; })()"
    )
    rewrite(studio, "pic.png", BIG_OTHER)
    studio.frame.wait_for_function("document.querySelector('img').complete")
    after = view(studio)
    assert after["scale"] == before["scale"] == 1
    now = studio.frame.evaluate(
        "(() => { const u = window.acViewer.toSpace(innerWidth / 2, innerHeight / 2);"
        " return [u.x, u.y]; })()"
    )
    assert now == [pytest.approx(centre[0], abs=1), pytest.approx(centre[1], abs=1)]
    assert studio.frame.evaluate(
        "window.__same === document.querySelector('[data-scroller]')"
    )


def test_view_08_two_quick_picture_updates_both_finish_on_the_latest(studio) -> None:  # noqa: ANN001
    """F7: the first update's promise (its "updated" report) is not lost."""
    show_picture(studio)
    (studio.folder / "pic.png").write_bytes(BIG_OTHER)
    script = """async () => {
      const done = [];
      const first = window.acViewer.update({version: 2}).then(() => done.push('first'));
      const second = window.acViewer.update({version: 3}).then(() => done.push('second'));
      const late = new Promise((resolve) => setTimeout(() => resolve('late'), 30000));
      const outcome = await Promise.race([Promise.all([first, second]).then(() => 'both'), late]);
      return [outcome, done, document.querySelector('img').src];
    }"""
    outcome, done, src = studio.frame.evaluate(script)
    assert (outcome, sorted(done)) == ("both", ["first", "second"])
    assert src.endswith("t=3")


def test_view_08_a_picture_of_another_size_starts_at_fit(studio) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    rewrite(studio, "pic.png", rgb_png(1600, 1200, []))
    studio.frame.wait_for_function("window.acImageView().width === 1600")
    assert view(studio)["scale"] < 1


def test_view_08_a_new_markdown_version_is_morphed_and_keeps_the_reading_place(
    studio,
) -> None:  # noqa: ANN001
    paragraphs = [
        f"Paragraph {i} " + "lorem ipsum dolor sit amet " * 8 for i in range(60)
    ]
    show_markdown(studio, "# Title\n\n" + "\n\n".join(paragraphs) + "\n")
    studio.frame.evaluate(
        "window.scrollTo(0, 1500); window.__flag = 'kept';"
        " window.__node = document.querySelectorAll('main.markdown p')[30]"
    )
    studio.frame.wait_for_function("window.scrollY === 1500")
    paragraphs[30] = "Paragraph 30 CHANGED " + "lorem ipsum dolor sit amet " * 8
    rewrite(studio, "notes.md", "# Title\n\n" + "\n\n".join(paragraphs) + "\n")
    assert studio.frame.evaluate("window.__flag") == "kept"
    assert studio.frame.evaluate("window.scrollY") == 1500
    assert studio.frame.evaluate(
        "window.__node.isConnected && window.__node.textContent.includes('CHANGED')"
    )


# ---- VIEW-07, ANC-08: the four kinds and finding them again in Markdown -----------------------

DOC = (
    "# Beams\n\nFirst paragraph about nothing in particular.\n\n"
    "A short note: alpha beta gamma delta epsilon.\n\n"
    "Third paragraph with `code` and more words to read.\n\n"
    + "\n\n".join(f"Filler paragraph number {i} with some words." for i in range(30))
    + "\n"
)


def md_box(studio, selector: str) -> dict:  # noqa: ANN001
    return studio.frame.evaluate(
        "(s) => { const e = document.querySelectorAll(s)[0]; e.scrollIntoView({block: 'center'});"
        " const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }",
        selector,
    )


def test_view_07_the_four_kinds_on_markdown_have_page_px_anchors_and_markers(
    studio,
) -> None:  # noqa: ANN001
    show_markdown(studio, DOC)
    pick(studio, "text")
    select_words(studio, "beta", "delta")
    what(studio)
    save(studio, "text")
    box = md_box(studio, "main.markdown p")
    pick(studio, "point")
    studio.page.mouse.click(
        studio.origin()[0] + box["x"] + 20, studio.origin()[1] + box["y"] + 10
    )
    what(studio)
    save(studio, "point")
    pick(studio, "rect")
    drag(studio, (box["x"] + 5, box["y"] + 2), (box["x"] + 105, box["y"] + 20))
    what(studio)
    save(studio, "rect")
    pick(studio, "lasso")
    mouse_path(
        studio,
        [
            (box["x"] + 5, box["y"]),
            (box["x"] + 90, box["y"]),
            (box["x"] + 50, box["y"] + 25),
        ],
    )
    what(studio)
    save(studio, "lasso")
    saved = comments_of(studio, "notes.md")
    assert [c["kind"] for c in saved] == ["text", "point", "rect", "lasso"]
    assert {c["anchor"]["space"] for c in saved} == {"page-px"}
    assert saved[0]["anchor"]["quote"] == "beta gamma delta"
    assert saved[0]["source_line"] == 5
    assert all(c["target"]["selector"] for c in saved)
    assert set(wait_marks(studio, {1, 2, 3, 4})) == {"1", "2", "3", "4"}


def test_anc_08_markdown_follows_the_page_rules_when_a_new_version_arrives(
    studio,
) -> None:  # noqa: ANN001
    show_markdown(studio, DOC)
    pick(studio, "text")
    select_words(studio, "beta", "delta")
    what(studio)
    save(studio, "moves")
    before = wait_marks(studio, {1})["1"]["y"]
    inserted = DOC.replace(
        "# Beams\n\n",
        "# Beams\n\nA new first paragraph.\n\nAnd a second one in front.\n\n",
    )
    rewrite(studio, "notes.md", inserted)
    after = wait_marks(studio, {1})["1"]["y"]
    assert after > before + 20
    assert [c["lost"] for c in comments_of(studio, "notes.md")] == [False]
    rewrite(
        studio,
        "notes.md",
        inserted.replace("alpha beta gamma delta epsilon", "all gone"),
    )
    wait_marks_none(studio)
    wait_lost(studio, [True], "notes.md")
    rewrite(studio, "notes.md", inserted)
    wait_lost(studio, [False], "notes.md")
    wait_marks(studio, {1})


# ---- COM-12: the pictures of comments ---------------------------------------------------------


def saved_picture(studio, name: str, index: int = -1) -> tuple:  # noqa: ANN001
    comment = comments_of(studio, name)[index]
    assert comment["picture_error"] is None, comment
    return decode_png((studio.folder / comment["picture"]).read_bytes())


def test_com_12_a_picture_rectangle_is_cut_from_the_pictures_own_pixels(studio) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    rect_on_picture(studio, (900, 700, 1100, 800))
    anchor = comments_of(studio, "pic.png")[0]["anchor"]
    width, height, rows = saved_picture(studio, "pic.png")
    assert width == pytest.approx(anchor["w"] + 32, abs=2)
    assert height == pytest.approx(anchor["h"] + 32, abs=2)
    assert near(rows[height // 2][width // 2], RED)
    assert near(rows[6][6], WHITE) and near(rows[height - 6][width - 6], WHITE)
    assert near(rows[8][width // 2], WHITE) and near(rows[height // 2][8], WHITE)


def test_com_12_at_fit_the_picture_has_at_least_one_image_pixel_per_css_pixel(
    studio,
) -> None:  # noqa: ANN001
    show_picture(studio)
    steady_layout(studio)
    assert view(studio)["scale"] < 0.9
    rect_on_picture(studio, (900, 700, 1100, 800))
    anchor = comments_of(studio, "pic.png")[0]["anchor"]
    scale = view(studio)["scale"]
    width, height, rows = saved_picture(studio, "pic.png")
    assert width == pytest.approx(anchor["w"] + 32 / scale, abs=3)
    assert width > anchor["w"] * scale + 32 + 20
    assert near(rows[height // 2][width // 2], RED)
    assert near(rows[3][3], WHITE)


def test_com_12_above_100_percent_the_crop_keeps_the_pictures_pixels(studio) -> None:  # noqa: ANN001
    """F5: no upscaling; at 400 % the crop has 0.25 image px per CSS px."""
    show_picture(studio)
    full_size(studio)
    studio.frame.evaluate(
        """() => {
      const scroller = document.querySelector('[data-scroller]');
      scroller.dispatchEvent(new WheelEvent('wheel', {ctrlKey: true, cancelable: true,
        deltaY: -Math.log(4) / 0.0015, clientX: innerWidth / 2, clientY: innerHeight / 2}));
    }"""
    )
    studio.frame.wait_for_function("window.acImageView().scale > 3.99")
    state = view(studio)
    box = (980, 730, 1020, 750)
    studio.frame.evaluate(
        "(box) => window.acViewer.reveal({x: box[0], y: box[1], w: box[2] - box[0], h: box[3] - box[1]})",
        box,
    )
    settled(studio)
    rect_on_picture(studio, box)
    anchor = comments_of(studio, "pic.png")[0]["anchor"]
    width, height, rows = saved_picture(studio, "pic.png")
    assert state["scale"] == pytest.approx(4, abs=0.01)
    # The picture's own pixels plus 16 CSS px of padding (= 4 picture px) each side.
    assert width == pytest.approx(anchor["w"] + 8, abs=2)
    assert height == pytest.approx(anchor["h"] + 8, abs=2)
    assert (
        width < anchor["w"] * state["scale"]
    )  # fewer pixels than CSS px: no upscaling
    assert near(rows[height // 2][width // 2], RED)


def test_com_12_a_picture_point_is_320_by_200_css_px_with_the_pin_on_it(studio) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    pick(studio, "point")
    studio.page.mouse.click(
        *[sum(p) for p in zip(studio.origin(), at(studio, 1000, 750), strict=True)]
    )
    what(studio)
    save(studio, "pin")
    width, height, rows = saved_picture(studio, "pic.png")
    assert (width, height) == (320, 200)
    anchor = comments_of(studio, "pic.png")[0]["anchor"]
    assert near(rows[100][160], ORANGE, 30)
    assert near(rows[100][160 - 40], RED) or near(rows[100][160 - 40], WHITE)
    assert anchor["x"] == pytest.approx(1000, abs=1)


def test_com_12_a_picture_lasso_is_its_bounding_box_with_the_path_drawn(studio) -> None:  # noqa: ANN001
    show_picture(studio)
    full_size(studio)
    pick(studio, "lasso")
    mouse_path(
        studio, [at(studio, 920, 720), at(studio, 1060, 720), at(studio, 990, 790)]
    )
    what(studio)
    save(studio, "loop")
    width, height, rows = saved_picture(studio, "pic.png")
    anchor = comments_of(studio, "pic.png")[0]["anchor"]
    assert width == pytest.approx(anchor["bbox"]["w"] + 32, abs=2)
    assert height == pytest.approx(anchor["bbox"]["h"] + 32, abs=2)
    top_edge = rows[16][width // 2]
    assert near(top_edge, ORANGE, 40), top_edge


def page_picture_case(studio, shape: str) -> tuple:  # noqa: ANN001
    show_markdown(studio, DOC)
    box = md_box(studio, "main.markdown p:nth-of-type(2)")
    left, top = studio.origin()
    if shape == "rect":
        pick(studio, "rect")
        drag(studio, (box["x"] + 5, box["y"] + 2), (box["x"] + 105, box["y"] + 22))
    elif shape == "point":
        pick(studio, "point")
        studio.page.mouse.click(left + box["x"] + 150, top + box["y"] + 8)
    elif shape == "lasso":
        pick(studio, "lasso")
        mouse_path(
            studio,
            [
                (box["x"] + 5, box["y"]),
                (box["x"] + 125, box["y"]),
                (box["x"] + 65, box["y"] + 40),
            ],
        )
    else:
        pick(studio, "text")
        select_words(studio, "beta", "delta")
    what(studio)
    save(studio, shape)
    return comments_of(studio, "notes.md")[0], saved_picture(studio, "notes.md", 0)


def test_com_12_markdown_rectangle_and_text_pictures_come_through_the_page_path(
    studio,
) -> None:  # noqa: ANN001
    comment, (width, height, _) = page_picture_case(studio, "rect")
    assert comment["picture"] == ".comments/notes.md.1.png"
    assert (width, height) == (
        pytest.approx(comment["anchor"]["w"] + 32, abs=2),
        pytest.approx(comment["anchor"]["h"] + 32, abs=2),
    )


def test_com_12_markdown_text_picture_is_the_quotes_box(studio) -> None:  # noqa: ANN001
    comment, (width, height, _) = page_picture_case(studio, "text")
    rects = comment["anchor"]["rects"]
    assert width >= max(r["w"] for r in rects) + 30
    assert height >= rects[0]["h"] + 30


def test_com_12_markdown_point_is_320_by_200_with_the_pin_and_lasso_has_its_path(
    studio,
) -> None:  # noqa: ANN001
    _, (width, height, rows) = page_picture_case(studio, "point")
    assert (width, height) == (320, 200)
    assert near(rows[100][160], ORANGE, 30)


def test_com_12_markdown_lasso_path_is_drawn_on_the_picture(studio) -> None:  # noqa: ANN001
    comment, (width, height, rows) = page_picture_case(studio, "lasso")
    bbox = comment["anchor"]["bbox"]
    assert width == pytest.approx(bbox["w"] + 32, abs=2)
    assert height == pytest.approx(bbox["h"] + 32, abs=2)
    assert near(rows[16][width // 2], ORANGE, 40)


# ---- gaps the earlier packages left ----------------------------------------------------------


def test_view_09_a_file_dragged_over_the_frame_raises_the_shells_drop_shield(
    studio,
) -> None:  # noqa: ANN001
    studio.make("<p>page</p>")
    script = """(withFile) => {
      const transfer = new DataTransfer();
      if (withFile) transfer.items.add(new File(['x'], 'secret-name.txt'));
      document.body.dispatchEvent(new DragEvent('dragenter', {dataTransfer: transfer, bubbles: true}));
    }"""
    studio.frame.evaluate(script, False)
    studio.page.wait_for_timeout(300)
    assert not studio.page.evaluate("document.body.classList.contains('file-drag')")
    studio.frame.evaluate(script, True)
    studio.page.wait_for_function("document.body.classList.contains('file-drag')")
    assert studio.page.evaluate("window.__guard.accepted['drag-notice']") == 1


def test_sec_09_the_drag_notice_carries_nothing_but_its_type(studio) -> None:  # noqa: ANN001
    studio.make("<p>page</p>")
    studio.page.evaluate(
        "window.__seen = []; window.addEventListener('message', (e) => window.__seen.push(e.data))"
    )
    studio.frame.evaluate(
        "(() => { const t = new DataTransfer(); t.items.add(new File(['x'], 'secret-name.txt'));"
        " document.body.dispatchEvent(new DragEvent('dragenter', {dataTransfer: t, bubbles: true})); })()"
    )
    studio.page.wait_for_function("window.__seen.some((m) => m.type === 'drag-notice')")
    notice = studio.page.evaluate("window.__seen.find((m) => m.type === 'drag-notice')")
    assert notice == {"type": "drag-notice"}


def test_view_14_a_picture_that_cannot_be_decoded_is_reported_to_the_hub(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make("<p>first</p>")
    (studio.folder / "bad.png").write_bytes(b"not a picture")
    call(
        studio.owner,
        "POST",
        f"/api/sessions/{sid}/show",
        json={"project": str(studio.tmp_path / "alpha"), "name": "bad.png"},
    )
    studio.frame.wait_for_selector("[data-notice]")
    state = studio.owner.hub.state

    def reasons() -> dict:
        return studio.owner.hub.on_loop(
            lambda: dict(state.page_status(sid, "bad.png").viewer_errors)
        )

    for _ in range(100):
        if reasons():
            break
        studio.page.wait_for_timeout(50)
    assert reasons() == {None: "image-undecodable"}
