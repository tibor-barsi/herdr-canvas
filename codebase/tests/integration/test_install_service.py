"""``install-service`` (OPS-02): unit text, files and systemctl calls.

Nothing here touches the real systemd: units go to a temporary directory and
``systemctl`` is a recording stand-in (injected runner, or a script first on
``PATH`` for the CLI runs).
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_canvas.service import (
    ServiceError,
    install_service,
    render_unit,
    resolve_executable,
)

pytestmark = pytest.mark.integration

EXECUTABLE = Path("/opt/tools/bin/agent-canvas")


class RecordingRunner:
    """Stand-in for running ``systemctl``; remembers the commands."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, command: list[str]) -> None:
        self.commands.append(command)
        if self.fail_on and self.fail_on in command:
            raise ServiceError(f"systemctl {self.fail_on} failed")


# ---- unit text --------------------------------------------------------------


def test_ops_02_unit_has_the_required_lines() -> None:
    lines = render_unit(EXECUTABLE).splitlines()
    assert f"ExecStart={EXECUTABLE} hub" in lines
    assert "Restart=always" in lines and "RestartSec=1" in lines  # M2
    assert "KillMode=process" in lines  # H1: a browser in the group survives
    assert lines.index("[Service]") < lines.index("[Install]")


def test_ops_02_unit_is_bound_to_the_graphical_session() -> None:
    text = render_unit(EXECUTABLE)
    unit, rest = text.split("[Service]")
    install = rest.split("[Install]")[1]
    assert "After=graphical-session.target" in unit.splitlines()
    assert "PartOf=graphical-session.target" in unit.splitlines()
    assert "WantedBy=graphical-session.target" in install.splitlines()
    assert "default.target" not in text


def test_ops_02_executable_must_be_absolute() -> None:
    with pytest.raises(ServiceError):
        render_unit(Path("agent-canvas"))


def test_ops_02_resolve_executable_prefers_the_path_lookup(tmp_path: Path) -> None:
    found = resolve_executable(lookup=lambda name: "/home/u/.local/bin/agent-canvas")
    assert found == Path("/home/u/.local/bin/agent-canvas")


def test_ops_02_resolve_executable_fails_when_nothing_is_found(tmp_path: Path) -> None:
    with pytest.raises(ServiceError, match="agent-canvas"):
        resolve_executable(lookup=lambda name: None, fallback_dir=tmp_path)


# ---- install_service ----------------------------------------------------------


def test_ops_02_writes_the_unit_then_reloads_and_enables(tmp_path: Path) -> None:
    runner = RecordingRunner()
    unit_dir = tmp_path / "systemd" / "user"
    result = install_service(
        unit_dir, EXECUTABLE, enable=True, runner=runner, probe=lambda c: False
    )
    unit = unit_dir / "agent-canvas.service"
    assert unit.read_text() == render_unit(EXECUTABLE)
    assert result == {"unit": str(unit), "enabled": True}
    assert runner.commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "agent-canvas"],
    ]


def test_ops_02_no_enable_writes_the_file_and_runs_nothing(tmp_path: Path) -> None:
    runner = RecordingRunner()
    result = install_service(tmp_path, EXECUTABLE, enable=False, runner=runner)
    assert result["enabled"] is False
    assert (tmp_path / "agent-canvas.service").is_file()
    assert runner.commands == []


def test_ops_02_a_failing_systemctl_is_an_error_but_the_unit_stays(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner(fail_on="enable")
    with pytest.raises(ServiceError, match="enable"):
        install_service(
            tmp_path, EXECUTABLE, enable=True, runner=runner, probe=lambda c: False
        )
    assert (tmp_path / "agent-canvas.service").is_file()


def test_ops_02_installing_twice_overwrites_the_unit(tmp_path: Path) -> None:
    (tmp_path / "agent-canvas.service").write_text("old")
    install_service(tmp_path, EXECUTABLE, enable=False, runner=RecordingRunner())
    assert (tmp_path / "agent-canvas.service").read_text() == render_unit(EXECUTABLE)


def test_ops_02_a_running_service_is_restarted_not_stopped_by_hand(
    tmp_path: Path,
) -> None:
    runner, stopped = RecordingRunner(), []
    install_service(
        tmp_path, EXECUTABLE, enable=True, runner=runner,
        probe=lambda command: "is-active" in command,
        stop_hub=lambda: stopped.append(True),
    )  # fmt: skip
    assert stopped == []
    assert runner.commands[-1] == ["systemctl", "--user", "restart", "agent-canvas"]


def test_ops_02_a_hand_started_hub_is_stopped_before_the_service_starts(
    tmp_path: Path,
) -> None:
    order: list[str] = []

    class Order(RecordingRunner):
        def __call__(self, command: list[str]) -> None:
            order.append(command[2])

    install_service(
        tmp_path, EXECUTABLE, enable=True, runner=Order(),
        probe=lambda command: False, stop_hub=lambda: order.append("stop-hub"),
    )  # fmt: skip
    assert order == ["daemon-reload", "stop-hub", "enable"]


def test_ops_02_a_venv_executable_gives_a_warning(tmp_path: Path) -> None:
    dev = Path("/work/codebase/.venv/bin/agent-canvas")
    result = install_service(tmp_path, dev, enable=False)
    assert ".venv" in str(result["warning"])
    assert "warning" not in install_service(tmp_path, EXECUTABLE, enable=False)


def test_ops_02_start_and_stop_use_systemd_only_with_an_installed_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_canvas import service

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    asked: list[list[str]] = []

    def yes(command: list[str]) -> bool:
        asked.append(command)
        return True

    assert service.start_enabled_service(yes) is False  # no unit file
    assert service.stop_service(yes) is False
    assert asked == []  # systemctl was never consulted
    (tmp_path / "systemd" / "user").mkdir(parents=True)
    (tmp_path / "systemd" / "user" / "agent-canvas.service").write_text("x")
    assert service.start_enabled_service(yes) is True
    assert asked[-1] == ["systemctl", "--user", "start", "agent-canvas"]
    assert service.stop_service(yes) is True
    assert asked[-1] == ["systemctl", "--user", "stop", "agent-canvas"]
    assert service.start_enabled_service(lambda c: "is-enabled" not in c) is False


# ---- the command ----------------------------------------------------------------


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, object]:
    """Fake HOME, XDG_CONFIG_HOME and a PATH holding only recording stand-ins."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "systemctl.log"
    # is-active says "inactive" (exit 3), so that install-service enables --now.
    (bin_dir / "systemctl").write_text(
        f'#!/bin/sh\necho "$@" >> "{log}"\ncase "$*" in *is-active*) exit 3;; esac\n'
    )
    (bin_dir / "agent-canvas").write_text("#!/bin/sh\nexit 0\n")
    for script in bin_dir.iterdir():
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    config_home = tmp_path / "xdg-config"
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(config_home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        # Never the default port: install-service looks for a hand-started hub.
        "AGENT_CANVAS_PORT": str(_free_port()),
        "AGENT_CANVAS_STATE_DIR": str(tmp_path / "state"),
        "AGENT_CANVAS_CONFIG_DIR": str(tmp_path / "config"),
    }
    return {
        "env": env,
        "log": log,
        "unit": config_home / "systemd" / "user" / "agent-canvas.service",
        "executable": bin_dir / "agent-canvas",
    }


def run(sandbox: dict[str, object], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_canvas.cli", "install-service", *args],
        env=sandbox["env"],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )


def test_ops_02_print_shows_the_unit_and_changes_nothing(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox, "--print")
    assert done.returncode == 0, done.stderr
    assert done.stdout == render_unit(sandbox["executable"])
    assert not sandbox["unit"].exists() and not sandbox["log"].exists()


def test_ops_02_command_writes_to_xdg_config_home_and_enables(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox)
    assert done.returncode == 0, done.stderr
    import json

    assert json.loads(done.stdout) == {"unit": str(sandbox["unit"]), "enabled": True}
    assert f"ExecStart={sandbox['executable']} hub" in sandbox["unit"].read_text()
    assert sandbox["log"].read_text().splitlines() == [
        "--user daemon-reload",
        "--user is-active --quiet agent-canvas",
        "--user enable --now agent-canvas",
    ]


def test_ops_02_command_no_enable(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox, "--no-enable")
    assert done.returncode == 0, done.stderr
    assert '"enabled": false' in done.stdout
    assert sandbox["unit"].is_file() and not sandbox["log"].exists()


def test_ops_02_command_defaults_to_home_config_without_xdg(sandbox) -> None:  # noqa: ANN001
    del sandbox["env"]["XDG_CONFIG_HOME"]
    done = run(sandbox, "--no-enable")
    expected = Path(sandbox["env"]["HOME"]) / ".config/systemd/user"
    assert done.returncode == 0, done.stderr
    assert (expected / "agent-canvas.service").is_file()


def test_ops_02_command_reports_a_failing_systemctl(sandbox) -> None:  # noqa: ANN001
    (sandbox["executable"].parent / "systemctl").write_text("#!/bin/sh\nexit 1\n")
    done = run(sandbox)
    assert done.returncode == 1 and '"error": "failed"' in done.stderr
    assert sandbox["unit"].is_file()
    assert os.access(sandbox["unit"], os.R_OK)


def test_ops_02_install_stops_a_hand_started_hub_first(hub, sandbox) -> None:  # noqa: ANN001
    sandbox["env"]["AGENT_CANVAS_PORT"] = str(hub.port)
    sandbox["env"]["AGENT_CANVAS_STATE_DIR"] = str(hub.state_dir)
    done = run(sandbox)
    assert done.returncode == 0, done.stderr
    hub.wait_for(lambda: hub.server.should_exit)
    hub.thread.join(timeout=10)
    assert not hub.thread.is_alive()
