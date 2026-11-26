"""Automatic page checks, one fixture page per rule (CHK-01 to CHK-13).

Each page is rendered through ``look`` (the owner's window as renderer) and the
``audit`` result is read: rule id, severity and ``where`` are asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_canvas.drafts import session_tag

from .support import call, owner_field

pytestmark = pytest.mark.browser

BASE_CSS = (
    "body{margin:8px;font:16px/1.4 system-ui,sans-serif;color:#111;background:#fff}"
)


def page(body: str, css: str = "", head: str = "") -> str:
    """Wrap ``body`` in a document with a plain, readable base style."""
    return (
        "<!doctype html><html><head><meta charset=utf-8><title>t</title>"
        f"<style>{BASE_CSS}{css}</style>{head}</head><body>{body}</body></html>"
    )


def block(tag: str, config: dict, canvas_id: str) -> str:
    """A block element with a JSON config."""
    return (
        f'<{tag} data-canvas-id="{canvas_id}">'
        f'<script type="application/json">{json.dumps(config)}</script></{tag}>'
    )


def numbers_table(rows: int = 3, align: str = "right", values=None) -> str:  # noqa: ANN001
    """A table with a name column and a numeric column."""
    values = values or [f"{i}.50" for i in range(1, rows + 1)]
    body = "".join(
        f'<tr><td>row {i}</td><td style="text-align:{align}">{v}</td></tr>'
        for i, v in enumerate(values)
    )
    return (
        "<table id=t><thead><tr><th>name</th><th>load (N)</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


PIXEL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
GOOD_PLOT = block(
    "canvas-plot",
    {
        "data": [{"x": [1, 2, 3], "y": [2, 5, 3]}],
        "layout": {
            "xaxis": {"title": {"text": "frequency (Hz)"}},
            "yaxis": {"title": {"text": "amplitude [mm]"}},
            "height": 260,
        },
    },
    "good",
)
SEVERITIES = ("error", "warn", "info")
LONG_WORDS = "word " * 90

# name -> (html, expectations); an expectation is (rule, severity, where_part).
FIXTURES: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "overflow-clipped": (
        page(
            '<div id="box" style="width:100px;height:40px;overflow:hidden;'
            'background:#eee"><div style="width:300px;white-space:nowrap">'
            "this content is much wider than its box</div></div>"
        ),
        [("overflow", "warn", "#box")],
    ),
    "overflow-ellipsis": (
        page(
            '<p id="cut" style="width:120px;white-space:nowrap;overflow:hidden;'
            'text-overflow:ellipsis">A very long title that does not fit</p>'
        ),
        [("overflow", "warn", "#cut")],
    ),
    "overflow-page": (
        page('<div id="wide" style="width:2000px;height:20px;background:#ccc"></div>'),
        [("overflow", "warn", "#wide")],
    ),
    "overflow-parent": (
        page(
            '<div id="card" style="width:200px;border:1px solid #888;padding:8px">'
            '<div id="stick" style="width:320px;height:30px;background:#9cf">'
            "Sticks out</div></div>"
        ),
        [("overflow", "warn", "#stick")],
    ),
    "overlap": (
        page(
            '<p id="a" style="position:absolute;left:10px;top:10px;margin:0">'
            "Overlapping headline text</p>"
            '<p id="b" style="position:absolute;left:20px;top:14px;margin:0">'
            "Second line of text</p>"
        ),
        [("overlap", "error", "#b")],
    ),
    "small-text": (
        page('<p id="tiny" style="font-size:9px">tiny print here</p>'),
        [("small-text", "warn", "#tiny")],
    ),
    "long-lines": (
        page(f'<p id="wide-text" style="width:1200px;font-size:14px">{LONG_WORDS}</p>'),
        [("long-lines", "info", "#wide-text")],
    ),
    "contrast": (
        page(
            '<p id="faint" style="color:#aaa">Low contrast text</p>'
            '<div style="background:#222"><p id="dark" style="color:#333">'
            "Dark on dark</p></div>"
        ),
        [("contrast", "warn", "#faint"), ("contrast", "error", "#dark")],
    ),
    "missing-font": (
        page(
            "<p id=fancy style=\"font-family:'Zzyzx Display',Georgia,serif\">"
            "Fancy heading</p>"
        ),
        [("missing-font", "info", "#fancy")],
    ),
    "empty": (
        page(
            '<h2 id="blankh"></h2><ul><li id="blankli"></li></ul>'
            '<div class="card" id="blankcard" style="border:1px solid #888"></div>'
            '<table><tr><td id="blankcell"></td><td>x</td></tr></table>'
            '<img id="noimg" alt="none"><img id="bad" alt="bad" src="missing.png">'
            + block("canvas-table", {"columns": ["a"], "rows": []}, "norows")
            + block("canvas-plot", {"data": []}, "notraces")
        ),
        [
            ("empty", "warn", "#blankh"),
            ("empty", "warn", "#blankli"),
            ("empty", "warn", "#blankcard"),
            ("empty", "info", "#blankcell"),
            ("empty", "error", "#noimg"),
            ("empty", "error", "#bad"),
            ("empty", "warn", "norows"),
            ("empty", "warn", "notraces"),
        ],
    ),
    "placeholder": (
        page(
            '<p id="ph">Result: (replace) here</p><p id="todo">TODO: fix this</p>'
            '<p id="lorem">Lorem ipsum dolor sit amet</p><p id="nan">Mean: NaN mm</p>'
            '<p id="obj">Value [object Object]</p>'
            '<p id="ok">The null hypothesis holds.</p>'
        ),
        [
            ("placeholder", "error", "#ph"),
            ("placeholder", "warn", "#todo"),
            ("placeholder", "error", "#lorem"),
            ("placeholder", "error", "#nan"),
            ("placeholder", "error", "#obj"),
        ],
    ),
    "page-height": (
        page('<div style="height:3000px"></div>'),
        [("page-height", "info", "page")],
    ),
    "plot": (
        page(
            block(
                "canvas-plot",
                {
                    "data": [{"x": [1, 2], "y": [1, 2]}],
                    "layout": {"yaxis": {"title": {"text": "stress"}}, "height": 240},
                },
                "bare",
            )
            + block(
                "canvas-plot",
                {
                    "data": [
                        {"x": [1, 2], "y": [i, i + 1], "name": f"t{i}"}
                        for i in range(9)
                    ],
                    "layout": {
                        "xaxis": {"title": {"text": "t (s)"}},
                        "yaxis": {"title": {"text": "y (m)"}},
                        "height": 240,
                    },
                },
                "crowded",
            )
        ),
        [
            ("plot", "info", "bare"),
            ("plot", "warn", "crowded"),
        ],
    ),
    "plot-string-title": (
        page(
            block(
                "canvas-plot",
                {
                    "data": [{"x": [1, 2], "y": [1, 2]}],
                    "layout": {
                        "xaxis": {"title": "t (s)"},
                        "yaxis": {"title": {"text": "y (m)"}},
                        "height": 240,
                    },
                },
                "strtitle",
            )
        ),
        [("plot", "info", "strtitle")],
    ),
    "table": (
        page(
            numbers_table(align="left")
            + "<div id=wrap>"
            + numbers_table(values=["1.5", "2.25", "3"]).replace("id=t", "id=mixed")
            + "</div>"
            + "<table id=long>"
            + "".join(f"<tr><td>r{i}</td></tr>" for i in range(60))
            + "</table>"
        ),
        [
            ("table", "info", "#t"),
            ("table", "info", "#mixed"),
            ("table", "warn", "#long"),
        ],
    ),
    "errors": (
        page("<p>fine</p><script>throw new Error('boom here')</script>"),
        [("errors", "error", "page")],
    ),
    "blocked-request": (
        page('<img alt="x" src="https://example.com/a.png" width=10 height=10>'),
        [("errors", "error", "example.com")],
    ),
}

CLEAN = page(
    '<h1>Report</h1><p style="max-width:60ch">A short readable paragraph of text '
    "that wraps at a sensible width and has good contrast.</p>"
    "<ul><li>one</li><li>two</li></ul>"
    + numbers_table(align="right")
    + f'<img alt="pixel" src="{PIXEL}" width=20 height=20>'
    + GOOD_PLOT
    + block("canvas-table", {"columns": ["a", "b"], "rows": [["x", 1]]}, "tbl")
    + "<details><summary>More</summary><p>Folded text.</p></details>"
    '<p style="color:#767676;font-size:24px">Large grey text is fine at 3:1.</p>'
    '<label style="font-size:11px">small label</label>'
)


def look(owner, sid: str, **body) -> dict:  # noqa: ANN001, ANN003
    """Render through the owner's window and return the answer."""
    return call(owner, "POST", f"/api/sessions/{sid}/look", json=body)


def findings_of(result: dict) -> list[dict]:
    """The findings of a look, failing with the whole answer when missing."""
    assert isinstance(result.get("audit"), dict), result
    return result["audit"]["findings"]


@pytest.mark.parametrize("name", list(FIXTURES))
def test_chk_02_to_12_rule_fixture_page_triggers_its_rule(
    owner, make, name: str
) -> None:  # noqa: ANN001
    html, expected = FIXTURES[name]
    made = make(html)
    size = {"width": 600, "height": 700}
    if name in ("long-lines", "overflow-page"):
        size = {"width": 1280, "height": 800}
    result = look(owner, made.sid, **size)
    assert result["source"] == "window", result
    found = findings_of(result)
    for rule, severity, part in expected:
        hits = [f for f in found if f["rule"] == rule and part in f["where"]]
        assert hits, (rule, part, found)
        assert any(f["severity"] == severity for f in hits), (severity, hits)
    for finding in found:
        assert finding["severity"] in SEVERITIES
        assert finding["message"].strip() and finding["where"].strip()


def test_chk_10_a_plain_string_axis_title_is_named_as_the_cause(owner, make) -> None:  # noqa: ANN001
    made = make(FIXTURES["plot-string-title"][0])
    found = findings_of(look(owner, made.sid, width=600, height=500))
    [plot] = [f for f in found if f["rule"] == "plot"]
    assert "plain string" in plot["message"] and "x axis" in plot["message"]


def test_chk_01_finding_shape_counts_and_order(owner, make) -> None:  # noqa: ANN001
    made = make(FIXTURES["placeholder"][0])
    audit = look(owner, made.sid, width=600, height=500)["audit"]
    found = audit["findings"]
    assert set(audit["counts"]) == {"error", "warn", "info"}
    for severity in SEVERITIES:
        assert audit["counts"][severity] == sum(
            f["severity"] == severity for f in found
        )
    ranks = [SEVERITIES.index(f["severity"]) for f in found]
    assert ranks == sorted(ranks)
    first = found[0]
    assert {"rule", "severity", "message", "where", "bbox"} <= set(first)
    assert set(first["bbox"]) == {"x", "y", "w", "h"} and first["bbox"]["w"] > 0


def test_chk_01_a_clean_page_has_no_findings(owner, make) -> None:  # noqa: ANN001
    made = make(CLEAN)
    result = look(owner, made.sid, width=900, height=900, full=True)
    assert result["audit"]["findings"] == [], result["audit"]
    assert result["audit"]["counts"] == {"error": 0, "warn": 0, "info": 0}


def test_chk_02_to_05_thresholds_do_not_flag_the_edge_cases(owner, make) -> None:  # noqa: ANN001
    html = page(
        '<label id=l style="font-size:11px">label at 11</label>'
        '<p id=big style="color:#767676;font-size:24px">large grey</p>'
        '<div style="position:relative"><p id=u1 style="margin:0">Under the bar</p>'
        '<p id=u2 style="position:fixed;left:8px;top:8px;margin:0;z-index:5">'
        "Fixed overlay text</p></div>"
        '<div id=ok style="width:100px;overflow:hidden"><p>short</p></div>'
    )
    made = make(html)
    found = findings_of(look(owner, made.sid, width=600, height=400))
    assert found == [], found


def test_chk_04_small_body_text_at_eleven_is_flagged(owner, make) -> None:  # noqa: ANN001
    made = make(page('<p id=p11 style="font-size:11px">small paragraph</p>'))
    found = findings_of(look(owner, made.sid, width=600, height=300))
    assert [f["rule"] for f in found] == ["small-text"], found


def test_chk_04_the_ask_recommended_tag_is_not_small_text(owner, make) -> None:  # noqa: ANN001
    ask = {
        "question": "Which infill?",
        "options": ["gyroid", "lines"],
        "recommended": "gyroid",
    }
    made = make(page(block("canvas-ask", ask, "q-infill")))
    found = findings_of(look(owner, made.sid, width=900, height=600))
    assert [f for f in found if f["rule"] == "small-text"] == [], found


def test_chk_05_a_dark_scheme_page_is_judged_on_its_own_colours(owner, make) -> None:  # noqa: ANN001
    css = "@media (prefers-color-scheme: dark){body{background:#111;color:#eee}}"
    made = make(page("<p id=t>Readable in both</p>", css))
    owner.page.emulate_media(color_scheme="dark")
    owner.page.wait_for_timeout(500)
    found = findings_of(look(owner, made.sid, width=600, height=300, scheme="dark"))
    assert found == [], found


def test_chk_13_crops_are_saved_next_to_the_look_png(owner, make) -> None:  # noqa: ANN001
    made = make(FIXTURES["placeholder"][0])
    result = look(owner, made.sid, width=600, height=500)
    found = result["audit"]["findings"]
    crops = [f["crop"] for f in found if "crop" in f]
    assert 1 <= len(crops) <= 5
    look_png = Path(result["png"])
    for crop in crops:
        path = Path(crop)
        assert path.parent == look_png.parent and path.read_bytes()[:4] == b"\x89PNG"
    assert all("crop" not in f for f in found[5:])


def test_chk_14_no_audit_skips_the_checks(owner, make) -> None:  # noqa: ANN001
    made = make(FIXTURES["placeholder"][0])
    result = look(owner, made.sid, width=600, height=500, audit=False)
    assert result["audit"] is None


def test_chk_17_audit_script_never_enters_the_owner_frame(owner, make) -> None:  # noqa: ANN001
    made = make(FIXTURES["placeholder"][0])
    scripts_before = owner.frame.evaluate(
        "Array.from(document.scripts).map((s) => s.src)"
    )
    look(owner, made.sid, width=600, height=500)
    assert owner.frame.evaluate("typeof window.agentCanvas.auditPage") == "undefined"
    scripts = owner.frame.evaluate("Array.from(document.scripts).map((s) => s.src)")
    assert scripts == scripts_before
    assert not any("audit.js" in s for s in scripts)
    reports = owner.page.evaluate("JSON.stringify(window.__reports)")
    assert "findings" not in reports and "audit" not in reports
    assert "findings" not in owner.page.evaluate("document.documentElement.outerHTML")
    assert owner.page.evaluate("window.__errors") == []


FOCUS_GRABBERS = {
    "autofocus": "<input id=a autofocus>",
    "focus-on-load": "<input id=a><script>a.focus()</script>",
    "focus-after-load": (
        "<input id=a><script>addEventListener('load',()=>a.focus())</script>"
    ),
    "focus-later": "<input id=a><script>setTimeout(()=>a.focus(),300)</script>",
    "window-focus": "<script>window.focus()</script>",
    "parent-focus": "<script>try{parent.focus()}catch(e){}</script>",
    "top-focus": "<script>try{top.focus()}catch(e){}</script>",
}


@pytest.mark.parametrize("grabber", list(FOCUS_GRABBERS))
def test_chk_17_a_page_that_takes_focus_cannot_move_the_owners_focus(
    owner, make, grabber: str
) -> None:  # noqa: ANN001
    made = make(page(FOCUS_GRABBERS[grabber]), "alpha")
    make("<p>the page the owner is reading</p>", "beta")  # not the grabber itself
    owner.page.wait_for_timeout(500)  # the grabber's own timers in its tab are over
    owner_field(owner.page)
    owner.page.fill("#owner-field", "half written thought")
    owner.page.focus("#owner-field")
    owner.page.evaluate(
        """() => {
          window.__focus = [];
          document.addEventListener('focusout', (e) => window.__focus.push(
            'out:' + (e.target.id || e.target.tagName)), true);
        }"""
    )
    result = look(owner, made.sid, width=500, height=300)
    assert result["source"] == "window"
    owner.page.wait_for_timeout(400)  # the delayed grabber fires inside the look
    assert owner.page.evaluate("document.activeElement.id") == "owner-field"
    assert owner.page.evaluate("window.__focus") == []  # never even blurred
    owner.page.keyboard.type(" more")
    assert owner.page.input_value("#owner-field") == "half written thought more"


def test_chk_17_the_render_wrapper_is_inert_while_it_exists(owner, make) -> None:  # noqa: ANN001
    made = make(page("<p>x</p><script>setTimeout(()=>{},1500)</script>"))
    seen: list[bool] = []
    owner.page.evaluate(
        """() => new MutationObserver((records) => {
          for (const r of records) for (const n of r.addedNodes) {
            if (n.querySelector && n.querySelector('iframe[title=render]')) {
              window.__inert = n.hasAttribute('inert');
            }
          }
        }).observe(document.body, {childList: true})"""
    )
    look(owner, made.sid, width=400, height=300)
    seen.append(owner.page.evaluate("window.__inert"))
    assert seen == [True]


# ---- the kit templates, as the owner would get them from `new` ---------------------


@pytest.mark.parametrize("template", ["compare", "results", "run", "geometry", "cards"])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_chk_18_a_template_draft_reports_only_its_placeholders(
    owner, make, template: str, scheme: str
) -> None:  # noqa: ANN001
    from agent_canvas.templates import new_page_result

    made = make("<p>start</p>")
    new_page_result(made.folder, "tpl", template, False, True, session_tag(made.sid))
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.wait_for_timeout(300)
    result = look(
        owner, made.sid, page="tpl", draft=True, width=1280, height=800, scheme=scheme
    )
    assert result["source"] == "window", result
    found = result["audit"]["findings"]
    others = [f for f in found if f["rule"] != "placeholder"]
    assert others == [], others
    assert any(f["rule"] == "placeholder" for f in found), found


# ---- headless renderer and `show` ---------------------------------------------------


@pytest.fixture
def headless_renderer(owner):  # noqa: ANN001, ANN201
    """Give the hub a headless renderer that can start in this environment."""
    from agent_canvas.hub.headless import HeadlessRenderer

    from .conftest import _launch_env

    renderer = HeadlessRenderer(launch_env=_launch_env())
    owner.hub.app.state.looks.headless = renderer
    return renderer


def test_chk_01_the_headless_renderer_runs_the_same_checks(
    owner, make, headless_renderer
) -> None:  # noqa: ANN001
    made = make(FIXTURES["placeholder"][0])
    result = look(owner, made.sid, width=600, height=500, scheme="dark")
    assert result["source"] == "headless", result
    found = result["audit"]["findings"]
    assert {"#ph", "#lorem", "#nan"} <= {
        f["where"].split(" ")[0] for f in found if f["rule"] == "placeholder"
    }
    assert any(Path(f["crop"]).is_file() for f in found if "crop" in f)


def test_chk_01_a_full_page_look_is_judged_at_the_window_size(owner, make) -> None:  # noqa: ANN001
    made = make(page('<div style="height:3000px"></div>'))
    result = look(owner, made.sid, width=600, height=700, full=True)
    assert result["height"] > 2900
    assert [f["rule"] for f in result["audit"]["findings"]] == ["page-height"]


show_audit = pytest.mark.hub_config(show_audit=True)


@show_audit
def test_chk_15_show_reports_the_problems_of_the_page_it_shows(owner, make) -> None:  # noqa: ANN001
    made = make(FIXTURES["placeholder"][0])
    audit = made.shown["audit"]
    assert audit["summary"].startswith("4 errors, 1 warning")
    assert {f["rule"] for f in audit["findings"]} == {"placeholder"}
    assert all(f["severity"] in ("error", "warn") for f in audit["findings"])
    assert owner.frame.evaluate("typeof window.agentCanvas.auditPage") == "undefined"
    assert not any(
        "audit.js" in s
        for s in owner.frame.evaluate("Array.from(document.scripts).map((s) => s.src)")
    )


@show_audit
def test_chk_15_show_of_a_clean_page_says_so(owner, make) -> None:  # noqa: ANN001
    made = make(CLEAN)
    assert made.shown["audit"]["summary"] == "no problems found"
    assert made.shown["audit"]["findings"] == []


@show_audit
def test_chk_15_show_does_not_wait_longer_than_its_budget(owner, make) -> None:  # noqa: ANN001
    owner.hub.app.state.looks.show_audit_seconds = 0.01
    made = make(FIXTURES["placeholder"][0])
    assert made.shown["audit"] == "pending"
    assert made.shown["page"] == "page.html"


def test_chk_11_a_table_with_a_th_header_row_and_no_thead_is_checked(
    owner, make
) -> None:  # noqa: ANN001
    html = page(
        "<table id=modes><tr><th>Mode</th><th>f [Hz]</th></tr>"
        "<tr><td>1</td><td>12.5</td></tr><tr><td>2</td><td>101.25</td></tr>"
        "<tr><td>3</td><td>7</td></tr></table>"
    )
    made = make(html)
    found = findings_of(look(owner, made.sid, width=600, height=400))
    messages = [f["message"] for f in found if f["rule"] == "table"]
    assert any('"f [Hz]"' in m and "right-aligned" in m for m in messages), found
    assert any('"f [Hz]"' in m and "decimal" in m for m in messages), found


SCROLL_BELOW = (
    '<div class="scroll" style="height:80px;overflow:auto;width:300px">{inside}</div>'
    "<p>Text under the scroll area that stays in view.</p>"
)
SCROLL_CASES = {
    "text": "".join(f"<p>Line {n} inside the scroll area</p>" for n in range(30)),
    "table": "<table>"
    + "".join(f"<tr><td>row {n} cell</td><td>{n}.0</td></tr>" for n in range(30))
    + "</table>",
}


@pytest.mark.parametrize("kind", SCROLL_CASES)
def test_chk_19_text_clipped_by_a_scroll_area_is_not_compared_with_the_page(
    owner, make, kind
) -> None:  # noqa: ANN001
    """Hidden rows of a scroll area do not overlap what follows it (#56)."""
    made = make(page(SCROLL_BELOW.format(inside=SCROLL_CASES[kind])))
    result = look(owner, made.sid, width=600, height=500)
    assert "overlap" not in [f["rule"] for f in result["audit"]["findings"]]


def test_chk_19_overlap_between_visible_text_is_still_found(owner, make) -> None:  # noqa: ANN001
    made = make(
        page(
            '<div style="height:80px;overflow:auto;width:300px"><p>Visible line</p></div>'
            '<p style="margin-top:-60px;position:relative">Visible line</p>'
        )
    )
    result = look(owner, made.sid, width=600, height=500)
    assert "overlap" in [f["rule"] for f in result["audit"]["findings"]]
