"""Plot theme and axis bar of ``canvas-plot`` (PLT-01 to PLT-06)."""

from __future__ import annotations

import json

import pytest

from .support import block
from .test_heavy_blocks import wait_plot

pytestmark = pytest.mark.browser

PLOTLY_PY_DEFAULT = {
    "layout": {
        "colorway": ["#636efa", "#EF553B", "#00cc96"],
        "paper_bgcolor": "white",
        "plot_bgcolor": "#E5ECF6",
        "font": {"color": "#2a3f5f"},
    },
    "data": {"scatter": [{"type": "scatter"}]},
}
PLOTLY_WHITE = {
    "layout": {
        "colorway": ["#636efa", "#EF553B", "#00cc96"],
        "paper_bgcolor": "white",
        "plot_bgcolor": "white",
    }
}
OKABE_BLUE = "#0072B2"
LINE = {"x": [1, 2, 3, 4], "y": [1, 10, 100, 1000], "mode": "lines+markers"}


def figure(layout: dict | None = None, **extra) -> dict:  # noqa: ANN003
    """A one-trace figure; ``extra`` adds block config keys."""
    return {"data": [dict(LINE)], "layout": layout or {}, **extra}


def js(owner, body: str, canvas_id: str = "p"):  # noqa: ANN001, ANN201
    """Evaluate ``body`` in the frame with ``gd`` (the Plotly div) and ``bar``."""
    script = (
        "(() => { const root = document.querySelector("
        f"'canvas-plot[data-canvas-id={canvas_id}]').shadowRoot;"
        " const gd = root.querySelector('.plot');"
        " const bar = root.querySelector('.axis-bar');"
        f" {body} }})()"
    )
    return owner.frame.evaluate(script)


def show_plot(make, owner, config: dict, files: dict | None = None):  # noqa: ANN001, ANN201
    """Show one plot called ``p`` and wait until it is drawn."""
    made = make(block("canvas-plot", "p", config), files=files)
    wait_plot(owner, "p")
    return made


def wait_js(owner, body: str, canvas_id: str = "p") -> None:  # noqa: ANN001
    """Wait until the JavaScript ``body`` (a return statement) is truthy."""
    script = (
        "() => { const root = document.querySelector("
        f"'canvas-plot[data-canvas-id={canvas_id}]').shadowRoot;"
        " const gd = root.querySelector('.plot');"
        " const bar = root.querySelector('.axis-bar');"
        f" try {{ {body} }} catch (e) {{ return false; }} }}"
    )
    owner.frame.wait_for_function(script)


def group(owner, axis: str):  # noqa: ANN001, ANN201
    """The locator of the bar group of ``axis`` (``x``, ``y``, ``y2``)."""
    return owner.frame.locator(f'canvas-plot .axis-group[data-axis="{axis}"]')


# ---- PLT-01 / PLT-02: the theme ----------------------------------------------------


def test_plt_01_default_theme_font_colours_grid_and_margins(owner, make) -> None:  # noqa: ANN001
    show_plot(make, owner, figure())
    colours = js(owner, "return gd._fullLayout.colorway;")
    assert colours[0] == OKABE_BLUE and len(set(colours)) >= 7
    family = js(owner, "return gd._fullLayout.font.family;")
    assert "system-ui" in family
    assert js(owner, "return gd._fullLayout.yaxis.gridcolor;") == "#e6eaef"
    # Plotly's default left margin is 80 px; the themed plot makes room as needed.
    assert js(owner, "return gd._fullLayout._size.l;") < 70


def test_plt_01_dark_variant_follows_the_scheme_also_while_open(owner, make) -> None:  # noqa: ANN001
    owner.page.emulate_media(color_scheme="dark")
    show_plot(make, owner, figure())
    assert js(owner, "return gd._fullLayout.yaxis.gridcolor;") != "#e6eaef"
    dark_paper = js(owner, "return gd._fullLayout.paper_bgcolor;")
    owner.page.emulate_media(color_scheme="light")
    wait_js(owner, "return gd._fullLayout.yaxis.gridcolor === '#e6eaef';")
    assert js(owner, "return gd._fullLayout.paper_bgcolor;") != dark_paper
    # The redraw keeps the plot's room: it must not collapse to a zero-height div.
    assert js(owner, "return gd.getBoundingClientRect().height;") >= 400


def test_plt_02_the_agents_layout_wins_over_the_theme(owner, make) -> None:  # noqa: ANN001
    layout = {
        "colorway": ["#123456", "#654321"],
        "font": {"family": "serif"},
        "margin": {"l": 110, "r": 30, "t": 30, "b": 60},
    }
    show_plot(make, owner, figure(layout))
    assert js(owner, "return gd._fullLayout.colorway[0];") == "#123456"
    assert js(owner, "return gd._fullLayout.font.family;") == "serif"
    assert js(owner, "return gd._fullLayout._size.l;") == 110
    # What the agent left open still comes from the theme.
    assert js(owner, "return gd._fullLayout.yaxis.gridcolor;") == "#e6eaef"


# ---- PLT-03: plotly.py's default template -------------------------------------------


def test_plt_03_the_plotly_py_default_template_is_replaced(owner, make) -> None:  # noqa: ANN001
    show_plot(make, owner, figure({"template": PLOTLY_PY_DEFAULT}))
    assert js(owner, "return gd._fullLayout.colorway[0];") == OKABE_BLUE
    assert js(owner, "return gd._fullLayout.plot_bgcolor;") != "#E5ECF6"


def test_plt_03_theme_figure_keeps_the_figures_own_template(owner, make) -> None:  # noqa: ANN001
    config = figure({"template": PLOTLY_PY_DEFAULT}, theme="figure")
    show_plot(make, owner, config)
    assert js(owner, "return gd._fullLayout.colorway[0];") == "#636efa"
    assert js(owner, "return gd._fullLayout.plot_bgcolor;") == "#E5ECF6"


def test_plt_03_another_template_is_the_agents_choice_and_is_kept(owner, make) -> None:  # noqa: ANN001
    show_plot(make, owner, figure({"template": PLOTLY_WHITE}))
    assert js(owner, "return gd._fullLayout.colorway[0];") == "#636efa"
    assert js(owner, "return gd._fullLayout.plot_bgcolor;") == "white"


def test_plt_03_src_figures_get_the_same_treatment(owner, make) -> None:  # noqa: ANN001
    themed = json.dumps(figure({"template": PLOTLY_PY_DEFAULT}))
    made = show_plot(make, owner, {"src": "fig.json"}, files={"fig.json": themed})
    assert js(owner, "return gd._fullLayout.colorway[0];") == OKABE_BLUE
    kept = json.dumps(figure({"template": PLOTLY_PY_DEFAULT}, theme="figure"))
    (made.folder / "fig.json").write_text(kept)
    wait_js(owner, "return gd._fullLayout.colorway[0] === '#636efa';")


# ---- PLT-04: the axis bar -----------------------------------------------------------


def test_plt_04_bar_lists_each_cartesian_axis(owner, make) -> None:  # noqa: ANN001
    config = {
        "data": [dict(LINE), {"x": [1, 2], "y": [5, 6], "yaxis": "y2"}],
        "layout": {"yaxis2": {"overlaying": "y", "side": "right"}},
    }
    show_plot(make, owner, config)
    for axis in ("x", "y", "y2"):
        assert group(owner, axis).count() == 1, axis
        for part in ("axis-lin", "axis-log", "axis-min", "axis-max", "axis-auto"):
            assert group(owner, axis).locator(f".{part}").count() == 1, (axis, part)


def test_plt_04_log_toggle_min_max_and_autoscale(owner, make) -> None:  # noqa: ANN001
    show_plot(make, owner, figure())
    y = group(owner, "y")
    y.locator(".axis-log").click()
    wait_js(owner, "return gd._fullLayout.yaxis.type === 'log';")
    assert y.locator(".axis-log").get_attribute("aria-pressed") == "true"
    y.locator(".axis-min").fill("10")
    y.locator(".axis-max").fill("100")
    y.locator(".axis-max").press("Enter")
    wait_js(owner, "return Math.abs(gd._fullLayout.yaxis.range[1] - 2) < 1e-6;")
    low = js(owner, "return gd._fullLayout.yaxis.range[0];")
    assert abs(low - 1) < 1e-6 and js(owner, "return !gd._fullLayout.yaxis.autorange;")
    y.locator(".axis-auto").click()
    wait_js(owner, "return gd._fullLayout.yaxis.autorange === true;")
    y.locator(".axis-lin").click()
    wait_js(owner, "return gd._fullLayout.yaxis.type === 'linear';")
    assert y.locator(".axis-log").get_attribute("aria-pressed") == "false"


def test_plt_04_the_inputs_show_the_current_range_in_data_units(owner, make) -> None:  # noqa: ANN001
    show_plot(make, owner, figure({"xaxis": {"range": [0, 5]}}))
    x = group(owner, "x")
    assert float(x.locator(".axis-min").input_value()) == 0
    assert float(x.locator(".axis-max").input_value()) == 5
    group(owner, "y").locator(".axis-log").click()
    wait_js(owner, "return gd._fullLayout.yaxis.type === 'log';")
    high = float(group(owner, "y").locator(".axis-max").input_value())
    assert 1000 <= high <= 2000  # a data value, not the exponent


def test_plt_04_axes_false_hides_the_bar(owner, make) -> None:  # noqa: ANN001
    show_plot(make, owner, figure(axes=False))
    assert owner.frame.locator("canvas-plot .axis-bar").count() == 0


@pytest.mark.parametrize(
    "trace",
    [
        {"type": "pie", "values": [1, 2, 3]},
        {"type": "scatter3d", "x": [1, 2], "y": [1, 2], "z": [1, 2], "mode": "markers"},
        {"type": "scatterpolar", "r": [1, 2], "theta": [0, 90]},
    ],
)
def test_plt_04_no_bar_without_cartesian_axes(owner, make, trace: dict) -> None:  # noqa: ANN001
    make(block("canvas-plot", "p", {"data": [trace]}))
    owner.frame.wait_for_function(
        "document.querySelector('canvas-plot').shadowRoot.querySelector('.plot.js-plotly-plot')"
    )
    owner.page.wait_for_timeout(300)
    assert owner.frame.locator("canvas-plot .axis-bar").count() == 0
    assert owner.frame.locator(".block-error").count() == 0


# ---- PLT-05: the owner's axes survive a rewrite ---------------------------------------  # noqa: E501


def set_log_and_range(owner) -> None:  # noqa: ANN001
    """Make y logarithmic and x run from 2 to 4 through the bar."""
    group(owner, "y").locator(".axis-log").click()
    wait_js(owner, "return gd._fullLayout.yaxis.type === 'log';")
    x = group(owner, "x")
    x.locator(".axis-min").fill("2")
    x.locator(".axis-max").fill("4")
    x.locator(".axis-max").press("Enter")
    wait_js(owner, "return gd._fullLayout.xaxis.range[0] === 2;")


def test_plt_05_axis_changes_survive_a_rewrite_of_the_src_file(owner, make) -> None:  # noqa: ANN001
    made = show_plot(
        make, owner, {"src": "fig.json"}, {"fig.json": json.dumps(figure())}
    )
    set_log_and_range(owner)
    newer = figure()
    newer["data"][0]["y"] = [7, 70, 700, 7000]
    (made.folder / "fig.json").write_text(json.dumps(newer))
    wait_js(owner, "return gd.data[0].y[0] === 7;")
    assert js(owner, "return gd._fullLayout.yaxis.type;") == "log"
    assert js(owner, "return gd._fullLayout.xaxis.range;") == [2, 4]
    assert float(group(owner, "x").locator(".axis-min").input_value()) == 2


def test_plt_05_axis_changes_survive_a_rewrite_of_the_page(owner, make) -> None:  # noqa: ANN001
    made = show_plot(make, owner, figure())
    set_log_and_range(owner)
    newer = figure()
    newer["data"][0]["y"] = [7, 70, 700, 7000]
    made.rewrite(block("canvas-plot", "p", newer))
    wait_js(owner, "return gd.data[0].y[0] === 7;")
    assert js(owner, "return gd._fullLayout.yaxis.type;") == "log"
    assert js(owner, "return gd._fullLayout.xaxis.range;") == [2, 4]


def test_plt_05_a_new_uirevision_resets_the_owner_view(owner, make) -> None:  # noqa: ANN001
    made = show_plot(make, owner, figure({"uirevision": "a"}))
    set_log_and_range(owner)
    made.rewrite(block("canvas-plot", "p", figure({"uirevision": "b"})))
    wait_js(owner, "return gd._fullLayout.yaxis.type === 'linear';")
    assert js(owner, "return gd._fullLayout.xaxis.autorange;") is True


def test_plt_05_mouse_zoom_is_kept_too(owner, make) -> None:  # noqa: ANN001
    made = show_plot(make, owner, figure())
    js(owner, "Plotly.relayout(gd, {'xaxis.range': [2, 3]}); return 1;")
    wait_js(owner, "return gd._fullLayout.xaxis.range[0] === 2;")
    newer = figure()
    newer["data"][0]["y"] = [9, 9, 9, 9]
    made.rewrite(block("canvas-plot", "p", newer))
    wait_js(owner, "return gd.data[0].y[0] === 9;")
    assert js(owner, "return gd._fullLayout.xaxis.range;") == [2, 3]


# ---- PLT-06: log with values that cannot be shown ------------------------------------


def test_plt_06_log_with_non_positive_values_still_draws_and_says_so(
    owner, make
) -> None:  # noqa: ANN001
    data = [{"x": [1, 2, 3, 4], "y": [0, -5, 10, 100], "mode": "lines+markers"}]
    show_plot(make, owner, {"data": data})
    note = owner.frame.locator("canvas-plot .axis-note")
    assert not note.is_visible()
    group(owner, "y").locator(".axis-log").click()
    wait_js(owner, "return gd._fullLayout.yaxis.type === 'log';")
    note.wait_for(state="visible")
    assert "y" in note.inner_text() and "2" in note.inner_text()
    assert owner.frame.locator(".block-error").count() == 0
    assert owner.page.evaluate("window.__errors") == []
    group(owner, "y").locator(".axis-lin").click()
    note.wait_for(state="hidden")


# ---- pictures for the owner ----------------------------------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_plt_04_bar_picture_with_secondary_axis_and_log_note(
    owner, make, scheme: str
) -> None:  # noqa: ANN001
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.set_viewport_size({"width": 900, "height": 800})
    data = [
        {"x": [1, 2, 3, 4, 5], "y": [0, 3, 12, 40, 150], "name": "force (N)",
         "mode": "lines+markers"},
        {"x": [1, 2, 3, 4, 5], "y": [0.2, 0.5, 0.9, 1.4, 2.2], "name": "stroke (mm)",
         "yaxis": "y2", "mode": "lines+markers"},
    ]  # fmt: skip
    layout = {
        "title": {"text": "Actuator test"},
        "xaxis": {"title": {"text": "step"}},
        "yaxis": {"title": {"text": "force (N)"}},
        "yaxis2": {
            "title": {"text": "stroke (mm)"},
            "overlaying": "y",
            "side": "right",
        },
        "height": 380,
    }
    show_plot(make, owner, {"data": data, "layout": layout})
    group(owner, "y").locator(".axis-log").click()
    wait_js(owner, "return gd._fullLayout.yaxis.type === 'log';")
    owner.frame.locator("canvas-plot .axis-note").wait_for(state="visible")
    owner.page.wait_for_timeout(500)
    owner.page.screenshot(path=f"/tmp/plot-check-{scheme}.png")


# ---- secondary axes keep their own ticks ---------------------------------------------

DUAL = {
    "data": [
        {"x": [1, 2, 3, 4, 5], "y": [1, 3, 12, 40, 150], "mode": "lines"},
        {"x": [1, 2, 3, 4, 5], "y": [0.2, 0.5, 0.9, 1.4, 2.2], "yaxis": "y2",
         "mode": "lines"},
    ],
    "layout": {"yaxis2": {"overlaying": "y", "side": "right"}, "height": 380},
}  # fmt: skip

TICK_BOXES = (
    "const t = [...gd.querySelectorAll('.y2tick text')]"
    ".map((e) => e.getBoundingClientRect());"
    " return t.map((r) => [r.top, r.bottom]);"
)


@pytest.mark.parametrize("y_log", [False, True])
@pytest.mark.parametrize("y2_log", [False, True])
def test_plt_04_secondary_axis_keeps_readable_ticks(owner, make, y_log, y2_log) -> None:  # noqa: ANN001
    show_plot(make, owner, DUAL)
    for axis, on in (("y", y_log), ("y2", y2_log)):
        if on:
            group(owner, axis).locator(".axis-log").click()
            wait_js(
                owner,
                f"return gd._fullLayout.{axis.replace('y', 'yaxis')}.type === 'log';",
            )
    owner.page.wait_for_timeout(300)
    boxes = js(owner, TICK_BOXES)
    assert 2 <= len(boxes) <= 12, boxes
    ordered = sorted(boxes)
    for upper, lower in zip(ordered, ordered[1:]):
        assert upper[1] <= lower[0] + 1, ordered  # no label overlaps the next
