"""How the window command is started outside the hub's service group (HUB-06)."""

from __future__ import annotations

import pytest

from agent_canvas.hub.window import launch_candidates

pytestmark = pytest.mark.unit

COMMAND = ["chromium", "--app=http://127.0.0.1:1/login?t=x"]


def fake_which(*present: str):  # noqa: ANN201
    return lambda name: f"/usr/bin/{name}" if name in present else None


def test_hub_06_auto_prefers_systemd_run_and_keeps_a_plain_fallback() -> None:
    found = launch_candidates(COMMAND, "auto", fake_which("systemd-run", "uwsm"))
    assert found == [
        ["/usr/bin/systemd-run", "--user", "--collect", "--quiet", "--", *COMMAND],
        COMMAND,
    ]


def test_hub_06_auto_uses_uwsm_when_systemd_run_is_missing() -> None:
    found = launch_candidates(COMMAND, "auto", fake_which("uwsm"))
    assert found == [["/usr/bin/uwsm", "app", "--", *COMMAND], COMMAND]


def test_hub_06_auto_without_either_launches_directly() -> None:
    assert launch_candidates(COMMAND, "auto", fake_which()) == [COMMAND]


def test_hub_06_explicit_choice_and_none() -> None:
    both = fake_which("systemd-run", "uwsm")
    assert launch_candidates(COMMAND, "uwsm", both)[0][1:3] == ["app", "--"]
    assert launch_candidates(COMMAND, "none", both) == [COMMAND]
    assert launch_candidates(COMMAND, "uwsm", fake_which("systemd-run")) == [COMMAND]


@pytest.mark.parametrize("program", ["systemd-run", "/usr/bin/uwsm"])
def test_hub_06_a_command_that_already_wraps_is_left_alone(program: str) -> None:
    own = [program, "app", "--", "chromium"]
    assert launch_candidates(own, "auto", fake_which("systemd-run", "uwsm")) == [own]
