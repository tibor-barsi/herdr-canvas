"""The picture viewer: Fit, 100 %, zoom around the pointer, panning (VIEW-06).

Slice of VIEW-06 (closed in P24.4): the vector "a comment made at 100 % stays on
the same image pixels at Fit" belongs to P24.4. VIEW-14's picture limits are
tested here as well.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from .support import call

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "comments"
sys.path.insert(0, str(FIXTURES))

from make_pictures import main as make_pictures  # noqa: E402

pytestmark = pytest.mark.browser

VIEW = "window.acImageView()"


@pytest.fixture(scope="module")
def pictures(tmp_path_factory) -> Path:  # noqa: ANN001
    """The large generated pictures."""
    out = tmp_path_factory.mktemp("pictures")
    make_pictures(out)
    return out


def show_picture(make, name: str, data: bytes):  # noqa: ANN001, ANN201
    """Show ``name`` as a page; return the session and the report count before."""
    made = make("<p>first</p>")
    (made.folder / name).write_bytes(data)
    seen = made.owner.count_reports("viewer-error")
    call(
        made.owner,
        "POST",
        f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parents[1]), "name": name},
    )
    return made, seen


def open_picture(make, name: str, data: bytes):  # noqa: ANN001, ANN201
    """Show ``name`` and wait until the viewer has laid it out."""
    made, _ = show_picture(make, name, data)
    made.owner.frame.wait_for_function(
        "window.acImageView && document.querySelector('img') "
        "&& document.querySelector('img').complete"
    )
    return made


def photo(make):  # noqa: ANN001, ANN201
    return open_picture(make, "photo.png", PHOTO.read_bytes())


def view(owner) -> dict:  # noqa: ANN001
    return owner.frame.evaluate(VIEW)


def pointer(owner, x: float, y: float) -> tuple[float, float]:  # noqa: ANN001
    """Move the mouse to frame point (x, y); return the window point."""
    box = owner.page.locator("#frame").bounding_box()
    owner.page.mouse.move(box["x"] + x, box["y"] + y)
    return box["x"] + x, box["y"] + y


def wheel(owner, dy: float) -> None:  # noqa: ANN001
    owner.page.keyboard.down("Control")
    owner.page.mouse.wheel(0, dy)
    owner.page.keyboard.up("Control")
    owner.frame.evaluate("new Promise(requestAnimationFrame)")


def click_button(owner, label: str) -> None:  # noqa: ANN001
    owner.frame.get_by_role("button", name=label, exact=True).click()


def frame_size(owner) -> tuple[int, int]:  # noqa: ANN001
    return tuple(owner.frame.evaluate("[innerWidth, innerHeight]"))


PHOTO = FIXTURES / "ramp-640x480.png"
SCROLLER = "document.querySelector('[data-scroller]')"


def test_view_06_a_large_photo_is_fitted_to_the_frame(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    width, height = frame_size(owner)
    state = view(owner)
    assert (state["width"], state["height"]) == (4000, 3000)
    assert state["scale"] == pytest.approx(min(width / 4000, height / 3000), rel=0.01)
    assert state["x"] >= -0.5 and state["y"] >= -0.5
    assert state["x"] + 4000 * state["scale"] <= width + 0.5
    assert state["y"] + 3000 * state["scale"] <= height + 0.5
    assert owner.frame.evaluate(
        f"{SCROLLER}.scrollWidth <= {SCROLLER}.clientWidth"
        f" && {SCROLLER}.scrollHeight <= {SCROLLER}.clientHeight"
    )


def test_view_06_fit_does_not_enlarge_a_small_picture(make) -> None:  # noqa: ANN001
    made = photo(make)
    assert view(made.owner)["scale"] == 1


def test_view_06_the_100_percent_button_shows_one_image_pixel_per_css_pixel(
    make, pictures
) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    click_button(owner, "100 %")
    assert view(owner)["scale"] == 1
    size = owner.frame.evaluate(
        "(() => { const r = document.querySelector('img').getBoundingClientRect();"
        " return [r.width, r.height]; })()"
    )
    assert size == [4000, 3000]
    click_button(owner, "Fit")
    assert view(owner)["scale"] < 0.5


def test_view_06_scrollbars_appear_when_the_picture_is_larger_than_the_frame(
    make, pictures
) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    click_button(owner, "100 %")
    extra = owner.frame.evaluate(
        f"[{SCROLLER}.scrollWidth - {SCROLLER}.clientWidth,"
        f" {SCROLLER}.scrollHeight - {SCROLLER}.clientHeight,"
        f" getComputedStyle({SCROLLER}).overflow]"
    )
    assert extra[0] > 0 and extra[1] > 0
    assert extra[2] == "auto"


def test_view_06_ctrl_wheel_zooms_around_the_pointer(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    click_button(owner, "100 %")
    width, height = frame_size(owner)
    for fx, fy in ((0.5, 0.5), (0.25, 0.7)):
        px, py = width * fx, height * fy
        before = view(owner)
        u = ((px - before["x"]) / before["scale"], (py - before["y"]) / before["scale"])
        pointer(owner, px, py)
        wheel(owner, -300)
        after = view(owner)
        assert after["scale"] > before["scale"] * 1.2
        assert after["x"] + u[0] * after["scale"] == pytest.approx(px, abs=1.5)
        assert after["y"] + u[1] * after["scale"] == pytest.approx(py, abs=1.5)
        wheel(owner, 200)
        back = view(owner)
        assert back["scale"] < after["scale"]
        assert back["x"] + u[0] * back["scale"] == pytest.approx(px, abs=1.5)
        assert back["y"] + u[1] * back["scale"] == pytest.approx(py, abs=1.5)


def test_view_06_zoom_stays_between_10_and_800_percent(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    pointer(owner, 100, 100)
    for _ in range(12):
        wheel(owner, -1000)
    assert view(owner)["scale"] == pytest.approx(8)
    for _ in range(12):
        wheel(owner, 1000)
    assert view(owner)["scale"] == pytest.approx(0.1)


def test_view_06_a_plain_wheel_scrolls_and_does_not_zoom(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    click_button(owner, "100 %")
    pointer(owner, 100, 100)
    before = view(owner)
    owner.page.mouse.wheel(0, 200)
    owner.frame.wait_for_function(f"{VIEW}.y < {before['y'] - 50}")
    assert view(owner)["scale"] == 1


def test_view_06_dragging_pans_the_picture(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    click_button(owner, "100 %")
    x, y = pointer(owner, 400, 300)
    before = view(owner)
    owner.page.mouse.down()
    owner.page.mouse.move(x - 120, y - 80, steps=5)
    owner.page.mouse.up()
    after = view(owner)
    assert after["x"] == pytest.approx(before["x"] - 120, abs=1)
    assert after["y"] == pytest.approx(before["y"] - 80, abs=1)


def test_view_06_dragging_does_not_pan_in_comment_mode(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    click_button(owner, "100 %")
    owner.page.evaluate(
        "document.querySelector('#frame').contentWindow.postMessage("
        "{type: 'comment-mode', on: true, kind: 'rect'}, '*')"
    )
    owner.frame.wait_for_function(
        "document.documentElement.hasAttribute('data-ac-commenting')"
    )
    x, y = pointer(owner, 400, 300)
    before = view(owner)
    owner.page.mouse.down()
    owner.page.mouse.move(x - 120, y - 80, steps=5)
    owner.page.mouse.up()
    assert view(owner) == before


def test_view_06_view_matches_the_pictures_place_in_the_frame(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "photo.png", (pictures / "photo-4000x3000.png").read_bytes()
    )
    owner = made.owner
    click_button(owner, "100 %")
    pointer(owner, 300, 200)
    wheel(owner, -250)
    state = view(owner)
    rect = owner.frame.evaluate(
        "(() => { const r = document.querySelector('img').getBoundingClientRect();"
        " return [r.left, r.top, r.width]; })()"
    )
    assert rect[0] == pytest.approx(state["x"], abs=0.01)
    assert rect[1] == pytest.approx(state["y"], abs=0.01)
    assert rect[2] == pytest.approx(4000 * state["scale"], abs=0.05)


def test_view_06_an_svg_is_shown_through_img_and_its_script_never_runs(make) -> None:  # noqa: ANN001
    made = open_picture(make, "drawing.svg", (FIXTURES / "script.svg").read_bytes())
    frame = made.owner.frame
    assert frame.evaluate("document.querySelector('img').naturalWidth") == 300
    assert frame.evaluate("document.querySelectorAll('svg, object, embed').length") == 0
    frame.wait_for_timeout(300)
    assert frame.evaluate("typeof window.__svgRan") == "undefined"


def test_view_14_an_undecodable_picture_shows_a_notice_and_reports_it(make) -> None:  # noqa: ANN001
    made, seen = show_picture(make, "bad.png", b"not a picture")
    report = made.owner.wait_report_after("viewer-error", seen)
    assert report["reason"] == "image-undecodable"
    assert report["page"] == "bad.png"
    text = made.owner.frame.evaluate("document.body.innerText")
    assert (
        "This file could not be shown: the picture is damaged or in a format the "
        "window cannot read. Ask the agent to make it again."
    ) in text


def test_view_14_a_picture_over_50_megapixels_is_refused(make, pictures) -> None:  # noqa: ANN001
    made, seen = show_picture(
        make, "huge.png", (pictures / "huge-10000x6000.png").read_bytes()
    )
    assert (
        made.owner.wait_report_after("viewer-error", seen)["reason"]
        == "image-too-large"
    )
    assert (
        "This file could not be shown: the picture is too large (over 50 megapixels). "
        "Ask the agent to make a smaller one."
    ) in made.owner.frame.evaluate("document.body.innerText")


def test_view_14_a_48_megapixel_picture_is_shown(make, pictures) -> None:  # noqa: ANN001
    made = open_picture(
        make, "edge.png", (pictures / "edge-8000x6000.png").read_bytes()
    )
    state = view(made.owner)
    assert (state["width"], state["height"]) == (8000, 6000)
    assert made.owner.count_reports("viewer-error") == 0
