"""The comment panel in a narrow window; the chip of a lost comment (COM-06, COM-08)."""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE
from .test_com_20_collapse import frame_width
from .test_comment_layer import comment_mode
from .test_comment_panel import entries, record, show_comments

pytestmark = pytest.mark.browser

THREE = [record(1), record(2), record(3)]


def resize(studio, width: int) -> None:  # noqa: ANN001
    studio.page.set_viewport_size({"width": width, "height": 900})


def panel_class(studio) -> str:  # noqa: ANN001
    return studio.page.locator("#comment-panel").get_attribute("class") or ""


def mid_width(studio) -> float:  # noqa: ANN001
    return studio.page.locator("#mid").bounding_box()["width"]


@pytest.mark.parametrize("width", [700, 900])
def test_com_06_in_a_narrow_window_the_open_panel_lies_over_the_page(
    studio, width
) -> None:  # noqa: ANN001
    resize(studio, width)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, THREE)
    panel = studio.page.locator("#comment-panel")
    studio.page.locator("#comment-panel .stripbutton").click()
    assert "strip" not in panel_class(studio)
    assert panel.bounding_box()["width"] == pytest.approx(320, abs=1)
    assert frame_width(studio) == pytest.approx(mid_width(studio), abs=1)
    frame = studio.page.locator("#frame").bounding_box()
    assert panel.bounding_box()["x"] + 320 == pytest.approx(
        frame["x"] + frame["width"], abs=1
    )
    assert entries(studio).count() == 3


@pytest.mark.parametrize("width", [700, 900])
def test_com_06_in_a_narrow_window_the_panel_stays_folded_in_comment_mode(
    studio, width
) -> None:  # noqa: ANN001
    resize(studio, width)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, THREE)
    comment_mode(studio)
    assert "strip" in panel_class(studio)
    studio.page.locator("#comment-panel .stripbutton").click()
    assert "strip" not in panel_class(studio)
    studio.page.locator("#comment-panel .collapse").click()  # D-61 works at every width
    assert "strip" in panel_class(studio)


def test_com_06_at_1215_px_the_layout_is_as_before(studio) -> None:  # noqa: ANN001
    resize(studio, 1215)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, [])
    comment_mode(studio)
    assert studio.page.locator("#comment-panel").is_hidden()  # no comments, no panel
    show_comments(studio, sid, THREE)
    assert frame_width(studio) == pytest.approx(mid_width(studio) - 320, abs=1)


def test_com_06_a_window_widened_past_1000_px_takes_the_panel_into_the_row(
    studio,
) -> None:  # noqa: ANN001
    resize(studio, 700)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, THREE)
    studio.page.locator("#comment-panel .stripbutton").click()
    resize(studio, 1215)
    studio.page.wait_for_timeout(300)
    assert "float" not in panel_class(studio)
    assert frame_width(studio) == pytest.approx(mid_width(studio) - 320, abs=1)


@pytest.mark.parametrize(
    ("status", "lost", "chip"),
    [
        ("sent", True, "lost"),
        ("seen", True, "seen · lost"),
        ("answered", True, "answered · lost"),
        ("done", True, "✓ done · lost"),
        ("seen", False, "seen"),
    ],
)
def test_com_08_a_lost_comment_keeps_what_the_chip_said_before(
    studio, status, lost, chip
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, [record(1, status, lost=lost)])
    comment_mode(studio)
    studio.page.locator('.filters button[data-filter="all"]').click()
    assert entries(studio).locator(".chip").inner_text() == chip


def strip_count(studio) -> str:  # noqa: ANN001
    return studio.page.locator("#comment-panel .stripbutton .cn").inner_text()


def test_com_06_in_a_narrow_window_the_panel_opens_only_when_the_owner_opens_it(
    studio,
) -> None:  # noqa: ANN001
    resize(studio, 700)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, [record(1)])
    assert "strip" in panel_class(studio)
    assert strip_count(studio) == "1"
    show_comments(studio, sid, [record(1), record(2)])
    assert "strip" in panel_class(studio)
    assert strip_count(studio) == "2"
    studio.page.locator("#comment-panel .stripbutton").click()
    assert "strip" not in panel_class(studio)
    show_comments(studio, sid, THREE)
    assert "strip" not in panel_class(studio)
    assert entries(studio).count() == 3


def test_com_06_in_a_narrow_window_a_click_on_a_marker_opens_the_panel(
    studio,
) -> None:  # noqa: ANN001
    resize(studio, 700)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, [record(1)])
    assert "strip" in panel_class(studio)
    token = studio.page.evaluate("(id) => commentTokens.get(id)", "cmt_1")
    if token is None:
        studio.page.evaluate("commentTokens.set('cmt_1', 'tok')")
        token = "tok"
    studio.page.evaluate("(t) => onCommentMarker({token: t, action: 'click'})", token)
    assert "strip" not in panel_class(studio)


def test_com_06_at_1215_px_comments_open_the_panel_by_themselves(
    studio,
) -> None:  # noqa: ANN001
    resize(studio, 1215)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, [record(1)])
    assert "strip" not in panel_class(studio)
    assert "float" not in panel_class(studio)


@pytest.mark.parametrize(("width", "narrow"), [(999, True), (1000, False)])
def test_com_06_the_limit_is_between_999_and_1000_px(studio, width, narrow) -> None:  # noqa: ANN001
    resize(studio, width)
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, [record(1)])
    assert ("strip" in panel_class(studio)) is narrow
    assert ("float" in panel_class(studio)) is narrow
    comment_mode(studio)
    assert ("strip" in panel_class(studio)) is narrow
