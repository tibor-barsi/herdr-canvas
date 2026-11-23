"""Ready-made blocks, part 1: runtime and six blocks (BLK-01 to BLK-04, BLK-08)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .support import block

pytestmark = pytest.mark.browser


# ---- BLK-02 ---------------------------------------------------------------------

BROKEN_PAGE = (
    "<h1>Mixed</h1>"
    '<canvas-buttons><script type="application/json">'
    '{"buttons": []}</script></canvas-buttons>'
    + block("canvas-choices", "badjson", "{not json")
    + block("canvas-table", "wrongtype", {"columns": "a", "rows": []})
    + block("canvas-textbox", "fine", {"label": "Name"})
)


def test_blk_02_broken_blocks_show_an_error_box_and_the_valid_one_works(
    owner, make
) -> None:  # noqa: ANN001
    made = make(BROKEN_PAGE)
    boxes = owner.frame.locator(".block-error")
    boxes.nth(2).wait_for()
    assert boxes.count() == 3
    texts = [boxes.nth(i).inner_text() for i in range(3)]
    assert "canvas-buttons" in texts[0] and "data-canvas-id" in texts[0]
    assert "canvas-choices" in texts[1] and "JSON" in texts[1]
    assert "canvas-table" in texts[2] and "columns" in texts[2]
    # the valid block still works
    owner.frame.locator("canvas-textbox input").fill("hello")
    owner.frame.locator("canvas-textbox button").click()
    [event] = made.wait_events(1)
    assert event["kind"] == "text" and event["value"] == "hello"
    # and `show` lists the errors as page errors
    errors = made.shown["errors"]
    assert {e["source"] for e in errors} == {"block"}
    assert {e["canvas_id"] for e in errors} == {None, "badjson", "wrongtype"}
    assert any("columns" in e["message"] for e in errors)


def test_blk_02_fixing_the_config_replaces_the_error_box(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-progress", "p", {"value": "oops"}))
    owner.frame.locator(".block-error").wait_for()
    made.rewrite(block("canvas-progress", "p", {"value": 0.5, "status": "running"}))
    owner.frame.locator("canvas-progress [role=progressbar]").wait_for()
    assert owner.frame.locator(".block-error").count() == 0


# ---- BLK-03 and BLK-08 ------------------------------------------------------------

TABLE = {
    "columns": ["name", "mass"],
    "rows": [["b", 30], ["a", 20], ["c", 10]],
    "select": "multi",
    "key": "name",
}


def names(owner) -> list[str]:  # noqa: ANN001
    return owner.frame.locator("canvas-table tbody tr td:first-child").all_inner_texts()


def test_blk_03_sort_state_is_kept_when_the_config_is_unchanged(owner, make) -> None:  # noqa: ANN001
    page = "<p id=note>one</p>" + block("canvas-table", "t", TABLE)
    made = make(page)
    owner.frame.locator("canvas-table th", has_text="mass").click()
    assert names(owner) == ["c", "a", "b"]
    made.rewrite(page.replace("one", "two"))
    owner.frame.wait_for_function("document.querySelector('#note').textContent==='two'")
    assert names(owner) == ["c", "a", "b"]


def test_blk_03_changed_options_keep_the_selection_that_still_exists(
    owner, make
) -> None:  # noqa: ANN001
    options = [{"id": i, "title": i.upper()} for i in "abc"]
    config = {"mode": "multi", "options": options, "submit": "Go"}
    made = make(block("canvas-choices", "c", config))
    for title in ("B", "C"):
        owner.frame.locator("canvas-choices .option", has_text=title).click()
    config["options"] = [options[0], options[1], {"id": "d", "title": "D"}]
    made.rewrite(block("canvas-choices", "c", config))
    owner.frame.wait_for_function(
        "(() => { const o = document.querySelector('canvas-choices').shadowRoot"
        ".querySelectorAll('.option'); return o.length === 3 &&"
        " o[2].textContent.includes('D'); })()"
    )
    selected = owner.frame.locator("canvas-choices .option[aria-checked=true]")
    assert selected.all_inner_texts() == ["B"]


def test_blk_01_choices_without_submit_show_only_their_options(owner, make) -> None:  # noqa: ANN001
    options = [{"id": i, "title": i.upper()} for i in "ab"]
    make(block("canvas-choices", "c", {"options": options}))
    owner.frame.locator("canvas-choices .option").nth(1).wait_for()
    assert owner.frame.locator("canvas-choices .block").inner_text().split() == [
        "A",
        "B",
    ]


def test_blk_08_unchanged_config_keeps_the_same_shadow_nodes(owner, make) -> None:  # noqa: ANN001
    page = "<p id=note>one</p>" + block("canvas-table", "t", TABLE)
    made = make(page)
    owner.frame.evaluate(
        "() => { const t = document.querySelector('canvas-table');"
        " window.__rows = t.shadowRoot.querySelector('tbody');"
        " window.__renders = t.renderCount; window.__probe = 1; }"
    )
    # same config with different whitespace and key order, sibling changed
    reordered = block(
        "canvas-table", "t", json.dumps(dict(reversed(list(TABLE.items()))), indent=2)
    )
    made.rewrite("<p id=note>two</p>" + reordered)
    owner.frame.wait_for_function("document.querySelector('#note').textContent==='two'")
    same = owner.frame.evaluate(
        "() => { const t = document.querySelector('canvas-table');"
        " return [window.__rows === t.shadowRoot.querySelector('tbody'),"
        " t.renderCount === window.__renders, window.__probe]; }"
    )
    assert same == [True, True, 1]


def test_blk_08_a_changed_config_renders_once(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-table", "t", TABLE))
    owner.frame.wait_for_selector("canvas-table tbody tr")
    before = owner.frame.evaluate("document.querySelector('canvas-table').renderCount")
    made.rewrite(block("canvas-table", "t", {**TABLE, "rows": [["z", 1]]}))
    owner.frame.wait_for_function(
        "document.querySelector('canvas-table').shadowRoot"
        ".querySelector('tbody td')?.textContent === 'z'"
    )
    owner.page.wait_for_timeout(200)
    after = owner.frame.evaluate("document.querySelector('canvas-table').renderCount")
    assert after == before + 1


def test_blk_08_blocks_render_into_a_shadow_root(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-progress", "p", {"value": 1, "status": "done"}))
    owner.frame.wait_for_selector("canvas-progress [role=progressbar]")
    assert owner.frame.evaluate(
        "(() => { const e = document.querySelector('canvas-progress');"
        " return [e.shadowRoot !== null, e.querySelector('[role=progressbar]')]; })()"
    ) == [True, None]


# ---- BLK-04 ---------------------------------------------------------------------


def test_blk_04_progress_updates_in_place_without_flicker(owner, make) -> None:  # noqa: ANN001
    def page(i: int) -> str:
        status = "done" if i == 20 else "running"
        config = {"value": i, "max": 20, "label": "Build", "status": status}
        return "<p>run</p>" + block("canvas-progress", "run", config)

    made = make(page(0))
    owner.frame.wait_for_selector("canvas-progress [role=progressbar]")
    owner.frame.evaluate(
        """() => {
          window.__probe = 1; window.__removed = 0; window.__shadowChanges = 0;
          const el = document.querySelector('canvas-progress');
          new MutationObserver((records) => {
            for (const r of records) for (const n of r.removedNodes)
              if (n === el) window.__removed += 1;
          }).observe(document.body, {childList: true, subtree: true});
          new MutationObserver((records) => {
            for (const r of records) if (r.type === 'childList')
              window.__shadowChanges += 1;
          }).observe(el.shadowRoot, {childList: true, subtree: true});
        }"""
    )
    for i in range(1, 21):
        made.rewrite(page(i))
        owner.page.wait_for_timeout(200)
    owner.frame.wait_for_function(
        "document.querySelector('canvas-progress').shadowRoot"
        ".querySelector('[role=progressbar]').getAttribute('aria-valuenow') === '20'"
    )
    state = owner.frame.evaluate(
        "[window.__probe, window.__removed, window.__shadowChanges,"
        " document.querySelector('canvas-progress').shadowRoot.textContent]"
    )
    assert state[:3] == [1, 0, 0]  # never removed, no reload, nodes reused
    assert "100%" in state[3]


# ---- BLK-01: choices --------------------------------------------------------------

CHOICES = {
    "mode": "single",
    "submit": "Use this design",
    "options": [
        {"id": "a", "title": "Ribbed", "description": "with ribs"},
        {"id": "b", "title": "Lattice", "image": "b.png"},
        {"id": "c", "title": "Plain"},
    ],
}


def test_blk_01_choices_render_options_and_a_disabled_submit(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-choices", "design", CHOICES))
    options = owner.frame.locator("canvas-choices .option")
    options.nth(2).wait_for()
    assert options.count() == 3
    assert "Ribbed" in options.nth(0).inner_text()
    assert "with ribs" in options.nth(0).inner_text()
    assert options.nth(1).locator("img").get_attribute("src") == "b.png"
    assert owner.frame.locator("canvas-choices button.submit").is_disabled()
    assert (
        owner.frame.locator("canvas-choices button.submit").inner_text()
        == "Use this design"
    )


def test_blk_01_choices_single_select_then_submit_gives_a_choice_event(
    owner, make
) -> None:  # noqa: ANN001
    made = make(block("canvas-choices", "design", CHOICES))
    options = owner.frame.locator("canvas-choices .option")
    options.nth(0).click()
    options.nth(1).click()  # replaces the first selection
    assert owner.frame.locator(".option[aria-checked=true]").count() == 1
    actions = made.wait_action("select", 2)
    assert actions[0]["value"] == ["a"] and actions[1]["value"] == ["b"]
    assert actions[1]["target"]["canvas_id"] == "design"
    assert made.events == []  # selecting alone sends nothing
    owner.frame.locator("canvas-choices button.submit").click()
    [event] = made.wait_events(1)
    assert event["kind"] == "choice" and event["value"] == ["b"]
    assert event["target"]["canvas_id"] == "design" and event["delivery"] == "now"


def test_blk_01_choices_multi_select_toggles_and_submits_in_option_order(
    owner, make
) -> None:  # noqa: ANN001
    made = make(block("canvas-choices", "design", {**CHOICES, "mode": "multi"}))
    options = owner.frame.locator("canvas-choices .option")
    options.nth(2).click()
    options.nth(0).click()
    options.nth(1).click()
    options.nth(1).click()  # toggled off again
    owner.frame.locator("canvas-choices button.submit").click()
    [event] = made.wait_events(1)
    assert event["value"] == ["a", "c"]


def test_blk_01_choices_without_submit_have_no_submit_button(owner, make) -> None:  # noqa: ANN001
    config = {k: v for k, v in CHOICES.items() if k != "submit"}
    make(block("canvas-choices", "design", config))
    owner.frame.wait_for_selector("canvas-choices .option")
    assert owner.frame.locator("canvas-choices button.submit").count() == 0


# ---- BLK-01: buttons --------------------------------------------------------------

BUTTONS = {
    "buttons": [
        {"id": "go", "label": "Go", "style": "primary"},
        {"id": "stop", "label": "Stop", "style": "danger"},
        {"id": "plain", "label": "Plain"},
    ]
}


def test_blk_01_buttons_render_styles_and_send_a_button_event(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-buttons", "ctl", BUTTONS))
    buttons = owner.frame.locator("canvas-buttons button")
    buttons.nth(2).wait_for()
    classes = [buttons.nth(i).get_attribute("class") for i in range(3)]
    assert "primary" in classes[0] and "danger" in classes[1]
    assert "primary" not in classes[2] and "danger" not in classes[2]
    buttons.nth(1).click()
    [event] = made.wait_events(1)
    assert event["kind"] == "button" and event["value"] == "stop"
    assert event["target"]["canvas_id"] == "ctl"
    assert made.wait_action("button")[0]["value"] == "stop"


def test_blk_01_a_pressed_button_shows_sent_for_one_second(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-buttons", "ctl", BUTTONS))
    button = owner.frame.locator("canvas-buttons button").first
    button.click()
    assert button.inner_text().lower() == "sent"
    owner.page.wait_for_timeout(500)
    assert button.inner_text().lower() == "sent"
    owner.frame.wait_for_function(
        "document.querySelector('canvas-buttons').shadowRoot"
        ".querySelector('button').textContent === 'Go'",
        timeout=2000,
    )


# ---- BLK-01: textbox --------------------------------------------------------------


def test_blk_01_textbox_input_action_then_text_event(owner, make) -> None:  # noqa: ANN001
    made = make(
        block("canvas-textbox", "note", {"label": "Note", "placeholder": "type"})
    )
    field = owner.frame.locator("canvas-textbox input")
    assert field.get_attribute("placeholder") == "type"
    assert owner.frame.locator("canvas-textbox label").inner_text() == "Note"
    submit = owner.frame.locator("canvas-textbox button.submit")
    assert submit.inner_text() == "Send" and submit.is_disabled()
    field.fill("why 3?")
    field.blur()
    [action] = made.wait_action("input")
    assert action["value"] == "why 3?" and action["target"]["canvas_id"] == "note"
    submit.click()
    [event] = made.wait_events(1)
    assert event["kind"] == "text" and event["value"] == "why 3?"
    assert event["target"]["canvas_id"] == "note"


def test_blk_01_textbox_multiline_and_custom_submit_label(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-textbox", "n", {"multiline": True, "submit": "Post"}))
    area = owner.frame.locator("canvas-textbox textarea")
    area.fill("line one\nline two")
    owner.frame.locator("canvas-textbox button.submit", has_text="Post").click()
    [event] = made.wait_events(1)
    assert event["value"] == "line one\nline two"


def test_blk_03_typed_text_survives_an_unrelated_update(owner, make) -> None:  # noqa: ANN001
    page = "<p id=note>one</p>" + block("canvas-textbox", "n", {"label": "L"})
    made = make(page)
    owner.frame.locator("canvas-textbox input").fill("draft text")
    made.rewrite(page.replace("one", "two"))
    owner.frame.wait_for_function("document.querySelector('#note').textContent==='two'")
    assert owner.frame.locator("canvas-textbox input").input_value() == "draft text"


# ---- BLK-01: table ----------------------------------------------------------------


def test_blk_01_table_renders_columns_and_rows(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-table", "t", {**TABLE, "select": "none"}))
    owner.frame.wait_for_selector("canvas-table tbody tr")
    assert owner.frame.locator("canvas-table th").all_inner_texts()[:2] == [
        "name",
        "mass",
    ]
    assert names(owner) == ["b", "a", "c"]


def test_blk_01_table_row_click_gives_a_select_action_with_the_row_key(
    owner, make
) -> None:  # noqa: ANN001
    made = make(block("canvas-table", "t", {**TABLE, "select": "single"}))
    rows = owner.frame.locator("canvas-table tbody tr")
    rows.nth(1).click()
    rows.nth(2).click()  # single mode: replaces the selection
    actions = made.wait_action("select", 2)
    assert [a["value"] for a in actions] == [["a"], ["c"]]
    assert actions[0]["target"]["canvas_id"] == "t"
    assert owner.frame.locator("canvas-table tr[aria-selected=true]").count() == 1


def test_blk_01_table_multi_select_and_index_when_there_is_no_key(owner, make) -> None:  # noqa: ANN001
    config = {k: v for k, v in TABLE.items() if k != "key"}
    made = make(block("canvas-table", "t", config))
    rows = owner.frame.locator("canvas-table tbody tr")
    rows.nth(0).click()
    owner.frame.locator("canvas-table th", has_text="mass").click()  # sort asc
    owner.frame.locator("canvas-table tbody tr").nth(0).click()  # row index 2
    actions = made.wait_action("select", 2)
    assert actions[-1]["value"] == [0, 2]  # indices into the given rows


def test_blk_01_table_without_selection_records_no_select_action(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-table", "t", {**TABLE, "select": "none"}))
    owner.frame.locator("canvas-table tbody tr").first.click()
    made.wait_action("click")
    actions = owner.page.evaluate(f"window.__drafts['{made.sid}'].actions")
    assert [a for a in actions if a["kind"] == "select"] == []


# ---- BLK-01: progress -------------------------------------------------------------


def test_blk_01_progress_shows_label_value_status_and_detail(owner, make) -> None:  # noqa: ANN001
    config = {"value": 3, "max": 4, "label": "Solve", "status": "running",
              "detail": "step 3 of 4"}  # fmt: skip
    made = make(block("canvas-progress", "p", config))
    bar = owner.frame.locator("canvas-progress [role=progressbar]")
    bar.wait_for()
    assert bar.get_attribute("aria-valuenow") == "3"
    assert bar.get_attribute("aria-valuemax") == "4"
    text = owner.frame.locator("canvas-progress .block").inner_text()
    assert "Solve" in text and "75%" in text and "step 3 of 4" in text
    assert owner.frame.locator("canvas-progress .status-running").count() == 1
    made.rewrite(block("canvas-progress", "p", {"value": 1, "status": "failed"}))
    owner.frame.locator("canvas-progress .status-failed").wait_for()
    assert "100%" in owner.frame.locator("canvas-progress .block").inner_text()  # max 1


# ---- BLK-01: markdown --------------------------------------------------------------


def test_blk_01_markdown_renders_text_and_katex_math(owner, make) -> None:  # noqa: ANN001
    text = "# Title\n\nSome **bold** and $x^2$ inline.\n\n$$\\int_0^1 f$$\n"
    make(block("canvas-markdown", "m", {"text": text}))
    root = owner.frame.locator("canvas-markdown")
    root.locator(".katex").nth(1).wait_for()
    assert root.locator("h1").inner_text() == "Title"
    assert root.locator("strong").inner_text() == "bold"
    assert root.locator(".katex-display").count() == 1
    assert root.locator(".katex").count() == 2
    owner.frame.wait_for_function("document.fonts.check('16px KaTeX_Main')")


def test_blk_01_markdown_without_math_shows_no_stray_null(owner, make) -> None:  # noqa: ANN001
    plain = "# Plain\n\nNo math here, only **bold** text.\n"
    math = "# Maths\n\nInline $x^2$.\n"
    page = block("canvas-markdown", "plain", {"text": plain}) + block(
        "canvas-markdown", "math", {"text": math}
    )
    make(page)
    owner.frame.locator("canvas-markdown[data-canvas-id=plain] h1").wait_for()
    owner.frame.locator("canvas-markdown[data-canvas-id=math] .katex").wait_for()
    texts = owner.frame.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('canvas-markdown')]
          .map((el) => [el.dataset.canvasId, el.shadowRoot.textContent]))"""
    )
    assert "null" not in texts["plain"], texts["plain"]
    assert "null" not in texts["math"], texts["math"]
    assert "Plain" in texts["plain"] and "Maths" in texts["math"]


def test_blk_01_markdown_child_and_src_and_dollar_in_code(owner, make) -> None:  # noqa: ANN001
    child = (
        '<canvas-markdown data-canvas-id="m1"><script type="text/markdown">'
        "Cost is $5 and $6, code `$x$`, math $y$.</script></canvas-markdown>"
    )
    from_file = '<canvas-markdown data-canvas-id="m2" data-x></canvas-markdown>'
    page = child + block("canvas-markdown", "m2", {"src": "notes.md"})
    make(page, files={"notes.md": "## From file\n"})
    owner.frame.locator("canvas-markdown[data-canvas-id=m1] .katex").wait_for()
    first = owner.frame.locator("canvas-markdown[data-canvas-id=m1] .markdown")
    assert first.locator(".katex").count() == 1  # only `$y$`
    assert "$5 and $6" in first.inner_text()
    assert first.locator("code").inner_text() == "$x$"
    owner.frame.locator("canvas-markdown[data-canvas-id=m2] h2").wait_for()
    assert from_file  # (declaration style: src keeps the config tiny)


def test_blk_07_markdown_libraries_load_only_when_used(owner, make) -> None:  # noqa: ANN001
    requested: list[str] = []
    owner.page.on("request", lambda r: requested.append(r.url))
    make(block("canvas-progress", "p", {"value": 1}))
    owner.frame.wait_for_selector("canvas-progress [role=progressbar]")
    assert not [u for u in requested if "katex" in u or "marked" in u]


def test_page_11_links_inside_a_block_are_not_followed(owner, make) -> None:  # noqa: ANN001
    text = "[out](https://example.com/x) and [other](b.html)"
    made = make(block("canvas-markdown", "m", {"text": text}))
    owner.frame.locator("canvas-markdown a", has_text="out").click()
    [action] = made.wait_action("click")
    assert action["target"]["href"] == "https://example.com/x"
    assert owner.frame.evaluate("location.pathname.endsWith('page.html')")
    # (the route guard fails the test if any request left the hub)


# ---- shared look --------------------------------------------------------------------


def test_blocks_share_one_stylesheet_and_follow_the_colour_scheme(owner, make) -> None:  # noqa: ANN001
    page = (
        block("canvas-progress", "p", {"value": 1})
        + block("canvas-buttons", "b", BUTTONS)
        + block("canvas-table", "t", TABLE)
    )
    make(page)
    owner.frame.wait_for_selector("canvas-table tbody tr")
    info = owner.frame.evaluate(
        """() => [...document.querySelectorAll(
            'canvas-progress,canvas-buttons,canvas-table')].map((e) => [
              0, getComputedStyle(e.shadowRoot.firstElementChild).fontFamily])"""
    )
    assert len({repr(i[1]) for i in info}) == 1
    assert "sans-serif" in info[0][1]
    same = owner.frame.evaluate(
        "(() => { const s = [...document.querySelectorAll('canvas-progress,"
        "canvas-buttons,canvas-table')].map((e) => e.shadowRoot.adoptedStyleSheets[0]);"
        " return s.every((x) => x === s[0]); })()"
    )
    assert same
    owner.page.emulate_media(color_scheme="dark")
    dark = owner.frame.evaluate(
        "getComputedStyle(document.querySelector('canvas-table').shadowRoot"
        ".firstElementChild).backgroundColor"
    )
    owner.page.emulate_media(color_scheme="light")
    light = owner.frame.evaluate(
        "getComputedStyle(document.querySelector('canvas-table').shadowRoot"
        ".firstElementChild).backgroundColor"
    )
    assert dark != light


# ---- CLI-06 with the real canvas-choices (re-run of the M7 test) -----------


def test_cli_06_ask_block_returns_the_choice_of_the_real_canvas_choices(
    owner, make, tmp_path: Path
) -> None:  # noqa: ANN001
    made = make(block("canvas-choices", "design", CHOICES) + '<p id="other">x</p>')
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AGENT_CANVAS_", "XDG_"))
    }
    env.update(
        HOME=str(home),
        AGENT_CANVAS_PORT=str(owner.hub.port),
        AGENT_CANVAS_STATE_DIR=str(owner.hub.state_dir),
        AGENT_CANVAS_CONFIG_DIR=str(owner.hub.config_dir),
        AGENT_CANVAS_WINDOW_COMMAND="true",
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", "ask", "Which design?",
         "--block", "design", "--session", made.sid],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )  # fmt: skip
    try:
        owner.frame.wait_for_function(
            "document.querySelector('canvas-choices').hasAttribute('data-canvas-waiting')"
        )
        owner.frame.locator("canvas-choices .option").nth(1).click()
        owner.frame.locator("canvas-choices button.submit").click()
        for _ in range(1000):
            if process.poll() is not None:
                break
            owner.page.wait_for_timeout(20)
        out, err = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    body = json.loads(out or err)
    assert process.returncode == 0, body
    assert body["event"]["kind"] == "choice" and body["event"]["value"] == ["b"]
    assert body["event"]["delivery"] == "ask"
    assert body["event"]["target"]["canvas_id"] == "design"
    owner.frame.wait_for_function(
        "!document.querySelector('canvas-choices').hasAttribute('data-canvas-waiting')"
    )
