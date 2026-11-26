"""``look`` in a real browser: window renderer and headless fallback (LOOK-03 to 09).

The owner's window is headless Chromium driving the shell; the hub is real.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub.headless import HeadlessRenderer
from helpers import decode_png, own_draft

from .conftest import _launch_env
from .support import SCROLL_PAGE, block, call, card_events, owner_field
from .test_heavy_blocks import GREEN, plot_config

pytestmark = pytest.mark.browser

TEAL = (42, 157, 143)
WHITE = (255, 255, 255)
LIGHT_TOP, DARK_TOP, DARK_BODY = (207, 232, 255), (18, 52, 86), (16, 24, 32)

# 300 px "top" strip, a 200 x 120 teal target at x = 100, then a 1500 px tail:
# 1920 px high. In dark mode the body and the strip change colour.
LOOK_PAGE = """<!doctype html><html><head><title>t</title><style>
body { margin: 0; background: #ffffff; }
#top { height: 300px; background: #cfe8ff; }
#target { margin-left: 100px; width: 200px; height: 120px; background: #2a9d8f; }
#tail { height: 1500px; }
@media (prefers-color-scheme: dark) {
  body { background: #101820; } #top { background: #123456; }
}
</style></head><body>
<div id="top"></div><div id="target" data-canvas-id="spectrum"></div>
<div id="tail"></div>
</body></html>"""


def near(pixel, colour, tolerance: int = 14) -> bool:  # noqa: ANN001
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


@pytest.fixture
def headless(owner) -> HeadlessRenderer:  # noqa: ANN001
    """Give the hub a headless renderer that can start in this environment."""
    renderer = HeadlessRenderer(launch_env=_launch_env())
    owner.hub.app.state.looks.headless = renderer
    return renderer


def look(owner, sid: str, **body) -> dict:  # noqa: ANN001, ANN003
    # A loaded machine may need longer than the hub's 10 s for the window: wait.
    owner.hub.app.state.looks.window_timeout = 60.0
    return call(owner, "POST", f"/api/sessions/{sid}/look", json=body, timeout=90)


def decoded(result: dict):  # noqa: ANN201
    width, height, rows = decode_png(Path(result["png"]).read_bytes())
    assert (width, height) == (result["width"], result["height"])
    return rows


def snapshot(owner) -> dict:  # noqa: ANN001
    """What the owner could notice changing in the shell."""
    return owner.page.evaluate(
        """() => ({
          active: activeId,
          scroll: document.getElementById('frame').contentWindow ? null : null,
          focused: document.activeElement && document.activeElement.id,
          iframes: document.querySelectorAll('iframe').length,
          reports: window.__reports.length,
          guard: JSON.stringify({
            ...window.__guard,
            // the page's heartbeat comes every second, whatever the owner does
            accepted: {...window.__guard.accepted, heartbeat: 0},
          }),
          errors: window.__errors.length,
          pills: document.querySelectorAll('.tab .pill').length,
          title: document.title,
        })"""
    )


# ---- LOOK-03 window renderer --------------------------------------------------


def test_look_03_the_window_renders_the_page_at_its_own_size(owner, make) -> None:  # noqa: ANN001
    # Tall enough that the 1920 px page stays under 3 windows (no page-height note).
    owner.page.set_viewport_size({"width": 1280, "height": 800})
    made = make(LOOK_PAGE)
    # The comment panel's strip changes the frame once the tab is open and the
    # window's report is debounced: wait until the hub holds the frame's size.
    for _ in range(60):
        size = owner.frame.evaluate("[innerWidth, innerHeight]")
        info = owner.hub.on_loop(owner.hub.state.looks.window_info)
        if info and [info.width, info.height] == size:
            break
        owner.page.wait_for_timeout(100)
    result = look(owner, made.sid)
    assert result["source"] == "window" and result["scheme"] == "light", result
    assert [result["width"], result["height"]] == size
    rows = decoded(result)
    assert near(rows[100][size[0] // 2], LIGHT_TOP)
    assert near(rows[360][200], TEAL) and near(rows[360][99], WHITE)
    assert near(rows[360][300], WHITE) and near(rows[size[1] - 5][200], WHITE)
    assert result["errors"] == [] and result["audit"]["findings"] == []
    assert Path(result["png"]).parent.name == "looks"


def test_look_02_the_window_reports_its_size_and_scheme(owner, make) -> None:  # noqa: ANN001
    made = make(LOOK_PAGE)
    hub = owner.hub

    def reported() -> tuple:
        info = hub.on_loop(hub.state.looks.window_info)
        return (info.width, info.height, info.scheme) if info else ()

    owner.page.set_viewport_size({"width": 1000, "height": 640})
    owner.page.emulate_media(color_scheme="dark")
    for _ in range(60):
        owner.page.wait_for_timeout(100)
        size = owner.page.evaluate(
            "[frame.clientWidth, frame.clientHeight, "
            "matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light']"
        )
        if reported() == tuple(size) and size[2] == "dark":
            break
    width = owner.page.locator("main").bounding_box()["width"]
    assert reported() == tuple(size) and size[2] == "dark"
    assert size[0] == width
    result = look(owner, made.sid, width=300, height=200)
    assert result["scheme"] == "dark" and result["source"] == "window"
    assert near(decoded(result)[100][250], DARK_TOP)


def test_look_03_a_look_changes_nothing_the_owner_could_notice(owner, studio) -> None:  # noqa: ANN001
    alpha = studio.make(LOOK_PAGE + "<input id=auto autofocus>", "alpha")
    beta = studio.make(SCROLL_PAGE, "beta")  # the tab the owner is on
    studio.frame.evaluate("window.scrollTo(0, 340)")
    studio.frame.wait_for_function("window.scrollY === 340")
    # the owner's own scroll reaches the shell (D-56) before the baseline
    owner.page.wait_for_function("(window.__guard.accepted['scroll-pos'] || 0) >= 1")
    owner_field(owner.page)
    owner.page.fill("#owner-field", "half written thought")
    owner.page.focus("#owner-field")
    before = snapshot(owner)
    assert before["active"] == beta and before["focused"] == "owner-field"
    events = card_events(owner.hub, alpha)
    result = look(owner, alpha, width=500, height=300)
    assert result["source"] == "window", result
    after = snapshot(owner)
    assert after == before
    assert studio.frame.evaluate("window.scrollY") == 340
    assert owner.page.input_value("#owner-field") == "half written thought"
    assert card_events(owner.hub, alpha) == events
    # the look's hidden frame is gone; the two pages keep their frames (SES-15)
    assert owner.page.locator("iframe").count() == before["iframes"]
    assert card_events(owner.hub, beta) == []


FOCUS_THIEF = (
    "<input id=thief autofocus>"
    "<script>addEventListener('load', () => {"
    " document.getElementById('thief').focus(); window.focus(); });</script>"
)


def test_look_03_a_page_that_grabs_focus_does_not_get_it(owner, studio) -> None:  # noqa: ANN001
    alpha = studio.make(LOOK_PAGE + FOCUS_THIEF, "alpha")
    studio.make(SCROLL_PAGE, "beta")
    owner_field(owner.page)
    owner.page.fill("#owner-field", "keep me")
    owner.page.focus("#owner-field")
    look(owner, alpha, width=300, height=200)
    assert owner.page.evaluate("document.activeElement.id") == "owner-field"
    assert owner.page.evaluate("document.hasFocus()")


def test_look_03_errors_of_the_rendered_page_come_back_and_stay_out_of_the_tab(
    owner, make
) -> None:  # noqa: ANN001
    made = make(LOOK_PAGE)
    (made.folder / "broken.html").write_text(
        "<p>x</p><script>throw new Error('kaboom')</script>"
        + block("canvas-table", "bad", {"columns": "a", "rows": []})
    )
    before = snapshot(owner)
    result = look(owner, made.sid, page="broken.html", width=300, height=200)
    messages = [e["message"] for e in result["errors"]]
    assert any("kaboom" in m for m in messages), result
    assert any(
        e["source"] == "block" and e["canvas_id"] == "bad" for e in result["errors"]
    )
    assert snapshot(owner) == before
    assert owner.page.locator("#tab-badge:visible").count() == 0


# ---- DRAFT-02: a draft is invisible, a look at it is not ---------------------


def test_draft_02_the_window_never_shows_a_draft_but_a_look_can(owner, make) -> None:  # noqa: ANN001
    made = make(LOOK_PAGE)
    owner.frame.evaluate("window.__marker = 'same document'")
    pills = owner.page.locator(".tab .pill.updated").count()
    draft = made.folder / own_draft(made.sid)
    draft.write_text(LOOK_PAGE.replace("#2a9d8f", "#e5484d"))
    owner.page.wait_for_timeout(900)
    draft.write_text(LOOK_PAGE.replace("#2a9d8f", "#e5484d") + "<!-- again -->")
    owner.page.wait_for_timeout(900)
    assert owner.frame.evaluate("window.__marker") == "same document"
    assert (
        owner.frame.evaluate("document.getElementById('target').style.background") == ""
    )
    assert owner.page.locator(".hv-card.focus .hv-pt").count() <= 1
    assert owner.page.locator(".tab .pill.updated").count() == pills
    result = look(owner, made.sid, draft=True, width=400, height=500)
    assert result["draft"] is True and result["source"] == "window"
    assert near(decoded(result)[360][200], (229, 72, 77))
    published = look(owner, made.sid, width=400, height=500)
    assert near(decoded(published)[360][200], TEAL)


# ---- LOOK-04 readiness -----------------------------------------------------------

SLOW_BLOCK = """<!doctype html><html><body style="margin:0">
<div id="flag" style="width:200px;height:100px;background:#e5484d"></div>
<script type="module">
import {CanvasBlock} from "/static/blocks/base.js";
class Slow extends CanvasBlock {
  async render() {
    await new Promise((resolve) => setTimeout(resolve, 700));
    for (let i = 0; i < 3; i++) await new Promise((r) => requestAnimationFrame(r));
    document.getElementById("flag").style.background = "#2a9d8f";
  }
}
customElements.define("canvas-slow", Slow);
</script>
<canvas-slow data-canvas-id="slow"></canvas-slow></body></html>"""

HANGING_BLOCK = """<!doctype html><html><body style="margin:0">
<div style="width:200px;height:100px;background:#2a9d8f"></div>
<script type="module">
import {CanvasBlock} from "/static/blocks/base.js";
class Hang extends CanvasBlock { render() { return new Promise(() => {}); } }
customElements.define("canvas-hang", Hang);
</script>
<canvas-hang data-canvas-id="hang"></canvas-hang></body></html>"""


def test_look_04_the_picture_waits_for_slow_blocks_and_animation_frames(
    owner, make
) -> None:  # noqa: ANN001
    made = make(SLOW_BLOCK)
    result = look(owner, made.sid, width=300, height=200)
    assert near(decoded(result)[50][100], TEAL), "captured before the block finished"
    assert not [n for n in result["notes"] if "settle" in n]


def test_look_04_plots_are_drawn_before_the_picture_is_taken(owner, make) -> None:  # noqa: ANN001
    html = "<body style='margin:0;background:#fff'>" + block(
        "canvas-plot", "spectrum", plot_config()
    )
    made = make(html)
    result = look(owner, made.sid, width=700, height=450)
    rows = decoded(result)
    greens = sum(near(p, GREEN, 30) for row in rows[:420] for p in row[:620:2])
    assert greens > 200, "the plot line is missing from the picture"


def test_look_04_blocks_report_when_they_are_rendered(owner, make) -> None:  # noqa: ANN001
    html = block("canvas-markdown", "md", {"text": "Euler $e^{i\\pi}=-1$"})
    made = make(html)
    state = owner.frame.evaluate(
        """async () => {
          const el = document.querySelector('canvas-markdown');
          await el.whenRendered();
          return [el.renderIdle, !!el.shadowRoot.querySelector('.katex')];
        }"""
    )
    assert state == [True, True] and made.sid


def test_look_04_a_page_that_never_settles_is_captured_with_a_note(owner, make) -> None:  # noqa: ANN001
    made = make(HANGING_BLOCK)
    owner.hub.app.state.looks.settle_seconds = 1.0
    result = look(owner, made.sid, width=300, height=200)
    assert result["source"] == "window", result
    assert near(decoded(result)[50][100], TEAL)
    assert any("did not settle" in n for n in result["notes"]), result


# ---- LOOK-05 / LOOK-06: sizes, full page, sections, in both renderers --------

RENDERERS = [
    pytest.param("light", "window", WHITE, LIGHT_TOP, id="window"),
    pytest.param("dark", "headless", DARK_BODY, DARK_TOP, id="headless"),
]


@pytest.mark.parametrize(("scheme", "source", "body", "top"), RENDERERS)
def test_look_05_the_default_picture_is_the_viewport_from_the_top(
    owner,
    make,
    headless,
    scheme,
    source,
    body,
    top,  # noqa: ANN001
) -> None:
    made = make(LOOK_PAGE)
    result = look(owner, made.sid, width=400, height=500, scheme=scheme)
    assert result["source"] == source and result["scheme"] == scheme, result
    assert (result["width"], result["height"]) == (400, 500)
    rows = decoded(result)
    assert near(rows[100][50], top) and near(rows[360][200], TEAL)
    assert near(rows[480][200], body) and near(rows[360][50], body)


@pytest.mark.parametrize(("scheme", "source", "body", "top"), RENDERERS)
def test_look_05_full_captures_the_whole_page_height(
    owner,
    make,
    headless,
    scheme,
    source,
    body,
    top,  # noqa: ANN001
) -> None:
    made = make(LOOK_PAGE)
    result = look(owner, made.sid, width=400, height=500, scheme=scheme, full=True)
    assert result["source"] == source
    assert (result["width"], result["height"]) == (400, 1920)
    rows = decoded(result)
    assert near(rows[100][50], top) and near(rows[360][200], TEAL)
    assert near(rows[1900][200], body)


@pytest.mark.parametrize(("scheme", "source", "body", "top"), RENDERERS)
def test_look_05_a_section_is_cropped_with_8_px_of_padding(
    owner,
    make,
    headless,
    scheme,
    source,
    body,
    top,  # noqa: ANN001
) -> None:
    made = make(LOOK_PAGE)
    result = look(
        owner, made.sid, width=400, height=500, scheme=scheme, section="spectrum"
    )
    assert result["source"] == source, result
    assert (result["width"], result["height"]) == (216, 136)
    rows = decoded(result)
    assert near(rows[68][108], TEAL) and near(rows[10][108], TEAL)  # the element
    assert near(rows[3][3], top)  # padding above the element: the top strip
    assert near(rows[130][3], body)  # padding below it: the page background
    by_id = look(owner, made.sid, width=400, height=500, scheme=scheme, section="top")
    assert (by_id["width"], by_id["height"]) == (400, 308)  # clamped at the edges


LOW_PAGE = LOOK_PAGE.replace(
    '<div id="top"></div>', '<div id="top" style="height:1300px"></div>'
)


@pytest.mark.parametrize(("scheme", "source", "body", "top"), RENDERERS)
def test_look_05_a_section_below_the_first_screen_is_not_blank(
    owner,
    make,
    headless,
    scheme,
    source,
    body,
    top,  # noqa: ANN001
) -> None:
    """A section lower than the window is drawn, not left white (#52)."""
    made = make(LOW_PAGE)
    result = look(
        owner, made.sid, width=400, height=500, scheme=scheme, section="spectrum"
    )
    assert result["source"] == source, result
    assert (result["width"], result["height"]) == (216, 136)
    rows = decoded(result)
    assert near(rows[68][108], TEAL)
    assert near(rows[3][3], top)


def test_look_05_a_draft_section_below_the_first_screen_is_not_blank(
    owner, make, headless
) -> None:  # noqa: ANN001
    """The same for a NAME.draft.html page (#52)."""
    made = make("<p>published</p>")
    (made.folder / own_draft(made.sid)).write_text(LOW_PAGE)
    result = look(
        owner, made.sid, width=400, height=500, draft=True, section="spectrum"
    )
    assert (result["width"], result["height"]) == (216, 136)
    assert near(decoded(result)[68][108], TEAL)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_look_05_an_unknown_section_is_an_error_in_either_renderer(
    owner,
    make,
    headless,
    scheme,  # noqa: ANN001
) -> None:
    made = make(LOOK_PAGE)
    result = call(
        owner, "POST", f"/api/sessions/{made.sid}/look",
        json={"section": "nope", "scheme": scheme, "width": 300, "height": 200},
    )  # fmt: skip
    assert result["error"] == "failed" and "nope" in result["message"]


# ---- LOOK-06 fallback ---------------------------------------------------------------


def test_look_06_headless_renders_exactly_what_the_window_would(
    owner,
    make,
    headless,  # noqa: ANN001
) -> None:
    made = make(LOOK_PAGE)
    in_window = look(owner, made.sid, width=400, height=500)
    in_headless = look(owner, made.sid, width=400, height=500, scheme="dark")
    assert in_window["source"] == "window" and in_headless["source"] == "headless"
    assert (in_window["width"], in_window["height"]) == (
        in_headless["width"],
        in_headless["height"],
    )
    a, b = decoded(in_window), decoded(in_headless)
    assert near(a[360][200], b[360][200][:3]) and near(a[360][200], TEAL)
    assert near(a[480][50], WHITE) and near(b[480][50], DARK_BODY)


def test_look_06_without_a_window_the_hub_renders_headless_at_1280_by_800(
    hub,
    tmp_path,  # noqa: ANN001
) -> None:
    hub.app.state.looks.headless = HeadlessRenderer(launch_env=_launch_env())
    hub.add_session("s1", {"page.html": LOOK_PAGE, "page.draft.html": LOOK_PAGE})
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/s1/look",
        headers=hub.key_headers,
        json={},
        timeout=90,
    )
    assert answer.status_code == 200, answer.text
    result = answer.json()
    assert result["source"] == "headless" and result["scheme"] == "light"
    assert (result["width"], result["height"]) == (1280, 800)
    rows = decoded(result)
    assert near(rows[100][640], LIGHT_TOP) and near(rows[360][200], TEAL)
    assert result["png"].endswith("history/looks/0001.png")
    assert hub.state.credentials.cookie_value not in json.dumps(result)


def test_look_06_headless_finds_no_browser_and_says_so(hub, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENT_CANVAS_BROWSER", "/nonexistent/chrome")
    hub.app.state.looks.headless = HeadlessRenderer(launch_env=_launch_env())
    hub.add_session("s1", {"page.html": LOOK_PAGE})
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/s1/look", headers=hub.key_headers, json={}
    )
    assert answer.status_code == 422
    message = answer.json()["message"]
    assert "agent-canvas open" in message and "AGENT_CANVAS_BROWSER" in message


# ---- LOOK-09 audit hook -------------------------------------------------------------

AUDITED = LOOK_PAGE.replace(
    "</body>",
    "<script>agentCanvas.runPageAudit = async () => ({findings: [{rule: 'custom',"
    " severity: 'warn', message: 'Own check.', where: '#x', bbox: null}]});"
    "</script></body>",
)


@pytest.mark.parametrize(
    ("scheme", "source"), [("light", "window"), ("dark", "headless")]
)
def test_look_09_the_audit_hook_runs_in_the_rendered_frame_and_returns_its_result(
    owner,
    make,
    headless,
    scheme,
    source,  # noqa: ANN001
) -> None:
    made = make(AUDITED)
    result = look(owner, made.sid, width=300, height=200, scheme=scheme)
    assert result["source"] == source
    [finding] = result["audit"]["findings"]
    assert finding["rule"] == "custom" and finding["severity"] == "warn"
    assert result["audit"]["counts"] == {"error": 0, "warn": 1, "info": 0}


def blocky_page() -> str:
    """A tall page like the agents build: kit tiles and cards around many blocks."""
    rows = [[f"r{i}", i * 0.5, "ok"] for i in range(25)]
    parts = [
        '<!doctype html><html><head><link rel="stylesheet" href="/static/kit/kit.css">'
        "</head><body>"
    ]
    for n in range(3):
        parts.append(
            f'<h2>Section {n}</h2><div class="card"><div class="tile">tile {n}</div>'
        )
        parts.append(
            block(
                "canvas-choices",
                f"c{n}",
                {
                    "mode": "single",
                    "submit": "Use",
                    "options": [
                        {
                            "id": f"o{k}",
                            "title": f"Option {k}",
                            "description": "x " * 30,
                        }
                        for k in range(5)
                    ],
                },
            )
        )
        parts.append(
            block("canvas-buttons", f"b{n}", {"buttons": [{"id": "go", "label": "Go"}]})
        )
        parts.append(block("canvas-textbox", f"t{n}", {"label": "Note"}))
        parts.append(
            block(
                "canvas-table",
                f"tb{n}",
                {"columns": ["run", "error", "state"], "rows": rows},
            )
        )
        parts.append(block("canvas-plot", f"p{n}", plot_config()))
        parts.append(
            block("canvas-progress", f"g{n}", {"value": 0.4, "status": "running"})
        )
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)


@pytest.mark.parametrize("audit", [True, False], ids=["audit", "no-audit"])
def test_look_05_full_gives_the_whole_page_in_the_window_with_the_audit_on(
    owner,
    make,
    audit,  # noqa: ANN001
) -> None:
    owner.page.set_viewport_size({"width": 1500, "height": 900})
    made = make(blocky_page())
    owner.frame.locator("canvas-plot .js-plotly-plot").first.wait_for()
    whole = owner.frame.evaluate("document.documentElement.scrollHeight")
    assert whole > 3000, whole
    result = look(owner, made.sid, full=True, audit=audit)
    assert result["source"] == "window", result
    assert result["height"] >= whole - 5, (result["height"], whole, result["notes"])


GROWING_PAGE = """<!doctype html><html><head><style>
body { margin: 0; } #top { height: 300px; background: #cfe8ff; }
#late { height: 3000px; background: #2a9d8f; }
</style></head><body><div id="top"></div>
<script>
// The page checks take a while here; the page grows while they run.
setTimeout(() => {
  const late = document.createElement("div");
  late.id = "late";
  document.body.append(late);
}, 700);
window.addEventListener("load", () => {
  window.agentCanvas.runPageAudit = () =>
    new Promise((done) => setTimeout(() => done({findings: []}), 1500));
});
</script></body></html>"""


def test_look_05_full_measures_again_after_the_page_checks(owner, make) -> None:  # noqa: ANN001
    made = make(GROWING_PAGE)
    result = look(owner, made.sid, full=True)
    assert result["source"] == "window", result
    assert result["audit"] is not None
    assert result["height"] == 3300, result
    assert near(decoded(result)[3250][50], TEAL)
