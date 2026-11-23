"""The page markers follow the panel filter Open / Done / All (COM-22, D-70)."""

from __future__ import annotations

import pytest

from .support import SCROLL_PAGE
from .test_comment_anchors import wait_marks
from .test_comment_panel import entries, filter_button, record, show_real
from .test_comment_replies import entry, sent_comments

pytestmark = pytest.mark.browser

MIXED = [record(1, "sent"), record(2, "done")]


def drawn(studio, numbers: set) -> None:  # noqa: ANN001
    wait_marks(studio, numbers)


def test_com_22_open_is_the_default_and_draws_no_marker_for_a_done_comment(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_real(studio, sid, MIXED)
    drawn(studio, {1})
    assert entries(studio).count() == 1


def test_com_22_done_shows_only_the_done_markers_and_all_shows_both(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_real(studio, sid, MIXED)
    filter_button(studio, "done").click()
    drawn(studio, {2})
    filter_button(studio, "all").click()
    drawn(studio, {1, 2})
    filter_button(studio, "open").click()
    drawn(studio, {1})


def test_com_22_switching_the_filter_needs_no_reload_and_keeps_the_counts(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_real(studio, sid, MIXED)
    filter_button(studio, "all").click()
    drawn(studio, {1, 2})
    assert [
        filter_button(studio, key).inner_text() for key in ("open", "done", "all")
    ] == ["Open 1", "Done 1", "All 2"]


def test_com_22_collapsing_the_panel_keeps_the_filter(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_real(studio, sid, MIXED)
    filter_button(studio, "all").click()
    studio.page.locator("#comment-panel .collapse").click()
    studio.page.wait_for_selector("#comment-panel.strip")
    drawn(studio, {1, 2})


def test_com_22_marking_done_removes_the_marker_at_once_and_reopening_restores_it(
    studio,
) -> None:  # noqa: ANN001
    sent_comments(studio)
    drawn(studio, {1, 2})
    entry(studio, 1).locator("button", has_text="Mark done").click()
    drawn(studio, {2})
    filter_button(studio, "done").click()
    drawn(studio, {1})
    entry(studio, 1).locator("button", has_text="Reopen").click()
    filter_button(studio, "open").click()
    drawn(studio, {1, 2})


def test_com_22_the_x_key_removes_the_marker_of_the_selected_comment(studio) -> None:  # noqa: ANN001
    sent_comments(studio)
    entry(studio, 2).click()
    studio.page.keyboard.press("x")
    drawn(studio, {1})
