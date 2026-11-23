"""Ready-made blocks, part 2: plot, image, model (M10).

BLK-01 (plot, image, model, and the nine-block sweep), BLK-03 (model camera),
BLK-05, BLK-06, BLK-07, BLK-09, DRAW-06, DRAW-08 and the NFR-02 all-blocks page.
"""

from __future__ import annotations

import json
import os
import shutil
import time

import pytest

from helpers import decode_png

from .solids import cube_step, cube_stl, png
from .support import block, until

pytestmark = pytest.mark.browser

# ---- fixtures --------------------------------------------------------------------

# Fixed margins and ranges, so that the expected data coordinates of a pixel are
# known without asking Plotly: the plot area is 520 x 330 px at (60, 20).
PLOT_W, PLOT_H = 600, 400
MARGIN = {"l": 60, "r": 20, "t": 20, "b": 50}
AREA = (60, 20, 520, 330)  # left, top, width, height inside the plot box
X_RANGE, Y_RANGE = (0, 10), (0, 100)
GREEN = (10, 143, 8)


def plot_config(dragmode: str = "zoom", **trace) -> dict:
    """A scatter plot with a bright green line and a peak at x = 5."""
    xs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    ys = [5, 10, 20, 35, 60, 90, 60, 35, 20, 10, 5]
    return {
        "data": [
            {"x": xs, "y": ys, "mode": "lines+markers", "name": "spectrum",
             "line": {"color": "#0a8f08", "width": 5},
             "marker": {"size": 10}, **trace},
        ],
        "layout": {
            "width": PLOT_W, "height": PLOT_H, "margin": MARGIN,
            "xaxis": {"range": list(X_RANGE)}, "yaxis": {"range": list(Y_RANGE)},
            "dragmode": dragmode, "showlegend": False,
        },
        "config": {"displayModeBar": False},
    }  # fmt: skip


def data_to_page(frame, canvas_id: str, x: float, y: float) -> tuple[float, float]:
    """Frame-viewport pixel of the data point (x, y), from the fixed layout."""
    box = frame.evaluate(
        "(id) => { const r = document"
        ".querySelector(`canvas-plot[data-canvas-id=${id}]`)"
        ".shadowRoot.querySelector('.plot').getBoundingClientRect();"
        " return [r.left, r.top]; }",
        canvas_id,
    )
    left, top, width, height = AREA
    px = box[0] + left + (x - X_RANGE[0]) / (X_RANGE[1] - X_RANGE[0]) * width
    py = box[1] + top + (Y_RANGE[1] - y) / (Y_RANGE[1] - Y_RANGE[0]) * height
    return px, py


def to_window(owner, x: float, y: float) -> tuple[float, float]:  # noqa: ANN001
    """Convert frame-viewport coordinates to window coordinates."""
    box = owner.frame.frame_element().bounding_box()
    return box["x"] + x, box["y"] + y


def wait_plot(owner, canvas_id: str = "spectrum") -> None:  # noqa: ANN001
    """Wait until the plot has drawn its traces."""
    owner.frame.wait_for_function(
        "(id) => { const e = document"
        ".querySelector(`canvas-plot[data-canvas-id=${id}]`);"
        " return !!(e && e.shadowRoot.querySelector('.plot .scatterlayer .trace')); }",
        arg=canvas_id,
    )


def wait_model(owner, canvas_id: str = "part") -> None:  # noqa: ANN001
    """Wait until the model is loaded and drawn."""
    owner.frame.wait_for_function(
        "(id) => !!document.querySelector(`canvas-model[data-canvas-id=${id}]`)"
        ".shadowRoot.querySelector('.viewer.ready')",
        arg=canvas_id,
        timeout=30000,
    )


def paint_stats(data: bytes, background: tuple[int, int, int]) -> tuple[int, int]:
    """Return (pixel count, pixels clearly different from ``background``)."""
    _, _, rows = decode_png(data)
    pixels = [p for row in rows for p in row]
    different = [
        p for p in pixels
        if sum(abs(a - b) for a, b in zip(p[:3], background, strict=True)) > 40
    ]  # fmt: skip
    return len(pixels), len(different)


def near(pixel, colour, tolerance: int = 40) -> bool:  # noqa: ANN001
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


MODEL_BACKGROUND = (243, 245, 248)

# ---- BLK-01: plot ------------------------------------------------------------------


def test_blk_01_plot_renders_traces_from_the_config(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-plot", "spectrum", plot_config()))
    wait_plot(owner)
    root = owner.frame.locator("canvas-plot")
    assert root.locator(".scatterlayer .trace").count() == 1
    assert root.locator(".main-svg").count() >= 1
    # Plotly's own stylesheet must reach the shadow tree (it is added to the
    # document head, which a shadow root does not see).
    cursor = owner.frame.evaluate(
        "getComputedStyle(document.querySelector('canvas-plot').shadowRoot"
        ".querySelector('.plot .nsewdrag, .plot .drag')).cursor"
    )
    assert cursor != "auto"


def test_blk_01_plot_click_gives_a_plot_click_action(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-plot", "spectrum", plot_config()))
    wait_plot(owner)
    x, y = to_window(owner, *data_to_page(owner.frame, "spectrum", 5, 90))
    owner.page.mouse.move(x - 3, y - 3)
    owner.page.mouse.click(x, y)
    actions = made.wait_action("plot-click")
    action = next(a for a in actions)
    assert action["target"]["canvas_id"] == "spectrum"
    assert action["value"] == {"trace": 0, "index": 5, "x": 5, "y": 90}
    assert action["at"] is not None


def test_blk_01_plot_box_select_gives_a_plot_select_action(owner, make) -> None:  # noqa: ANN001
    made = make(block("canvas-plot", "spectrum", plot_config("select")))
    wait_plot(owner)
    start = to_window(owner, *data_to_page(owner.frame, "spectrum", 3.5, 95))
    end = to_window(owner, *data_to_page(owner.frame, "spectrum", 6.5, 50))
    owner.page.mouse.move(*start)
    owner.page.mouse.down()
    owner.page.mouse.move(*end, steps=6)
    owner.page.mouse.up()
    [action] = made.wait_action("plot-select")
    points = action["value"]["points"]
    assert [p["x"] for p in points] == [4, 5, 6]
    assert [p["y"] for p in points] == [60, 90, 60]
    assert action["value"]["total"] == 3 and action["target"]["canvas_id"] == "spectrum"


def test_blk_01_plot_select_reports_at_most_100_points(owner, make) -> None:  # noqa: ANN001
    config = plot_config("select")
    config["data"][0].update(
        x=[i / 30 for i in range(300)], y=[50 + (i % 7) for i in range(300)],
        mode="markers",
    )  # fmt: skip
    made = make(block("canvas-plot", "spectrum", config))
    wait_plot(owner)
    start = to_window(owner, *data_to_page(owner.frame, "spectrum", 0.1, 90))
    end = to_window(owner, *data_to_page(owner.frame, "spectrum", 9.9, 10))
    owner.page.mouse.move(*start)
    owner.page.mouse.down()
    owner.page.mouse.move(*end, steps=6)
    owner.page.mouse.up()
    [action] = made.wait_action("plot-select")
    assert len(action["value"]["points"]) == 100
    assert action["value"]["total"] >= 290


def test_blk_01_plot_errors_and_src(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-plot", "empty", {"layout": {}}))
    owner.frame.locator(".block-error").wait_for()
    assert "data" in owner.frame.locator(".block-error").inner_text()


def test_blk_03_plot_zoom_is_kept_when_the_page_changes_elsewhere(owner, make) -> None:  # noqa: ANN001
    page = "<p id=note>one</p>" + block("canvas-plot", "spectrum", plot_config())
    made = make(page)
    wait_plot(owner)
    owner.frame.evaluate(
        "Plotly.relayout(document.querySelector('canvas-plot').shadowRoot"
        ".querySelector('.plot'), {'xaxis.range': [2, 4]})"
    )
    made.rewrite(page.replace("one", "two"))
    owner.frame.wait_for_function("document.querySelector('#note').textContent==='two'")
    zoom = owner.frame.evaluate(
        "document.querySelector('canvas-plot').shadowRoot.querySelector('.plot')"
        "._fullLayout.xaxis.range"
    )
    assert zoom == [2, 4]


# ---- BLK-01: image -----------------------------------------------------------------

IMAGE_W, IMAGE_H = 200, 100


def image_file(width: int = IMAGE_W, height: int = IMAGE_H) -> bytes:
    """Left half red, right half blue."""
    return png(
        width, height, lambda x, y: (200, 30, 30) if x < width // 2 else (30, 30, 200)
    )


def image_rect(owner) -> dict:  # noqa: ANN001
    return owner.frame.evaluate(
        "(() => { const r = document.querySelector('canvas-image').shadowRoot"
        ".querySelector('img').getBoundingClientRect();"
        " return {left: r.left, top: r.top, width: r.width, height: r.height,"
        " natural: document.querySelector('canvas-image').shadowRoot"
        ".querySelector('img').naturalWidth}; })()"
    )


def image_page(make):  # noqa: ANN001, ANN201
    made = make(
        block("canvas-image", "pic", {"src": "pic.png", "alt": "red and blue"}),
        files={"pic.png": image_file()},
    )
    return made


def wait_image(owner) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "(() => { const i = document.querySelector('canvas-image')"
        " && document.querySelector('canvas-image').shadowRoot.querySelector('img');"
        " return !!i && i.complete && i.naturalWidth > 0; })()"
    )


def test_blk_01_image_renders_with_alt_text(owner, make) -> None:  # noqa: ANN001
    image_page(make)
    wait_image(owner)
    img = owner.frame.locator("canvas-image img")
    assert img.get_attribute("alt") == "red and blue"
    assert image_rect(owner)["natural"] == IMAGE_W


def test_blk_01_image_click_reports_image_pixels_also_after_zoom(owner, make) -> None:  # noqa: ANN001
    made = image_page(make)
    wait_image(owner)
    rect = image_rect(owner)
    # Click a quarter in from the left, half way down: pixel (50, 50).
    owner.page.mouse.click(
        *to_window(
            owner,
            rect["left"] + rect["width"] * 0.25,
            rect["top"] + rect["height"] * 0.5,
        )
    )
    [first] = made.wait_action("image-click")
    assert first["target"]["canvas_id"] == "pic"
    assert abs(first["value"]["x"] - 50) <= 1 and abs(first["value"]["y"] - 50) <= 1
    # The draft bar appears with the first action and moves the frame: measure
    # again. Then zoom in with the wheel and click a spot of the picture again.
    owner.page.wait_for_timeout(300)
    rect = image_rect(owner)
    centre = to_window(
        owner, rect["left"] + rect["width"] / 2, rect["top"] + rect["height"] / 2
    )
    owner.page.mouse.move(*centre)
    owner.page.mouse.wheel(0, -400)
    owner.frame.wait_for_function(
        "(w) => document.querySelector('canvas-image').shadowRoot"
        ".querySelector('img').getBoundingClientRect().width > w * 1.2",
        arg=rect["width"],
    )
    scale = image_rect(owner)["width"] / rect["width"]
    # The pixel under the click follows from where the zoomed picture now is
    # (the frame sits at a fractional offset, so the wheel's own position is not
    # exactly the centre that was asked for).
    zoomed = image_rect(owner)
    owner.page.mouse.click(centre[0] + 20, centre[1] + 10)
    second = made.wait_action("image-click", 2)[1]["value"]
    frame_box = owner.frame.frame_element().bounding_box()
    assert scale > 1.2
    wanted_x = (centre[0] + 20 - frame_box["x"] - zoomed["left"]) / scale
    wanted_y = (centre[1] + 10 - frame_box["y"] - zoomed["top"]) / scale
    assert abs(second["x"] - wanted_x) <= 1
    assert abs(second["y"] - wanted_y) <= 1


def test_blk_01_image_drag_pans_and_double_click_resets(owner, make) -> None:  # noqa: ANN001
    made = image_page(make)
    wait_image(owner)
    start = image_rect(owner)
    centre = to_window(owner, start["left"] + 100, start["top"] + 50)
    owner.page.mouse.move(*centre)
    owner.page.mouse.wheel(0, -600)
    owner.frame.wait_for_function(
        "(w) => document.querySelector('canvas-image').shadowRoot"
        ".querySelector('img').getBoundingClientRect().width > w * 1.5",
        arg=start["width"],
    )
    before = image_rect(owner)
    owner.page.mouse.move(*centre)
    owner.page.mouse.down()
    owner.page.mouse.move(centre[0] + 40, centre[1] + 20, steps=5)
    owner.page.mouse.up()
    after = image_rect(owner)
    assert after["left"] - before["left"] > 20 and after["top"] - before["top"] > 5
    assert made.wait_action("image-click", 0) == []  # a drag is not a click
    owner.page.mouse.dblclick(*centre)
    owner.frame.wait_for_function(
        "(w) => Math.abs(document.querySelector('canvas-image').shadowRoot"
        ".querySelector('img').getBoundingClientRect().width - w) < 1",
        arg=start["width"],
    )
    reset = image_rect(owner)
    assert (
        abs(reset["left"] - start["left"]) < 1 and abs(reset["top"] - start["top"]) < 1
    )


def test_blk_01_image_without_src_shows_an_error_box(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-image", "pic", {"alt": "x"}))
    owner.frame.locator(".block-error").wait_for()
    assert "src" in owner.frame.locator(".block-error").inner_text()


def test_blk_01_image_that_cannot_load_shows_an_error_box(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-image", "pic", {"src": "missing.png"}))
    owner.frame.locator(".block-error").wait_for()
    assert "missing.png" in owner.frame.locator(".block-error").inner_text()


# ---- BLK-01 and BLK-05: model ----------------------------------------------------

MODEL_SIZE = 10.0


def model_page(make, name: str, content, **config):  # noqa: ANN001, ANN201
    config = {"src": name, "units": "mm", "colour": "#2a9d8f", **config}
    return make(block("canvas-model", "part", config), files={name: content})


def canvas_png(owner) -> bytes:  # noqa: ANN001
    return owner.frame.locator("canvas-model canvas").screenshot()


def point_is_on_cube(point: list[float], size: float = MODEL_SIZE) -> bool:
    """True when ``point`` is within 1 % of the cube size of the cube surface."""
    tolerance = 0.01 * size
    inside = all(-tolerance <= c <= size + tolerance for c in point)
    on_face = any(min(abs(c), abs(c - size)) <= tolerance for c in point)
    return inside and on_face


@pytest.mark.parametrize(
    ("name", "content"),
    [("cube.stl", cube_stl(MODEL_SIZE)), ("cube.step", cube_step(MODEL_SIZE))],
    ids=["stl", "step"],
)
def test_blk_05_cube_loads_and_renders_a_non_blank_canvas(
    owner, make, name, content
) -> None:  # noqa: ANN001
    model_page(make, name, content)
    wait_model(owner)
    total, painted = paint_stats(canvas_png(owner), MODEL_BACKGROUND)
    assert painted > total * 0.05, (painted, total)
    bounds = owner.frame.evaluate("document.querySelector('canvas-model').bounds")
    assert bounds["max"] == pytest.approx([MODEL_SIZE] * 3, abs=0.01)
    assert bounds["min"] == pytest.approx([0, 0, 0], abs=0.01)


@pytest.mark.parametrize(
    ("name", "content"),
    [("cube.stl", cube_stl(MODEL_SIZE)), ("cube.stp", cube_step(MODEL_SIZE))],
    ids=["stl", "stp"],
)
def test_blk_05_mark_mode_click_gives_a_point_on_the_cube_surface(
    owner, make, name, content
) -> None:  # noqa: ANN001
    made = model_page(make, name, content)
    wait_model(owner)
    toggle = owner.frame.locator("canvas-model button.mark-toggle")
    assert toggle.get_attribute("aria-pressed") == "false"
    canvas = owner.frame.locator("canvas-model canvas")
    box = canvas.bounding_box()
    # A click outside mark mode records nothing.
    owner.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert made.wait_action("model-mark", 0) == []
    toggle.click()
    assert toggle.get_attribute("aria-pressed") == "true"
    owner.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    owner.page.mouse.click(
        box["x"] + box["width"] / 2 + 40, box["y"] + box["height"] / 2 + 10
    )
    marks = made.wait_action("model-mark", 2)
    for number, mark in enumerate(marks, start=1):
        value = mark["value"]
        assert point_is_on_cube(value["point"]), value
        assert value["label"] == number
        normal = value["normal"]
        assert sorted(abs(c) for c in normal) == pytest.approx([0, 0, 1], abs=0.01)
        assert mark["target"]["canvas_id"] == "part" and mark["at"] is not None


def test_blk_01_model_orbit_and_zoom_move_the_camera(owner, make) -> None:  # noqa: ANN001
    model_page(make, "cube.stl", cube_stl(MODEL_SIZE))
    wait_model(owner)
    read = "[...document.querySelector('canvas-model').camera.matrix.elements]"
    before = owner.frame.evaluate(read)
    box = owner.frame.locator("canvas-model canvas").bounding_box()
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    owner.page.mouse.move(*centre)
    owner.page.mouse.down()
    owner.page.mouse.move(centre[0] + 60, centre[1] + 20, steps=6)
    owner.page.mouse.up()
    orbited = owner.frame.evaluate(read)
    assert orbited != before
    owner.page.mouse.wheel(0, -300)
    until(owner.page, lambda: owner.frame.evaluate(read) != orbited)


def test_blk_03_model_camera_is_unchanged_by_an_unrelated_update(owner, make) -> None:  # noqa: ANN001
    config = {"src": "cube.stl", "colour": "#2a9d8f"}
    page = "<p id=note>one</p>" + block("canvas-model", "part", config)
    made = make(page, files={"cube.stl": cube_stl(MODEL_SIZE)})
    wait_model(owner)
    box = owner.frame.locator("canvas-model canvas").bounding_box()
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    owner.page.mouse.move(*centre)
    owner.page.mouse.down()
    owner.page.mouse.move(centre[0] - 50, centre[1] + 30, steps=6)
    owner.page.mouse.up()
    read = "[...document.querySelector('canvas-model').camera.matrixWorld.elements]"
    rotated = owner.frame.evaluate(read)
    node = owner.frame.evaluate_handle(
        "document.querySelector('canvas-model').shadowRoot.firstChild"
    )
    made.rewrite(page.replace("one", "two"))
    owner.frame.wait_for_function("document.querySelector('#note').textContent==='two'")
    assert owner.frame.evaluate(read) == rotated
    assert owner.frame.evaluate(
        "(n) => document.querySelector('canvas-model').shadowRoot.firstChild === n",
        node,
    )


def test_blk_05_model_errors(owner, make) -> None:  # noqa: ANN001
    make(
        block("canvas-model", "a", {"src": "part.obj"})
        + block("canvas-model", "b", {"src": "broken.step"})
        + block("canvas-model", "c", {"colour": "red"}),
        files={"part.obj": "o x", "broken.step": "not a step file"},
    )
    boxes = owner.frame.locator(".block-error")
    boxes.nth(2).wait_for(timeout=30000)
    texts = " | ".join(boxes.all_inner_texts())
    assert ".obj" in texts or "STL" in texts
    assert "broken.step" in texts and "src" in texts


# ---- BLK-06 and DRAW-06: send screenshots -----------------------------------------

SHOT_PAGE = (
    "<style>body{margin:8px;background:#fff}</style>"
    + block("canvas-plot", "spectrum", plot_config())
    + block(
        "canvas-model",
        "part",
        {"src": "cube.step", "colour": "#2a9d8f", "height": 240},
    )
    + block("canvas-image", "pic", {"src": "pic.png"})
)  # fmt: skip


def rect_of(frame, selector: str) -> dict:  # noqa: ANN001
    return frame.evaluate(
        "(s) => { const e = document.querySelector(s); const r = (e.shadowRoot "
        "&& e.shadowRoot.querySelector('.plot, canvas, img') || e)"
        ".getBoundingClientRect();"
        " return {x: r.left, y: r.top, w: r.width, h: r.height}; }",
        selector,
    )


def count_colour(rows, rect: dict, colour, tolerance: int = 40) -> int:  # noqa: ANN001
    x0, y0 = int(rect["x"]), int(rect["y"])
    return sum(
        near(rows[y][x], colour, tolerance)
        for y in range(y0, min(len(rows), y0 + int(rect["h"])))
        for x in range(x0, min(len(rows[0]), x0 + int(rect["w"])))
    )


def send_with_message(studio, sid):  # noqa: ANN001, ANN201
    """Send a message about the peak at x = 5."""
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    return event


def test_blk_06_plot_model_and_image_appear_in_the_send_screenshot(studio) -> None:  # noqa: ANN001
    studio.page.set_viewport_size({"width": 1280, "height": 1000})  # all in view
    sid = studio.make(
        SHOT_PAGE,
        files={
            "cube.step": cube_step(MODEL_SIZE),
            "pic.png": image_file(),
        },
    )
    wait_plot(studio.owner)
    wait_model(studio.owner)
    wait_image(studio.owner)
    studio.frame.evaluate("window.scrollTo(0, 0)")
    event = send_with_message(studio, sid)
    assert event["screenshot_error"] is None, event
    record = studio.send_record(event)
    assert record["screenshot_warnings"] == []
    _, _, rows = decode_png(studio.screenshot(event))
    plot = rect_of(studio.frame, "canvas-plot")
    model = rect_of(studio.frame, "canvas-model")
    pic = rect_of(studio.frame, "canvas-image")
    assert count_colour(rows, plot, GREEN) > 300  # the 5 px green line
    peak_x, peak_y = data_to_page(studio.frame, "spectrum", 5, 90)
    assert near(rows[round(peak_y)][round(peak_x)], GREEN)  # the peak, in place
    cells = model["w"] * model["h"]
    painted = sum(
        not near(rows[y][x], MODEL_BACKGROUND, 15)
        for y in range(int(model["y"]), int(model["y"] + model["h"]))
        for x in range(int(model["x"]), int(model["x"] + model["w"]))
    )
    assert painted > cells * 0.05
    assert count_colour(rows, model, (42, 157, 143), 70) > 200  # the part itself
    assert count_colour(rows, pic, (200, 30, 30), 20) > 5000  # red half of the image
    assert count_colour(rows, pic, (30, 30, 200), 20) > 5000
    destination = os.environ.get("AC_M10_SCREENSHOT")
    if destination:
        shutil.copy(event["screenshot"], destination)


RAW_GL = """<canvas id="raw-gl" width="120" height="80"></canvas>
<script>
const gl = document.getElementById('raw-gl').getContext('webgl');
gl.clearColor(1, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
</script>"""


def test_draw_06_raw_webgl_canvas_gives_one_warning_and_the_send_succeeds(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(RAW_GL + "<p>after</p>")
    studio.frame.wait_for_function("document.readyState === 'complete'")
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    assert event["screenshot_error"] is None and event["screenshot"]
    record = studio.send_record(event)
    assert record["screenshot_warnings"] == [
        {"canvas_id": None, "selector": "#raw-gl", "reason": "webgl-not-captured"}
    ]
    assert record["screenshot"] == "0001.png"


def test_draw_06_webgl_canvas_with_preserved_buffer_is_merged_without_a_warning(
    studio,
) -> None:  # noqa: ANN001
    page = RAW_GL.replace(
        "getContext('webgl')", "getContext('webgl', {preserveDrawingBuffer: true})"
    )
    sid = studio.make(page)
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    record = studio.send_record(event)
    assert record["screenshot_warnings"] == []
    _, _, rows = decode_png(studio.screenshot(event))
    assert near(rows[40][60], (255, 0, 0), 25)  # canvas at (8, 8), 120 x 80


# ---- BLK-07: lazy libraries ---------------------------------------------------------


def requested(owner) -> list[str]:  # noqa: ANN001
    urls: list[str] = []
    owner.page.on("request", lambda r: urls.append(r.url))
    return urls


def test_blk_07_a_page_without_a_plot_makes_no_plotly_request(owner, make) -> None:  # noqa: ANN001
    urls = requested(owner)
    make(
        block("canvas-progress", "p", {"value": 1})
        + block("canvas-image", "pic", {"src": "pic.png"}),
        files={"pic.png": image_file()},
    )
    wait_image(owner)
    assert not [u for u in urls if "plotly" in u or "three" in u or "occt" in u]


def test_blk_07_an_stl_model_loads_three_but_not_occt_or_plotly(owner, make) -> None:  # noqa: ANN001
    urls = requested(owner)
    model_page(make, "cube.stl", cube_stl())
    wait_model(owner)
    assert [u for u in urls if "three.module" in u] and [
        u for u in urls if "STLLoader" in u
    ]
    assert not [u for u in urls if "occt" in u or "plotly" in u]


def test_blk_07_a_step_model_loads_occt_and_a_plot_loads_plotly(owner, make) -> None:  # noqa: ANN001
    urls = requested(owner)
    make(
        block("canvas-model", "part", {"src": "cube.step"})
        + block("canvas-plot", "spectrum", plot_config()),
        files={"cube.step": cube_step()},
    )
    wait_model(owner)
    wait_plot(owner)
    assert [u for u in urls if u.endswith("occt-import-js.wasm")]
    assert [u for u in urls if "plotly" in u]


# ---- BLK-09: src refresh ------


def wait_within(owner, script: str, arg, seconds: float = 1.0) -> float:  # noqa: ANN001
    """Wait for ``script`` to be truthy; return how long it took, up to ``seconds``."""
    started = time.monotonic()
    owner.frame.wait_for_function(script, arg=arg, timeout=seconds * 1000, polling=20)
    return time.monotonic() - started


@pytest.mark.timing
def test_blk_09_rewriting_plot_json_updates_the_plot_within_a_second(
    owner, make
) -> None:  # noqa: ANN001
    first = plot_config()
    spec = {k: first[k] for k in ("data", "layout", "config")}
    made = make(
        block("canvas-plot", "spectrum", {"src": "plot.json"}),
        files={"plot.json": json.dumps(spec)},
    )
    wait_plot(owner)
    owner.frame.evaluate("window.__probe = 'alive'")
    spec["data"][0]["y"] = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 99]
    (made.folder / "plot.json").write_text(json.dumps(spec))
    elapsed = wait_within(
        owner,
        "() => document.querySelector('canvas-plot').shadowRoot"
        ".querySelector('.plot').data[0].y[10] === 99",
        None,
    )
    assert elapsed < 1.0
    assert owner.frame.evaluate("window.__probe") == "alive"


def test_blk_09_rewriting_the_image_reloads_it_and_keeps_the_zoom(owner, make) -> None:  # noqa: ANN001
    made = image_page(make)
    wait_image(owner)
    owner.frame.evaluate("window.__probe = 'alive'")
    rect = image_rect(owner)
    owner.page.mouse.move(*to_window(owner, rect["left"] + 100, rect["top"] + 50))
    owner.page.mouse.wheel(0, -400)
    until(owner.page, lambda: image_rect(owner)["width"] > rect["width"] * 1.1)
    zoomed = image_rect(owner)["width"]
    (made.folder / "pic.png").write_bytes(image_file(300, 150))
    wait_within(
        owner,
        "() => document.querySelector('canvas-image').shadowRoot"
        ".querySelector('img').naturalWidth === 300",
        None,
    )
    assert owner.frame.evaluate("window.__probe") == "alive"
    assert image_rect(owner)["width"] > rect["width"] * 1.1 and zoomed > rect["width"]


def test_blk_09_rewriting_the_model_file_reloads_it_and_keeps_the_camera(
    owner, make
) -> None:  # noqa: ANN001
    made = model_page(make, "cube.stl", cube_stl(10))
    wait_model(owner)
    box = owner.frame.locator("canvas-model canvas").bounding_box()
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    owner.page.mouse.move(*centre)
    owner.page.mouse.down()
    owner.page.mouse.move(centre[0] + 50, centre[1] + 10, steps=5)
    owner.page.mouse.up()
    read = "[...document.querySelector('canvas-model').camera.quaternion.toArray()]"
    rotated = owner.frame.evaluate(read)
    owner.frame.evaluate("window.__probe = 'alive'")
    (made.folder / "cube.stl").write_text(cube_stl(20))
    wait_within(
        owner,
        "() => document.querySelector('canvas-model').bounds.max[0] > 19",
        None,
        seconds=3,
    )
    assert owner.frame.evaluate("window.__probe") == "alive"
    assert owner.frame.evaluate(read) == pytest.approx(rotated, abs=1e-6)


# ---- NFR-02 final case and the BLK-01 sweep ------

ALL_BLOCKS = (
    block(
        "canvas-choices",
        "c",
        {"mode": "single", "options": [{"id": "a", "title": "A"}]},
    )
    + block("canvas-buttons", "b", {"buttons": [{"id": "go", "label": "Go"}]})
    + block("canvas-textbox", "t", {"label": "Name"})
    + block(
        "canvas-table",
        "tab",
        {"columns": ["a"], "rows": [[1], [2]], "select": "single"},
    )
    + block("canvas-progress", "pr", {"value": 0.5})
    + block("canvas-markdown", "md", {"text": "Euler $e^{i\\pi}=-1$"})
    + block("canvas-plot", "spectrum", plot_config())
    + block("canvas-image", "pic", {"src": "pic.png"})
    + block("canvas-model", "part", {"src": "cube.step", "height": 200})
)  # fmt: skip


def test_nfr_02_a_page_with_every_block_works_with_no_foreign_request(
    owner, make
) -> None:  # noqa: ANN001
    # The `owner` route guard aborts any request leaving the hub and fails the
    # test at teardown; this test also sweeps the nine blocks (BLK-01).
    made = make(
        ALL_BLOCKS,
        files={"cube.step": cube_step(), "pic.png": image_file()},
    )
    wait_plot(owner)
    wait_model(owner)
    wait_image(owner)
    owner.frame.locator("canvas-markdown .katex").wait_for()
    assert owner.frame.locator(".block-error").count() == 0
    assert made.shown["errors"] == []
    owner.frame.locator("canvas-choices .option").click()
    owner.frame.locator("canvas-buttons button").click()
    [event] = made.wait_events(1)
    assert event["kind"] == "button" and event["target"]["canvas_id"] == "b"
    assert owner.foreign_requests == []
