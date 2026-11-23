"""canvas-file and canvas-source: Copy and Open, the status and doubt, links that never navigate (CNT-03, CNT-04)."""

# ruff: noqa: E501
from __future__ import annotations

import json

import pytest

from .support import block

pytestmark = pytest.mark.browser

LONG_NOTE = "Raw results of run 4, 2 % noise"
SOURCE = "Handbook p. 4, see https://example.org/handbook and [doc](https://example.org/doc) <a href='https://example.org/z'>z</a>"


def wait_blocks(studio, tag: str, count: int = 1) -> None:  # noqa: ANN001
    studio.frame.wait_for_function(
        """([tag, n]) => { const all = [...document.querySelectorAll(tag)];
          return all.length === n && all.every((e) => e.renderIdle && e.shadowRoot
            && e.shadowRoot.querySelector('.block')); }""",
        arg=[tag, count],
    )


def show(studio, build, files: dict | None = None) -> None:  # noqa: ANN001
    """Make the session, then rewrite the page with ``build(folder)`` (the folder is known only now)."""
    studio.owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    studio.make("<p>start</p>", files=files)
    folder = str(studio.folder)
    (studio.folder / "page.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        + build(folder)
        + "</body></html>"
    )
    studio.frame.wait_for_function(
        "document.querySelector('canvas-file, canvas-source')"
    )
    studio.frame.wait_for_function(
        "window.agentCanvas.sessionFolder && !!window.agentCanvas.answerItems"
    )


def card(studio, tag: str, selector: str):  # noqa: ANN001, ANN201
    return studio.frame.locator(f"{tag} {selector}")


def clipboard(studio) -> str:  # noqa: ANN001
    return studio.page.evaluate("navigator.clipboard.readText()")


def active_page(studio) -> str:  # noqa: ANN001
    return json.loads((studio.folder / "session.json").read_text())["active_page"]


def files_page(folder: str) -> str:
    inside = f"{folder}/notes.md"
    cards = [
        ("f-out", {"path": "/data/run 4/result.csv", "note": LONG_NOTE, "size": "2.1 MB",
                   "date": "2026-11-09", "machine": "work"}),
        ("f-in", {"path": inside}),
        ("f-pdf", {"path": f"{folder}/report.pdf"}),
        ("f-img", {"path": f"{folder}/shot.png"}),
        ("f-py", {"path": f"{folder}/tool.py"}),
        ("f-sub", {"path": f"{folder}/sub/inner.md"}),
        ("f-else", {"path": "/tmp/elsewhere/notes.md"}),
        ("f-nodot", {"path": f"{folder}/README"}),
    ]  # fmt: skip
    return "".join(block("canvas-file", name, config) for name, config in cards)


FILES = {
    "notes.md": "# note\n",
    "report.pdf": b"%PDF-1.4\n",
    "shot.png": b"\x89PNG\r\n",
}


def one(studio, name: str):  # noqa: ANN001, ANN201
    return studio.frame.locator(f'canvas-file[data-canvas-id="{name}"]')


def wait_all(studio) -> None:  # noqa: ANN001
    wait_blocks(studio, "canvas-file", 8)


def open_buttons(studio, name: str) -> int:  # noqa: ANN001
    return one(studio, name).locator('button:text-is("Open")').count()


# ---- CNT-03 ----------------------------------------------------------------------------


def test_cnt_03_the_card_shows_badge_name_folder_facts_and_note(studio) -> None:  # noqa: ANN001
    show(studio, files_page, FILES)
    wait_all(studio)
    text = one(studio, "f-out").locator(".block").inner_text()
    assert "result.csv" in text and "/data/run 4" in text and LONG_NOTE in text
    assert "2.1 MB · 2026-11-09 · work" in text
    assert one(studio, "f-out").locator(".file-badge").inner_text() == "CSV"
    assert one(studio, "f-nodot").locator(".file-badge").inner_text() == "FILE"


def test_cnt_03_copy_puts_exactly_the_absolute_path_on_the_clipboard(studio) -> None:  # noqa: ANN001
    show(studio, files_page, FILES)
    wait_all(studio)
    studio.page.evaluate("navigator.clipboard.writeText('before')")
    one(studio, "f-out").locator('button:text-is("Copy")').click()
    studio.page.wait_for_selector("#copied.visible")
    assert clipboard(studio) == "/data/run 4/result.csv"
    assert studio.page.inner_text("#copied") == "Copied: /data/run 4/result.csv"


def test_cnt_03_open_shows_only_for_viewer_types_directly_in_the_session_folder(
    studio,  # noqa: ANN001
) -> None:
    show(studio, files_page, FILES)
    wait_all(studio)
    assert [open_buttons(studio, n) for n in ("f-in", "f-pdf", "f-img")] == [1, 1, 1]
    for refused in ("f-out", "f-py", "f-sub", "f-else", "f-nodot"):
        assert open_buttons(studio, refused) == 0, refused


def test_cnt_03_open_shows_the_file_as_a_page(studio) -> None:  # noqa: ANN001
    show(studio, files_page, FILES)
    wait_all(studio)
    assert active_page(studio) == "page.html"
    one(studio, "f-in").locator('button:text-is("Open")').click()
    studio.page.wait_for_function(
        "document.getElementById('frame').src.includes('notes.md')"
    )
    assert active_page(studio) == "notes.md"


def test_cnt_03_a_file_card_with_a_relative_path_is_an_error_box(studio) -> None:  # noqa: ANN001
    show(studio, lambda _: block("canvas-file", "bad", {"path": "data/result.csv"}))
    studio.frame.wait_for_function(
        "document.querySelector('canvas-file').shadowRoot.querySelector('.block-error')"
    )
    assert "absolute" in studio.frame.locator("canvas-file .block-error").inner_text()


def test_cnt_03_a_path_the_page_file_does_not_hold_is_not_copied(studio) -> None:  # noqa: ANN001
    show(studio, files_page, FILES)
    wait_all(studio)
    studio.page.evaluate("navigator.clipboard.writeText('before')")
    for message in (
        {"type": "copy", "kind": "path", "text": "/etc/passwd"},
        {
            "type": "copy",
            "kind": "path",
            "text": f"{studio.folder}/notes.md-not-written",
        },
        {"type": "copy", "kind": "source", "text": "/data/run 4/result.csv"},
        {"type": "copy", "kind": "other", "text": "/data/run 4/result.csv"},
        {"type": "copy", "kind": "path"},
        {"type": "copy", "kind": "path", "text": 5},
    ):
        studio.page.evaluate("(m) => privateMessage(m)", message)
        studio.page.wait_for_timeout(1100)  # past the one-a-second gap of the shell
    assert clipboard(studio) == "before"
    # Positive control: the same message with the written path copies it.
    studio.page.evaluate(
        "(m) => privateMessage(m)",
        {"type": "copy", "kind": "path", "text": "/data/run 4/result.csv"},
    )
    # The refusals above left "Copy failed: ..." in the note (A-441).
    studio.page.wait_for_function(
        "document.getElementById('copied').textContent.startsWith('Copied:')"
    )
    assert clipboard(studio) == "/data/run 4/result.csv"


def test_cnt_03_a_path_changed_in_the_dom_by_page_script_is_not_copied(studio) -> None:  # noqa: ANN001
    show(studio, files_page, FILES)
    wait_all(studio)
    studio.page.evaluate("navigator.clipboard.writeText('before')")
    studio.frame.evaluate(
        """() => { const s = document.querySelector('[data-canvas-id="f-out"] > script');
          s.textContent = s.textContent.replace('/data/run 4/result.csv', '/etc/shadow'); }"""
    )
    studio.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=\"f-out\"]').shadowRoot.textContent.includes('shadow')"
    )
    one(studio, "f-out").locator('button:text-is("Copy")').click()
    studio.page.wait_for_timeout(1000)
    assert clipboard(studio) == "before"


# ---- CNT-04 ----------------------------------------------------------------------------


def source_page(_: str) -> str:
    cases = [
        ("s-ok", {"claim": "E = 70 GPa", "source": SOURCE, "status": "verified", "quote": "Table 2: E = 70 GPa"}),
        ("s-default", {"claim": "Poisson 0.33", "source": "Handbook p. 5"}),
        ("s-bad", {"claim": "Yield 300 MPa", "source": "Supplier mail", "status": "disputed"}),
    ]  # fmt: skip
    return "".join(block("canvas-source", name, config) for name, config in cases)


def source(studio, name: str):  # noqa: ANN001, ANN201
    return studio.frame.locator(f'canvas-source[data-canvas-id="{name}"]')


def test_cnt_04_claim_source_status_word_and_a_folded_quote(studio) -> None:  # noqa: ANN001
    show(studio, source_page)
    wait_blocks(studio, "canvas-source", 3)
    ok = source(studio, "s-ok")
    assert ok.locator(".src-claim").inner_text() == "E = 70 GPa"
    assert ok.locator(".src-text").inner_text() == SOURCE
    assert ok.locator(".src-status").inner_text().endswith("verified")
    assert (
        source(studio, "s-default")
        .locator(".src-status")
        .inner_text()
        .endswith("not checked")
    )
    assert (
        source(studio, "s-bad").locator(".src-status").inner_text().endswith("disputed")
    )
    marks = [
        source(studio, n).locator(".src-mark").inner_text()
        for n in ("s-ok", "s-default", "s-bad")
    ]
    assert len(set(marks)) == 3
    assert not ok.locator("blockquote").is_visible()
    ok.locator("summary").click()
    assert ok.locator("blockquote").inner_text() == "Table 2: E = 70 GPa"
    assert source(studio, "s-default").locator("details").count() == 0


def test_cnt_04_copy_puts_the_source_line_on_the_clipboard(studio) -> None:  # noqa: ANN001
    show(studio, source_page)
    wait_blocks(studio, "canvas-source", 3)
    source(studio, "s-ok").locator('button:text-is("Copy")').click()
    studio.page.wait_for_selector("#copied.visible")
    assert clipboard(studio) == SOURCE


def test_cnt_04_a_link_in_the_source_is_shown_and_never_followed(studio) -> None:  # noqa: ANN001
    show(studio, source_page)
    wait_blocks(studio, "canvas-source", 3)
    ok = source(studio, "s-ok")
    assert (
        studio.frame.evaluate(
            "document.querySelector('[data-canvas-id=\"s-ok\"]').shadowRoot.querySelectorAll('a, [href]').length"
        )
        == 0
    )
    url = studio.page.evaluate("document.getElementById('frame').src")
    ok.locator(".src-text").click()
    ok.locator(".src-text").dblclick()
    studio.page.wait_for_timeout(500)
    assert studio.page.evaluate("document.getElementById('frame').src") == url
    assert studio.owner.foreign_requests == []
    assert studio.frame.evaluate("location.href") == url


def test_cnt_04_doubt_opens_a_one_line_field_and_sends_a_text_event(studio) -> None:  # noqa: ANN001
    show(studio, source_page)
    wait_blocks(studio, "canvas-source", 3)
    sid = studio.page.evaluate("activeId")
    ok = source(studio, "s-ok")
    assert ok.locator("input").count() == 0
    ok.locator('button:text-is("Doubt this…")').click()
    field = ok.locator("input")
    field.wait_for()
    assert ok.locator('button:text-is("Send")').is_disabled()
    field.fill("The table is for 6061, not 7075")
    field.press("Enter")
    ok.locator('[role="status"]').wait_for()
    [event] = [e for e in studio.wait_events(sid, 1) if e["kind"] == "text"]
    assert event["value"] == "The table is for 6061, not 7075"
    assert event["target"]["canvas_id"] == "s-ok"
    assert "Doubt sent" in ok.locator(".block").inner_text()
    assert source(studio, "s-bad").locator("input").count() == 0


def test_cnt_04_cancel_closes_the_field_and_sends_nothing(studio) -> None:  # noqa: ANN001
    show(studio, source_page)
    wait_blocks(studio, "canvas-source", 3)
    sid = studio.page.evaluate("activeId")
    ok = source(studio, "s-default")
    ok.locator('button:text-is("Doubt this…")').click()
    ok.locator("input").fill("typed")
    ok.locator('button:text-is("Cancel")').click()
    ok.locator('button:text-is("Doubt this…")').wait_for()
    studio.page.wait_for_timeout(300)
    assert [e for e in studio.events(sid) if e["kind"] == "text"] == []


@pytest.mark.parametrize(
    ("config", "problem"),
    [
        ({"claim": "x"}, "source"),
        ({"source": "x"}, "claim"),
        ({"claim": "x", "source": "y", "status": "sure"}, "status"),
    ],
)
def test_cnt_04_a_wrong_config_is_an_error_box(studio, config, problem) -> None:  # noqa: ANN001
    show(studio, lambda _: block("canvas-source", "bad", config))
    studio.frame.wait_for_function(
        "document.querySelector('canvas-source').shadowRoot.querySelector('.block-error')"
    )
    assert problem in studio.frame.locator("canvas-source .block-error").inner_text()


def test_cnt_04_a_source_line_the_page_does_not_hold_is_not_copied(studio) -> None:  # noqa: ANN001
    show(studio, source_page)
    wait_blocks(studio, "canvas-source", 3)
    studio.page.evaluate("navigator.clipboard.writeText('before')")
    studio.page.evaluate(
        "(m) => privateMessage(m)",
        {"type": "copy", "kind": "source", "text": "Handbook p. 99"},
    )
    studio.page.wait_for_timeout(1000)
    assert clipboard(studio) == "before"
