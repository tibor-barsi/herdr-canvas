"""``canvas-scene``, the multi-part 3D viewer (SCN-01 to SCN-08).

Every test drives the real block in the owner's headless window. Part files are
generated here (binary STL boxes and tori, a GLB cube, a two-solid STEP file).
"""

# ruff: noqa: E501  (long JavaScript snippets and section rules)

from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path

import pytest

from agent_canvas.hub.headless import HeadlessRenderer
from helpers import decode_png, own_draft

from .conftest import _launch_env
from .scene_fixtures import box_stl, glb_cube, torus_stl, two_solid_step
from .solids import cube_step
from .support import block, call

pytestmark = pytest.mark.browser

SCENE = "document.querySelector('canvas-scene[data-canvas-id=scene]')"
LIGHT_BACKGROUND = (243, 245, 248)
DARK_BACKGROUND = (38, 44, 53)
TEAL = "#2a9d8f"
TEAL_CAP = (106, 186, 177)  # TEAL lightened 30 % towards white: the cut faces

FILES = {
    "a.stl": box_stl((0, 0, 0)),
    "b.stl": box_stl((20, 0, 0)),
    "c.stl": box_stl((0, 20, 0)),
    "d.stl": box_stl((20, 20, 0)),
}


def scene_page(parts: list[dict], canvas_id: str = "scene", **config) -> str:  # noqa: ANN003
    """The markup of one scene block."""
    return block("canvas-scene", canvas_id, {"parts": parts, **config})


def parts_of(*names: str, **each) -> list[dict]:  # noqa: ANN003
    """Part entries for the files ``names`` (``a.stl`` ...)."""
    return [{"src": name, **each} for name in names]


def wait_scene(owner, timeout: int = 60000, canvas_id: str = "scene") -> None:  # noqa: ANN001
    """Wait until every part that has to load is loaded or has failed."""
    owner.frame.wait_for_function(
        "(id) => { const e = document.querySelector(`canvas-scene[data-canvas-id=${id}]`);"
        " return !!(e && e.shadowRoot.querySelector('.viewer.ready')); }",
        arg=canvas_id,
        timeout=timeout,
    )


def run(owner, expression: str, arg=None):  # noqa: ANN001, ANN201
    """Evaluate ``(el, arg) => expression`` with ``el`` the scene block."""
    return owner.frame.evaluate(f"(arg) => {{ const el = {SCENE}; {expression} }}", arg)


def info(owner) -> dict:  # noqa: ANN001
    """The parts of the scene by name."""
    return {p["name"]: p for p in run(owner, "return el.partInfo();")}


def shadow(owner, selector: str):  # noqa: ANN001, ANN201
    """A locator inside the scene's shadow root."""
    return owner.frame.locator(f"canvas-scene {selector}")


def button(owner, label: str):  # noqa: ANN001, ANN201
    """The toolbar button with the visible text ``label``."""
    return shadow(owner, "button").filter(has_text=label).first


def set_value(locator, value: str) -> None:  # noqa: ANN001
    """Set an input's value and send the ``input`` event, as a drag would."""
    locator.evaluate(
        "(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }",
        value,
    )


def canvas_rows(owner):  # noqa: ANN001, ANN201
    """The WebGL canvas as pixel rows."""
    _, _, rows = decode_png(owner.frame.locator("canvas-scene canvas").screenshot())
    return rows


def painted(rows, background=LIGHT_BACKGROUND) -> int:  # noqa: ANN001
    """Number of pixels clearly different from ``background``."""
    return sum(
        sum(abs(a - b) for a, b in zip(p[:3], background, strict=True)) > 40
        for row in rows
        for p in row
    )


def near(pixel, colour, tolerance: int = 30) -> bool:  # noqa: ANN001
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


def direction(owner) -> list[float]:  # noqa: ANN001
    """The unit vector from the orbit target to the camera."""
    return run(
        owner,
        "const v = el.camera.position.clone().sub(el.controls.target).normalize();"
        " return v.toArray();",
    )


# ---- SCN-01: config -----------------------------------------------------------------


def test_scn_01_parts_in_the_config_become_rows_and_one_picture(owner, make) -> None:  # noqa: ANN001
    parts = [
        {"src": "a.stl", "group": "frame"},
        {
            "src": "b.stl",
            "group": "frame",
            "colour": "#ff0000",
            "opacity": 0.5,
            "name": "bee",
        },
        {"src": "c.stl"},
    ]
    make(scene_page(parts, units="mm"), files=FILES)
    wait_scene(owner)
    found = info(owner)
    assert list(found) == ["a", "bee", "c"]
    assert [found[n]["group"] for n in found] == ["frame", "frame", None]
    assert {p["status"] for p in found.values()} == {"ready"}
    assert found["bee"]["colour"] == "#ff0000" and found["bee"]["opacity"] == 0.5
    assert found["a"]["colour"] != found["c"]["colour"]  # palette, not all one grey
    assert shadow(owner, ".part-row").count() == 3
    assert shadow(owner, ".group-row").count() == 1
    assert run(owner, "return el.bounds;") == {"min": [0, 0, 0], "max": [30, 30, 10]}
    assert "30 × 30 × 10 mm" in shadow(owner, ".size-note").inner_text()
    rows = canvas_rows(owner)
    assert painted(rows) > len(rows) * len(rows[0]) * 0.03


def test_scn_01_a_manifest_file_gives_the_same_scene(owner, make) -> None:  # noqa: ANN001
    manifest = {"units": "mm", "parts": parts_of("a.stl", "b.stl")}
    page = block("canvas-scene", "scene", {"src": "scene.json"})
    made = make(page, files={**FILES, "scene.json": json.dumps(manifest)})
    wait_scene(owner)
    assert list(info(owner)) == ["a", "b"]
    assert "mm" in shadow(owner, ".size-note").inner_text()
    owner.frame.evaluate("window.__probe = 1")
    manifest["parts"].append({"src": "c.stl"})
    (made.folder / "scene.json").write_text(json.dumps(manifest))
    owner.frame.wait_for_function(f"{SCENE}.partInfo().length === 3", timeout=15000)
    wait_scene(owner)
    assert owner.frame.evaluate("window.__probe") == 1  # no frame reload


def test_scn_01_scene_fields_in_the_tag_win_over_the_manifest(owner, make) -> None:  # noqa: ANN001
    manifest = {"height": 300, "units": "inch", "parts": parts_of("a.stl")}
    page = block("canvas-scene", "scene", {"src": "scene.json", "height": 360})
    make(page, files={**FILES, "scene.json": json.dumps(manifest)})
    wait_scene(owner)
    assert owner.frame.locator("canvas-scene .viewer").bounding_box()["height"] == 360
    assert "inch" in shadow(owner, ".size-note").inner_text()


BAD_CONFIGS = {
    "no-source": ({"units": "mm"}, 'needs "parts" or "src"'),
    "extension": ({"parts": [{"src": "x.obj"}]}, "x.obj"),
    "colour": ({"parts": [{"src": "a.stl", "colour": "red"}]}, "hex colour"),
    "opacity": ({"parts": [{"src": "a.stl", "opacity": 2}]}, "between 0 and 1"),
    "split": (
        {"parts": [{"src": "a.stl", "split": True}]},
        "split only works for STEP",
    ),
    "up": ({"parts": [{"src": "a.stl"}], "up": "w"}, "one of z, y"),
    "empty": ({"parts": []}, "at least one part"),
    "manifest-missing": ({"src": "nothing.json"}, "nothing.json"),
    "manifest-bad": ({"src": "bad.json"}, "bad.json"),
}


def test_scn_01_a_bad_config_shows_an_error_box_naming_the_problem(owner, make) -> None:  # noqa: ANN001
    html = "".join(
        block("canvas-scene", name, cfg) for name, (cfg, _) in BAD_CONFIGS.items()
    )
    make(html, files={**FILES, "bad.json": '{"parts": [{"src": "z.txt"}]}'})
    owner.frame.wait_for_function(
        "document.querySelectorAll('canvas-scene').length === %d && [...document"
        ".querySelectorAll('canvas-scene')].every((e) => e.shadowRoot.querySelector"
        "('.block-error'))" % len(BAD_CONFIGS),
        timeout=30000,
    )
    texts = owner.frame.evaluate(
        "[...document.querySelectorAll('canvas-scene')].map((e) => "
        "e.shadowRoot.querySelector('.block-error').textContent)"
    )
    for text, (_, expected) in zip(texts, BAD_CONFIGS.values(), strict=True):
        assert expected in text, (expected, text)


# ---- SCN-02: part list ---------------------------------------------------------------


def test_scn_02_group_and_part_controls_change_the_parts(owner, make) -> None:  # noqa: ANN001
    parts = [
        {"src": "a.stl", "group": "A"}, {"src": "b.stl", "group": "A"},
        {"src": "c.stl", "group": "B"}, {"src": "d.stl", "group": "B"},
    ]  # fmt: skip
    made = make(scene_page(parts), files=FILES)
    wait_scene(owner)
    group_checks = shadow(owner, ".group-row input[type=checkbox]")
    part_checks = shadow(owner, ".part-row input[type=checkbox]")
    assert group_checks.count() == 2 and part_checks.count() == 4
    group_checks.nth(0).uncheck()
    shown = {n: p["visible"] for n, p in info(owner).items()}
    assert shown == {"a": False, "b": False, "c": True, "d": True}
    assert run(owner, "return el.parts[0].object.visible;") is False
    part_checks.nth(0).check()
    assert group_checks.nth(0).evaluate("(e) => e.indeterminate") is True
    assert group_checks.nth(0).evaluate("(e) => e.checked") is False
    group_checks.nth(0).check()  # mixed -> all shown
    assert all(p["visible"] for p in info(owner).values())
    # Group opacity moves every member; part opacity only its own.
    set_value(shadow(owner, ".group-row input[type=range]").nth(1), "0.4")
    assert [p["opacity"] for p in info(owner).values()] == [1, 1, 0.4, 0.4]
    set_value(shadow(owner, ".part-row input[type=range]").nth(2), "0.7")
    assert info(owner)["c"]["opacity"] == 0.7 and info(owner)["d"]["opacity"] == 0.4
    assert run(owner, "return el.parts[2].materials[0].opacity;") == pytest.approx(0.7)
    assert run(owner, "return el.parts[2].materials[0].transparent;") is True
    assert run(owner, "return el.parts[0].materials[0].transparent;") is False
    # A colour from the swatch's colour input.
    set_value(shadow(owner, ".part-row input[type=color]").nth(1), "#00ff00")
    assert info(owner)["b"]["colour"] == "#00ff00"
    assert (
        run(owner, "return el.parts[1].materials[0].color.getHexString();") == "00ff00"
    )
    # Visibility, opacity and colour are not events.
    actions = owner.page.evaluate(
        f"(window.__drafts['{made.sid}'] || {{actions: []}}).actions"
    )
    # (plain clicks are recorded like any click; no scene-mark, input or select)
    assert {a["kind"] for a in actions} <= {"click"} and made.events == []


def test_scn_02_collapsing_a_group_hides_its_rows_only(owner, make) -> None:  # noqa: ANN001
    parts = [{"src": "a.stl", "group": "A"}, {"src": "b.stl", "group": "B"}]
    make(scene_page(parts), files=FILES)
    wait_scene(owner)
    shadow(owner, ".group-row button.chevron").nth(0).click()
    assert shadow(owner, ".part-row").count() == 1
    assert info(owner)["a"]["visible"] is True  # collapsing does not hide the part


def test_scn_02_glb_keeps_its_own_colour_and_step_split_gives_one_row_per_solid(
    owner, make
) -> None:  # noqa: ANN001
    parts = [
        {"src": "cube.glb"},
        {"src": "two.step", "split": True, "group": "assembly"},
        {"src": "cube.step", "name": "whole"},
    ]
    files = {
        "cube.glb": glb_cube(),
        "two.step": two_solid_step(),
        "cube.step": cube_step(10.0),
    }
    make(scene_page(parts, up="y"), files=files)
    wait_scene(owner)
    found = info(owner)
    assert list(found) == ["cube", "left", "right", "whole"]
    assert (
        found["left"]["group"] == "assembly" and found["right"]["group"] == "assembly"
    )
    red = int(found["cube"]["colour"][1:3], 16)
    assert red > 200 and found["cube"]["colour"] != "#e6" + "e6e6"  # the GLB's own red
    assert {p["status"] for p in found.values()} == {"ready"}


def test_scn_02_a_split_step_without_group_is_grouped_by_its_file_name(
    owner, make
) -> None:  # noqa: ANN001
    make(
        scene_page([{"src": "two.step", "split": True}]),
        files={"two.step": two_solid_step()},
    )
    wait_scene(owner)
    assert {p["group"] for p in info(owner).values()} == {"two"}
    assert shadow(owner, ".group-row .part-name").inner_text().startswith("two")


# ---- SCN-03: views --------------------------------------------------------------------

Z_UP = {
    "iso": (1, -1, 0.8), "top": (0, 0, 1), "front": (0, -1, 0), "side": (1, 0, 0),
}  # fmt: skip
Y_UP = {
    "iso": (1, 0.8, 1), "top": (0, 1, 0), "front": (0, 0, 1), "side": (1, 0, 0),
}  # fmt: skip


def unit(vector) -> list[float]:  # noqa: ANN001
    length = math.sqrt(sum(c * c for c in vector))
    return [c / length for c in vector]


@pytest.mark.parametrize(("up", "views"), [("z", Z_UP), ("y", Y_UP)])
def test_scn_03_view_buttons_look_along_the_named_axes(owner, make, up, views) -> None:  # noqa: ANN001
    make(scene_page(parts_of("a.stl", "b.stl"), up=up), files=FILES)
    wait_scene(owner)
    assert direction(owner) == pytest.approx(unit(views["iso"]), abs=0.02)  # the start
    for name in ("top", "front", "side", "iso"):
        shadow(owner, f"button[aria-label='{name} view']").click()
        assert direction(owner) == pytest.approx(unit(views[name]), abs=0.02), name
    # The vertical axis of the data stays vertical on the screen in a side view.
    shadow(owner, "button[aria-label='front view']").click()
    axis = 2 if up == "z" else 1
    screen_up = run(
        owner,
        "return new el.THREE.Vector3(0, 1, 0).applyQuaternion(el.camera.quaternion).toArray();",
    )
    assert screen_up[axis] == pytest.approx(1, abs=0.02)


def test_scn_03_reset_returns_to_the_initial_camera_and_fit_frames_the_visible_parts(
    owner, make
) -> None:  # noqa: ANN001
    make(scene_page(parts_of("a.stl", "b.stl")), files=FILES)
    wait_scene(owner)
    start = run(owner, "return el.camera.position.toArray();")
    shadow(owner, "button[aria-label='top view']").click()
    button(owner, "reset").click()
    assert run(owner, "return el.camera.position.toArray();") == pytest.approx(
        start, abs=1e-3
    )
    shadow(owner, ".part-row input[type=checkbox]").nth(1).uncheck()  # b away
    button(owner, "fit").click()
    target = run(owner, "return el.controls.target.toArray();")
    assert target == pytest.approx([5, 5, 5], abs=0.01)  # centre of a alone
    button(owner, "reset").click()
    # The initial camera is defined by the parts the config shows: both of them.
    assert run(owner, "return el.controls.target.toArray();") == pytest.approx(
        [15, 5, 5], abs=0.01
    )


# ---- SCN-04: section plane --------------------------------------------------------------


def test_scn_04_section_plane_cuts_the_visible_box_and_shows_the_cut_faces(
    owner, make
) -> None:  # noqa: ANN001
    parts = [{"src": "a.stl", "colour": TEAL}]
    files = {"a.stl": box_stl((0, 0, 0), (20, 20, 20))}
    make(scene_page(parts), files=files)
    wait_scene(owner)
    shadow(owner, "button[aria-label='side view']").click()
    assert run(owner, "return el.renderer.clippingPlanes.length;") == 0
    assert shadow(owner, "input[aria-label='Section position']").is_disabled()
    shadow(owner, "button[aria-label='Section plane X']").click()
    assert run(owner, "return el.renderer.clippingPlanes.length;") == 1
    assert run(owner, "return el.state.section.value;") == pytest.approx(10, abs=0.01)
    # Looking from +X into the half that is kept (x <= 10): the far wall's inside
    # shows in the flat cap colour.
    rows = canvas_rows(owner)
    middle = rows[len(rows) // 2][len(rows[0]) // 2]
    assert near(middle, TEAL_CAP), middle
    # Seen from the front, the slider moves the cut across the box: all of it at
    # one end, a thin slice at the other; flip keeps the other side.
    shadow(owner, "button[aria-label='front view']").click()
    slider = shadow(owner, "input[aria-label='Section position']")
    set_value(slider, "1000")
    assert run(owner, "return el.state.section.value;") == pytest.approx(20, abs=0.01)
    whole = painted(canvas_rows(owner))
    set_value(slider, "500")
    assert painted(canvas_rows(owner)) == pytest.approx(whole / 2, rel=0.1)
    set_value(slider, "0")
    assert painted(canvas_rows(owner)) < whole * 0.3
    button(owner, "flip").click()
    assert painted(canvas_rows(owner)) == pytest.approx(whole, rel=0.05)
    assert run(owner, "return el.plane.normal.toArray();") == [1, 0, 0]
    shadow(owner, "button[aria-label='Section off']").click()
    assert run(owner, "return el.renderer.clippingPlanes.length;") == 0


def test_scn_04_section_range_follows_the_visible_parts(owner, make) -> None:  # noqa: ANN001
    make(scene_page(parts_of("a.stl", "b.stl")), files=FILES)
    wait_scene(owner)
    shadow(owner, "button[aria-label='Section plane X']").click()
    assert run(owner, "return el.state.section.value;") == pytest.approx(15, abs=0.01)
    shadow(owner, ".part-row input[type=checkbox]").nth(1).uncheck()
    set_value(shadow(owner, "input[aria-label='Section position']"), "1000")
    assert run(owner, "return el.state.section.value;") == pytest.approx(10, abs=0.01)


# ---- SCN-05: loading ---------------------------------------------------------------------


def test_scn_05_hidden_parts_are_not_fetched_until_shown(owner, make) -> None:  # noqa: ANN001
    requests: list[str] = []
    owner.page.on("request", lambda r: requests.append(r.url))
    parts = [{"src": "a.stl"}, {"src": "b.stl", "visible": False}]
    make(scene_page(parts), files=FILES)
    wait_scene(owner)
    assert any(u.endswith("/a.stl") for u in requests)
    assert not any(u.endswith("/b.stl") for u in requests)
    assert info(owner)["b"]["status"] == "pending"
    assert "not loaded" in shadow(owner, ".part-row").nth(1).inner_text()
    shadow(owner, ".part-row input[type=checkbox]").nth(1).check()
    owner.frame.wait_for_function(f"{SCENE}.partInfo()[1].status === 'ready'")
    assert any(u.endswith("/b.stl") for u in requests)


def test_scn_05_a_part_that_fails_shows_in_its_row_and_in_the_errors(
    owner, make
) -> None:  # noqa: ANN001
    parts = [
        {"src": "a.stl"},
        {"src": "gone.stl"},
        {"src": "broken.stl"},
        {"src": "b.stl"},
    ]
    made = make(scene_page(parts), files={**FILES, "broken.stl": b"not an stl at all"})
    wait_scene(owner)
    found = info(owner)
    assert found["a"]["status"] == "ready" and found["b"]["status"] == "ready"
    assert found["gone"]["status"] == "error" and "gone.stl" in found["gone"]["error"]
    assert found["broken"]["status"] == "error"
    assert "gone.stl" in shadow(owner, ".part-row").nth(1).inner_text()
    assert painted(canvas_rows(owner)) > 500  # the rest of the scene still works
    result = call(
        owner,
        "POST",
        f"/api/sessions/{made.sid}/look",
        json={"width": 900, "height": 700},
    )
    messages = json.dumps(result["errors"])
    assert 'part \\"gone\\"' in messages and 'part \\"broken\\"' in messages, result[
        "errors"
    ]


@pytest.mark.hub_config(show_audit=True)
def test_scn_05_show_names_a_failed_part_in_its_page_checks(owner, make) -> None:  # noqa: ANN001
    made = make(scene_page([{"src": "a.stl"}, {"src": "gone.stl"}]), files=FILES)
    audit = made.shown["audit"]
    assert isinstance(audit, dict), audit
    found = [f for f in audit["findings"] if f["rule"] == "errors"]
    assert any('part "gone"' in f["message"] for f in found), audit


def test_scn_05_five_large_binary_stls_load_in_parallel_and_become_interactive(
    owner, make
) -> None:  # noqa: ANN001
    files = {f"p{i}.stl": torus_stl((90.0 * i, 0.0, 0.0)) for i in range(5)}
    assert all(len(data) > 4_400_000 for data in files.values())
    begin = time.monotonic()
    make(scene_page(parts_of(*files)), files=files)
    owner.frame.wait_for_function(
        f"!!{SCENE} && !!{SCENE}.shadowRoot.querySelector('.viewer.interactive')"
    )
    wait_scene(owner, timeout=90000)
    elapsed = time.monotonic() - begin
    assert {p["status"] for p in info(owner).values()} == {"ready"}
    assert elapsed < 45, f"scene took {elapsed:.1f} s"
    # The page's own timeline: Playwright's request events come late or not at all under load.
    spans = owner.frame.evaluate(
        """performance.getEntriesByType('resource')
          .filter((e) => e.name.endsWith('.stl'))
          .map((e) => [e.startTime, e.responseEnd])"""
    )
    assert len(spans) == 5 and max(s for s, _ in spans) < min(e for _, e in spans), (
        "files were not fetched in parallel"
    )
    # Interactive: a view button and an orbit drag both move the camera.
    shadow(owner, "button[aria-label='top view']").click()
    before = run(owner, "return el.camera.position.toArray();")
    orbit(owner, 50, 20)
    assert run(owner, "return el.camera.position.toArray();") != before
    assert painted(canvas_rows(owner)) > 2000


def test_scn_05_removed_parts_and_removed_blocks_free_their_gpu_resources(
    owner, make
) -> None:  # noqa: ANN001
    page = "<p>x</p>" + scene_page(parts_of("a.stl", "b.stl", "c.stl"))
    made = make(page, files=FILES)
    wait_scene(owner)
    assert run(owner, "return el.renderer.info.memory.geometries;") == 3
    handle = owner.frame.evaluate_handle(SCENE)
    made.rewrite("<p>x</p>" + scene_page(parts_of("a.stl", "b.stl")))
    owner.frame.wait_for_function(f"{SCENE}.partInfo().length === 2")
    assert run(owner, "return el.renderer.info.memory.geometries;") == 2
    made.rewrite("<p>no scene now</p>")
    owner.frame.wait_for_function("!document.querySelector('canvas-scene')")
    assert handle.evaluate("(e) => e.renderer === null && e.parts.length === 0") is True


# ---- SCN-06: state --------------------------------------------------------------------------


def orbit(owner, dx: int, dy: int) -> None:  # noqa: ANN001
    box = owner.frame.locator("canvas-scene canvas").bounding_box()
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    owner.page.mouse.move(*centre)
    owner.page.mouse.down()
    owner.page.mouse.move(centre[0] + dx, centre[1] + dy, steps=5)
    owner.page.mouse.up()


def snapshot_of(owner) -> dict:  # noqa: ANN001
    return run(
        owner,
        "return {parts: el.partInfo().map((p) => [p.name, p.visible, p.opacity, p.colour]),"
        " section: el.state.section, camera: el.camera.matrixWorld.elements.slice(),"
        " planes: el.renderer.clippingPlanes.length};",
    )


def change_everything(owner) -> dict:  # noqa: ANN001
    """Hide a part, change opacity and colour, cut, orbit; return what to compare."""
    shadow(owner, ".part-row input[type=checkbox]").nth(1).uncheck()
    set_value(shadow(owner, ".part-row input[type=range]").nth(0), "0.6")
    set_value(shadow(owner, ".part-row input[type=color]").nth(0), "#123456")
    shadow(owner, "button[aria-label='Section plane Y']").click()
    set_value(shadow(owner, "input[aria-label='Section position']"), "700")
    button(owner, "flip").click()
    orbit(owner, -40, 25)
    return snapshot_of(owner)


def test_scn_06_state_survives_an_unrelated_rewrite_and_a_config_change(
    owner, make
) -> None:  # noqa: ANN001
    requests: list[str] = []
    owner.page.on("request", lambda r: requests.append(r.url))

    def page(note: str, names: tuple[str, ...]) -> str:
        return f"<p id=note>{note}</p>" + scene_page(parts_of(*names), units="mm")

    made = make(page("one", ("a.stl", "b.stl")), files=FILES)
    wait_scene(owner)
    before = change_everything(owner)
    assert before["planes"] == 1
    node = owner.frame.evaluate_handle(f"{SCENE}.shadowRoot.firstChild")
    made.rewrite(page("two", ("a.stl", "b.stl")))
    owner.frame.wait_for_function(
        "document.querySelector('#note').textContent === 'two'"
    )
    assert snapshot_of(owner) == before
    assert owner.frame.evaluate(
        f"(n) => {SCENE}.shadowRoot.firstChild === n", node
    )  # the rendered nodes are the same objects
    # A changed config adds a part: settings and camera stay, loaded files are kept.
    made.rewrite(page("three", ("a.stl", "b.stl", "c.stl")))
    owner.frame.wait_for_function(f"{SCENE}.partInfo().length === 3")
    wait_scene(owner)
    after = snapshot_of(owner)
    assert after["parts"][:2] == before["parts"] and after["parts"][2][1] is True
    assert after["section"] == before["section"] and after["camera"] == before["camera"]
    assert sum(u.endswith("/a.stl") for u in requests) == 1


def test_scn_06_state_survives_publishing_a_draft(owner, make) -> None:  # noqa: ANN001
    def page(note: str) -> str:
        return f"<p id=note>{note}</p>" + scene_page(parts_of("a.stl", "b.stl"))

    made = make(page("live"), files=FILES)
    wait_scene(owner)
    before = change_everything(owner)
    (made.folder / own_draft(made.sid)).write_text(page("published"))
    call(
        owner, "POST", f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parent.parent), "name": "page.html", "publish": True},
    )  # fmt: skip
    owner.frame.wait_for_function(
        "document.querySelector('#note').textContent === 'published'"
    )
    assert snapshot_of(owner) == before


def test_scn_06_a_rewritten_part_file_reloads_and_keeps_the_settings(
    owner, make
) -> None:  # noqa: ANN001
    made = make(scene_page(parts_of("a.stl", "b.stl")), files=FILES)
    wait_scene(owner)
    shadow(owner, ".part-row input[type=checkbox]").nth(1).uncheck()
    set_value(shadow(owner, ".part-row input[type=color]").nth(0), "#123456")
    assert run(owner, "return el.bounds.max[0];") == 10
    (made.folder / "a.stl").write_bytes(box_stl((0, 0, 0), (40, 10, 10)))
    owner.frame.wait_for_function(f"{SCENE}.bounds.max[0] === 40", timeout=20000)
    found = info(owner)
    assert found["a"]["colour"] == "#123456" and found["b"]["visible"] is False


# ---- SCN-07: marks -----------------------------------------------------------------------------


def screen_point(owner, part_index: int) -> tuple[float, float]:  # noqa: ANN001
    """Window position of the centre of a part's box."""
    x, y = run(
        owner,
        "const c = el.parts[arg].box.getCenter(new el.THREE.Vector3()).project(el.camera);"
        " const r = el.canvas.getBoundingClientRect();"
        " return [r.left + (c.x + 1) / 2 * r.width, r.top + (1 - c.y) / 2 * r.height];",
        part_index,
    )
    frame = owner.page.locator("#frame").bounding_box()  # frame to window coordinates
    return frame["x"] + x, frame["y"] + y


def test_scn_07_mark_mode_gives_a_scene_mark_with_point_normal_label_and_part(
    owner, make
) -> None:  # noqa: ANN001
    made = make(scene_page(parts_of("a.stl", "b.stl")), files=FILES)
    wait_scene(owner)
    owner.page.mouse.click(*screen_point(owner, 0))  # not in mark mode: no mark
    assert made.wait_action("scene-mark", 0) == []
    toggle = shadow(owner, "button.mark-toggle")
    toggle.click()
    assert toggle.get_attribute("aria-pressed") == "true"
    owner.page.mouse.click(*screen_point(owner, 0))
    owner.page.mouse.click(*screen_point(owner, 1))
    marks = made.wait_action("scene-mark", 2)
    first, second = (m["value"] for m in marks)
    assert (first["label"], first["part"]) == (1, "a")
    assert (second["label"], second["part"]) == (2, "b")
    assert sorted(abs(c) for c in first["normal"])[-1] > 0.99
    assert all(-0.01 <= c <= 10.01 for c in first["point"])
    assert (
        19.99 <= second["point"][0] <= 30.01
        and marks[0]["target"]["canvas_id"] == "scene"
    )
    # A hidden part cannot be marked.
    shadow(owner, ".part-row input[type=checkbox]").nth(1).uncheck()
    owner.page.mouse.click(*screen_point(owner, 1))
    owner.page.wait_for_timeout(300)
    assert len(made.wait_action("scene-mark", 0)) == 2
    button(owner, "Clear marks").click()
    assert run(owner, "return el.markSprites.length;") == 0


def test_scn_07_marks_follow_the_section_plane(owner, make) -> None:  # noqa: ANN001
    made = make(
        scene_page([{"src": "a.stl"}]),
        files={"a.stl": box_stl((0, 0, 0), (20, 20, 20))},
    )
    wait_scene(owner)
    shadow(owner, "button[aria-label='side view']").click()
    shadow(owner, "button[aria-label='Section plane X']").click()  # keeps x <= 10
    shadow(owner, "button.mark-toggle").click()
    owner.page.mouse.click(*screen_point(owner, 0))
    [mark] = made.wait_action("scene-mark", 1)
    # The outer wall at x = 20 is cut away: the click lands on the inside, at x = 0.
    assert mark["value"]["point"][0] == pytest.approx(0, abs=0.01)


# ---- SCN-08: screenshots and page checks ------------------------------------------------------------------------

SHOT_FILES = {**FILES, "t.stl": torus_stl((40, 10, 10), 25, 8, 90, 45)}


def look_page() -> str:
    parts = [
        {"src": "a.stl", "group": "frame", "colour": "#4e79a7"},
        {"src": "b.stl", "group": "frame", "colour": "#f28e2b", "opacity": 0.6},
        {"src": "t.stl", "name": "ring", "colour": "#59a14f"},
        {"src": "c.stl", "name": "post"},
    ]
    return (
        "<title>Scene</title><style>body{margin:8px;font:16px system-ui,sans-serif}</style><h1>Scene</h1>"
        + scene_page(parts, units="mm", height=420)
    )


def keep_picture(result: dict, name: str) -> None:
    """Copy a look to ``$SCENE_PNG_DIR`` (set by hand to view the pictures)."""
    if folder := os.environ.get("SCENE_PNG_DIR"):
        shutil.copy(result["png"], Path(folder) / name)


def canvas_rect(frame) -> dict:  # noqa: ANN001
    return frame.evaluate(
        f"(() => {{ const r = {SCENE}.shadowRoot.querySelector('canvas')"
        ".getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; })()"
    )


def region_painted(rows, rect: dict, background) -> int:  # noqa: ANN001
    y0, x0 = int(rect["y"]), int(rect["x"])
    window = [row[x0 : x0 + int(rect["w"])] for row in rows[y0 : y0 + int(rect["h"])]]
    return painted(window, background)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_scn_08_look_shows_the_webgl_view_and_the_page_checks_find_nothing(
    owner, make, scheme: str
) -> None:  # noqa: ANN001
    owner.page.emulate_media(color_scheme=scheme)
    made = make(look_page(), files=SHOT_FILES)
    wait_scene(owner)
    result = call(
        owner, "POST", f"/api/sessions/{made.sid}/look",
        json={"width": 1100, "height": 760, "scheme": scheme},
    )  # fmt: skip
    keep_picture(result, f"look-{scheme}.png")
    assert result["source"] == "window" and result["errors"] == []
    assert result["audit"]["findings"] == [], result["audit"]["findings"]
    _, _, rows = decode_png(Path(result["png"]).read_bytes())
    rect = canvas_rect(owner.frame)
    background = LIGHT_BACKGROUND if scheme == "light" else DARK_BACKGROUND
    assert region_painted(rows, rect, background) > rect["w"] * rect["h"] * 0.03


@pytest.fixture
def headless(owner) -> HeadlessRenderer:  # noqa: ANN001
    renderer = HeadlessRenderer(launch_env=_launch_env())
    owner.hub.app.state.looks.headless = renderer
    return renderer


def test_scn_08_the_headless_look_also_draws_the_scene(owner, make, headless) -> None:  # noqa: ANN001
    made = make(look_page(), files=SHOT_FILES)
    wait_scene(owner)
    # The window is light, so a dark look is made by the headless browser.
    result = call(
        owner, "POST", f"/api/sessions/{made.sid}/look",
        json={"width": 1100, "height": 760, "scheme": "dark"},
    )  # fmt: skip
    assert result["source"] == "headless", result
    keep_picture(result, "look-headless-dark.png")
    assert result["errors"] == [] and result["audit"]["findings"] == []
    _, _, rows = decode_png(Path(result["png"]).read_bytes())
    assert painted(rows[100:560], DARK_BACKGROUND) > 20000


def test_scn_08_the_send_screenshot_contains_the_scene(studio) -> None:  # noqa: ANN001
    studio.page.set_viewport_size({"width": 1280, "height": 1000})
    sid = studio.make(look_page(), files=SHOT_FILES)
    wait_scene(studio.owner)
    studio.frame.evaluate("window.scrollTo(0, 0)")
    studio.queue_action()
    studio.page.click("#send-button")
    [event] = studio.wait_events(sid, 1)
    assert event["screenshot_error"] is None, event
    assert studio.send_record(event)["screenshot_warnings"] == []
    _, _, rows = decode_png(studio.screenshot(event))
    rect = canvas_rect(studio.frame)
    assert region_painted(rows, rect, LIGHT_BACKGROUND) > rect["w"] * rect["h"] * 0.03
    # The part list (DOM) is in the picture too: the swatch of the orange part.
    orange = sum(
        near(p, (242, 142, 43), 20)
        for row in rows[int(rect["y"]) : int(rect["y"] + rect["h"])]
        for p in row[int(rect["x"] + rect["w"]) :]
    )
    assert orange > 5
