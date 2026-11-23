"""Age strings of ``cleanup --older-than`` (CLI-11)."""

from __future__ import annotations

import pytest

from agent_canvas.hub.cleanup import CleanupError, parse_age

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("30s", 30), ("5m", 300), ("12h", 43200), ("30d", 2592000), ("2w", 1209600)],
)
def test_cli_11_parse_age_units(text: str, seconds: int) -> None:
    assert parse_age(text) == seconds


@pytest.mark.parametrize("text", ["", "d", "30", "1.5d", "0d", "-1d", "3 d", "3y"])
def test_cli_11_parse_age_rejects_bad_text(text: str) -> None:
    with pytest.raises(CleanupError):
        parse_age(text)
