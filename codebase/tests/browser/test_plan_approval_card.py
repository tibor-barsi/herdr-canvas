# ruff: noqa: F811, ANN001, E501
"""The approval card and the question card in the shared look (PLAN-01, PLAN-02, KIND-05).

A real ``agent-canvas ask --approval`` runs against the test hub and Playwright is
the owner. The card is drawn by the card module as an Ask.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from helpers import decode_png

from .support import SCROLL_PAGE
from .test_ask_cards import Asking, card_of, make  # noqa: F401
from .test_shell_update import (
    BANNER,
    mark_document,
    same_document,
    update_hub,
)

pytestmark = pytest.mark.browser

DETAILS = (
    "Intro <b>text</b>\n- first <i>step</i>\n- second\n1. one\n2. two\nclosing line"
)
LINE = re.compile(r"^(Approved \d\d:\d\d|Sent back \d\d:\d\d: .+)$")


def approval(make, sid: str, *extra: str, title: str = "Use plan B?") -> Asking:  # noqa: ANN001, F811
    return make.asking(title, "--approval", "--session", sid, *extra)


def line_of(owner) -> str:  # noqa: ANN001
    line = owner.page.locator("#ask-bar .ask-line")
    line.wait_for()
    return line.inner_text().replace("\u00d7", "").strip()


# ---- PLAN-01 ----------------------------------------------------------------------


def test_plan_01_the_card_shows_title_details_and_the_two_buttons_above_the_page(
    owner,
    make,  # noqa: ANN001, F811
) -> None:
    sid = make()
    ask = approval(make, sid, "--details", DETAILS)
    card = card_of(owner)
    card.wait_for()
    assert "Use plan B?" in card.inner_text()
    box, frame_box = card.bounding_box(), owner.page.locator("#frame").bounding_box()
    assert box["y"] + box["height"] <= frame_box["y"] + 1
    assert card.get_by_role("button", name="Approve", exact=True).is_visible()
    assert card.get_by_role("button", name="Send back…", exact=True).is_visible()
    shadow_text = card.locator(".ask-host").evaluate("h => h.shadowRoot.textContent")
    assert "Approve" in shadow_text and "always" not in shadow_text.lower()
    assert "always" not in card.inner_text().lower()
    assert card.locator(".kl").text_content() == "Needs you: Ask"
    card.get_by_role("button", name="Approve", exact=True).click()
    code, body = ask.finish()
    assert code == 0 and body["event"]["value"] == {"decision": "approved"}
    assert body["event"]["delivery"] == "ask"


def test_plan_01_details_show_lists_and_text_and_never_html(owner, make) -> None:  # noqa: ANN001, F811
    sid = make()
    ask = approval(make, sid, "--details", DETAILS)
    card = card_of(owner)
    card.wait_for()
    assert card.locator(".details ul > li").count() == 2
    assert card.locator(".details ol > li").count() == 2
    assert card.locator(".details p").count() == 2
    assert "Intro <b>text</b>" in card.locator(".details").inner_text()
    assert card.locator("b, i").count() == 0
    card.get_by_role("button", name="Approve", exact=True).click()
    ask.finish()


def test_plan_01_details_come_from_a_file(owner, make, tmp_path: Path) -> None:  # noqa: ANN001, F811
    sid = make()
    path = tmp_path / "plan.md"
    path.write_text("- from a file\n")
    ask = approval(make, sid, "--details-file", str(path))
    card = card_of(owner)
    card.wait_for()
    assert card.locator(".details li").inner_text() == "from a file"
    card.get_by_role("button", name="Approve", exact=True).click()
    ask.finish()


def test_plan_01_send_back_needs_a_reason_and_enter_sends_it(owner, make) -> None:  # noqa: ANN001, F811
    sid = make()
    ask = approval(make, sid)
    card = card_of(owner)
    card.wait_for()
    card.get_by_role("button", name="Send back…", exact=True).click()
    field = card.get_by_label("Reason for sending it back")
    assert field.get_attribute("maxlength") == "300"
    assert card.get_by_role("button", name="Send back", exact=True).is_disabled()
    field.press("Enter")  # empty: nothing is sent
    assert ask.process.poll() is None and card.count() == 1
    field.fill("too slow")
    field.press("Enter")
    code, body = ask.finish()
    assert code == 0
    assert body["event"]["value"] == {"decision": "sent-back", "reason": "too slow"}


def test_plan_01_escape_returns_to_the_buttons_and_keeps_the_ask_open(
    owner, make
) -> None:  # noqa: ANN001, F811
    sid = make()
    ask = approval(make, sid)
    card = card_of(owner)
    card.wait_for()
    card.get_by_role("button", name="Send back…", exact=True).click()
    card.get_by_label("Reason for sending it back").press("Escape")
    assert card.get_by_role("button", name="Approve", exact=True).is_visible()
    assert card.get_by_label("Reason for sending it back").count() == 0
    card.get_by_role("button", name="Approve", exact=True).click()
    assert ask.finish()[0] == 0


def test_plan_01_the_x_dismisses_the_ask_with_exit_7(owner, make) -> None:  # noqa: ANN001, F811
    sid = make()
    ask = approval(make, sid)
    card_of(owner).get_by_role("button", name="Dismiss question").click()
    code, body = ask.finish()
    assert code == 7 and body["reason"] == "owner"
    assert owner.page.locator("#ask-bar .ask-line").count() == 0


# ---- PLAN-02 ----------------------------------------------------------------------


def test_plan_02_an_approved_card_shrinks_to_one_line(owner, make) -> None:  # noqa: ANN001, F811
    sid = make()
    ask = approval(make, sid, "--details", DETAILS)
    card_of(owner).get_by_role("button", name="Approve", exact=True).click()
    ask.finish()
    text = line_of(owner)
    assert LINE.match(text) and text.startswith("Approved ")
    assert owner.page.locator("#ask-bar .ask-card").count() == 0
    assert owner.page.locator("#ask-bar .ask-line").bounding_box()["height"] < 60


def test_plan_02_a_sent_back_line_carries_the_reason_as_text(owner, make) -> None:  # noqa: ANN001, F811
    sid = make()
    ask = approval(make, sid)
    card = card_of(owner)
    card.get_by_role("button", name="Send back…", exact=True).click()
    card.get_by_label("Reason for sending it back").fill("use <b>C</b> instead")
    card.get_by_role("button", name="Send back", exact=True).click()
    ask.finish()
    text = line_of(owner)
    assert LINE.match(text) and text.endswith(": use <b>C</b> instead")
    assert owner.page.locator("#ask-bar .ask-line b").count() == 0


def test_plan_02_the_line_stays_over_a_tab_visit_until_x_or_the_next_card(
    owner, make
) -> None:  # noqa: ANN001, F811
    first = make(name="one")
    ask = approval(make, first)
    card_of(owner).get_by_role("button", name="Approve", exact=True).click()
    ask.finish()
    line_of(owner)
    other = make(name="two")
    assert owner.page.locator("#ask-bar .ask-line").count() == 0  # another session
    owner.page.locator(f'.hv-pill[data-session="{first}"]').click()
    assert line_of(owner).startswith("Approved")
    # the next card of the session replaces it
    second = approval(make, first, title="And plan C?")
    card_of(owner).wait_for()
    assert owner.page.locator("#ask-bar .ask-line").count() == 0
    card_of(owner).get_by_role("button", name="Approve", exact=True).click()
    second.finish()
    line_of(owner)
    owner.page.locator("#ask-bar .ask-line").get_by_role("button", name="Close").click()
    assert owner.page.locator("#ask-bar .ask-line").count() == 0
    assert other


def test_plan_02_a_question_card_leaves_no_line(owner, make) -> None:  # noqa: ANN001, F811
    sid = make()
    ask = make.asking("Which?", "--choice", "A", "--session", sid)
    card_of(owner).get_by_role("button", name="A", exact=True).click()
    ask.finish()
    owner.page.wait_for_function("document.querySelectorAll('.ask-card').length === 0")
    assert owner.page.locator("#ask-bar .ask-line").count() == 0


# ---- SHELL-04 ---------------------------------------------------------------------


def test_shell_04_a_send_back_reason_being_typed_keeps_the_shell(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    ask = Asking(studio.owner, studio.tmp_path, "Plan?", "--approval", "--session", sid)
    try:
        card = studio.page.locator("#ask-bar .ask-card")
        card.get_by_role("button", name="Send back…", exact=True).click()
        field = card.get_by_label("Reason for sending it back")
        field.fill("not yet")
        mark_document(studio.page)
        update_hub(studio)
        studio.page.wait_for_selector(BANNER, state="visible", timeout=20000)
        assert same_document(studio.page)
        assert field.input_value() == "not yet"
    finally:
        ask.process.kill()
        ask.process.wait()
        ask.process.stdout.close()
        ask.process.stderr.close()


def test_shell_04_an_untouched_approval_card_does_not_hold_the_shell_back(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    ask = Asking(studio.owner, studio.tmp_path, "Plan?", "--approval", "--session", sid)
    try:
        studio.page.locator("#ask-bar .ask-card").wait_for()
        assert studio.page.evaluate("window.shellUpdate.hasUnsaved()") is False
    finally:
        ask.process.kill()
        ask.process.wait()
        ask.process.stdout.close()
        ask.process.stderr.close()


# ---- KIND-05 ----------------------------------------------------------------------

ASK_PAGE = """<!doctype html><title>t</title>
<canvas-ask data-canvas-id="q1"><script type="application/json">
{"question": "Use plan B?", "form": "approve"}</script></canvas-ask>"""


def light(pixel: tuple[int, ...]) -> float:
    return (pixel[0] * 299 + pixel[1] * 587 + pixel[2] * 114) / 1000


def head_pixels(owner, selector: str, directory: Path, name: str, frame: bool):  # noqa: ANN001, ANN201
    """Screenshot the left part of a head line (past the rounded corner) and return its pixel rows."""
    locator = (owner.frame if frame else owner.page).locator(selector).first
    box = locator.bounding_box()
    clip = {"x": box["x"] + 24, "y": box["y"], "width": 300, "height": box["height"]}
    png = directory / name
    owner.page.screenshot(path=str(png), clip=clip)
    return decode_png(png.read_bytes())


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_kind_05_the_head_line_of_the_shell_card_equals_that_of_the_page_card(
    owner,
    make,  # noqa: ANN001, F811
    tmp_path: Path,
    scheme: str,
) -> None:
    owner.page.emulate_media(color_scheme=scheme)
    sid = make(ASK_PAGE)
    owner.frame.locator("canvas-ask .kh").wait_for()
    ask = approval(make, sid)
    card_of(owner).wait_for()
    # let the glow of both cards settle at the same phase: the head line is not animated
    page_head = head_pixels(owner, "canvas-ask .kh", tmp_path, "page.png", frame=True)
    shell_head = head_pixels(owner, "#ask-bar .kh", tmp_path, "shell.png", frame=False)
    assert page_head[:2] == shell_head[:2]
    pairs = [
        (x, y)
        for left, right in zip(page_head[2], shell_head[2], strict=True)
        for x, y in zip(left, right, strict=True)
    ]
    # Text in the shell may be drawn with sub-pixel colour fringes and in the frame in grey
    # (seen on `work`): only a lightness change of more than 60 of 255 is a difference.
    assert sum(abs(light(x) - light(y)) > 60 for x, y in pairs) / len(pairs) <= 0.01
    page_style = owner.frame.locator("canvas-ask .kt").evaluate(
        "e => [e.textContent, getComputedStyle(e).color, getComputedStyle(e).fontSize]"
    )
    shell_style = owner.page.locator("#ask-bar .kt").evaluate(
        "e => [e.textContent, getComputedStyle(e).color, getComputedStyle(e).fontSize]"
    )
    assert page_style == shell_style
    card = card_of(owner)
    directory = os.environ.get("KINDS_LOOK_DIR")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        card.screenshot(path=str(Path(directory) / f"approval-{scheme}.png"))
        shutil.copy(
            tmp_path / "shell.png", Path(directory) / f"head-shell-{scheme}.png"
        )
        shutil.copy(tmp_path / "page.png", Path(directory) / f"head-page-{scheme}.png")
    card.get_by_role("button", name="Approve", exact=True).click()
    ask.finish()


CONTRAST_JS = """(root) => {
  const parse = (c) => c.match(/[\\d.]+/g).slice(0, 4).map(Number);
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + .05) / (y + .05); };
  const back = (el) => { for (let e = el; e; e = e.parentNode.host || e.parentElement) {
    const c = parse(getComputedStyle(e).backgroundColor); if (c[3] !== 0) return c; } return [255, 255, 255]; };
  const out = [];
  for (const el of root.querySelectorAll('.kl, .kt, .q, button')) {
    if (!el.textContent.trim()) continue;
    out.push([el.textContent.trim(), ratio(parse(getComputedStyle(el).color), back(el))]);
  }
  return out; }"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_kind_05_the_text_of_the_shell_card_has_contrast_4_5(
    owner, make, scheme: str
) -> None:  # noqa: ANN001, F811
    owner.page.emulate_media(color_scheme=scheme)
    sid = make()
    ask = approval(make, sid, "--details", "- one")
    card_of(owner).wait_for()
    host = owner.page.locator("#ask-bar .ask-host")
    found = host.evaluate(f"(h) => ({CONTRAST_JS})(h.shadowRoot)")
    assert len(found) >= 4
    assert [f for f in found if f[1] < 4.5] == [], found
    card_of(owner).get_by_role("button", name="Approve", exact=True).click()
    ask.finish()
