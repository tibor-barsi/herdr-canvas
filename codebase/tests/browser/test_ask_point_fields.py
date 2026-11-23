# ruff: noqa: E501
"""The Ask answered by pointing and the parameter form (ASK-05, ASK-06).

An Ask of form ``point`` takes the click of its one child block (plot, image,
model, scene) as the answer; form ``fields`` is a labelled form that marks the
changed fields. Answers travel the real way: frame, shell relay, hub.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from .solids import cube_stl
from .support import block
from .test_comment_kinds import click_at, pick, save_box, what
from .test_comment_layer import comment_file
from .test_heavy_blocks import (
    IMAGE_H,
    IMAGE_W,
    MODEL_SIZE,
    data_to_page,
    image_file,
    image_rect,
    plot_config,
    point_is_on_cube,
    to_window,
    wait_image,
    wait_model,
    wait_plot,
)
from .test_look_window import headless, look  # noqa: F401
from .test_scene_block import FILES, parts_of, scene_page, screen_point, wait_scene

pytestmark = pytest.mark.browser

QUESTION = {"form": "point", "question": "Which peak?"}


def ask_over(child: str, **config) -> str:  # noqa: ANN003
    return block("canvas-ask", "q", {**QUESTION, **config}, extra=child)


def plot_ask(**config) -> str:  # noqa: ANN003
    return ask_over(block("canvas-plot", "spectrum", plot_config()), **config)


def wait_ask(owner) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "() => { const e = document.querySelector('canvas-ask');"
        " return !!(e && e.renderIdle && e.shadowRoot.querySelector('.k, .block-error')); }"
    )


def ask_eval(owner, expression: str):  # noqa: ANN001, ANN201
    return owner.frame.evaluate(
        f"(() => {{ const ask = document.querySelector('canvas-ask'); {expression} }})()"
    )


def submit(owner):  # noqa: ANN001, ANN201
    return owner.frame.locator("canvas-ask button.submit")


def click_data(owner, x: float, y: float) -> None:  # noqa: ANN001
    px, py = to_window(owner, *data_to_page(owner.frame, "spectrum", x, y))
    owner.page.mouse.move(px - 3, py - 3)
    owner.page.wait_for_timeout(120)  # Plotly throttles hover to one update per 50 ms
    owner.page.mouse.click(px, py)


def point_notes(owner) -> list[dict]:  # noqa: ANN001
    return owner.frame.evaluate(
        "(document.querySelector('canvas-plot').gd.layout.annotations || [])"
        ".filter((n) => n.name === 'ac-point').map((n) => ({x: n.x, y: n.y}))"
    )


def answer_value(made) -> dict:  # noqa: ANN001
    return next(e for e in made.wait_events(1) if e["kind"] == "answer")["value"]


# ---- ASK-05: a plot ----------------------------------------------------------------


def test_ask_05_a_click_on_the_plot_is_the_answer_and_waits_for_answer(
    owner, make
) -> None:  # noqa: ANN001
    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    assert submit(owner).is_disabled()
    assert submit(owner).get_attribute("title") == "click a point on the plot"
    click_data(owner, 3, 35)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point"
    )
    assert submit(owner).is_enabled()
    assert "Your point: trace 0, point 3 (x 3, y 35)" in ask_eval(
        owner, "return ask.shadowRoot.querySelector('.point-line').textContent;"
    )
    assert made.events == []  # nothing is sent before Answer
    submit(owner).click()
    value = answer_value(made)
    assert value["form"] == "point" and value["question"] == "Which peak?"
    assert value["answer"] == {"trace": 0, "index": 3, "x": 3, "y": 35}
    event = next(e for e in made.events if e["kind"] == "answer")
    assert event["target"]["canvas_id"] == "q"


def test_ask_05_the_click_is_taken_over_and_records_no_plot_click(owner, make) -> None:  # noqa: ANN001
    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 3, 35)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point"
    )
    assert made.wait_action("plot-click", 0) == []


def test_ask_05_the_mark_sits_at_the_point_and_a_new_click_moves_it(
    owner, make
) -> None:  # noqa: ANN001
    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 3, 35)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-plot').gd.layout.annotations"
    )
    assert point_notes(owner) == [{"x": 3, "y": 35}]
    click_data(owner, 7, 35)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-plot').gd.layout.annotations.some((n) => n.x === 7)"
    )
    assert point_notes(owner) == [{"x": 7, "y": 35}]
    submit(owner).click()
    assert answer_value(made)["answer"]["index"] == 7


def test_ask_05_the_answered_line_names_the_point_and_the_mark_stays(
    owner, make
) -> None:  # noqa: ANN001
    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 5, 90)
    submit(owner).click()
    made.wait_events(1)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.said')"
    )
    line = ask_eval(owner, "return ask.shadowRoot.querySelector('.said').textContent;")
    assert "trace 0, point 5 (x 5, y 90)" in line
    assert point_notes(owner) == [{"x": 5, "y": 90}]
    # Change reopens the Ask: the point is still there and Answer is enabled.
    owner.frame.locator("canvas-ask button.link", has_text="Change").click()
    assert submit(owner).is_enabled()
    click_data(owner, 6, 60)
    submit(owner).click()
    second = made.wait_events(2)[1]["value"]
    assert second["answer"]["index"] == 6 and second["replaces"]


def test_ask_05_the_mark_survives_a_rewrite_of_the_plot(owner, make) -> None:  # noqa: ANN001
    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 3, 35)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-plot').gd.layout.annotations"
    )
    config = plot_config()
    config["layout"]["title"] = {"text": "rewritten"}
    made.rewrite(ask_over(block("canvas-plot", "spectrum", config)))
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-plot').gd.layout.title"
        " && document.querySelector('canvas-plot').gd.layout.title.text === 'rewritten'"
    )
    assert point_notes(owner) == [{"x": 3, "y": 35}]


def test_ask_05_the_plot_keeps_its_own_click_after_the_ask_is_answered(
    owner, make
) -> None:  # noqa: ANN001
    made = make(plot_ask())
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 5, 90)
    submit(owner).click()
    made.wait_events(1)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.said')"
    )
    click_data(owner, 2, 20)
    [action] = made.wait_action("plot-click")
    assert action["value"] == {"trace": 0, "index": 2, "x": 2, "y": 20}
    assert point_notes(owner) == [{"x": 5, "y": 90}]  # the answer's mark did not move


def test_ask_05_a_plot_inside_another_form_keeps_its_own_click(owner, make) -> None:  # noqa: ANN001
    made = make(plot_ask(form="text"))
    wait_plot(owner)
    wait_ask(owner)
    click_data(owner, 4, 60)
    [action] = made.wait_action("plot-click")
    assert action["value"]["index"] == 4
    assert point_notes(owner) == []


def test_ask_05_comment_mode_still_selects_on_the_plot_and_answers_nothing(
    studio,
) -> None:  # noqa: ANN001
    studio.make(plot_ask())
    wait_plot(studio.owner)
    wait_ask(studio.owner)
    pick(studio, "point")
    x, y = data_to_page(studio.frame, "spectrum", 5, 90)
    click_at(studio, x, y)
    what(studio)
    saved = save_box(studio, "why this peak?")
    assert saved["data"]["canvas_id"] == "spectrum"
    assert saved["data"]["x"] == pytest.approx(5, abs=0.2)
    assert (
        studio.frame.evaluate("document.querySelector('canvas-ask').draft.point")
        is None
    )
    assert len(comment_file(studio)["comments"]) == 1


# ---- ASK-05: a picture, a model, a scene ----------------------------------------------


def test_ask_05_a_click_on_a_picture_answers_in_image_pixels_and_marks_it(
    owner, make
) -> None:  # noqa: ANN001
    child = block("canvas-image", "pic", {"src": "pic.png"})
    made = make(ask_over(child), files={"pic.png": image_file()})
    wait_image(owner)
    wait_ask(owner)
    rect = image_rect(owner)
    target = (rect["left"] + rect["width"] * 0.25, rect["top"] + rect["height"] * 0.5)
    owner.page.mouse.click(*to_window(owner, *target))
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-image').shadowRoot.querySelector('.point-mark')"
    )
    mark = owner.frame.evaluate(
        "(() => { const r = document.querySelector('canvas-image').shadowRoot.querySelector('.point-mark').getBoundingClientRect();"
        " return [r.left + r.width / 2, r.top + r.height / 2]; })()"
    )
    assert mark == pytest.approx(target, abs=2)
    assert made.wait_action("image-click", 0) == []
    # A second click moves the one mark.
    other = (rect["left"] + rect["width"] * 0.75, rect["top"] + rect["height"] * 0.5)
    owner.page.mouse.click(*to_window(owner, *other))
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point.x > 100"
    )
    assert owner.frame.locator("canvas-image .point-mark").count() == 1
    submit(owner).click()
    answer = answer_value(made)["answer"]
    assert (
        abs(answer["x"] - IMAGE_W * 0.75) <= 1 and abs(answer["y"] - IMAGE_H / 2) <= 1
    )


def test_ask_05_a_click_on_a_model_marks_the_surface_without_mark_mode(
    owner, make
) -> None:  # noqa: ANN001
    child = block("canvas-model", "part", {"src": "cube.stl", "units": "mm"})
    made = make(ask_over(child), files={"cube.stl": cube_stl(MODEL_SIZE)})
    wait_model(owner, "part")
    wait_ask(owner)
    box = owner.frame.locator("canvas-model canvas").bounding_box()
    assert (
        owner.frame.locator("canvas-model button.mark-toggle").get_attribute(
            "aria-pressed"
        )
        == "false"
    )
    owner.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point"
    )
    first = owner.frame.evaluate(
        "document.querySelector('canvas-ask').draft.point.point"
    )
    owner.page.mouse.click(
        box["x"] + box["width"] / 2 + 40, box["y"] + box["height"] / 2 + 10
    )
    owner.frame.wait_for_function(
        "(first) => document.querySelector('canvas-ask').draft.point.point"
        ".some((c, i) => c !== first[i])",
        arg=first,
    )
    assert (
        owner.frame.evaluate(
            "document.querySelector('canvas-model').markSprites.length"
        )
        == 1
    )
    assert made.wait_action("model-mark", 0) == []
    submit(owner).click()
    answer = answer_value(made)["answer"]
    assert point_is_on_cube(answer["point"]) and len(answer["normal"]) == 3


def test_ask_05_the_model_keeps_its_own_mark_mode_after_the_ask_is_answered(
    owner, make
) -> None:  # noqa: ANN001
    child = block("canvas-model", "part", {"src": "cube.stl", "units": "mm"})
    made = make(ask_over(child), files={"cube.stl": cube_stl(MODEL_SIZE)})
    wait_model(owner, "part")
    wait_ask(owner)
    box = owner.frame.locator("canvas-model canvas").bounding_box()
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    owner.page.mouse.click(*centre)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point"
    )
    submit(owner).click()
    made.wait_events(1)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.said')"
    )
    owner.page.mouse.click(*centre)  # mark mode is off: no new mark, no action
    owner.page.wait_for_timeout(300)
    assert made.wait_action("model-mark", 0) == []
    assert (
        owner.frame.evaluate(
            "document.querySelector('canvas-model').markSprites.length"
        )
        == 1
    )
    owner.frame.locator("canvas-model button.mark-toggle").click()
    owner.page.mouse.click(centre[0] + 30, centre[1] + 5)
    [action] = made.wait_action("model-mark")
    assert action["target"]["canvas_id"] == "part"


def test_ask_05_a_click_on_a_scene_answers_with_the_part(owner, make) -> None:  # noqa: ANN001
    made = make(ask_over(scene_page(parts_of("a.stl", "b.stl"))), files=FILES)
    wait_scene(owner)
    wait_ask(owner)
    owner.page.mouse.click(*screen_point(owner, 0))
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point"
    )
    owner.page.mouse.click(*screen_point(owner, 1))
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').draft.point.part === 'b'"
    )
    assert (
        owner.frame.evaluate(
            "document.querySelector('canvas-scene').markSprites.length"
        )
        == 1
    )
    assert made.wait_action("scene-mark", 0) == []
    submit(owner).click()
    answer = answer_value(made)["answer"]
    assert answer["part"] == "b" and len(answer["point"]) == 3


@pytest.mark.parametrize(
    "children",
    [
        "",
        block("canvas-plot", "a", plot_config())
        + block("canvas-plot", "b", plot_config()),
        block("canvas-textbox", "t", {"label": "Name"}),
    ],
    ids=["no-child", "two-children", "other-block"],
)
def test_ask_05_a_point_ask_needs_one_plot_picture_model_or_scene(
    owner, make, children
) -> None:  # noqa: ANN001
    made = make(block("canvas-ask", "q", QUESTION, extra=children))
    box = owner.frame.locator("canvas-ask .block-error")
    box.wait_for()
    assert "needs one child block" in box.inner_text()
    assert any(e["canvas_id"] == "q" for e in made.shown["errors"])


# ---- ASK-06: the parameter form ------------------------------------------------------

FIELDS = [
    {
        "id": "mesh",
        "label": "Mesh size",
        "type": "number",
        "value": 2,
        "unit": "mm",
        "min": 0.5,
        "max": 3,
    },
    {
        "id": "infill",
        "label": "Infill",
        "type": "one",
        "value": "gyroid",
        "options": ["gyroid", "lines"],
    },
    {"id": "supports", "label": "Supports", "type": "onoff", "value": True},
    {"id": "name", "label": "Part name", "type": "text", "value": "bracket"},
]
FORM = {
    "form": "fields",
    "question": "Run the simulation with these?",
    "fields": FIELDS,
    "submit": "Run with these",
}


def fields_page(**config) -> str:  # noqa: ANN003
    return block("canvas-ask", "q", {**FORM, **config})


def field(owner, name: str, selector: str = ":is(input, select)"):  # noqa: ANN001, ANN201
    return owner.frame.locator(
        f'canvas-ask .field[data-field="{name}"] {selector}'
    ).first


def changed_rows(owner) -> list[str]:  # noqa: ANN001
    return ask_eval(
        owner,
        "return [...ask.shadowRoot.querySelectorAll('.field.changed')].map((r) => r.dataset.field);",
    )


def test_ask_06_the_form_shows_labelled_fields_with_their_values_and_the_submit_label(
    owner, make
) -> None:  # noqa: ANN001
    make(fields_page())
    wait_ask(owner)
    labels = ask_eval(
        owner,
        "return [...ask.shadowRoot.querySelectorAll('.field label')].map((l) => l.textContent);",
    )
    assert labels == ["Mesh size", "Infill", "Supports", "Part name"]
    assert field(owner, "mesh").input_value() == "2"
    assert field(owner, "infill").input_value() == "gyroid"
    assert field(owner, "supports").is_checked()
    assert field(owner, "name").input_value() == "bracket"
    assert (
        ask_eval(
            owner, "return ask.shadowRoot.querySelector('.field .meta').textContent;"
        )
        == "mm"
    )
    assert submit(owner).inner_text() == "Run with these"
    assert changed_rows(owner) == []


def test_ask_06_the_default_submit_label_is_answer(owner, make) -> None:  # noqa: ANN001
    config = {k: v for k, v in FORM.items() if k != "submit"}
    make(block("canvas-ask", "q", config))
    wait_ask(owner)
    assert submit(owner).inner_text() == "Answer"


def test_ask_06_a_changed_field_is_marked_and_the_answer_lists_all_values_and_the_change(
    owner, make
) -> None:  # noqa: ANN001
    made = make(fields_page())
    wait_ask(owner)
    field(owner, "mesh").fill("1.5")
    assert changed_rows(owner) == ["mesh"]
    tag = ask_eval(
        owner,
        "return ask.shadowRoot.querySelector('.field.changed .changed-tag').textContent;",
    )
    assert tag == "changed (was 2 mm)"
    assert (
        ask_eval(
            owner,
            "return ask.shadowRoot.querySelector('.field:not(.changed) .changed-tag').hidden;",
        )
        is True
    )
    submit(owner).click()
    value = answer_value(made)
    assert value["form"] == "fields"
    assert value["answer"] == {
        "values": {
            "mesh": 1.5,
            "infill": "gyroid",
            "supports": True,
            "name": "bracket",
        },
        "changed": ["mesh"],
    }


def test_ask_06_every_field_type_can_change_and_changed_follows_field_order(
    owner, make
) -> None:  # noqa: ANN001
    made = make(fields_page())
    wait_ask(owner)
    field(owner, "name").fill("clamp")
    field(owner, "supports").uncheck()
    field(owner, "infill").select_option("lines")
    assert changed_rows(owner) == ["infill", "supports", "name"]
    submit(owner).click()
    answer = answer_value(made)["answer"]
    assert answer["changed"] == ["infill", "supports", "name"]
    assert answer["values"] == {
        "mesh": 2,
        "infill": "lines",
        "supports": False,
        "name": "clamp",
    }


def test_ask_06_changing_a_field_back_removes_its_mark(owner, make) -> None:  # noqa: ANN001
    make(fields_page())
    wait_ask(owner)
    field(owner, "mesh").fill("1.5")
    field(owner, "mesh").fill("2")
    assert changed_rows(owner) == []


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("9", "Mesh size: between 0.5 and 3 mm"),
        ("0.1", "Mesh size: between 0.5 and 3 mm"),
        ("", "Mesh size: between 0.5 and 3 mm"),
    ],
)
def test_ask_06_a_value_outside_its_limits_disables_the_button_with_the_reason(
    owner, make, text, reason
) -> None:  # noqa: ANN001
    made = make(fields_page())
    wait_ask(owner)
    field(owner, "mesh").fill(text)
    assert submit(owner).is_disabled()
    assert submit(owner).get_attribute("title") == reason
    assert (
        ask_eval(owner, "return ask.shadowRoot.querySelector('.reason').textContent;")
        == reason
    )
    field(owner, "mesh").fill("1")
    assert submit(owner).is_enabled()
    assert made.events == []


def test_ask_06_the_answered_line_names_the_changes_and_change_reopens_the_form_filled(
    owner, make
) -> None:  # noqa: ANN001
    made = make(fields_page())
    wait_ask(owner)
    field(owner, "mesh").fill("1.5")
    submit(owner).click()
    made.wait_events(1)
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.said')"
    )
    assert "changed Mesh size 1.5 mm" in ask_eval(
        owner, "return ask.shadowRoot.querySelector('.said').textContent;"
    )
    owner.frame.locator("canvas-ask button.link", has_text="Change").click()
    assert field(owner, "mesh").input_value() == "1.5"
    assert changed_rows(owner) == ["mesh"]
    field(owner, "mesh").fill("2")
    submit(owner).click()
    second = made.wait_events(2)[1]["value"]
    assert second["answer"]["changed"] == [] and second["replaces"]


def test_ask_06_an_answer_without_changes_says_no_change(owner, make) -> None:  # noqa: ANN001
    made = make(fields_page())
    wait_ask(owner)
    submit(owner).click()
    assert answer_value(made)["answer"]["changed"] == []
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.said')"
    )
    assert "no change" in ask_eval(
        owner, "return ask.shadowRoot.querySelector('.said').textContent;"
    )


def test_ask_06_new_values_from_the_agent_replace_the_owners_draft(owner, make) -> None:  # noqa: ANN001
    made = make(fields_page())
    wait_ask(owner)
    field(owner, "mesh").fill("1.5")
    changed = [{**f, "value": 1} if f["id"] == "mesh" else f for f in FIELDS]
    made.rewrite(fields_page(fields=changed))
    owner.frame.wait_for_function(
        "() => document.querySelector('canvas-ask').shadowRoot.querySelector('.field input').value === '1'"
    )
    assert changed_rows(owner) == []


def _spec(**change) -> dict:  # noqa: ANN003
    return {**FORM, **change}


def _field(**change) -> dict:  # noqa: ANN003
    return {"id": "x", "label": "X", "type": "number", "value": 1, **change}


@pytest.mark.parametrize(
    ("config", "word"),
    [
        (_spec(fields=[]), "1 to 12"),
        (_spec(fields=[_field(id=f"f{i}") for i in range(13)]), "1 to 12"),
        (_spec(fields=[_field(), _field()]), "duplicate field id"),
        (_spec(fields=[_field(type="slider")]), "type must be"),
        (_spec(fields=[_field(value="1")]), "value must be a number"),
        (_spec(fields=[_field(type="one", value="a", options=["b", "c"])]), "options"),
        (
            _spec(fields=[{"id": "x", "type": "text", "value": ""}]),
            "id and a string label",
        ),
        (
            {"question": "?", "form": "yesno", "fields": [_field()]},
            'belongs to form "fields"',
        ),
        ({"question": "?", "form": "fields"}, "1 to 12"),
    ],
    ids=[
        "none",
        "thirteen",
        "duplicate",
        "type",
        "value",
        "options",
        "label",
        "other-form",
        "missing",
    ],
)
def test_ask_06_a_bad_fields_list_shows_the_error_box(
    owner, make, config, word
) -> None:  # noqa: ANN001
    make(block("canvas-ask", "q", config))
    box = owner.frame.locator("canvas-ask .block-error")
    box.wait_for()
    assert word in box.inner_text()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_ask_05_06_look_the_contrast_check_finds_nothing_open_or_answered(
    owner,
    make,
    headless,  # noqa: F811
    scheme: str,
) -> None:  # noqa: ANN001
    directory = os.environ.get("KINDS_LOOK_DIR")
    made = make(plot_ask() + block("canvas-ask", "f", FORM))
    wait_plot(owner)
    owner.frame.wait_for_function(
        "() => [...document.querySelectorAll('canvas-ask')].every((e) => e.renderIdle && e.shadowRoot.querySelector('.k'))"
    )
    owner.page.set_viewport_size({"width": 1100, "height": 1500})
    owner.page.wait_for_timeout(400)
    click_data(owner, 5, 90)
    owner.frame.locator(
        'canvas-ask[data-canvas-id=f] .field[data-field="mesh"] input'
    ).fill("1.5")
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.wait_for_timeout(600)  # the plot draws itself again for the scheme

    def live(stage: str) -> None:
        if not directory:
            return
        Path(directory).mkdir(parents=True, exist_ok=True)
        for name, ask in (("point", "q"), ("fields", "f")):
            owner.frame.locator(f"canvas-ask[data-canvas-id={ask}]").screenshot(
                path=Path(directory) / f"live-{name}-{stage}-{scheme}.png"
            )

    live("open")
    for stage in ("open", "answered"):
        if stage == "answered":
            owner.frame.locator("canvas-ask[data-canvas-id=q] button.submit").click()
            owner.frame.locator("canvas-ask[data-canvas-id=f] button.submit").click()
            made.wait_events(2)
            owner.frame.wait_for_function(
                "() => [...document.querySelectorAll('canvas-ask')].every((e) => e.shadowRoot.querySelector('.said'))"
            )
            live("answered")
        result = look(owner, made.sid, width=900, height=1100, scheme=scheme, full=True)
        findings = result["audit"]["findings"]
        assert [f for f in findings if f["rule"] == "contrast"] == [], findings
        if directory:
            shutil.copy(
                result["png"], Path(directory) / f"point-fields-{stage}-{scheme}.png"
            )
