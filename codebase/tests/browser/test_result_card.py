# ruff: noqa: F811, ANN001, E501
"""The result card in the shell and on the home row (RES-02, RES-03, KIND-05).

A real hub stores the card through its route with the key; Playwright is the owner who
clicks it. The head lines are compared with those of the page's cards (KIND-05).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from .test_ask_cards import call, make  # noqa: F401
from .test_plan_approval_card import head_pixels, light

pytestmark = pytest.mark.browser

SUMMARY = "Re-fitted modes 1-4.\nSecond line, never on the home row."
REPORT_PAGE = """<!doctype html><title>t</title>
<canvas-report data-canvas-id="r1"><script type="application/json">
{"type": "result", "title": "Re-fitted"}</script></canvas-report>
<canvas-ask data-canvas-id="q1"><script type="application/json">
{"question": "Use plan B?", "form": "approve"}</script></canvas-ask>"""


def store(owner, sid: str, **fields) -> dict:
    body = {"summary": SUMMARY, **fields}
    return call(owner, "POST", f"/api/sessions/{sid}/result", json=body)


def decision(owner, sid: str, **fields) -> dict:
    return store(
        owner, sid, decision="Repeat run 15?", choices=["Keep", "Drop"], **fields
    )


def card_of(owner):
    return owner.page.locator("#ask-bar .result-card")


def decisions(owner, sid: str) -> list[dict]:
    return [e for e in owner.hub.state.events.all(sid) if e["kind"] == "decision"]


# ---- RES-02 ------------------------------------------------------------------------


def test_res_02_the_card_shows_summary_chips_decision_and_dismiss_above_the_page(
    owner,
    make,
) -> None:
    sid = make()
    folder = owner.hub.state.session_of(sid).folder
    decision(owner, sid, files=[str(folder / "page.html"), "/abs/out.csv"])
    card = card_of(owner)
    card.wait_for()
    assert card.locator(".kl").first.text_content() == "Report: result"
    text = card.locator(".k.report").inner_text()
    assert (
        "Re-fitted modes 1-4." in text and "One decision left: Repeat run 15?" in text
    )
    assert card.get_by_role("button", name="Keep", exact=True).is_visible()
    assert card.get_by_role("button", name="Drop", exact=True).is_visible()
    assert card.get_by_role("button", name="Dismiss", exact=True).is_visible()
    assert card.get_by_role("button", name="page.html", exact=True).is_visible()
    assert card.get_by_role("button", name="out.csv", exact=True).is_visible()
    box, frame_box = card.bounding_box(), owner.page.locator("#frame").bounding_box()
    assert box["y"] + box["height"] <= frame_box["y"] + 1


def test_res_03_the_decision_part_says_decision_waiting_and_the_first_line_is_bold(
    owner, make
) -> None:
    sid = make()
    decision(owner, sid)
    card = card_of(owner)
    card.wait_for()
    assert "decision waiting" in card.locator(".k.need .kt").text_content()
    assert "waits for you" not in card.locator(".k.report").inner_text()
    first = card.locator(".k.report .q").first
    assert first.text_content() == "Re-fitted modes 1-4."
    assert first.evaluate("e => getComputedStyle(e).fontWeight") == "650"
    assert (
        "Second line, never on the home row." in card.locator(".k.report").inner_text()
    )


def test_res_02_agent_text_is_never_html(owner, make) -> None:
    sid = make()
    decision(owner, sid, summary="<b>bold</b> <img src=x onerror=alert(1)>")
    card_of(owner).wait_for()
    assert "<b>bold</b>" in card_of(owner).locator(".k.report").inner_text()
    assert card_of(owner).locator("b, img").count() == 0


def test_res_02_a_choice_makes_one_decision_event_and_the_card_shrinks(
    owner, make
) -> None:
    sid = make()
    card_id = decision(owner, sid)["result"]
    card = card_of(owner)
    card.wait_for()
    card.get_by_role("button", name="Keep", exact=True).click()
    card.get_by_text("Decided: Keep").wait_for()
    (event,) = decisions(owner, sid)
    assert (event["value"], event["delivery"], event["target"]) == ("Keep", "now", None)
    assert event["result"] == card_id
    assert card.get_by_role("button", name="Keep", exact=True).count() == 0
    assert card.get_by_role("button", name="Dismiss", exact=True).count() == 0


def test_res_02_dismiss_closes_the_card_and_creates_no_event(owner, make) -> None:
    sid = make()
    decision(owner, sid)
    card = card_of(owner)
    card.wait_for()
    card.get_by_role("button", name="Dismiss", exact=True).click()
    card.wait_for(state="detached")
    assert owner.hub.state.events.all(sid) == []


def test_res_02_a_decided_card_closes_with_its_cross_and_a_replacement_comes_back(
    owner,
    make,
) -> None:
    sid = make()
    decision(owner, sid)
    card_of(owner).get_by_role("button", name="Keep", exact=True).click()
    card_of(owner).get_by_text("Decided: Keep").wait_for()
    card_of(owner).get_by_role("button", name="Close the result").click()
    card_of(owner).wait_for(state="detached")
    store(owner, sid, summary="Second")
    card_of(owner).get_by_text("Second").wait_for()


def test_res_02_a_card_without_decision_has_no_ask_part(owner, make) -> None:
    sid = make()
    store(owner, sid)
    card_of(owner).wait_for()
    assert card_of(owner).locator(".k.ask").count() == 0
    assert card_of(owner).get_by_role("button", name="Dismiss").is_visible()


def test_res_02_a_chip_of_a_page_opens_that_page_and_another_chip_copies_its_path(
    owner,
    make,
) -> None:
    sid = make("<p>first</p>")
    folder = owner.hub.state.session_of(sid).folder
    (folder / "second.html").write_text("<title>s</title><p>second</p>")
    call(
        owner,
        "POST",
        f"/api/sessions/{sid}/show",
        json={"project": str(folder.parent.parent), "name": "second.html"},
    )
    owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    store(owner, sid, files=[str(folder / "page.html"), "/abs/out.csv"])
    card = card_of(owner)
    card.wait_for()
    owner.page.wait_for_function("document.title.length > 0")
    card.get_by_role("button", name="page.html", exact=True).click()
    owner.page.wait_for_function(
        "document.querySelector('#frame').src.includes('page.html')"
    )
    card.get_by_role("button", name="out.csv", exact=True).click()
    card.get_by_role("button", name="Copied", exact=True).wait_for()
    assert owner.page.evaluate("navigator.clipboard.readText()") == "/abs/out.csv"


def test_res_02_the_card_belongs_to_its_session(owner, make) -> None:
    first = make(name="alpha")
    second = make(name="beta")
    decision(owner, first)
    owner.visit(first)
    card_of(owner).wait_for()
    owner.visit(second)
    card_of(owner).wait_for(state="detached")
    owner.visit(first)
    card_of(owner).wait_for()


# ---- KIND-05 -----------------------------------------------------------------------


def differing(first, second) -> float:
    assert first[:2] == second[:2]
    pairs = [
        (x, y)
        for left, right in zip(first[2], second[2], strict=True)
        for x, y in zip(left, right, strict=True)
    ]
    return sum(abs(light(x) - light(y)) > 60 for x, y in pairs) / len(pairs)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_kind_05_the_head_lines_of_the_result_card_equal_those_of_the_page_cards(
    owner,
    make,
    tmp_path: Path,
    scheme: str,
) -> None:
    owner.page.emulate_media(color_scheme=scheme)
    sid = make(REPORT_PAGE)
    owner.frame.locator("canvas-report .kh").wait_for()
    decision(owner, sid)
    card_of(owner).wait_for()
    page_report = head_pixels(
        owner, "canvas-report .kh", tmp_path, "pr.png", frame=True
    )
    shell_report = head_pixels(
        owner, "#ask-bar .result-card .k.report > .kh", tmp_path, "sr.png", frame=False
    )
    page_ask = head_pixels(owner, "canvas-ask .kh", tmp_path, "pa.png", frame=True)
    shell_ask = head_pixels(
        owner, "#ask-bar .result-card .k.ask > .kh", tmp_path, "sa.png", frame=False
    )
    assert differing(page_report, shell_report) <= 0.01
    assert differing(page_ask, shell_ask) <= 0.01
    directory = os.environ.get("KINDS_LOOK_DIR")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        card_of(owner).screenshot(path=str(Path(directory) / f"result-{scheme}.png"))
        shutil.copy(tmp_path / "sr.png", Path(directory) / f"head-result-{scheme}.png")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_kind_05_the_head_line_of_the_question_card_equals_that_of_the_page_card(
    owner,
    make,
    tmp_path: Path,
    scheme: str,
) -> None:
    owner.page.emulate_media(color_scheme=scheme)
    sid = make(REPORT_PAGE)
    owner.frame.locator("canvas-ask .kh").wait_for()
    ask = make.asking("Which layout?", "--choice", "A", "--session", sid)
    owner.page.locator("#ask-bar .ask-card").wait_for()
    page_ask = head_pixels(owner, "canvas-ask .kh", tmp_path, "pa.png", frame=True)
    shell_ask = head_pixels(
        owner, "#ask-bar .ask-card .kh", tmp_path, "sq.png", frame=False
    )
    assert differing(page_ask, shell_ask) <= 0.01
    owner.page.locator("#ask-bar .ask-card").get_by_role("button", name="A").click()
    ask.finish()
