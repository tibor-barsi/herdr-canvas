"""Fixes of the M25 review: a rebuilt PDF that fails, passwords, unread text, old frames."""

# ruff: noqa: E501
from __future__ import annotations


import pytest

from .pdf_fixtures import assemble, encrypted_pdf, text_pdf
from .test_comment_anchors import wait_marks
from .test_view_04_pdf_viewer import show_pdf, wait_ready
from .test_view_07_pdf_comments import go, open_doc, rect_on_page, text_on_page
from .test_viewer_comments import rewrite, wait_lost

pytestmark = pytest.mark.browser

LIB_IMPORT = (
    "import(new URL('/static/vendor/pdfjs-dist/pdf.min.mjs', location.href).href)"
)


def test_view_14_a_rebuilt_pdf_that_cannot_be_opened_shows_the_notice_and_reports_it(
    make, owner
) -> None:  # noqa: ANN001
    made = show_pdf(make, text_pdf(3))
    wait_ready(owner)
    seen = owner.count_reports("viewer-error")
    (made.folder / "doc.pdf").write_bytes(b"%PDF-1.4 this is not a document")
    report = owner.wait_report_after("viewer-error", seen)
    assert report["reason"] == "pdf-corrupt"
    owner.frame.wait_for_selector("[data-notice]")
    assert owner.frame.evaluate(
        "document.querySelector('[data-notice]').textContent"
    ) == (
        "This file could not be shown: the PDF is damaged. Ask the agent to make it again."
    )
    assert owner.count_reports("viewer-error") == seen + 1


def broken_pages_pdf() -> bytes:
    """A PDF that opens (two pages are counted) but whose pages cannot be read."""
    return assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 2 /Kids [4 0 R 9 0 R] >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
            b"<< /Type /Bogus >>",
        ]
    )


def test_view_14_a_rebuilt_pdf_whose_pages_fail_closes_both_workers(
    make, owner
) -> None:  # noqa: ANN001
    made = show_pdf(make, text_pdf(2))
    wait_ready(owner)
    owner.frame.evaluate(
        """() => {
      window.__ended = 0;
      const end = Worker.prototype.terminate;
      Worker.prototype.terminate = function () { window.__ended++; return end.call(this); };
    }"""
    )
    seen = owner.count_reports("viewer-error")
    (made.folder / "doc.pdf").write_bytes(broken_pages_pdf())
    owner.wait_report_after("viewer-error", seen)
    owner.frame.wait_for_selector("[data-notice]")
    owner.frame.evaluate("new Promise((r) => setTimeout(r, 300))")
    assert owner.frame.evaluate("window.__ended") == 2  # the old and the new worker


def test_view_14_an_encrypted_pdf_reports_pdf_password(make, owner) -> None:  # noqa: ANN001
    seen = owner.count_reports("viewer-error")
    show_pdf(make, encrypted_pdf(), "locked.pdf")
    report = owner.wait_report_after("viewer-error", seen)
    assert report["page"] == "locked.pdf"
    assert report["reason"] == "pdf-password"
    assert owner.frame.evaluate(
        "document.querySelector('[data-notice]').textContent"
    ) == (
        "This file could not be shown: the PDF is locked with a password. Ask the agent for a copy without the password."
    )


def test_view_14_the_encrypted_fixture_is_valid_and_opens_with_its_password(
    make, owner
) -> None:  # noqa: ANN001
    """Positive control: the file is sound; only the password is missing."""
    show_pdf(make, text_pdf(1))
    wait_ready(owner)
    text = owner.frame.evaluate(
        f"""async (hex) => {{
      const lib = await {LIB_IMPORT};
      const data = Uint8Array.from(hex.match(/../g).map((h) => parseInt(h, 16)));
      const doc = await lib.getDocument({{data, password: 'secret'}}).promise;
      const page = await doc.getPage(1);
      return (await page.getTextContent()).items.map((i) => i.str).join('');
    }}""",
        encrypted_pdf().hex(),
    )
    assert text == "Secret page"


def test_anc_08_a_pdf_whose_text_cannot_be_read_still_reports_text_lost_and_keeps_shapes(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio, text_pdf(2))
    text_on_page(
        studio, "Line 5 of page 1", "Line 5 of page 1: the quick brown", "text"
    )
    rect_on_page(studio, 1, (100, 400, 300, 470), "rect")
    wait_marks(studio, {1, 2})
    studio.frame.evaluate(
        f"""async (hex) => {{
      const lib = await {LIB_IMPORT};
      const data = Uint8Array.from(hex.match(/../g).map((h) => parseInt(h, 16)));
      const page = await (await lib.getDocument({{data}}).promise).getPage(1);
      Object.getPrototypeOf(page).getTextContent = () => Promise.reject(new Error('unreadable'));
    }}""",
        text_pdf(1).hex(),
    )
    rewrite(studio, "doc.pdf", text_pdf(2, tag=" new"))
    wait_lost(studio, [True, False], "doc.pdf")
    assert set(wait_marks(studio, {2})) == {"2"}


def test_com_12_a_crop_of_a_page_far_from_the_view_survives_a_scroll_while_it_waits(
    studio,
) -> None:  # noqa: ANN001
    open_doc(studio, text_pdf(6))
    go(studio, 1)
    outcome = studio.frame.evaluate(
        """async () => {
      const scroller = document.querySelector('[data-scroller]');
      const crop = acViewer.crop(6, {x: 10, y: 10, w: 100, h: 50}).then(
        (r) => 'ok ' + r.canvas.width, (e) => 'error ' + e.message);
      const timer = setInterval(() => scroller.dispatchEvent(new Event('scroll')), 0);
      const result = await crop;
      clearInterval(timer);
      return result;
    }"""
    )
    assert outcome.startswith("ok"), outcome


def test_view_14_an_unknown_reason_code_gives_a_plain_notice_without_undefined(
    make, owner
) -> None:  # noqa: ANN001
    def other_code(route) -> None:  # noqa: ANN001
        text = route.fetch().text()
        assert '"pdf-corrupt"' in text
        route.fulfill(
            body=text.replace('"pdf-corrupt"', '"pdf-strange"'),
            content_type="text/javascript",
        )

    owner.page.route("**/static/pdf-core.js*", other_code)
    seen = owner.count_reports("viewer-error")
    show_pdf(make, b"%PDF-1.4 this is not a document", "odd.pdf")
    owner.wait_report_after("viewer-error", seen)
    owner.frame.wait_for_selector("[data-notice]")
    assert (
        owner.frame.evaluate("document.querySelector('[data-notice]').textContent")
        == "This file could not be shown."
    )
