"""The PDF viewer: pages, zoom, text layer, lazy canvases (VIEW-04) and PDF.js under the CSP (VIEW-05).

Slice: VIEW-14's notice for a PDF that cannot be opened is tested here; the
``viewer_error`` of ``show`` and ``look`` belongs to P25.3.
"""

# ruff: noqa: E501
from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx
import pytest

from .pdf_fixtures import (
    cjk_pdf,
    font_pdf,
    image_pdf,
    script_pdf,
    text_pdf,
)
from .support import call

pytestmark = pytest.mark.browser

CSS_PER_PT = 96 / 72
PAGE = "document.querySelector('[data-pdf-page=\"{n}\"]')"
LINE = "Line {i} of page {n}: the quick brown fox jumps over the lazy dog"


class Watch:
    """What the owner's window saw while a PDF was shown."""

    def __init__(self, owner) -> None:  # noqa: ANN001
        self.console: list[str] = []
        self.errors: list[str] = []
        self.requests: list[str] = []
        self.dialogs: list[str] = []
        page = owner.page
        page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.on("dialog", self._dialog)

    def _dialog(self, dialog) -> None:  # noqa: ANN001
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def violations(self) -> list[str]:
        return [
            m
            for m in self.console
            if "Content Security Policy" in m or "Refused to" in m
        ]


def show_pdf(make, data: bytes, name: str = "doc.pdf"):  # noqa: ANN001, ANN201
    """Show ``data`` as the page ``name`` and return the made session."""
    made = make("<p>first</p>")
    (made.folder / name).write_bytes(data)
    call(
        made.owner,
        "POST",
        f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parents[1]), "name": name},
    )
    return made


def open_pdf(make, data: bytes, name: str = "doc.pdf"):  # noqa: ANN001, ANN201
    """Show ``data`` and wait until the viewer has mounted and page 1 has its text."""
    made = show_pdf(make, data, name)
    wait_ready(made.owner)
    return made


def wait_ready(owner, page: int = 1) -> None:  # noqa: ANN001
    owner.frame.wait_for_function("window.acViewer && window.acViewer.mounted")
    wait_text(owner, page)


def wait_text(owner, page: int) -> None:  # noqa: ANN001
    """Wait until the page has a canvas of the current zoom and a text layer."""
    owner.frame.wait_for_function(
        f"() => {{ const p = {PAGE.format(n=page)}; return p && p.querySelector('canvas') "
        "&& p.querySelector('.textLayer span'); }"
    )


def settle(owner) -> None:  # noqa: ANN001
    """Let the zoom hold end and the rerender finish."""
    owner.frame.evaluate("new Promise((r) => setTimeout(r, 400))")
    owner.frame.evaluate("new Promise(requestAnimationFrame)")


def canvases(owner) -> int:  # noqa: ANN001
    """Page canvases (PDF.js keeps one more, hidden, to measure text)."""
    return owner.frame.evaluate(
        "document.querySelectorAll('[data-pdf-page] canvas').length"
    )


def page_rect(owner, page: int) -> dict:  # noqa: ANN001
    return owner.frame.evaluate(
        f"(() => {{ const r = {PAGE.format(n=page)}.getBoundingClientRect();"
        " return {x: r.left, y: r.top, w: r.width, h: r.height}; })()"
    )


def scroll_to_page(owner, page: int) -> None:  # noqa: ANN001
    owner.frame.evaluate(f"{PAGE.format(n=page)}.scrollIntoView({{block: 'start'}})")
    owner.frame.evaluate("new Promise(requestAnimationFrame)")


def click(owner, label: str) -> None:  # noqa: ANN001
    owner.frame.get_by_role("button", name=label, exact=True).click()


def window_point(owner, x: float, y: float) -> tuple[float, float]:  # noqa: ANN001
    box = owner.page.locator("#frame").bounding_box()
    return box["x"] + x, box["y"] + y


def ctrl_wheel(owner, dy: float) -> None:  # noqa: ANN001
    owner.page.keyboard.down("Control")
    owner.page.mouse.wheel(0, dy)
    owner.page.keyboard.up("Control")
    owner.frame.evaluate("new Promise(requestAnimationFrame)")


def span_of(owner, text: str) -> dict:  # noqa: ANN001
    """Frame rectangle of the text-layer span that starts with ``text``."""
    return owner.frame.evaluate(
        """(t) => { const s = [...document.querySelectorAll('.textLayer span')]
          .find((e) => e.textContent.startsWith(t)); if (!s) return null;
          const r = s.getBoundingClientRect();
          return {x: r.left, y: r.top, w: r.width, h: r.height, text: s.textContent}; }""",
        text,
    )


# ---- VIEW-04 -------------------------------------------------------------------------


@pytest.mark.timing
def test_view_04_page_1_of_50_is_shown_within_2_seconds(make) -> None:  # noqa: ANN001
    data = text_pdf(50)
    made = make("<p>first</p>")
    (made.folder / "doc.pdf").write_bytes(data)
    started = time.monotonic()
    call(
        made.owner,
        "POST",
        f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parents[1]), "name": "doc.pdf"},
    )
    wait_ready(made.owner)
    assert time.monotonic() - started < 2.0
    assert made.owner.frame.evaluate("acViewer.pageCount") == 50


def test_view_04_pages_lie_one_under_another_fitted_to_the_width(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(3))
    owner = made.owner
    width = owner.frame.evaluate(
        "document.querySelector('[data-scroller]').clientWidth"
    )
    first, second = page_rect(owner, 1), page_rect(owner, 2)
    assert first["w"] == pytest.approx(width - 16, abs=1)
    assert first["h"] == pytest.approx(first["w"] * 842 / 595, abs=1)
    assert second["x"] == pytest.approx(first["x"], abs=0.5)
    assert second["y"] >= first["y"] + first["h"]
    assert owner.frame.evaluate(
        "(() => { const s = document.querySelector('[data-scroller]');"
        " return s.scrollWidth <= s.clientWidth; })()"
    )


def test_view_04_the_viewer_has_the_shared_interface(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(3))
    shape = made.owner.frame.evaluate(
        """(() => { const v = window.acViewer;
          return {kind: v.kind, space: v.space, mounted: v.mounted,
            mount: typeof v.mount, update: typeof v.update,
            toSpace: typeof v.toSpace, fromSpace: typeof v.fromSpace}; })()"""
    )
    assert shape == {
        "kind": "pdf",
        "space": "pdf-pt",
        "mounted": True,
        "mount": "function",
        "update": "function",
        "toSpace": "function",
        "fromSpace": "function",
    }


def test_view_04_scrolling_to_page_40_renders_it_with_at_most_10_canvases(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(50))
    owner = made.owner
    assert canvases(owner) <= 10
    assert owner.frame.evaluate(f"!{PAGE.format(n=40)}.querySelector('canvas')")
    scroll_to_page(owner, 40)
    wait_text(owner, 40)
    assert canvases(owner) <= 10
    # Page 1 is far away now: its canvas was dropped.
    assert owner.frame.evaluate(f"!{PAGE.format(n=1)}.querySelector('canvas')")
    # A walk down the whole document never keeps more than 10.
    for n in range(1, 51, 7):
        scroll_to_page(owner, n)
        owner.frame.evaluate("new Promise((r) => setTimeout(r, 120))")
        assert canvases(owner) <= 10, n


def test_view_04_with_more_than_10_pages_near_the_view_exactly_10_are_rendered(
    make,  # noqa: ANN001
) -> None:
    # Strip-shaped pages: dozens of them lie within reach of the view at once,
    # so only the cap of 10 (not the reach) limits the canvases.
    made = open_pdf(make, text_pdf(50, width=595, height=100))
    owner = made.owner
    for _ in range(8):
        click(owner, "Zoom out")
    settle(owner)
    scroll_to_page(owner, 25)
    settle(owner)
    near = owner.frame.evaluate(
        """() => { const h = innerHeight; return [...document.querySelectorAll('[data-pdf-page]')]
          .filter((p) => { const r = p.getBoundingClientRect();
            return r.bottom >= -h && r.top <= 2 * h; }).length; }"""
    )
    assert near > 10, near
    owner.frame.wait_for_function(
        "document.querySelectorAll('[data-pdf-page] canvas').length >= 10"
    )
    settle(owner)
    assert canvases(owner) == 10


def test_view_04_at_50_percent_still_at_most_10_canvases(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(50))
    owner = made.owner
    for _ in range(8):
        click(owner, "Zoom out")
    settle(owner)
    assert (
        owner.frame.evaluate("document.querySelector('[data-bar] output').textContent")
        == "50 %"
    )
    count = canvases(owner)
    assert 1 <= count <= 10
    scroll_to_page(owner, 20)
    settle(owner)
    assert 1 <= canvases(owner) <= 10


def test_view_04_selecting_a_line_of_page_3_gives_its_text(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(5))
    owner = made.owner
    scroll_to_page(owner, 3)
    wait_text(owner, 3)
    line = LINE.format(i=3, n=3)
    span = span_of(owner, line)
    assert span is not None
    y = span["y"] + span["h"] / 2
    start = window_point(owner, span["x"] + 1, y)
    end = window_point(owner, span["x"] + span["w"] - 1, y)
    owner.page.mouse.move(*start)
    owner.page.mouse.down()
    owner.page.mouse.move(*end, steps=6)
    owner.page.mouse.up()
    selected = owner.frame.evaluate("getSelection().toString()")
    assert selected.strip() == line


def test_view_04_text_layer_text_is_what_the_page_says(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(3))
    texts = made.owner.frame.evaluate(
        f"[...{PAGE.format(n=1)}.querySelectorAll('.textLayer span')].map((e) => e.textContent)"
    )
    assert "Page 1 of 3" in texts
    assert LINE.format(i=30, n=1) in texts


def test_view_04_zoom_buttons_and_wheel_stop_at_50_and_400_percent(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(3))
    owner = made.owner
    shown = "document.querySelector('[data-bar] output').textContent"
    for _ in range(12):
        click(owner, "Zoom in")
    assert owner.frame.evaluate(shown) == "400 %"
    assert page_rect(owner, 1)["w"] == pytest.approx(595 * 4 * CSS_PER_PT, abs=1)
    click(owner, "Zoom in")
    assert page_rect(owner, 1)["w"] == pytest.approx(595 * 4 * CSS_PER_PT, abs=1)
    ctrl_wheel(owner, -2000)
    assert owner.frame.evaluate(shown) == "400 %"
    for _ in range(14):
        click(owner, "Zoom out")
    assert owner.frame.evaluate(shown) == "50 %"
    assert page_rect(owner, 1)["w"] == pytest.approx(595 * 0.5 * CSS_PER_PT, abs=1)
    ctrl_wheel(owner, 4000)
    assert owner.frame.evaluate(shown) == "50 %"
    click(owner, "Fit width")
    width = owner.frame.evaluate(
        "document.querySelector('[data-scroller]').clientWidth"
    )
    assert page_rect(owner, 1)["w"] == pytest.approx(width - 16, abs=1)


def test_view_04_ctrl_wheel_zoom_keeps_the_point_under_the_pointer(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(3))
    owner = made.owner
    click(owner, "Zoom in")  # leave Fit, so that there is room to scroll
    settle(owner)
    span = span_of(owner, LINE.format(i=12, n=1))
    centre = (span["x"] + span["w"] / 2, span["y"] + span["h"] / 2)
    px, py = centre[0] - 40, centre[1] + 3
    owner.page.mouse.move(*window_point(owner, px, py))
    before = span_of(owner, LINE.format(i=12, n=1))
    ctrl_wheel(owner, -500)
    settle(owner)
    after = span_of(owner, LINE.format(i=12, n=1))
    factor = after["w"] / before["w"]
    assert factor > 1.3
    expected = (
        px + factor * (before["x"] + before["w"] / 2 - px),
        py + factor * (before["y"] + before["h"] / 2 - py),
    )
    assert after["x"] + after["w"] / 2 == pytest.approx(expected[0], abs=10)
    assert after["y"] + after["h"] / 2 == pytest.approx(expected[1], abs=10)
    # Zooming back out around the same point returns to the same place.
    ctrl_wheel(owner, 500)
    settle(owner)
    back = span_of(owner, LINE.format(i=12, n=1))
    assert back["x"] + back["w"] / 2 == pytest.approx(
        before["x"] + before["w"] / 2, abs=10
    )


def test_view_04_the_text_stays_on_its_page_after_a_zoom(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(3))
    owner = made.owner
    for _ in range(3):
        click(owner, "Zoom in")
    settle(owner)
    page = page_rect(owner, 1)
    span = span_of(owner, LINE.format(i=1, n=1))
    ratio = page["w"] / 595
    assert span["x"] - page["x"] == pytest.approx(56 * ratio, abs=3)
    assert (
        owner.frame.evaluate(f"{PAGE.format(n=1)}.querySelector('canvas').width")
        >= page["w"] - 1
    )


def test_view_04_the_page_number_in_view_follows_the_scrolling(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(50))
    owner = made.owner
    label = "[...document.querySelectorAll('[data-bar] output')].pop().textContent"
    assert owner.frame.evaluate(label) == "1 / 50"
    scroll_to_page(owner, 3)
    owner.frame.wait_for_function(f"{label} === '3 / 50'")
    assert owner.frame.evaluate("acViewer.page") == 3
    scroll_to_page(owner, 40)
    owner.frame.wait_for_function(f"{label} === '40 / 50'")


def test_view_04_a_point_converts_to_points_from_the_page_top_left(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(3))
    owner = made.owner
    page = page_rect(owner, 2)
    point = owner.frame.evaluate(
        f"acViewer.toSpace({page['x'] + page['w'] / 2}, {page['y'] + page['h'] / 4})"
    )
    assert point["p"] == 2
    assert point["x"] == pytest.approx(595 / 2, abs=0.5)
    assert point["y"] == pytest.approx(842 / 4, abs=0.5)
    back = owner.frame.evaluate(f"acViewer.fromSpace(2, {point['x']}, {point['y']})")
    assert back["x"] == pytest.approx(page["x"] + page["w"] / 2, abs=0.5)
    assert back["y"] == pytest.approx(page["y"] + page["h"] / 4, abs=0.5)


def test_view_04_a_new_version_keeps_the_page_offset_and_zoom(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(8))
    owner = made.owner
    for _ in range(2):
        click(owner, "Zoom in")
    settle(owner)
    scroll_to_page(owner, 4)
    owner.frame.evaluate("document.querySelector('[data-scroller]').scrollTop += 300")
    settle(owner)
    before = owner.frame.evaluate(
        "(() => ({zoom: document.querySelector('[data-bar] output').textContent,"
        " spot: acViewer.toSpace(10, 0)}))()"
    )
    (made.folder / "doc.pdf").write_bytes(text_pdf(9, tag=" v2"))
    owner.frame.evaluate("acViewer.update({viewer: 'pdf', version: 2})")
    owner.frame.wait_for_function("acViewer.pageCount === 9")
    # The old pages stay until version 2 is drawn and the offset is put back.
    owner.frame.wait_for_function(
        """([zoom, spot]) => {
          const output = document.querySelector('[data-bar] output');
          const now = acViewer.toSpace(10, 0);
          return acViewer.pageCount === 9 && output.textContent === zoom
            && now.p === spot.p && Math.abs(now.y - spot.y) <= 842 * 0.05;
        }""",
        arg=[before["zoom"], before["spot"]],
    )
    after = owner.frame.evaluate(
        "(() => ({zoom: document.querySelector('[data-bar] output').textContent,"
        " spot: acViewer.toSpace(10, 0)}))()"
    )
    assert after["zoom"] == before["zoom"]
    assert after["spot"]["p"] == before["spot"]["p"] == 4
    assert after["spot"]["y"] == pytest.approx(before["spot"]["y"], abs=842 * 0.05)
    # The text layers are drawn again after the canvas: wait for the version-2 text.
    owner.frame.wait_for_function(
        "(t) => [...document.querySelectorAll('.textLayer span')]"
        ".some((e) => e.textContent.startsWith(t))",
        arg=LINE.format(i=1, n=4) + " v2",
    )


# ---- VIEW-05 -------------------------------------------------------------------------

SEC06 = (
    "default-src 'none'; "
    "script-src {f}/static/ {f}/s/{t}/ 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'; "
    "style-src {f}/static/ {f}/s/{t}/ 'unsafe-inline'; "
    "img-src {f}/s/{t}/ {f}/static/ data: blob:; "
    "font-src {f}/static/ data:; "
    "media-src {f}/s/{t}/ data: blob:; "
    "connect-src {f}/s/{t}/ {f}/static/ data: blob:; "
    "worker-src blob:; form-action 'none'; frame-src 'none'; base-uri 'none'"
)


def test_view_05_the_csp_of_the_viewer_document_is_the_one_of_sec_06(make) -> None:  # noqa: ANN001
    made = open_pdf(make, text_pdf(2))
    hub = made.owner.hub
    frame_url = made.owner.frame.url
    parts = urlparse(frame_url)
    token = parts.path.split("/")[2]
    expected = SEC06.format(f=f"http://localhost:{hub.port}", t=token)
    for url in (frame_url, frame_url.split("?")[0]):
        got = httpx.get(url.replace("127.0.0.1", "localhost"), timeout=10)
        assert got.status_code == 200
        assert got.headers["content-security-policy"] == expected, url


def reshow(made, name: str, data: bytes) -> None:  # noqa: ANN001
    """Write ``data`` as another page of the session, show it and wait for its text."""
    (made.folder / name).write_bytes(data)
    call(
        made.owner,
        "POST",
        f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parents[1]), "name": name},
    )
    made.owner.frame.wait_for_function(
        "(n) => location.pathname.endsWith(n) && window.acViewer && window.acViewer.mounted",
        arg=name,
    )
    # The text layer element is added once page 1 is drawn (it may hold no text).
    made.owner.frame.wait_for_function(
        f"!!{PAGE.format(n=1)}.querySelector('.textLayer')"
    )


def test_view_05_pdfjs_runs_in_a_worker_with_the_three_options(make, owner) -> None:  # noqa: ANN001
    watch = Watch(owner)
    open_pdf(make, text_pdf(3))
    state = owner.frame.evaluate(
        "({thread: acViewer.thread, options: acViewer.options})"
    )
    assert state == {
        "thread": "worker",
        "options": {
            "useSystemFonts": False,
            "isEvalSupported": False,
            "enableScripting": False,
        },
    }
    assert watch.violations() == []
    assert watch.errors == []


@pytest.mark.parametrize("failure", ["throws", "errors"])
def test_view_05_the_page_thread_takes_over_when_the_worker_does_not_start(  # noqa: ANN201
    make, owner, failure: str
) -> None:  # noqa: ANN001
    if failure == "throws":
        script = "window.Worker = function () { throw new Error('no workers here'); };"
    else:
        script = (
            "const Real = window.Worker; window.Worker = function (url, options) {"
            " if (String(url).startsWith('blob:')) url = URL.createObjectURL("
            "new Blob(['throw new Error(\"boom\")']));"
            " return new Real(url, options); };"
        )
    owner.page.add_init_script(
        f"if (location.pathname.startsWith('/s/')) {{ {script} }}"
    )
    watch = Watch(owner)
    open_pdf(make, text_pdf(3))
    assert owner.frame.evaluate("acViewer.thread") == "page"
    texts = owner.frame.evaluate(
        f"[...{PAGE.format(n=1)}.querySelectorAll('.textLayer span')].map((e) => e.textContent)"
    )
    assert "Page 1 of 3" in texts
    assert watch.errors == []


def test_view_05_a_pdf_with_scripts_runs_none_of_them(make, owner) -> None:  # noqa: ANN001
    watch = Watch(owner)
    open_pdf(make, script_pdf())
    # Positive control: PDF.js, asked outside the viewer, does see the scripts in the file.
    found = owner.page.evaluate(
        """async (bytes) => {
          const pdfjs = await import("/static/vendor/pdfjs-dist/pdf.min.mjs");
          pdfjs.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs-dist/pdf.worker.min.mjs";
          const doc = await pdfjs.getDocument({data: new Uint8Array(bytes)}).promise;
          return JSON.stringify([await doc.getFieldObjects(), await doc.getJSActions()]);
        }""",
        list(script_pdf()),
    )
    assert "app.alert" in found
    owner.frame.evaluate("new Promise((r) => setTimeout(r, 500))")
    assert watch.dialogs == []
    assert owner.frame.evaluate("acViewer.options.enableScripting") is False
    assert (
        owner.frame.evaluate("document.querySelector('.textLayer span').textContent")
        == "Script fixture"
    )
    assert watch.errors == []


def test_view_05_text_images_embedded_fonts_and_cmaps_render_without_violation(  # noqa: ANN201
    make, owner
) -> None:  # noqa: ANN001
    watch = Watch(owner)
    made = open_pdf(make, text_pdf(2))
    # Standard fonts (not embedded) load from /static/.
    assert any("/static/vendor/pdfjs-dist/standard_fonts/" in u for u in watch.requests)

    reshow(made, "cjk.pdf", cjk_pdf())
    assert "あいうえお" in owner.frame.evaluate(
        "document.querySelector('.textLayer').textContent"
    )
    assert any(
        "/static/vendor/pdfjs-dist/cmaps/UniJIS-UCS2-H" in u for u in watch.requests
    )

    pixel = """([x, y]) => { const c = document.querySelector('canvas');
      const k = c.width / 595; const d = c.getContext('2d')
        .getImageData(Math.round(x * k), Math.round(y * k), 1, 1).data;
      return [d[0], d[1], d[2]]; }"""
    reshow(made, "font.pdf", font_pdf())
    assert owner.frame.evaluate(pixel, [135, 107])[0] < 60  # inside the first box
    assert owner.frame.evaluate(pixel, [170, 107])[0] > 200  # between two boxes
    assert owner.frame.evaluate("document.querySelector('.textLayer').textContent") == (
        "AAAA"
    )

    reshow(made, "image.pdf", image_pdf())
    red = owner.frame.evaluate(pixel, [130, 192])
    blue = owner.frame.evaluate(pixel, [270, 192])
    assert red[0] > 200 and red[2] < 60
    assert blue[2] > 200 and blue[0] < 60

    assert watch.violations() == []
    assert watch.errors == []


def test_view_05_no_request_leaves_the_hub(make, owner) -> None:  # noqa: ANN001
    watch = Watch(owner)
    open_pdf(make, text_pdf(5))
    scroll_to_page(owner, 4)
    wait_text(owner, 4)
    hosts = {f"127.0.0.1:{owner.hub.port}", f"localhost:{owner.hub.port}"}
    outside = [
        u
        for u in watch.requests
        if not u.startswith(("blob:", "data:")) and urlparse(u).netloc not in hosts
    ]
    assert outside == []
    assert owner.foreign_requests == []
    assert any("/static/vendor/pdfjs-dist/pdf.min.mjs" in u for u in watch.requests)


# ---- VIEW-14 (the notice; the hub's viewer_error comes with P25.3) ---------------------


def test_view_14_a_truncated_pdf_shows_the_notice_and_reports_it(make, owner) -> None:  # noqa: ANN001
    seen = owner.count_reports("viewer-error")
    show_pdf(make, text_pdf(3)[:300], "broken.pdf")
    report = owner.wait_report_after("viewer-error", seen)
    assert report["page"] == "broken.pdf"
    assert report["reason"] == "pdf-corrupt"
    assert owner.frame.evaluate(
        "document.querySelector('[data-notice]').textContent"
    ) == ("This file could not be shown: the PDF is damaged. Ask the agent to make it again.")
