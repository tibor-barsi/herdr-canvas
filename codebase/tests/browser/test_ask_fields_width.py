# ruff: noqa: E501
"""A parameter form uses the width of the card, at any window width (ASK-07, #65)."""

from __future__ import annotations

import pytest

from .support import block
from .test_ask_point_fields import wait_ask

pytestmark = pytest.mark.browser

LONG = (
    "Replace the bearing housing on the left support before the next measurement series"
)
OPTIONS = ["approve", "later", "no"]
MIXED = [
    {"id": "a", "label": LONG, "type": "one", "value": "later", "options": OPTIONS},
    {"id": "b", "label": LONG + " again", "type": "text", "value": "hello"},
    {
        "id": "c",
        "label": LONG + " once more",
        "type": "number",
        "value": 2,
        "unit": "mm",
    },
    {
        "id": "d",
        "label": "Use the refined mesh near the contact surface",
        "type": "onoff",
        "value": True,
    },
    {"id": "e", "label": "Short", "type": "one", "value": "later", "options": OPTIONS},
]
SHORT = [
    {
        "id": f"f{n}",
        "label": f"Mesh {n}",
        "type": "one",
        "value": "later",
        "options": OPTIONS,
    }
    for n in range(3)
]


def show(owner, make, fields: list[dict], width: int, scheme: str = "light") -> None:  # noqa: ANN001
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.set_viewport_size({"width": width, "height": 900})
    config = {"form": "fields", "question": "Which?", "fields": fields}
    make(block("canvas-ask", "q", config))
    wait_ask(owner)


def measure(owner) -> dict:  # noqa: ANN001
    """Edges of the card's content box, and of each row's label and control."""
    return owner.frame.evaluate(
        """() => { const r = document.querySelector('canvas-ask').shadowRoot;
          const k = r.querySelector('.k'), kb = k.getBoundingClientRect(), cs = getComputedStyle(k);
          const inner = kb.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
          const rows = [...r.querySelectorAll('.field')].map((row) => {
            const l = row.querySelector('label').getBoundingClientRect();
            const c = row.querySelector('input, select').getBoundingClientRect();
            const u = row.querySelector('.meta');
            const unit = u ? u.getBoundingClientRect() : null;
            return {unitRight: unit && unit.right, unitTop: unit && unit.top, controlTop: c.top,
                    labelLeft: l.left, labelRight: l.right, labelHeight: l.height,
                    controlLeft: c.left, controlRight: c.right, width: c.width};
          });
          return {inner, line: parseFloat(cs.lineHeight), rows}; }"""
    )


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [900, 700, 500])
def test_ask_07_labels_and_controls_stay_inside_the_card(
    owner, make, width, scheme
) -> None:  # noqa: ANN001
    show(owner, make, MIXED, width, scheme)
    got = measure(owner)
    for row in got["rows"]:
        assert row["labelRight"] <= got["inner"] + 0.5, got
        assert row["controlRight"] <= got["inner"] + 0.5, got
        if row["unitRight"] is not None:
            assert row["unitRight"] <= got["inner"] + 0.5, got
            assert abs(row["unitTop"] - row["controlTop"]) < 10, got


@pytest.mark.parametrize(("width", "lines"), [(900, 2.2), (700, 3.2)])
def test_ask_07_a_long_label_uses_the_free_width(owner, make, width, lines) -> None:  # noqa: ANN001
    show(owner, make, MIXED, width)
    got = measure(owner)
    assert got["rows"][0]["labelHeight"] / got["line"] <= lines, got


def test_ask_07_controls_keep_their_natural_width(owner, make) -> None:  # noqa: ANN001
    show(owner, make, SHORT, 900)
    narrow = measure(owner)["rows"][0]["width"]
    show(owner, make, MIXED, 900)
    widths = [row["width"] for row in measure(owner)["rows"]]
    assert widths[4] == pytest.approx(narrow, abs=1), widths
    assert widths[1] > widths[4], widths


def test_ask_07_short_labels_keep_the_control_near_14em(owner, make) -> None:  # noqa: ANN001
    show(owner, make, SHORT, 900)
    row = measure(owner)["rows"][0]
    assert row["controlLeft"] - row["labelLeft"] == pytest.approx(
        14 * 14.7 + 12, abs=15
    ), row


@pytest.mark.parametrize("width", [900, 500])
def test_ask_07_changing_a_field_moves_no_label_or_control_sideways(
    owner, make, width
) -> None:  # noqa: ANN001
    show(owner, make, MIXED, width)
    before = measure(owner)["rows"]
    owner.frame.locator("canvas-ask select").first.select_option("no")
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.field.changed')"
    )
    after = measure(owner)["rows"]
    for was, now in zip(before, after, strict=True):
        for key in ("labelLeft", "labelRight", "controlLeft", "controlRight"):
            assert now[key] == pytest.approx(was[key], abs=0.5), (was, now)
