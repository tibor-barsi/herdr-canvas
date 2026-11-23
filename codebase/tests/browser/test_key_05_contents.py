"""The table of contents of the page, opened with one key (KEY-05, #73, D-67)."""

from __future__ import annotations

import pytest

from .support import call
from .test_key_keyboard_control import press

pytestmark = pytest.mark.browser

PANEL = "#page-contents"
ENTRY = "#page-contents li"
SELECTED = "#page-contents li[aria-selected=true]"


def sections(count: int = 5) -> str:
    return "".join(
        f"<h{1 + i % 2} id=s{i}>Section {i}</h{1 + i % 2}>"
        f"<div style='height:900px'>text {i}</div>"
        for i in range(count)
    )


def chosen(owner) -> str:  # noqa: ANN001
    return owner.page.locator(SELECTED).inner_text()


def test_key_05_the_key_lists_the_headings_indented_by_level(make, owner) -> None:  # noqa: ANN001
    make(sections())
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    assert owner.page.locator(ENTRY).all_inner_texts() == [f"Section {i}" for i in range(5)]
    levels = owner.page.locator(ENTRY).evaluate_all("(l) => l.map((e) => e.dataset.level)")
    assert levels == ["1", "2", "1", "2", "1"]
    assert chosen(owner) == "Section 0"


def test_key_05_two_j_and_enter_scroll_to_the_third_heading_and_close(make, owner) -> None:  # noqa: ANN001
    make(sections())
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    press(owner, "j", "j")
    assert chosen(owner) == "Section 2"
    press(owner, "Enter")
    owner.page.locator(PANEL).wait_for(state="detached")
    owner.frame.wait_for_function("Math.abs(document.getElementById('s2').getBoundingClientRect().top) < 5")


def test_key_05_the_heading_in_view_is_selected_and_k_and_arrows_move(make, owner) -> None:  # noqa: ANN001
    make(sections())
    owner.frame.evaluate("window.scrollTo(0, document.getElementById('s3').offsetTop)")
    owner.page.wait_for_timeout(300)
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    assert chosen(owner) == "Section 3"
    press(owner, "k")
    assert chosen(owner) == "Section 2"
    press(owner, "ArrowDown", "ArrowDown", "ArrowDown")
    assert chosen(owner) == "Section 4"


def test_key_05_esc_and_the_key_again_close_without_moving(make, owner) -> None:  # noqa: ANN001
    make(sections())
    for closer in ("Escape", "o"):
        press(owner, "o")
        owner.page.locator(PANEL).wait_for()
        press(owner, "j", closer)
        owner.page.locator(PANEL).wait_for(state="detached")
        assert owner.frame.evaluate("window.scrollY") == 0


def test_key_05_a_click_does_what_enter_does(make, owner) -> None:  # noqa: ANN001
    make(sections())
    press(owner, "o")
    owner.page.locator(ENTRY).nth(4).click()
    owner.page.locator(PANEL).wait_for(state="detached")
    owner.frame.wait_for_function("Math.abs(document.getElementById('s4').getBoundingClientRect().top) < 5")


def test_key_05_a_page_without_headings_says_so(make, owner) -> None:  # noqa: ANN001
    make("<p>plain</p>")
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    assert "No headings" in owner.page.locator(PANEL).inner_text()
    press(owner, "Escape")
    owner.page.locator(PANEL).wait_for(state="detached")


def test_key_05_the_key_works_from_inside_the_frame_but_not_in_a_text_field(make, owner) -> None:  # noqa: ANN001
    make("<input id=t>" + sections())
    owner.frame.locator("#t").focus()
    press(owner, "o")
    owner.page.wait_for_timeout(300)
    assert owner.page.locator(PANEL).count() == 0
    owner.frame.evaluate("document.activeElement.blur()")
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()


def test_key_05_a_markdown_file_lists_its_headings(make, owner) -> None:  # noqa: ANN001
    first = make("<p>first</p>")
    (first.folder / "notes.md").write_text("# Top\n\ntext\n\n## Sub\n\n" + "x\n\n" * 200 + "# End\n\n" + "y\n\n" * 200)
    call(
        owner,
        "POST",
        f"/api/sessions/{first.sid}/show",
        json={"project": str(first.folder.parents[1]), "name": "notes.md"},
    )
    owner.frame.wait_for_selector("main.markdown h1")
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    assert owner.page.locator(ENTRY).all_inner_texts() == ["Top", "Sub", "End"]
    press(owner, "j", "j", "Enter")
    owner.page.locator(PANEL).wait_for(state="detached")
    owner.frame.wait_for_function(
        "Math.abs([...document.querySelectorAll('h1')].at(-1).getBoundingClientRect().top) < 40"
    )


def test_key_05_a_page_cannot_open_the_list_by_itself(make, owner) -> None:  # noqa: ANN001
    make(sections())
    owner.frame.evaluate(
        "parent.postMessage({type: 'contents', items: [{level: 1, text: 'forged'}], current: 0}, '*')"
    )
    owner.page.wait_for_timeout(300)
    assert owner.page.locator(PANEL).count() == 0


def test_key_05_the_key_is_in_the_key_map_and_the_overview(make, owner) -> None:  # noqa: ANN001
    make("<p>x</p>")
    assert owner.page.evaluate("keyMap.is('contents.open', 'o')")
    press(owner, "?")
    assert "table of contents" in owner.page.locator("#key-help").inner_text()


BLOCKS = (
    "<h1 id=first>Page start</h1>"
    "<canvas-markdown data-canvas-id=m><script type='text/markdown'>"
    "# Block heading\n\ntext\n\n## Block sub</script></canvas-markdown>"
    "<div style='height:900px'></div>"
    "<canvas-report data-canvas-id=r><script type='application/json'>"
    '{"type": "result", "title": "T", "text": "x"}</script>'
    "<canvas-markdown data-canvas-id=n><script type='text/markdown'>"
    "# Inside a card</script></canvas-markdown></canvas-report>"
    "<h2 id=last>Page end</h2><div style='height:900px'></div>"
)


def test_key_05_headings_inside_blocks_are_listed_in_page_order(make, owner) -> None:  # noqa: ANN001
    make(BLOCKS)
    owner.frame.wait_for_function("document.querySelector('canvas-markdown').shadowRoot.querySelector('h1')")
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    assert owner.page.locator(ENTRY).all_inner_texts() == [
        "Page start", "Block heading", "Block sub", "Inside a card", "Page end",
    ]  # fmt: skip
    press(owner, "j", "Enter")
    owner.page.locator(PANEL).wait_for(state="detached")
    owner.frame.wait_for_function(
        "Math.abs(document.querySelector('canvas-markdown').shadowRoot.querySelector('h1').getBoundingClientRect().top) < 5"
    )


def test_key_05_at_the_top_of_the_page_the_first_heading_is_selected(make, owner) -> None:  # noqa: ANN001
    make("<h1>One</h1><h2>Two</h2><h2>Three</h2><div style='height:2000px'></div>")
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    assert chosen(owner) == "One"


def test_key_05_a_page_that_does_not_answer_cannot_open_the_list_later(make, owner) -> None:  # noqa: ANN001
    make(sections())
    owner.page.evaluate("pageContents.ask(() => {})")
    owner.page.wait_for_timeout(2500)
    owner.frame.evaluate(
        "parent.postMessage({type: 'contents', items: [{level: 1, text: 'late'}], current: 0}, '*')"
    )
    owner.page.wait_for_timeout(300)
    assert owner.page.locator(PANEL).count() == 0


def test_key_05_malformed_entries_are_ignored(make, owner) -> None:  # noqa: ANN001
    make(sections())
    owner.page.evaluate(
        "pageContents.ask(() => {}); pageContents.onItems({items: [null, {level: 2}, {text: 'x'}, {level: 1, text: 'ok'}], current: 3})"
    )
    owner.page.locator(PANEL).wait_for()
    assert owner.page.locator(ENTRY).all_inner_texts() == ["ok"]


def test_key_05_an_update_of_the_page_closes_the_list(make, owner) -> None:  # noqa: ANN001
    made = make(sections())
    press(owner, "o")
    owner.page.locator(PANEL).wait_for()
    made.rewrite(sections(3))
    owner.page.locator(PANEL).wait_for(state="detached")
