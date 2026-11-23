"""Page expiry vectors and the test clock (LIFE-02, LIFE-14)."""

from __future__ import annotations

import time

import pytest

from agent_canvas.config import ConfigError
from agent_canvas.hub import clock
from agent_canvas.hub.lifetime import DAY_SECONDS, expiry, is_expired

pytestmark = pytest.mark.unit

T = 1_800_000_000.0
D = DAY_SECONDS


def entry(kind: str, **fields: object) -> dict:
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


def test_life_02_single_use_answered_a_day_after_the_change_expires_at_t_plus_4_days():
    e = entry("single-use", answered=clock.iso(T + D))
    assert expiry(e, T) == pytest.approx(T + 4 * D, abs=0.001)


def test_life_02_answered_does_not_count_for_a_transitional_page():
    e = entry("transitional", answered=clock.iso(T + 20 * D))
    assert expiry(e, T) == pytest.approx(T + 30 * D, abs=0.001)


def test_life_02_extended_at_29_days_gives_59_days():
    e = entry("transitional", extended=clock.iso(T + 29 * D))
    assert expiry(e, T) == pytest.approx(T + 59 * D, abs=0.001)


def test_life_02_long_term_never_expires():
    e = entry("long-term", extended=clock.iso(T + D))
    assert expiry(e, T) is None
    assert not is_expired(e, T, T + 3650 * D)


def test_life_02_a_change_of_kind_does_not_restart_the_clock():
    e = entry("single-use")  # was transitional, changed at T, made single-use at T+10d
    assert is_expired(e, T, T + 10 * D)
    assert not is_expired(entry("transitional"), T, T + 10 * D)


def test_life_02_a_newer_version_restarts_the_clock():
    assert expiry(entry("transitional"), T + 5 * D) == pytest.approx(
        T + 35 * D, abs=0.001
    )


def test_life_02_expired_exactly_at_the_expiry_and_never_when_archived():
    e = entry("transitional")
    assert not is_expired(e, T, T + 30 * D - 1)
    assert is_expired(e, T, T + 30 * D)
    assert not is_expired(entry("transitional", archived=clock.iso(T)), T, T + 99 * D)


def test_life_14_offset_is_ignored_without_test_mode(monkeypatch):
    monkeypatch.delenv(clock.TEST_MODE, raising=False)
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(31 * D))
    assert abs(clock.now() - time.time()) < 5


def test_life_14_offset_shifts_the_clock_in_test_mode(monkeypatch):
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(31 * D))
    assert clock.now() - time.time() == pytest.approx(31 * D, abs=5)
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, "-60")
    assert clock.now() - time.time() == pytest.approx(-60, abs=5)


def test_life_14_unset_offset_leaves_the_clock_alone(monkeypatch):
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.delenv(clock.TEST_CLOCK_OFFSET, raising=False)
    assert abs(clock.now() - time.time()) < 5
    clock.check_environment()


def test_life_14_check_refuses_an_offset_without_test_mode_naming_it(monkeypatch):
    monkeypatch.delenv(clock.TEST_MODE, raising=False)
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, "5")
    with pytest.raises(ConfigError, match=clock.TEST_CLOCK_OFFSET):
        clock.check_environment()


def test_life_14_check_refuses_a_non_number(monkeypatch):
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, "soon")
    with pytest.raises(ConfigError, match=clock.TEST_CLOCK_OFFSET):
        clock.check_environment()
