"""Page checks for interaction mistakes, rule `interaction` (AGI-15 to AGI-19)."""

from __future__ import annotations

import pytest

from .test_page_checks import block, findings_of, look

pytestmark = pytest.mark.browser

ASK = block(
    "canvas-ask",
    {"question": "Which infill?", "options": ["gyroid", "lines"]},
    "q1",
)


def titled(body: str, title: str = "Test page") -> str:
    """A readable page with a ``<title>``."""
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        f"<title>{title}</title><style>body{{font:16px system-ui;color:#111;"
        f"background:#fff}}</style></head><body>{body}</body></html>"
    )


def interaction(owner, make, html: str) -> list[dict]:  # noqa: ANN001
    """The `interaction` findings of a page."""
    made = make(html)
    found = findings_of(look(owner, made.sid, width=800, height=600))
    return [f for f in found if f["rule"] == "interaction"]


HAND_MADE = {
    "button": "<p>Pick one</p><button id=go>Option A</button>",
    "input": '<p>Name</p><input id=f type="text">',
    "textarea": "<p>Why</p><textarea id=f></textarea>",
    "select": "<select id=f><option>a</option><option>b</option></select>",
}


@pytest.mark.parametrize("name", list(HAND_MADE))
def test_agi_15_hand_made_buttons_and_fields_warn(owner, make, name: str) -> None:  # noqa: ANN001
    [hit] = interaction(owner, make, titled(HAND_MADE[name]))
    assert hit["severity"] == "warn"
    assert "canvas-ask" in hit["message"]
    assert "ignore this" in hit["message"]


def test_agi_15_many_hand_made_controls_give_one_warning(owner, make) -> None:  # noqa: ANN001
    body = "<button>a</button><button>b</button><input><textarea></textarea>"
    assert len(interaction(owner, make, titled(body))) == 1


def test_agi_15_the_blocks_own_controls_do_not_warn(owner, make) -> None:  # noqa: ANN001
    textbox = block("canvas-textbox", {"label": "Why?"}, "why")
    buttons = block("canvas-buttons", {"buttons": [{"id": "go", "label": "Go"}]}, "b")
    assert interaction(owner, make, titled(ASK + textbox + buttons)) == []


def test_agi_16_choices_with_submit_warn(owner, make) -> None:  # noqa: ANN001
    choices = block(
        "canvas-choices",
        {
            "options": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            "submit": "Send",
        },
        "c",
    )
    [hit] = interaction(owner, make, titled(choices))
    assert hit["severity"] == "warn"
    assert "canvas-choices" in hit["message"] and "canvas-ask" in hit["message"]


def test_agi_16_choices_without_submit_do_not_warn(owner, make) -> None:  # noqa: ANN001
    choices = block(
        "canvas-choices",
        {"options": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]},
        "c",
    )
    assert interaction(owner, make, titled(choices)) == []


def test_agi_17_a_question_in_prose_without_an_answer_field_warns(owner, make) -> None:  # noqa: ANN001
    body = "<p>Gyroid is stiffer. Which infill should I use for the bracket?</p>"
    [hit] = interaction(owner, make, titled(body))
    assert hit["severity"] == "warn"
    assert "canvas-ask" in hit["message"]


@pytest.mark.parametrize(
    "body",
    [
        "<p>Gyroid is stiffer and lines are faster.</p>",
        "<h2>Why does it matter?</h2><p>Gyroid is stiffer.</p>",
        "<p>Which infill should I use for the bracket?</p>" + ASK,
        "<pre>what is this thing, really?</pre>",
        "<p>Is gyroid really stiffer than lines in this bracket?</p>"
        "<p>Yes: it carries 30 percent more load in the test.</p>",
        "<ul><li>Is it safe to reprint the part today?</li>"
        "<li>Who signs off the new print settings?</li></ul>"
        "<p>The log answers both.</p>",
        "<p>The reviewer asked: is it strong enough for the field?</p>"
        "<p>The test run says it holds 8.4 kN.</p>",
    ],
    ids=["no-question", "heading", "with-ask", "code", "rhetorical", "faq", "quoted"],
)
def test_agi_17_no_warning_without_a_prose_question(owner, make, body: str) -> None:  # noqa: ANN001
    assert interaction(owner, make, titled(body)) == []


def test_agi_17_a_final_question_in_a_section_warns_though_text_follows_elsewhere(
    owner, make
) -> None:  # noqa: ANN001
    body = (
        "<section><p>Is gyroid really stiffer than lines here?</p></section>"
        "<section><p>Other results follow in this part.</p></section>"
    )
    assert len(interaction(owner, make, titled(body))) == 1


def test_agi_15_a_slider_driving_a_page_is_allowed_for_by_the_message(
    owner, make
) -> None:  # noqa: ANN001
    body = "<input type=range id=speed><p>Speed filter for the plot.</p>"
    [hit] = interaction(owner, make, titled(body))
    assert "only change this page" in hit["message"]


def test_agi_17_a_prose_question_beside_hand_made_fields_gets_only_the_field_warning(
    owner, make
) -> None:  # noqa: ANN001
    body = "<p>Which infill should I use for the bracket?</p><input id=f>"
    [hit] = interaction(owner, make, titled(body))
    assert "field" in hit["message"] or "button" in hit["message"]


def test_agi_18_two_questions_in_one_ask_warn(owner, make) -> None:  # noqa: ANN001
    two = block(
        "canvas-ask",
        {"question": "Which infill? And at what speed?", "options": ["a", "b"]},
        "q2",
    )
    [hit] = interaction(owner, make, titled(two))
    assert hit["severity"] == "warn"
    assert "q2" in hit["where"] and "one question" in hit["message"]


def test_agi_18_one_question_does_not_warn(owner, make) -> None:  # noqa: ANN001
    one = block(
        "canvas-ask",
        {"question": "Is https://x.org/a?b=1 the right link?", "options": ["a", "b"]},
        "q3",
    )
    assert interaction(owner, make, titled(one)) == []


def test_agi_19_a_missing_title_warns(owner, make) -> None:  # noqa: ANN001
    html = titled(ASK).replace("<title>Test page</title>", "")
    [hit] = interaction(owner, make, html)
    assert hit["severity"] == "warn"
    assert "<title>" in hit["message"]


def test_agi_19_a_title_does_not_warn(owner, make) -> None:  # noqa: ANN001
    assert interaction(owner, make, titled(ASK)) == []
