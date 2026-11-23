# ruff: noqa: E501
"""The Ask element: seven forms, validation, default, answered line, Change (ASK-01 to ASK-04).

Fixture: ``tests/fixtures/kinds/asks.html``. Answers travel the real way: frame,
shell relay, hub, stored item, back to the card.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from helpers import CODEBASE_DIR

from .support import call
from .test_look_window import headless, look  # noqa: F401

pytestmark = pytest.mark.browser

ASKS = (CODEBASE_DIR / "tests" / "fixtures" / "kinds" / "asks.html").read_text()
LINE = re.compile(r"^Answered \d\d:\d\d: ")


def card(owner, card_id: str) -> str:  # noqa: ANN001
    return f"[data-canvas-id={card_id}]"


def wait_asks(owner) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        """() => { const all = [...document.querySelectorAll('canvas-ask')];
          return all.length > 0 && all.every((e) => e.renderIdle && e.shadowRoot
            && e.shadowRoot.querySelector('.k, .block-error')); }"""
    )


def text_of(owner, card_id: str, selector: str) -> str:  # noqa: ANN001
    return owner.frame.evaluate(
        "([id, s]) => document.querySelector(`[data-canvas-id=${id}]`)"
        ".shadowRoot.querySelector(s).textContent",
        [card_id, selector],
    )


def pulsing(owner, card_id: str) -> bool:  # noqa: ANN001
    return owner.frame.evaluate(
        "(id) => document.querySelector(`[data-canvas-id=${id}]`)"
        ".shadowRoot.querySelector('.k').classList.contains('pulse')",
        card_id,
    )


def wait_line(owner, card_id: str) -> str:  # noqa: ANN001
    owner.frame.wait_for_function(
        """(id) => { const l = document.querySelector(`[data-canvas-id=${id}]`)
          .shadowRoot.querySelector('.said'); return l && l.textContent.startsWith('Answered'); }""",
        arg=card_id,
    )
    return text_of(owner, card_id, ".said")


def answers(made) -> list[dict]:  # noqa: ANN001
    return [e for e in made.events if e["kind"] == "answer"]


@pytest.fixture
def asks(owner, make):  # noqa: ANN001, ANN201
    shown = make(ASKS)
    wait_asks(owner)
    return shown


def click(owner, card_id: str, selector: str) -> None:  # noqa: ANN001
    owner.frame.locator(f"[data-canvas-id={card_id}] {selector}").first.click()


def answer_of(owner, made, count: int = 1) -> dict:  # noqa: ANN001
    return made.wait_events(count)[count - 1 if count else 0]["value"]


# ---- ASK-01: the forms render their controls ---------------------------------------------


def controls(owner, card_id: str) -> dict:  # noqa: ANN001
    return owner.frame.evaluate(
        """(id) => { const r = document.querySelector(`[data-canvas-id=${id}]`).shadowRoot;
          return {
            buttons: [...r.querySelectorAll('.answer button')].map((b) => b.textContent.trim()),
            opts: [...r.querySelectorAll('.opt')].map((b) => b.dataset.id),
            roles: [...new Set([...r.querySelectorAll('.opt')].map((b) => b.getAttribute('role')))],
            textarea: r.querySelectorAll('textarea').length,
            number: r.querySelectorAll('input[type=number]').length,
            text: r.querySelector('.kb').textContent };
        }""",
        card_id,
    )


def test_ask_01_yesno_offers_yes_no_and_a_note(owner, asks) -> None:  # noqa: ANN001
    found = controls(owner, "a-yesno")
    assert found["buttons"] == ["Yes", "No", "Add a note"]


def test_ask_01_one_offers_radio_options_other_and_a_note(owner, asks) -> None:  # noqa: ANN001
    found = controls(owner, "a-one")
    assert found["roles"] == ["radio"]
    assert found["opts"] == ["gyroid", "lines", "cubic", "other"]  # recommended first
    assert "Add a note" in found["buttons"] and "Answer" in found["buttons"]


def test_ask_01_the_recommended_option_has_its_mark(owner, asks) -> None:  # noqa: ANN001
    first = text_of(owner, "a-one", ".opt")
    assert "recommended" in first and "Gyroid" in first and "stiffer" in first
    assert text_of(owner, "a-one", ".kb").count("recommended") == 1


def test_ask_01_several_offers_checkboxes_other_and_a_note(owner, asks) -> None:  # noqa: ANN001
    found = controls(owner, "a-several")
    assert found["roles"] == ["checkbox"]
    assert found["opts"] == ["PLA", "PETG", "ASA", "TPU", "other"]
    assert "Add a note" in found["buttons"]


def test_ask_01_text_offers_a_field_and_a_note(owner, asks) -> None:  # noqa: ANN001
    found = controls(owner, "a-text")
    assert found["textarea"] == 1 and found["opts"] == []
    assert "Answer" in found["buttons"] and "Add a note" in found["buttons"]


def test_ask_01_number_offers_a_number_field_with_its_unit(owner, asks) -> None:  # noqa: ANN001
    found = controls(owner, "a-number")
    assert found["number"] == 1 and "mm" in found["text"]
    assert "Answer" in found["buttons"] and "Add a note" in found["buttons"]


def test_ask_01_confirm_offers_keep_and_change(owner, asks) -> None:  # noqa: ANN001
    assert controls(owner, "a-confirm")["buttons"] == ["Keep", "Change…", "Add a note"]


def test_ask_01_approve_offers_approve_and_send_back_inside_a_report(
    owner, asks
) -> None:  # noqa: ANN001
    assert controls(owner, "a-approve")["buttons"] == [
        "Approve",
        "Send back…",
        "Add a note",
    ]
    assert not owner.frame.evaluate(
        "() => document.querySelector('[data-canvas-id=r-plan]').shadowRoot.querySelector('.block-error')"
    )


def test_ask_01_no_form_without_options_is_text_and_with_options_is_one(
    owner, make
) -> None:  # noqa: ANN001
    make(
        '<canvas-ask data-canvas-id="t"><script type="application/json">{"question": "Why?"}</script></canvas-ask>'
        '<canvas-ask data-canvas-id="o"><script type="application/json">{"question": "Which?", "options": ["a", "b"]}</script></canvas-ask>'
    )
    wait_asks(owner)
    assert controls(owner, "t")["textarea"] == 1
    assert controls(owner, "o")["roles"] == ["radio"]


def test_ask_01_a_one_with_one_option_and_an_unknown_key_show_the_error_box(
    owner, asks
) -> None:  # noqa: ANN001
    assert "2 to 8 options" in text_of(owner, "e-one", ".block-error")
    assert 'unknown config key "colour"' in text_of(owner, "e-key", ".block-error")


@pytest.mark.parametrize(
    "config",
    [
        '{"question": "q", "options": ["a", "b"], "recommended": "z"}',
        '{"question": "q", "form": "several", "options": ["a", "a"]}',
        '{"question": "q", "form": "number", "min": 5, "max": 1}',
        '{"question": "q", "form": "dial"}',
        '{"form": "text"}',
    ],
)
def test_ask_01_other_bad_configs_show_the_error_box(owner, make, config) -> None:  # noqa: ANN001
    make(
        f'<canvas-ask data-canvas-id="b"><script type="application/json">{config}</script></canvas-ask>'
    )
    wait_asks(owner)
    assert text_of(owner, "b", ".block-error").startswith("canvas-ask:")


# ---- ASK-02: one answer event per Ask, the value per form ---------------------------------


def test_ask_02_yesno_value(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-yesno", "button:text-is('Yes')")
    value = answer_of(owner, asks)
    assert value == {
        "question": "Is the bed clean?", "form": "yesno", "answer": "yes",
        "other": None, "note": None, "replaces": None,
    }  # fmt: skip


def test_ask_02_one_value_and_the_event_targets_the_element(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-one", ".opt[data-id=lines]")
    click(owner, "a-one", "button.submit")
    [event] = asks.wait_events(1)
    assert event["target"]["canvas_id"] == "a-one" and event["kind"] == "answer"
    assert event["value"]["answer"] == ["lines"] and event["value"]["form"] == "one"


def test_ask_02_several_value_follows_the_option_order(owner, asks) -> None:  # noqa: ANN001
    for option in ("ASA", "PLA"):
        click(owner, "a-several", f".opt[data-id={option}]")
    click(owner, "a-several", "button.submit")
    assert answer_of(owner, asks)["answer"] == ["PLA", "ASA"]


def test_ask_02_text_value(owner, asks) -> None:  # noqa: ANN001
    owner.frame.locator(f"{card(owner, 'a-text')} textarea").first.fill("Bracket A")
    click(owner, "a-text", "button.submit")
    assert answer_of(owner, asks)["answer"] == "Bracket A"


def test_ask_02_number_value_is_a_number(owner, asks) -> None:  # noqa: ANN001
    owner.frame.locator(f"{card(owner, 'a-number')} input[type=number]").fill("12.5")
    click(owner, "a-number", "button.submit")
    assert answer_of(owner, asks)["answer"] == 12.5


def test_ask_02_confirm_keep_value(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-confirm", "button:text-is('Keep')")
    assert answer_of(owner, asks)["answer"] == "keep"


def test_ask_02_confirm_change_sends_the_reason_on_enter(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-confirm", "button:text-is('Change…')")
    field = owner.frame.locator(f"{card(owner, 'a-confirm')} input[type=text]")
    field.fill("use 0.6 mm")
    field.press("Enter")
    assert answer_of(owner, asks)["answer"] == {"change": "use 0.6 mm"}


def test_ask_02_approve_value_is_plan_01s(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-approve", "button:text-is('Approve')")
    assert answer_of(owner, asks)["answer"] == {"decision": "approved"}


def test_ask_02_approve_send_back_needs_a_reason_and_esc_returns_to_the_buttons(
    owner, asks
) -> None:  # noqa: ANN001
    click(owner, "a-approve", "button:text-is('Send back…')")
    field = owner.frame.locator(f"{card(owner, 'a-approve')} input[type=text]")
    field.press("Enter")  # empty: sends nothing
    owner.page.wait_for_timeout(300)
    assert answers(asks) == []
    field.press("Escape")
    assert controls(owner, "a-approve")["buttons"][:2] == ["Approve", "Send back…"]
    click(owner, "a-approve", "button:text-is('Send back…')")
    field = owner.frame.locator(f"{card(owner, 'a-approve')} input[type=text]")
    field.fill("wider please")
    field.press("Enter")
    assert answer_of(owner, asks)["answer"] == {
        "decision": "sent-back",
        "reason": "wider please",
    }


def test_ask_02_other_and_a_note_travel_with_the_answer(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-several", ".opt[data-id=PETG]")
    click(owner, "a-several", ".opt[data-id=other]")
    owner.frame.locator(f"{card(owner, 'a-several')} input[type=text]").fill("nylon")
    click(owner, "a-several", "button:text-is('Add a note')")
    owner.frame.locator(f"{card(owner, 'a-several')} textarea").fill("but dry")
    click(owner, "a-several", "button.submit")
    value = answer_of(owner, asks)
    assert (value["answer"], value["other"], value["note"]) == (
        ["PETG"],
        "nylon",
        "but dry",
    )


def test_ask_02_a_note_travels_with_a_button_answer(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-yesno", "button:text-is('Add a note')")
    owner.frame.locator(f"{card(owner, 'a-yesno')} textarea").fill("ok")
    click(owner, "a-yesno", "button:text-is('No')")
    assert answer_of(owner, asks)["note"] == "ok"


def disabled_reason(owner, card_id: str) -> tuple[bool, str]:  # noqa: ANN001
    return tuple(
        owner.frame.evaluate(
            """(id) => { const r = document.querySelector(`[data-canvas-id=${id}]`).shadowRoot;
              return [r.querySelector('button.submit').disabled, r.querySelector('.reason').textContent]; }""",
            card_id,
        )
    )


def test_ask_02_a_number_outside_its_limits_keeps_answer_disabled_with_the_reason(
    owner, asks
) -> None:  # noqa: ANN001
    field = owner.frame.locator(f"{card(owner, 'a-number')} input[type=number]")
    field.fill("25")
    assert disabled_reason(owner, "a-number") == (True, "between 0 and 20 mm")
    field.fill("-1")
    assert disabled_reason(owner, "a-number") == (True, "between 0 and 20 mm")
    field.fill("20")
    assert disabled_reason(owner, "a-number") == (False, "")
    field.fill("")
    assert disabled_reason(owner, "a-number")[0] is True


def test_ask_02_each_form_with_one_answer_button_says_why_it_is_disabled(
    owner, asks
) -> None:  # noqa: ANN001
    assert disabled_reason(owner, "a-text") == (True, "type an answer")
    assert disabled_reason(owner, "a-several") == (True, "pick at least one option")
    click(owner, "a-several", ".opt[data-id=other]")
    assert disabled_reason(owner, "a-several") == (True, "type your other answer")
    click(owner, "a-one", ".opt[data-id=other]")
    assert disabled_reason(owner, "a-one") == (True, "type your other answer")
    click(owner, "a-one", ".opt[data-id=lines]")
    assert disabled_reason(owner, "a-one") == (False, "")


def test_ask_02_one_answer_per_ask_even_when_pressed_twice(owner, asks) -> None:  # noqa: ANN001
    owner.frame.evaluate(
        "() => { const e = document.querySelector('[data-canvas-id=a-yesno]'); e.send('yes'); e.send('yes'); }"
    )
    asks.wait_events(1)
    owner.page.wait_for_timeout(700)
    assert len(answers(asks)) == 1
    click(owner, "a-text", "textarea")
    owner.frame.locator(f"{card(owner, 'a-text')} textarea").fill("x")
    owner.frame.locator(f"{card(owner, 'a-text')} button.submit").dblclick()
    owner.page.wait_for_timeout(700)
    assert len(answers(asks)) == 2


# ---- ASK-03: the default ------------------------------------------------------------------


def test_ask_03_the_head_line_words_with_and_without_a_default(owner, asks) -> None:  # noqa: ANN001
    assert text_of(owner, "a-one", ".kt") == "waits for you"
    assert (
        text_of(owner, "a-default", ".kt") == "goes on with flat unless you change it"
    )
    assert (
        text_of(owner, "a-confirm", ".kt")
        == "goes on with 0.4 mm nozzle unless you change it"
    )
    assert pulsing(owner, "a-default")  # A-86: an open Ask pulses, default or not


def test_ask_03_only_an_ask_without_default_counts_as_waiting(owner, asks) -> None:  # noqa: ANN001
    listing = call(owner, "GET", f"/api/sessions/{asks.sid}/answers")["items"]
    waits = {row["id"]: row["waits"] for row in listing}
    assert waits["a-one"] is True and waits["a-default"] is False
    assert waits["a-confirm"] is False


def test_ask_03_the_default_is_filled_in_and_answerable_at_any_time(
    owner, asks
) -> None:  # noqa: ANN001
    assert disabled_reason(owner, "a-default") == (False, "")
    click(owner, "a-default", ".opt[data-id=upright]")
    click(owner, "a-default", "button.submit")
    assert answer_of(owner, asks)["answer"] == ["upright"]


# ---- ASK-04: the answered line, its receipt and Change ----------------------------------


def test_ask_04_an_answered_ask_shrinks_to_one_line_with_receipt_and_change(
    owner, asks
) -> None:  # noqa: ANN001
    click(owner, "a-one", ".opt[data-id=lines]")
    click(owner, "a-one", "button.submit")
    said = wait_line(owner, "a-one")
    assert LINE.match(said) and said.endswith(": Lines")
    assert "not read by the agent yet" in text_of(owner, "a-one", ".receipt")
    assert controls(owner, "a-one")["buttons"] == ["Change"]
    assert "prints faster" not in text_of(owner, "a-one", ".kb")  # the form is gone
    assert not pulsing(owner, "a-one")
    assert pulsing(owner, "a-text")


def test_ask_04_the_line_is_drawn_from_the_store_after_a_reload(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-yesno", "button:text-is('No')")
    asks.wait_events(1)
    said = wait_line(owner, "a-yesno")
    owner.page.reload()
    owner.visit(asks.sid)
    wait_asks(owner)
    assert wait_line(owner, "a-yesno") == said
    assert said.endswith(": no") and not pulsing(owner, "a-yesno")
    assert len(answers(asks)) == 1


def test_ask_04_the_receipt_turns_to_read_once_the_agent_lists_the_answers(
    owner, asks
) -> None:  # noqa: ANN001
    click(owner, "a-yesno", "button:text-is('Yes')")
    wait_line(owner, "a-yesno")
    call(owner, "GET", f"/api/sessions/{asks.sid}/answers")
    owner.frame.wait_for_function(
        """() => document.querySelector('[data-canvas-id=a-yesno]').shadowRoot
          .querySelector('.receipt').textContent.startsWith('read by the agent')"""
    )


def test_ask_04_change_reopens_the_form_filled_and_the_next_answer_replaces_the_first(
    owner, asks
) -> None:  # noqa: ANN001
    click(owner, "a-one", ".opt[data-id=lines]")
    click(owner, "a-one", "button.submit")
    first = asks.wait_events(1)[0]
    wait_line(owner, "a-one")
    click(owner, "a-one", "button.link")
    checked = owner.frame.evaluate(
        "() => [...document.querySelector('[data-canvas-id=a-one]').shadowRoot"
        ".querySelectorAll('.opt[aria-checked=true]')].map((b) => b.dataset.id)"
    )
    assert checked == ["lines"]
    assert not pulsing(owner, "a-one")
    click(owner, "a-one", ".opt[data-id=cubic]")
    click(owner, "a-one", "button.submit")
    second = asks.wait_events(2)[1]
    assert (
        second["value"]["replaces"] == first["id"]
        and first["value"]["replaces"] is None
    )
    owner.frame.wait_for_function(
        """() => document.querySelector('[data-canvas-id=a-one]').shadowRoot
          .querySelector('.said')?.textContent.endsWith('cubic')"""
    )
    listing = call(owner, "GET", f"/api/sessions/{asks.sid}/answers")["items"]
    row = next(r for r in listing if r["id"] == "a-one")
    assert row["answer"]["answer"] == ["cubic"] and row["event"] == second["id"]


def test_ask_04_the_line_names_other_and_the_note(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-several", ".opt[data-id=ASA]")
    click(owner, "a-several", ".opt[data-id=other]")
    owner.frame.locator(f"{card(owner, 'a-several')} input[type=text]").fill("nylon")
    click(owner, "a-several", "button:text-is('Add a note')")
    owner.frame.locator(f"{card(owner, 'a-several')} textarea").fill("dry")
    click(owner, "a-several", "button.submit")
    said = wait_line(owner, "a-several")
    assert said.endswith(": ASA, Other: nylon · note: dry")


def test_ask_04_a_changed_question_opens_the_ask_again(owner, asks) -> None:  # noqa: ANN001
    click(owner, "a-yesno", "button:text-is('Yes')")
    wait_line(owner, "a-yesno")
    asks.rewrite(ASKS.replace("Is the bed clean?", "Is the bed really clean?"))
    owner.frame.wait_for_function(
        "() => document.querySelector('[data-canvas-id=a-yesno]').shadowRoot.textContent.includes('really')"
    )
    owner.frame.wait_for_function(
        "() => document.querySelector('[data-canvas-id=a-yesno]').shadowRoot.querySelector('.kt').textContent === 'waits for you'"
    )
    assert pulsing(owner, "a-yesno")


# ---- the look: contrast in both modes, open and answered ---------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_ask_look_the_contrast_check_finds_nothing_open_or_answered(
    owner,
    asks,
    headless,  # noqa: F811
    scheme: str,  # noqa: ANN001, F811
) -> None:
    directory = os.environ.get("KINDS_LOOK_DIR")
    for stage in ("open", "answered"):
        if stage == "answered":
            click(owner, "a-yesno", "button:text-is('Yes')")
            click(owner, "a-one", ".opt[data-id=lines]")
            click(owner, "a-one", "button.submit")
            click(owner, "a-confirm", "button:text-is('Keep')")
            asks.wait_events(3)
            wait_line(owner, "a-confirm")
        result = look(owner, asks.sid, width=900, height=900, scheme=scheme, full=True)
        findings = result["audit"]["findings"]
        assert [f for f in findings if f["rule"] == "contrast"] == [], findings
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            shutil.copy(result["png"], Path(directory) / f"asks-{stage}-{scheme}.png")
