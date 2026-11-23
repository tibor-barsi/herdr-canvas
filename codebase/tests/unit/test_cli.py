"""Tests for the console entry point."""

from __future__ import annotations

import pytest

from agent_canvas.cli import main

pytestmark = pytest.mark.unit


def test_ops_01_help_prints_usage_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "usage: agent-canvas" in capsys.readouterr().out


def test_ops_01_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "agent-canvas" in capsys.readouterr().out


@pytest.mark.parametrize(("minutes", "asked", "used"), [(30, 99999, 1800), (1, 61, 60)])
def test_cli_07_a_timeout_above_the_limit_is_cut_to_the_limit(
    monkeypatch: pytest.MonkeyPatch, minutes: int, asked: int, used: int
) -> None:
    import types

    import agent_canvas.cli as cli
    import agent_canvas.config as config
    import agent_canvas.watch as watch

    seen: list[float] = []
    monkeypatch.setattr(
        config, "load_config", lambda: types.SimpleNamespace(watch_max_minutes=minutes)
    )
    monkeypatch.setattr(
        cli, "_client", lambda: types.SimpleNamespace(open_watch=lambda *a, **k: None)
    )
    monkeypatch.setattr(
        watch, "run_watch", lambda _s, timeout, *_: seen.append(timeout) or 0
    )
    assert main(["watch", "--session", "a", "--timeout", str(asked)]) == 0
    assert seen == [used]
