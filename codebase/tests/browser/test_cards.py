"""Design cards of the kit and the ``cards`` template (CARD-01 to CARD-05)."""

from __future__ import annotations

import pytest

from agent_canvas.templates import write_template

from .support import call
from .test_heavy_blocks import wait_model, wait_plot
from .test_page_checks import look

pytestmark = pytest.mark.browser

KIT = '<link rel="stylesheet" href="/static/kit/kit.css">'
BADGES = "recommended fallback fails placeholder ok warn bad info".split()


def card(index: int, heights: tuple[int, ...], tiles: int, badge: str = "") -> str:
    """One design card with fake panels of the given heights."""
    badge_html = f'<span class="badge {badge}">{badge}</span>' if badge else ""
    tile_html = "".join(
        f'<div class="tile"><b class="value">{n}</b><span class="label">L</span></div>'
        for n in range(tiles)
    )
    panels = "".join(
        f'<div style="height:{h}px;background:#8884">panel</div>' for h in heights
    )
    return (
        f'<article class="card"><header><h2>Design {index}</h2>{badge_html}</header>'
        f'<div class="tiles">{tile_html}</div><div class="panels">{panels}</div>'
        "</article>"
    )


def cards_page(mode: str = "") -> str:
    """Three cards of different content heights."""
    cards = "".join(
        (
            card(1, (120, 200, 160), 3, "recommended"),
            card(2, (180, 140, 220), 5, "fallback"),
            card(3, (100, 260, 120), 2, "fails"),
        )
    )
    return (
        f"<!doctype html><html><head>{KIT}</head><body><main class='page'>"
        f'<section class="cards {mode}">{cards}</section></main></body></html>'
    )


def boxes(owner, selector: str) -> list[dict]:  # noqa: ANN001
    """Bounding boxes of the elements matching ``selector``."""
    return owner.frame.evaluate(
        "(s) => [...document.querySelectorAll(s)].map((e) => {"
        " const r = e.getBoundingClientRect();"
        " return {left: r.left, top: r.top, width: r.width, height: r.height}; })",
        selector,
    )


def resize(owner, width: int) -> None:  # noqa: ANN001
    """Set the window width and let the layout settle."""
    owner.page.set_viewport_size({"width": width, "height": 900})
    owner.page.wait_for_timeout(300)


# ---- CARD-01: panels ------------------------------------------------------------------  # noqa: E501


def test_card_01_panels_sit_side_by_side_when_wide_and_stack_when_narrow(
    owner, make
) -> None:  # noqa: ANN001
    make(cards_page())
    resize(owner, 1600)
    first = boxes(owner, ".card:first-child .panels > *")
    assert len({round(b["top"]) for b in first}) == 1
    assert len({round(b["left"]) for b in first}) == 3
    resize(owner, 700)
    first = boxes(owner, ".card:first-child .panels > *")
    assert len({round(b["left"]) for b in first}) == 1
    assert [round(b["top"]) for b in first] == sorted(round(b["top"]) for b in first)
    assert len({round(b["top"]) for b in first}) == 3


def test_card_01_header_puts_the_badge_beside_the_title(owner, make) -> None:  # noqa: ANN001
    make(cards_page())
    resize(owner, 1280)
    title = boxes(owner, ".card:first-child header h2")[0]
    badge = boxes(owner, ".card:first-child header .badge")[0]
    assert (
        abs((title["top"] + title["height"] / 2) - (badge["top"] + badge["height"] / 2))
        < 12
    )
    assert badge["left"] > title["left"] + title["width"] - 1


# ---- CARD-02: badges ------------------------------------------------------------------  # noqa: E501


def badge_page() -> str:
    spans = " ".join(f'<span class="badge {name}">{name}</span>' for name in BADGES)
    return f"<!doctype html><html><head>{KIT}</head><body><main class='page'><p>{spans}</p></main></body></html>"  # noqa: E501


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_card_02_badge_variants_look_different(owner, make, scheme: str) -> None:  # noqa: ANN001
    made = make(badge_page())
    owner.page.emulate_media(color_scheme=scheme)
    owner.page.wait_for_timeout(200)
    looks = owner.frame.evaluate(
        "() => [...document.querySelectorAll('.badge')].map((e) => {"
        " const s = getComputedStyle(e);"
        " return [s.color, s.backgroundColor, s.borderTopColor, s.borderTopStyle].join('|'); })"  # noqa: E501
    )
    assert len(set(looks)) == len(BADGES), looks
    result = look(owner, made.sid, width=900, height=500, scheme=scheme)
    assert [f for f in result["audit"]["findings"] if f["rule"] == "contrast"] == []


# ---- CARD-03: compare mode ------------------------------------------------------------  # noqa: E501


def test_card_03_compare_aligns_the_rows_across_the_cards(owner, make) -> None:  # noqa: ANN001
    make(cards_page("compare"))
    resize(owner, 1600)
    for selector in (
        ".card header",
        ".card .tiles",
        ".card .panels > :nth-child(1)",
        ".card .panels > :nth-child(2)",
        ".card .panels > :nth-child(3)",
    ):
        found = boxes(owner, selector)
        assert len(found) == 3, selector
        assert len({round(b["top"]) for b in found}) == 1, (selector, found)
        assert len({round(b["left"]) for b in found}) == 3, selector
    resize(owner, 700)
    assert (
        owner.frame.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"  # noqa: E501
        )
        <= 0
    )
    # Cards keep their columns: the row scrolls instead of the page.
    assert owner.frame.evaluate(
        "(() => { const c = document.querySelector('.cards.compare');"
        " return c.scrollWidth > c.clientWidth; })()"
    )
    stacked = boxes(owner, ".card .panels > :nth-child(1)")
    assert len({round(b["top"]) for b in stacked}) == 1


def test_card_03_normal_mode_does_not_align_rows(owner, make) -> None:  # noqa: ANN001
    make(cards_page())
    resize(owner, 1600)
    cards = boxes(owner, ".card")
    assert len({round(b["left"]) for b in cards}) == 1  # stacked, one per row


# ---- CARD-04 / CARD-05: the template, rendered -----------------------------------------  # noqa: E501

SIZES = (1600, 700)
TALL = {
    ("normal", 1600): 2300,
    ("normal", 700): 4300,
    ("compare", 1600): 1900,
    ("compare", 700): 1900,
}
SCHEMES = ("light", "dark")


def show_template(owner, make, tmp_path, compare: bool):  # noqa: ANN001, ANN201
    """Write the ``cards`` template, show it and wait for every block."""
    made = make("<p>start</p>")
    page = write_template(made.folder, "tpl.html", "cards")
    if compare:
        page.write_text(
            page.read_text().replace('class="cards"', 'class="cards compare"', 1)
        )
    body = {"project": str(tmp_path / "alpha"), "name": "tpl.html"}
    shown = call(owner, "POST", f"/api/sessions/{made.sid}/show", json=body)
    assert shown["errors"] == []
    owner.frame.wait_for_function("window.agentCanvas !== undefined")
    owner.frame.locator("canvas-plot").first.wait_for()
    wait_plot(owner, "plot-a")
    wait_model(owner, "model-a")
    owner.frame.wait_for_function(
        "[...document.querySelectorAll('canvas-image')].every((b) => {"
        " const i = b.shadowRoot.querySelector('img'); return i && i.complete; })"
    )
    return made


@pytest.mark.parametrize("compare", [False, True], ids=["normal", "compare"])
def test_card_05_template_renders_cleanly_in_both_modes(
    owner, make, tmp_path, compare: bool
) -> None:  # noqa: ANN001
    show_template(owner, make, tmp_path, compare)
    for scheme in SCHEMES:
        owner.page.emulate_media(color_scheme=scheme)
        for width in SIZES:
            owner.page.set_viewport_size({"width": width, "height": 1000})
            owner.page.wait_for_timeout(500)
            where = f"{scheme} {width}px compare={compare}"
            assert (
                owner.frame.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"  # noqa: E501
                )
                <= 0
            ), where
            assert owner.frame.locator(".block-error").count() == 0, where
            assert owner.page.evaluate("window.__errors") == [], where
            mode = "compare" if compare else "normal"
            # A tall window shows the whole page in one picture.
            owner.page.set_viewport_size({"width": width, "height": TALL[mode, width]})
            owner.page.wait_for_timeout(500)
            owner.page.screenshot(path=f"/tmp/cards-check-{mode}-{scheme}-{width}.png")


def test_card_04_compare_template_aligns_pictures_models_and_plots(
    owner, make, tmp_path
) -> None:  # noqa: ANN001
    show_template(owner, make, tmp_path, True)
    resize(owner, 1600)
    for selector in (
        ".card header",
        ".card .tiles",
        ".card .panels > :nth-child(1)",
        ".card .panels > :nth-child(2)",
        ".card .panels > :nth-child(3)",
    ):
        found = boxes(owner, selector)
        assert len(found) == 3, selector
        assert len({round(b["top"]) for b in found}) == 1, (selector, found)


def test_card_04_model_background_follows_the_scheme_live(
    owner, make, tmp_path
) -> None:  # noqa: ANN001
    show_template(owner, make, tmp_path, False)
    read = (
        "(() => { const m = document.querySelector('canvas-model');"
        " const c = m.renderer.getClearColor(new m.THREE.Color());"
        " return c.r + c.g + c.b; })()"
    )
    light = owner.frame.evaluate(read)
    owner.page.emulate_media(color_scheme="dark")
    owner.frame.wait_for_function(f"{read} < {light} - 0.5")
    owner.page.emulate_media(color_scheme="light")
    owner.frame.wait_for_function(f"{read} > {light} - 0.05")
