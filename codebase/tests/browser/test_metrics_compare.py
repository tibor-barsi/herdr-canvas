# ruff: noqa: E501
"""canvas-metrics and canvas-compare: state computed from the limits, before and after (CNT-05, CNT-06).

Fixtures: ``tests/fixtures/animation`` (frame ``i`` has a red bar ``8 * (i + 1)`` px wide
on a 160 x 90 picture, so frame 19 is red all over and frame 0 is mostly not).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from helpers import CODEBASE_DIR, decode_png

from .support import block
from .test_look_window import look

pytestmark = pytest.mark.browser

FIXTURES = CODEBASE_DIR / "tests" / "fixtures" / "animation"
FILES = {
    name: (FIXTURES / name).read_bytes() for name in ("frame-00.png", "frame-19.png")
}
SHOTS = os.environ.get("AC_P314_SHOTS")
RED = (229, 72, 77)

TILES = [
    {"label": "Safety factor", "value": 1.8, "min": 1.5},
    {"label": "Margin", "value": 1.55, "min": 1.5},
    {"label": "Buckling", "value": 1.4, "min": 1.5},
    {"label": "Frequency", "value": 250, "unit": "Hz", "max": 300},
    {"label": "Mass", "value": 412, "unit": "g", "previous": 400},
    {"label": "Cost", "value": 95, "unit": "EUR", "previous": 100},
]


def metrics(tiles: list[dict], canvas_id: str = "m", **config) -> str:  # noqa: ANN003
    return block("canvas-metrics", canvas_id, {"tiles": tiles, **config})


def compare(canvas_id: str = "c", **config) -> str:  # noqa: ANN003
    return block(
        "canvas-compare",
        canvas_id,
        {"before": "frame-00.png", "after": "frame-19.png", **config},
    )


def wait_idle(owner, tag: str, count: int = 1) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        """([tag, n]) => { const all = [...document.querySelectorAll(tag)];
          return all.length === n && all.every((e) => e.renderIdle && e.shadowRoot
            && e.shadowRoot.querySelector('.block')); }""",
        arg=[tag, count],
    )


def wait_selector(owner, tag: str, selector: str) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        "([tag, s]) => { const e = document.querySelector(tag); return e && e.shadowRoot && e.shadowRoot.querySelector(s); }",
        arg=[tag, selector],
    )


def tiles_of(owner, canvas_id: str = "m") -> list[dict]:  # noqa: ANN001
    return owner.frame.evaluate(
        """(id) => [...document.querySelector(`[data-canvas-id="${id}"]`).shadowRoot
          .querySelectorAll('.met-tile')].map((t) => {
            const q = (s) => { const e = t.querySelector(s); return e ? e.textContent.trim() : null; };
            return {state: t.dataset.state, label: q('.met-label'), value: q('.met-value'),
              limit: q('.met-limit'), word: q('.met-state'), change: q('.met-change')}; })""",
        canvas_id,
    )


def error_of(owner, tag: str, canvas_id: str) -> str | None:  # noqa: ANN001
    return owner.frame.evaluate(
        """([tag, id]) => { const e = document.querySelector(`${tag}[data-canvas-id="${id}"]`);
          const box = e.shadowRoot.querySelector('.block-error'); return box ? box.textContent : null; }""",
        [tag, canvas_id],
    )


def show_metrics(owner, make, tiles: list[dict], **config):  # noqa: ANN001, ANN003, ANN201
    made = make(metrics(tiles, **config))
    wait_idle(owner, "canvas-metrics")
    return made


# ---- CNT-05 ----------------------------------------------------------------------------


def test_cnt_05_the_state_is_computed_from_value_and_limits(owner, make) -> None:  # noqa: ANN001
    show_metrics(owner, make, TILES)
    states = [t["state"] for t in tiles_of(owner)]
    assert states == ["ok", "near", "out", "ok", "none", "none"]


def test_cnt_05_each_state_has_a_word_and_a_mark(owner, make) -> None:  # noqa: ANN001
    show_metrics(owner, make, TILES[:3])
    assert [t["word"] for t in tiles_of(owner)] == [
        "✓ ok",
        "! near limit",
        "✗ out of limit",
    ]
    marks = owner.frame.evaluate(
        """() => [...document.querySelector('canvas-metrics').shadowRoot.querySelectorAll('.met-state .met-mark')]
          .map((m) => m.getAttribute('aria-hidden'))"""
    )
    assert marks == ["true", "true", "true"]


def test_cnt_05_the_limit_is_written_out(owner, make) -> None:  # noqa: ANN001
    show_metrics(
        owner,
        make,
        [
            TILES[0],
            TILES[3],
            {"label": "Band", "value": 5, "min": 1, "max": 9, "unit": "mm"},
        ],
    )
    limits = [t["limit"] for t in tiles_of(owner)]
    assert limits == [
        "needs ≥ 1.5",
        "must be ≤ 300 Hz",
        "needs ≥ 1 mm · must be ≤ 9 mm",
    ]


def test_cnt_05_the_change_from_previous_is_shown_in_percent(owner, make) -> None:  # noqa: ANN001
    show_metrics(owner, make, [*TILES[4:], TILES[0]])
    tiles = tiles_of(owner)
    assert [t["change"] for t in tiles] == [
        "+3 % vs previous",
        "-5 % vs previous",
        None,
    ]
    assert tiles[0]["word"] is None and tiles[0]["limit"] is None


def test_cnt_05_near_is_a_fraction_of_the_limit_and_can_be_set(owner, make) -> None:  # noqa: ANN001
    tile = {"label": "a", "value": 1.8, "min": 1.5}
    made = show_metrics(owner, make, [tile])
    assert tiles_of(owner)[0]["state"] == "ok"
    made.rewrite(metrics([tile], near=0.25))
    owner.frame.wait_for_function(
        "document.querySelector('canvas-metrics').shadowRoot.querySelector('.met-tile').dataset.state === 'near'"
    )


def test_cnt_05_two_limits_judge_the_nearer_one(owner, make) -> None:  # noqa: ANN001
    cases = [
        {"label": "low", "value": 10.5, "min": 10, "max": 100},
        {"label": "mid", "value": 50, "min": 10, "max": 100},
        {"label": "high", "value": 95, "min": 10, "max": 100},
        {"label": "over", "value": 101, "min": 10, "max": 100},
    ]
    show_metrics(owner, make, cases)
    assert [t["state"] for t in tiles_of(owner)] == ["near", "ok", "near", "out"]


def test_cnt_05_the_state_never_comes_from_the_agent(owner, make) -> None:  # noqa: ANN001
    lying = [
        {"label": "a", "value": 1.4, "min": 1.5, "state": "ok", "status": "ok"},
        {"label": "b", "value": 1.8, "min": 1.5, "state": "out"},
        {"label": "c", "value": 7, "state": "out"},
    ]
    show_metrics(owner, make, lying, state="ok")
    assert [t["state"] for t in tiles_of(owner)] == ["out", "ok", "none"]


def test_cnt_05_one_to_twelve_tiles(owner, make) -> None:  # noqa: ANN001
    twelve = [{"label": f"t{i}", "value": i} for i in range(12)]
    made = show_metrics(owner, make, twelve)
    assert len(tiles_of(owner)) == 12
    made.rewrite(metrics([*twelve, {"label": "t12", "value": 12}]))
    wait_selector(owner, "canvas-metrics", ".block-error")
    assert "1 to 12" in error_of(owner, "canvas-metrics", "m")
    made.rewrite(metrics([]))
    owner.frame.wait_for_function(
        "document.querySelector('canvas-metrics').shadowRoot.querySelector('.met-tile') === null"
    )
    assert "1 to 12" in error_of(owner, "canvas-metrics", "m")


@pytest.mark.parametrize(
    ("tile", "problem"),
    [
        ({"label": "x"}, "value"),
        ({"label": "x", "value": "5"}, "value"),
        ({"label": "x", "value": 5, "min": 9, "max": 3}, "min"),
        ({"label": "x", "value": 5, "previous": "a"}, "previous"),
    ],
)
def test_cnt_05_a_bad_tile_is_an_error_box(
    owner, make, tile: dict, problem: str
) -> None:  # noqa: ANN001
    make(metrics([tile]))
    wait_selector(owner, "canvas-metrics", ".block-error")
    assert problem in error_of(owner, "canvas-metrics", "m")


def test_cnt_05_agent_text_is_text_not_markup(owner, make) -> None:  # noqa: ANN001
    show_metrics(
        owner, make, [{"label": "<b>Mass</b>", "value": 1, "unit": "<i>g</i>"}]
    )
    assert (
        owner.frame.evaluate(
            "document.querySelector('canvas-metrics').shadowRoot.querySelectorAll('b, i').length"
        )
        == 0
    )
    assert tiles_of(owner)[0]["label"] == "<b>Mass</b>"


# ---- CNT-06 ----------------------------------------------------------------------------


def stage_pixel(owner) -> tuple[int, int, int]:  # noqa: ANN001
    png = owner.frame.locator("canvas-compare .cmp-stage").screenshot()
    width, height, rows = decode_png(png)
    r, g, b, _ = rows[height // 2][width - 10]
    return r, g, b


def test_cnt_06_side_by_side_shows_both_pictures_with_their_labels(owner, make) -> None:  # noqa: ANN001
    make(compare(before_label="Rev A", after_label="Rev B"), files=FILES)
    wait_idle(owner, "canvas-compare")
    found = owner.frame.evaluate(
        """() => { const r = document.querySelector('canvas-compare').shadowRoot;
          const imgs = [...r.querySelectorAll('img')];
          return {n: imgs.length, loaded: imgs.every((i) => i.naturalWidth > 0),
            labels: [...r.querySelectorAll('.cmp-label')].map((e) => e.textContent),
            xs: imgs.map((i) => i.getBoundingClientRect().left), slider: !!r.querySelector('input[type=range]')}; }"""
    )
    assert found["n"] == 2 and found["loaded"] and found["slider"] is False
    assert found["labels"] == ["Rev A", "Rev B"] and found["xs"][0] < found["xs"][1]


def test_cnt_06_default_labels_are_before_and_after(owner, make) -> None:  # noqa: ANN001
    make(compare(), files=FILES)
    wait_idle(owner, "canvas-compare")
    labels = owner.frame.evaluate(
        "[...document.querySelector('canvas-compare').shadowRoot.querySelectorAll('.cmp-label')].map((e) => e.textContent)"
    )
    assert labels == ["Before", "After"]


def test_cnt_06_slider_mode_reveals_the_after_picture(owner, make) -> None:  # noqa: ANN001
    make(compare(mode="slider", before_label="Old", after_label="New"), files=FILES)
    wait_idle(owner, "canvas-compare")
    slider = owner.frame.locator("canvas-compare input[type=range]")
    assert slider.count() == 1
    assert owner.frame.locator("canvas-compare .cmp-label").all_inner_texts() == [
        "Old",
        "New",
    ]
    slider.fill("0")
    assert stage_pixel(owner) != RED
    slider.fill("100")
    assert stage_pixel(owner) == RED
    slider.fill("0")
    assert stage_pixel(owner) != RED


def test_cnt_06_the_slider_keeps_its_place_on_a_rewrite(owner, make) -> None:  # noqa: ANN001
    made = make(compare(mode="slider"), files=FILES)
    wait_idle(owner, "canvas-compare")
    owner.frame.locator("canvas-compare input[type=range]").fill("80")
    made.rewrite(compare(mode="slider", after_label="Newest"))
    owner.frame.wait_for_function(
        "document.querySelector('canvas-compare').shadowRoot.textContent.includes('Newest')"
    )
    assert owner.frame.locator("canvas-compare input[type=range]").input_value() == "80"


def test_cnt_06_a_missing_picture_is_an_error_box(owner, make) -> None:  # noqa: ANN001
    make(compare(after="nowhere.png"), files=FILES)
    wait_selector(owner, "canvas-compare", ".block-error")
    assert "nowhere.png" in error_of(owner, "canvas-compare", "c")


def test_cnt_06_a_bad_mode_or_missing_picture_is_an_error_box(owner, make) -> None:  # noqa: ANN001
    make(
        compare(mode="wipe") + block("canvas-compare", "d", {"before": "frame-00.png"}),
        files=FILES,
    )
    owner.frame.wait_for_function(
        "[...document.querySelectorAll('canvas-compare')].length === 2 && [...document.querySelectorAll('canvas-compare')]"
        ".every((e) => e.shadowRoot && e.shadowRoot.querySelector('.block-error'))"
    )


def test_cnt_06_agent_labels_are_text_not_markup(owner, make) -> None:  # noqa: ANN001
    make(compare(before_label="<b>x</b>"), files=FILES)
    wait_idle(owner, "canvas-compare")
    assert (
        owner.frame.evaluate(
            "document.querySelector('canvas-compare').shadowRoot.querySelectorAll('b').length"
        )
        == 0
    )


# ---- looks ------------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_cnt_05_cnt_06_look_passes_the_contrast_check(owner, make, scheme: str) -> None:  # noqa: ANN001
    html = (
        metrics(TILES)
        + compare("c1")
        + compare("c2", mode="slider")
        + block(
            "canvas-report",
            "r",
            {"type": "result", "title": "In a card"},
            metrics(TILES[:3], "m2"),
        )
    )
    made = make(html, files=FILES)
    owner.frame.wait_for_function(
        """() => [...document.querySelectorAll('canvas-metrics, canvas-compare')].every(
          (e) => e.renderIdle && e.shadowRoot && e.shadowRoot.querySelector('.block'))"""
    )
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.wait_for_timeout(300)
    result = look(owner, made.sid, width=900, height=1500, scheme=scheme)
    assert [f for f in result["audit"]["findings"] if f["rule"] == "contrast"] == []
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        shutil.copy(result["png"], Path(SHOTS) / f"look-{scheme}.png")
