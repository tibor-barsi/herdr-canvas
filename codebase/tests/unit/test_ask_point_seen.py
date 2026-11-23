"""A point Ask is keyed by the data of the block it points at (ASK-05, F7)."""

from __future__ import annotations

import json

import pytest

from agent_canvas.hub.answers import AnswerStore, scan

pytestmark = pytest.mark.unit

POINT = {"form": "point", "question": "Which peak?"}


def page(data: list[int], form: str = "point") -> str:
    plot = json.dumps({"traces": [{"x": [1, 2, 3], "y": data}]})
    ask = json.dumps({**POINT, "form": form})
    return (
        '<canvas-ask data-canvas-id="q">'
        f'<script type="application/json">{ask}</script>'
        '<canvas-plot data-canvas-id="spectrum">'
        f'<script type="application/json">{plot}</script></canvas-plot></canvas-ask>'
    )


def key(html: str) -> str:
    return scan(html).items["q"].key


def test_ask_05_f7_a_point_asks_key_changes_with_the_data_of_its_block() -> None:
    assert key(page([1, 5, 2])) == key(page([1, 5, 2]))
    assert key(page([1, 5, 2])) != key(page([1, 6, 2]))


def test_ask_05_f7_the_key_of_the_client_seen_config_equals_the_hubs() -> None:
    plot = {"traces": [{"x": [1, 2, 3], "y": [1, 5, 2]}]}
    seen = {**POINT, "_child": plot}
    assert AnswerStore.key_of("ask", seen) == key(page([1, 5, 2]))
    assert AnswerStore.key_of("ask", POINT) != key(page([1, 5, 2]))


def test_ask_05_f7_other_asks_keep_the_keys_they_had() -> None:
    config = '{"question": "Which peak?", "form": "one", "options": ["a"]}'
    plain = (
        '<canvas-ask data-canvas-id="q"><script type="application/json">'
        f"{config}</script></canvas-ask>"
    )
    with_plot = page([1, 5, 2], form="one")
    assert key(with_plot) == key(page([9, 9, 9], form="one"))
    old = AnswerStore.key_of(
        "ask", {"question": "Which peak?", "form": "one", "options": ["a"]}
    )
    assert key(plain) == old
