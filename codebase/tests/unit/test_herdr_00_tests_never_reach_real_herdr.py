"""Tests run inside the owner's herdr panes: no herdr variable may reach them."""

import os

import pytest

pytestmark = pytest.mark.unit


def test_no_herdr_variable_reaches_a_test() -> None:
    """Without them no hook event names a real pane, so no hub calls herdr."""
    assert [n for n in os.environ if n.startswith("HERDR_")] == []
