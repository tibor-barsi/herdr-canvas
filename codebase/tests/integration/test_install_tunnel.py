"""``install-tunnel`` and ``uninstall-tunnel`` (OPS-07, OPS-08).

Nothing here touches the real systemd or the real ssh: units go to a temporary
directory, ``systemctl`` is an injected recorder (or a script first on ``PATH``
for the CLI runs) and ``ssh`` is a file that is never executed.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_canvas.service import ServiceError
from agent_canvas.tunnel import (
    TUNNEL_UNIT_NAME,
    agent_socket_setting,
    install_tunnel,
    local_hub_warnings,
    render_tunnel_unit,
    resolve_ssh,
    uninstall_tunnel,
)

pytestmark = pytest.mark.integration

SSH = Path("/usr/bin/ssh")
PORT = 27463


class RecordingRunner:
    """Stand-in for running ``systemctl``; remembers the commands."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, command: list[str]) -> None:
        self.commands.append(command)
        if self.fail_on and self.fail_on in command:
            raise ServiceError(f"systemctl {self.fail_on} failed")


def unit_lines(**kwargs: object) -> list[str]:
    arguments = {"ssh": SSH, "host": "work", "port": PORT, "auth_socket": None}
    return render_tunnel_unit(**{**arguments, **kwargs}).splitlines()  # type: ignore[arg-type]


# ---- unit text --------------------------------------------------------------


def test_ops_07_unit_runs_the_ssh_forward_with_the_required_options() -> None:
    expected = (
        f"ExecStart={SSH} -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 "
        "-o ServerAliveCountMax=3 -o BatchMode=yes -o GatewayPorts=no "
        f"-L {PORT}:127.0.0.1:{PORT} work"
    )
    assert expected in unit_lines()


def test_ops_07_unit_restarts_every_20_s_and_starts_at_login() -> None:
    lines = unit_lines()
    assert "Restart=always" in lines and "RestartSec=20" in lines
    assert "WantedBy=default.target" in lines
    assert lines.index("[Service]") < lines.index("[Install]")


def test_ops_07_forward_has_no_bind_address_so_both_loopbacks_are_used() -> None:
    # ssh binds 127.0.0.1 and ::1 when no bind address is given and
    # GatewayPorts is "no" (checked against a private sshd, see design.md);
    # a wildcard or a single address here would break localhost:<port>.
    forward = next(line for line in unit_lines() if line.startswith("ExecStart="))
    assert f" -L {PORT}:127.0.0.1:{PORT} " in forward
    assert "0.0.0.0" not in forward and "GatewayPorts=no" in forward


def test_ops_07_ssh_must_be_absolute() -> None:
    with pytest.raises(ServiceError, match="absolute"):
        render_tunnel_unit(Path("ssh"), "work", PORT, None)


@pytest.mark.parametrize(
    "host", ["", "-oProxyCommand=x", "a b", "work;x", "w%t", "a\nb", 'w"x']
)
def test_ops_07_unsafe_host_names_are_refused(host: str) -> None:
    with pytest.raises(ServiceError, match="host"):
        render_tunnel_unit(SSH, host, PORT, None)


@pytest.mark.parametrize("host", ["work", "me@work.example.org", "10.1.2.3", "fe80::1"])
def test_ops_07_ordinary_host_names_are_accepted(host: str) -> None:
    assert any(line.endswith(f" {host}") for line in unit_lines(host=host))


def test_ops_07_port_is_range_checked() -> None:
    for bad in (0, 65536):
        with pytest.raises(ServiceError, match="port"):
            render_tunnel_unit(SSH, "work", bad, None)


# ---- ssh-agent socket ---------------------------------------------------------


def test_ops_07_agent_socket_inside_the_runtime_dir_becomes_a_specifier() -> None:
    environ = {
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "SSH_AUTH_SOCK": "/run/user/1000/gcr/ssh",
    }
    assert agent_socket_setting(environ) == "%t/gcr/ssh"
    assert 'Environment="SSH_AUTH_SOCK=%t/gcr/ssh"' in unit_lines(
        auth_socket="%t/gcr/ssh"
    )


@pytest.mark.parametrize(
    "environ",
    [
        {"XDG_RUNTIME_DIR": "/run/user/1000"},  # no agent
        {"XDG_RUNTIME_DIR": "/run/user/1000", "SSH_AUTH_SOCK": "/tmp/ssh-x/agent.1"},
        {"XDG_RUNTIME_DIR": "/run/user/1000", "SSH_AUTH_SOCK": "/run/user/1000/../x"},
        {"XDG_RUNTIME_DIR": "/run/user/1000", "SSH_AUTH_SOCK": "/run/user/1000x/s"},
        {"XDG_RUNTIME_DIR": "/run/user/1000", "SSH_AUTH_SOCK": "/run/user/1000/a b"},
        {"XDG_RUNTIME_DIR": "/run/user/1000", "SSH_AUTH_SOCK": "/run/user/1000/a%b"},
        {"SSH_AUTH_SOCK": "/run/user/1000/gcr/ssh"},  # no runtime dir
        {"XDG_RUNTIME_DIR": "run/user", "SSH_AUTH_SOCK": "run/user/s"},
    ],
)
def test_ops_07_other_agent_sockets_are_not_put_into_the_unit(
    environ: dict[str, str],
) -> None:
    assert agent_socket_setting(environ) is None
    assert not any("SSH_AUTH_SOCK" in line for line in unit_lines())


# ---- resolve_ssh ----------------------------------------------------------------


def test_ops_07_resolve_ssh_returns_an_absolute_path() -> None:
    assert resolve_ssh(lookup=lambda name: "/usr/bin/ssh") == Path("/usr/bin/ssh")


def test_ops_07_resolve_ssh_fails_when_ssh_is_missing() -> None:
    with pytest.raises(ServiceError, match="ssh"):
        resolve_ssh(lookup=lambda name: None)


# ---- install_tunnel -------------------------------------------------------------


def test_ops_07_writes_the_unit_then_reloads_and_enables(tmp_path: Path) -> None:
    runner = RecordingRunner()
    unit_dir = tmp_path / "systemd" / "user"
    result = install_tunnel(
        unit_dir, SSH, "work", PORT, enable=True, auth_socket=None,
        runner=runner, probe=lambda c: False,
    )  # fmt: skip
    unit = unit_dir / TUNNEL_UNIT_NAME
    assert TUNNEL_UNIT_NAME == "agent-canvas-tunnel.service"
    assert unit.read_text() == render_tunnel_unit(SSH, "work", PORT, None)
    assert result == {"unit": str(unit), "enabled": True, "host": "work", "port": PORT}
    assert runner.commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "agent-canvas-tunnel"],
    ]


def test_ops_07_no_enable_writes_the_file_and_runs_nothing(tmp_path: Path) -> None:
    runner = RecordingRunner()
    result = install_tunnel(
        tmp_path, SSH, "work", PORT, enable=False, auth_socket=None, runner=runner
    )
    assert result["enabled"] is False
    assert (tmp_path / TUNNEL_UNIT_NAME).is_file() and runner.commands == []


def test_ops_07_a_running_tunnel_is_restarted_to_pick_up_the_new_unit(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    install_tunnel(
        tmp_path, SSH, "work", PORT, enable=True, auth_socket=None,
        runner=runner, probe=lambda command: "is-active" in command,
    )  # fmt: skip
    assert runner.commands[-2:] == [
        ["systemctl", "--user", "enable", "agent-canvas-tunnel"],
        ["systemctl", "--user", "restart", "agent-canvas-tunnel"],
    ]


def test_ops_07_a_failing_systemctl_is_an_error_but_the_unit_stays(
    tmp_path: Path,
) -> None:
    with pytest.raises(ServiceError, match="enable"):
        install_tunnel(
            tmp_path, SSH, "work", PORT, enable=True, auth_socket=None,
            runner=RecordingRunner(fail_on="enable"), probe=lambda c: False,
        )  # fmt: skip
    assert (tmp_path / TUNNEL_UNIT_NAME).is_file()


def test_ops_07_installing_twice_overwrites_the_unit(tmp_path: Path) -> None:
    (tmp_path / TUNNEL_UNIT_NAME).write_text("old")
    install_tunnel(
        tmp_path, SSH, "other", PORT, enable=False, auth_socket=None,
        runner=RecordingRunner(),
    )  # fmt: skip
    assert (
        (tmp_path / TUNNEL_UNIT_NAME)
        .read_text()
        .endswith(render_tunnel_unit(SSH, "other", PORT, None)[-80:])
    )
    assert "old" not in (tmp_path / TUNNEL_UNIT_NAME).read_text()


# ---- warnings about a local hub ---------------------------------------------------


def test_ops_07_no_warning_when_nothing_holds_the_port() -> None:
    assert (
        local_hub_warnings(PORT, probe=lambda c: False, hub_answers=lambda p: False)
        == []
    )


def test_ops_07_warns_when_the_local_hub_service_is_enabled() -> None:
    warnings = local_hub_warnings(
        PORT, probe=lambda c: "is-enabled" in c and "agent-canvas" in c,
        hub_answers=lambda p: False,
    )  # fmt: skip
    assert len(warnings) == 1 and "agent-canvas.service" in warnings[0]


def test_ops_07_warns_when_a_local_hub_answers_on_the_port() -> None:
    warnings = local_hub_warnings(
        PORT, probe=lambda c: False, hub_answers=lambda p: p == PORT
    )
    assert len(warnings) == 1 and str(PORT) in warnings[0]


def test_ops_07_an_active_tunnel_is_not_mistaken_for_a_local_hub() -> None:
    # On a reinstall the tunnel itself answers on the port (with the remote hub).
    def probe(command: list[str]) -> bool:
        return "is-active" in command and "agent-canvas-tunnel" in command

    assert local_hub_warnings(PORT, probe=probe, hub_answers=lambda p: True) == []


# ---- uninstall_tunnel -------------------------------------------------------------


def test_ops_08_uninstall_stops_disables_and_removes_the_unit(tmp_path: Path) -> None:
    (tmp_path / TUNNEL_UNIT_NAME).write_text("x")
    runner = RecordingRunner()
    result = uninstall_tunnel(tmp_path, runner=runner)
    assert result == {"unit": str(tmp_path / TUNNEL_UNIT_NAME), "removed": True}
    assert not (tmp_path / TUNNEL_UNIT_NAME).exists()
    assert runner.commands == [
        ["systemctl", "--user", "stop", "agent-canvas-tunnel"],
        ["systemctl", "--user", "disable", "agent-canvas-tunnel"],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_ops_08_uninstall_without_a_unit_does_nothing(tmp_path: Path) -> None:
    runner = RecordingRunner()
    result = uninstall_tunnel(tmp_path, runner=runner)
    assert result["removed"] is False and runner.commands == []


def test_ops_08_a_failing_stop_keeps_the_unit(tmp_path: Path) -> None:
    (tmp_path / TUNNEL_UNIT_NAME).write_text("x")
    with pytest.raises(ServiceError, match="stop"):
        uninstall_tunnel(tmp_path, runner=RecordingRunner(fail_on="stop"))
    assert (tmp_path / TUNNEL_UNIT_NAME).is_file()


# ---- the commands -----------------------------------------------------------------


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, object]:
    """Fake HOME, XDG dirs and a PATH holding only recording stand-ins."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "systemctl.log"
    # Every query says "no" (exit 3), so that nothing looks enabled or active.
    (bin_dir / "systemctl").write_text(
        f'#!/bin/sh\necho "$@" >> "{log}"\n'
        'case "$*" in *is-active*|*is-enabled*) exit 3;; esac\n'
    )
    (bin_dir / "ssh").write_text("#!/bin/sh\nexit 99\n")  # must never run
    for script in bin_dir.iterdir():
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    config_home = tmp_path / "xdg-config"
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "AGENT_CANVAS_PORT": str(_free_port()),
        "AGENT_CANVAS_STATE_DIR": str(tmp_path / "state"),
        "AGENT_CANVAS_CONFIG_DIR": str(tmp_path / "config"),
    }
    return {
        "env": env,
        "log": log,
        "unit": config_home / "systemd" / "user" / TUNNEL_UNIT_NAME,
        "ssh": bin_dir / "ssh",
    }


def run(
    sandbox: dict[str, object], *args: str, command: str = "install-tunnel"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_canvas.cli", command, *args],
        env=sandbox["env"], capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip


def test_ops_07_print_shows_the_unit_with_the_configured_port(sandbox) -> None:  # noqa: ANN001
    port = sandbox["env"]["AGENT_CANVAS_PORT"]
    done = run(sandbox, "work", "--print")
    assert done.returncode == 0, done.stderr
    assert done.stdout == render_tunnel_unit(sandbox["ssh"], "work", int(port), None)
    assert not sandbox["unit"].exists() and not sandbox["log"].exists()


def test_ops_07_port_option_overrides_the_configured_port(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox, "work", "--print", "--port", "31999")
    assert "-L 31999:127.0.0.1:31999 work" in done.stdout


def test_ops_07_command_passes_the_agent_socket_from_the_runtime_dir(sandbox) -> None:  # noqa: ANN001
    runtime = sandbox["env"]["XDG_RUNTIME_DIR"]
    sandbox["env"]["SSH_AUTH_SOCK"] = f"{runtime}/keyring/ssh"
    done = run(sandbox, "work", "--print")
    assert 'Environment="SSH_AUTH_SOCK=%t/keyring/ssh"' in done.stdout


def test_ops_07_command_leaves_other_agent_sockets_out(sandbox) -> None:  # noqa: ANN001
    sandbox["env"]["SSH_AUTH_SOCK"] = "/tmp/ssh-abc/agent.1"
    done = run(sandbox, "work", "--print")
    assert "SSH_AUTH_SOCK" not in done.stdout


def test_ops_07_command_writes_to_xdg_config_home_and_enables(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox, "work")
    assert done.returncode == 0, done.stderr
    port = int(sandbox["env"]["AGENT_CANVAS_PORT"])
    assert json.loads(done.stdout) == {
        "unit": str(sandbox["unit"]), "enabled": True, "host": "work", "port": port,
    }  # fmt: skip
    assert done.stderr == ""
    assert sandbox["log"].read_text().splitlines() == [
        "--user is-enabled --quiet agent-canvas",
        "--user is-active --quiet agent-canvas-tunnel",
        "--user daemon-reload",
        "--user is-active --quiet agent-canvas-tunnel",
        "--user enable --now agent-canvas-tunnel",
    ]


def test_ops_07_command_no_enable(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox, "work", "--no-enable")
    assert done.returncode == 0, done.stderr
    assert '"enabled": false' in done.stdout and sandbox["unit"].is_file()
    assert "daemon-reload" not in sandbox["log"].read_text()


def test_ops_07_command_needs_a_host(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox)
    assert done.returncode == 2 and '"error": "usage"' in done.stderr


def test_ops_07_command_refuses_an_option_like_host(sandbox) -> None:  # noqa: ANN001
    done = run(sandbox, "-oProxyCommand=x")
    assert done.returncode != 0 and not sandbox["unit"].exists()


def test_ops_07_command_fails_without_ssh_on_the_path(sandbox) -> None:  # noqa: ANN001
    sandbox["ssh"].unlink()
    sandbox["env"]["PATH"] = str(sandbox["ssh"].parent)
    done = run(sandbox, "work", "--print")
    assert done.returncode == 1 and '"error": "failed"' in done.stderr


def test_ops_07_command_warns_on_stderr_when_a_local_hub_holds_the_port(
    hub,
    sandbox,  # noqa: ANN001
) -> None:
    sandbox["env"]["AGENT_CANVAS_PORT"] = str(hub.port)
    done = run(sandbox, "work", "--no-enable")
    assert done.returncode == 0, done.stderr
    assert "warning" in done.stderr.lower() and str(hub.port) in done.stderr
    assert json.loads(done.stdout)["enabled"] is False  # stdout stays JSON only


def test_ops_08_uninstall_command(sandbox) -> None:  # noqa: ANN001
    run(sandbox, "work", "--no-enable")
    sandbox["log"].unlink(missing_ok=True)  # the install's own queries
    done = run(sandbox, command="uninstall-tunnel")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["removed"] is True and not sandbox["unit"].exists()
    assert sandbox["log"].read_text().splitlines() == [
        "--user stop agent-canvas-tunnel",
        "--user disable agent-canvas-tunnel",
        "--user daemon-reload",
    ]
