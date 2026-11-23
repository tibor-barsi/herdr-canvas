"""The hub's wall clock, shiftable in test mode only (LIFE-14, A-78)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

TEST_MODE = "AGENT_CANVAS_TEST_MODE"
TEST_CLOCK_OFFSET = "AGENT_CANVAS_TEST_CLOCK_OFFSET"


def check_environment() -> None:
    """
    Refuse an offset without test mode (LIFE-14).

    Raises
    ------
    agent_canvas.config.ConfigError
        If the offset is set and test mode is not ``1``, or it is not a number.
    """
    from agent_canvas.config import ConfigError  # keeps the CLI's imports light

    text = os.environ.get(TEST_CLOCK_OFFSET)
    if not text:
        return
    if os.environ.get(TEST_MODE) != "1":
        raise ConfigError(f"{TEST_CLOCK_OFFSET} is only allowed with {TEST_MODE}=1")
    try:
        float(text)
    except ValueError as error:
        raise ConfigError(f"{TEST_CLOCK_OFFSET} must be a number of seconds") from error


def now() -> float:
    """Return the POSIX time, shifted by the test offset when test mode is on."""
    text = os.environ.get(TEST_CLOCK_OFFSET)
    shift = float(text) if text and os.environ.get(TEST_MODE) == "1" else 0.0
    return time.time() + shift


def iso(seconds: float) -> str:
    """Return POSIX ``seconds`` as ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    stamp = datetime.fromtimestamp(seconds, UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"


def seconds_of(stamp: str) -> float:
    """Return the POSIX time of an ``iso`` stamp."""
    return (
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        .replace(tzinfo=UTC)
        .timestamp()
    )
