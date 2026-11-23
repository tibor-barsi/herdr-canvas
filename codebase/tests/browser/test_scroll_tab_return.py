"""A page comes back at the scroll position the owner left (PAGE-06, D-56)."""

from __future__ import annotations

import pytest

from .pdf_fixtures import text_pdf
from .support import call

pytestmark = pytest.mark.browser

TALL = "<div style='height:4000px'>tall</div><p id=end>end</p>"
LONG_MD = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(120))
Y = 1500
SCROLL_Y = "window.scrollY"
SCROLLER_TOP = "document.querySelector('[data-scroller]').scrollTop"


def scroll_to(owner, expression: str, y: int) -> None:  # noqa: ANN001
    target = (
        "document.querySelector('[data-scroller]')"
        if "scroller" in expression
        else "window"
    )
    # The window loads the page a second time just after `show`; scroll after that.
    owner.page.wait_for_timeout(1000)
    owner.frame.evaluate(f"{target}.scrollTo(0, {y})")
    owner.page.wait_for_timeout(400)
    assert abs(owner.frame.evaluate(expression) - y) < 5


def show_file(owner, made, name: str, data: bytes) -> None:  # noqa: ANN001
    (made.folder / name).write_bytes(data)
    call(
        owner,
        "POST",
        f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parents[1]), "name": name},
    )


def leave_and_return(make, owner, first) -> None:  # noqa: ANN001
    make("<p>other</p>", name="beta")
    owner.visit(first.sid)
    owner.frame.wait_for_function("document.readyState === 'complete'")


def test_page_06_an_html_page_comes_back_at_its_scroll_position(make, owner) -> None:  # noqa: ANN001
    first = make(TALL)
    scroll_to(owner, SCROLL_Y, Y)
    leave_and_return(make, owner, first)
    owner.frame.wait_for_function(f"Math.abs(window.scrollY - {Y}) < 5")


def test_page_06_the_position_survives_a_new_version_of_the_page(make, owner) -> None:  # noqa: ANN001
    first = make(TALL)
    scroll_to(owner, SCROLL_Y, Y)
    leave_and_return(make, owner, first)
    owner.frame.wait_for_function(f"Math.abs(window.scrollY - {Y}) < 5")
    first.rewrite(TALL.replace(">end<", ">changed<"))
    owner.frame.wait_for_function(
        "document.getElementById('end').textContent === 'changed'"
    )
    assert abs(owner.frame.evaluate(SCROLL_Y) - Y) < 5


def test_page_06_a_markdown_view_comes_back_at_its_scroll_position(make, owner) -> None:  # noqa: ANN001
    first = make("<p>first</p>")
    show_file(owner, first, "notes.md", LONG_MD.encode())
    owner.frame.wait_for_selector("main.markdown p")
    scroll_to(owner, SCROLL_Y, Y)
    leave_and_return(make, owner, first)
    owner.frame.wait_for_function(f"Math.abs(window.scrollY - {Y}) < 5")


def test_page_06_a_pdf_view_comes_back_at_its_scroll_position(make, owner) -> None:  # noqa: ANN001
    first = make("<p>first</p>")
    show_file(owner, first, "doc.pdf", text_pdf(pages=6))
    owner.frame.wait_for_function("window.acViewer && window.acViewer.mounted")
    scroll_to(owner, SCROLLER_TOP, Y)
    leave_and_return(make, owner, first)
    owner.frame.wait_for_function(f"Math.abs({SCROLLER_TOP} - {Y}) < 5")
