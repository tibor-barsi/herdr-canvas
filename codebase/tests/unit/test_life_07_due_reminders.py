"""Which expired pages are named in a reminder (LIFE-07)."""

from __future__ import annotations

import pytest

from agent_canvas.hub import clock
from agent_canvas.hub.lifetime import DAY_SECONDS, REMIND_SECONDS, due_reminders

pytestmark = pytest.mark.unit

T = 1_800_000_000.0
D = DAY_SECONDS


def entry(kind: str = "single-use", **fields: object) -> dict:
    base = {
        "kind": kind,
        "set_by": "agent",
        "counted_from": clock.iso(T),
        "extended": None,
        "answered": None,
        "reminded": None,
        "archived": None,
    }
    return {**base, **fields}


def due(now: float, **fields: object) -> list[dict]:
    return due_reminders([("plot.html", entry(**fields), T)], now)


def test_life_07_a_page_is_named_at_its_expiry_with_kind_and_expiry_time() -> None:
    assert due(T + 3 * D) == [
        {"page": "plot.html", "kind": "single-use", "expired": clock.iso(T + 3 * D)}
    ]


def test_life_07_a_page_before_its_expiry_is_not_named() -> None:
    assert due(T + 3 * D - 1) == []


def test_life_07_a_page_named_less_than_24_hours_ago_is_not_named_again() -> None:
    stamp = clock.iso(T + 4 * D)
    assert due(T + 4 * D + 24 * 3600 - 60, reminded=stamp) == []


def test_life_07_a_page_named_24_hours_ago_is_named_again() -> None:
    stamp = clock.iso(T + 4 * D)
    assert len(due(T + 4 * D + REMIND_SECONDS, reminded=stamp)) == 1
    assert REMIND_SECONDS == 24 * 3600


def test_life_07_an_archived_page_is_not_named() -> None:
    assert due(T + 9 * D, archived=clock.iso(T + 5 * D)) == []


def test_life_07_a_long_term_page_is_never_named() -> None:
    assert due(T + 900 * D, kind="long-term") == []


def test_life_07_the_pages_keep_their_order() -> None:
    pages = [(n, entry(), T) for n in ("b.html", "a.html")]
    assert [r["page"] for r in due_reminders(pages, T + 9 * D)] == ["b.html", "a.html"]
