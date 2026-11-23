"""Fixes of the M31 review that go through `look` and the answer relay: F7, F10 (ASK-05, ANS-02, LOOK-01)."""

# ruff: noqa: E501, F811
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from .support import block
from .test_ask_point_fields import FORM, QUESTION, plot_ask, submit, wait_ask
from .test_heavy_blocks import plot_config, wait_plot
from .test_look_window import decoded, headless, look  # noqa: F401

pytestmark = pytest.mark.browser

LOOK_DIR = os.environ.get("M31_FIX_LOOK_DIR")


def test_ans_02_f10_look_shows_an_answered_ask_as_answered(
    owner, make, headless
) -> None:  # noqa: ANN001
    made = make(block("canvas-ask", "f", FORM))
    wait_ask(owner)
    before = look(owner, made.sid, width=700, height=500)
    submit(owner).click()
    made.wait_events(1)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.said')"
    )
    after = look(owner, made.sid, width=700, height=500)
    assert decoded(before) != decoded(after)
    if LOOK_DIR:
        Path(LOOK_DIR).mkdir(parents=True, exist_ok=True)
        shutil.copy(after["png"], Path(LOOK_DIR) / "look-answered.png")
        shutil.copy(before["png"], Path(LOOK_DIR) / "look-open.png")


def test_ask_05_f7_a_point_made_on_data_that_changed_since_is_refused(
    owner, make
) -> None:  # noqa: ANN001
    from .test_ask_point_fields import click_data

    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 3, 35)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point"
    )
    changed = plot_config()
    changed["data"][0]["y"] = [v + 1 for v in changed["data"][0]["y"]]
    made.rewrite(plot_ask().replace(_plot_json(plot_config()), _plot_json(changed)))
    owner.frame.wait_for_function(
        "(y) => JSON.stringify(document.querySelector('canvas-plot').readConfig().data[0].y) === y",
        arg=str(changed["data"][0]["y"]).replace(" ", ""),
    )
    submit(owner).click()
    owner.page.wait_for_selector("#notice.visible")
    assert "changed since you saw it" in owner.page.inner_text("#notice")
    assert made.events == []


def _plot_json(config: dict) -> str:
    import json

    return json.dumps(config)


def test_ask_05_f7_the_question_still_answers_when_nothing_changed(owner, make) -> None:  # noqa: ANN001
    from .test_ask_point_fields import answer_value, click_data

    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 3, 35)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point"
    )
    submit(owner).click()
    assert answer_value(made)["answer"] == {"trace": 0, "index": 3, "x": 3, "y": 35}
    assert QUESTION["form"] == "point"
