"""The start page code is gone from the shell (ARC-05)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src/agent_canvas/static"


def test_arc_05_the_start_page_code_is_gone_from_the_shell() -> None:
    names = ("homeGroups", "homeSession", "home-open", "home-closed", "Closed tabs")
    for file in ("shell.js", "shell.html"):
        text = (STATIC / file).read_text()
        assert [n for n in names if n in text] == [], file
