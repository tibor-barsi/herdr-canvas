"""The systemd user unit for the hub (OPS-02).

Standard library only; the command line imports this module on demand.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

UNIT_NAME = "agent-canvas.service"
SERVICE_NAME = "agent-canvas"
COMMAND_NAME = "agent-canvas"

Runner = Callable[[list[str]], None]
Probe = Callable[[list[str]], bool]


class ServiceError(Exception):
    """Installing the service failed; the message says why."""


def render_unit(executable: Path) -> str:
    """
    Return the text of the systemd user unit.

    Parameters
    ----------
    executable : pathlib.Path
        Absolute path of the ``agent-canvas`` command.

    Returns
    -------
    str
        Unit file content that runs ``<executable> hub`` and always restarts
        it after one second. It belongs to the graphical session, so that
        ``WAYLAND_DISPLAY`` exists when the hub opens the window, and it stops
        only its main process (``KillMode=process``) so that a browser left in
        its group survives a restart.

    Raises
    ------
    ServiceError
        If ``executable`` is not an absolute path.
    """
    if not executable.is_absolute():
        raise ServiceError(f"The command path must be absolute: {executable}")
    return (
        "[Unit]\n"
        "Description=agent-canvas hub\n"
        "After=graphical-session.target\n"
        "PartOf=graphical-session.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={executable} hub\n"
        # uvicorn exits cleanly on SIGTERM, which "on-failure" does not restart.
        "Restart=always\n"
        "RestartSec=1\n"
        "KillMode=process\n"
        "\n"
        "[Install]\n"
        "WantedBy=graphical-session.target\n"
    )


def resolve_executable(
    lookup: Callable[[str], str | None] = shutil.which,
    fallback_dir: Path | None = None,
) -> Path:
    """
    Find the absolute path of the ``agent-canvas`` command.

    Parameters
    ----------
    lookup : Callable[[str], str | None], optional
        Search on ``PATH``; default is :func:`shutil.which`.
    fallback_dir : pathlib.Path | None, optional
        Directory tried when ``PATH`` has no such command; default is the
        directory of the running Python (the tool's own environment).

    Returns
    -------
    pathlib.Path
        Absolute path of the command.

    Raises
    ------
    ServiceError
        If the command is nowhere to be found.
    """
    found = lookup(COMMAND_NAME)
    if found:
        return Path(os.path.abspath(found))
    directory = fallback_dir or Path(sys.executable).parent
    candidate = directory / COMMAND_NAME
    if candidate.is_file():
        return candidate.absolute()
    raise ServiceError(
        "Cannot find the agent-canvas command; install it with "
        "`uv tool install` so that it is on PATH."
    )


def unit_directory(environ: dict[str, str] | os._Environ[str] = os.environ) -> Path:
    """
    Return the systemd user unit directory.

    Parameters
    ----------
    environ : Mapping[str, str], optional
        Environment; ``XDG_CONFIG_HOME`` (if absolute) or ``~/.config`` is used.

    Returns
    -------
    pathlib.Path
        ``<config home>/systemd/user``.
    """
    configured = environ.get("XDG_CONFIG_HOME", "")
    base = Path(configured) if configured.startswith("/") else Path.home() / ".config"
    return base / "systemd" / "user"


def run_systemctl(command: list[str]) -> None:
    """
    Run one ``systemctl`` command.

    Parameters
    ----------
    command : list[str]
        Full command line.

    Raises
    ------
    ServiceError
        If systemctl is missing or exits with an error.
    """
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise ServiceError(f"Cannot run {' '.join(command)}: {error}") from error
    if done.returncode != 0:
        detail = done.stderr.strip() or f"exit code {done.returncode}"
        raise ServiceError(f"{' '.join(command)} failed: {detail}")


def run_probe(command: list[str]) -> bool:
    """
    Run a command and tell whether it exited with 0.

    Parameters
    ----------
    command : list[str]
        Full command line, for example ``systemctl --user is-active``.

    Returns
    -------
    bool
        False for a non-zero exit, a missing program or a timeout.
    """
    try:
        done = subprocess.run(command, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def systemctl(*arguments: str) -> list[str]:
    """Return the command line of ``systemctl --user <arguments>``."""
    return ["systemctl", "--user", *arguments]


def unit_installed(directory: Path | None = None) -> bool:
    """
    Tell whether the unit file exists (checked before any systemctl call).

    Parameters
    ----------
    directory : pathlib.Path | None, optional
        Unit directory; default is :func:`unit_directory`.

    Returns
    -------
    bool
        True if ``agent-canvas.service`` is in the directory.
    """
    return ((directory or unit_directory()) / UNIT_NAME).is_file()


def service_is_active(probe: Probe = run_probe) -> bool:
    """Tell whether the user service runs (``systemctl --user is-active``)."""
    return probe(systemctl("is-active", "--quiet", SERVICE_NAME))


def service_is_enabled(probe: Probe = run_probe) -> bool:
    """Tell whether the user service is enabled (``is-enabled``)."""
    return probe(systemctl("is-enabled", "--quiet", SERVICE_NAME))


def start_enabled_service(probe: Probe = run_probe) -> bool:
    """
    Start the hub through systemd if its unit is installed and enabled (M3).

    Returns
    -------
    bool
        True if ``systemctl --user start`` succeeded; False when there is no
        enabled unit (the caller then starts a detached process).
    """
    if not unit_installed() or not service_is_enabled(probe):
        return False
    return probe(systemctl("start", SERVICE_NAME))


def stop_service(probe: Probe = run_probe) -> bool:
    """
    Stop the hub through systemd if its unit is installed and active.

    A running service must be stopped this way: it restarts a hub that merely
    exits.

    Returns
    -------
    bool
        True if the service was active and ``systemctl --user stop`` worked.
    """
    if not unit_installed() or not service_is_active(probe):
        return False
    return probe(systemctl("stop", SERVICE_NAME))


def development_warning(executable: Path) -> str | None:
    """Return a warning when ``executable`` lies in a ``.venv`` (L6), else None."""
    if ".venv" not in executable.parts:
        return None
    return (
        f"{executable} is in a development environment (.venv); the service "
        "would run that checkout. Install with `uv tool install` and run "
        "install-service again."
    )


def install_service(
    directory: Path,
    executable: Path,
    *,
    enable: bool,
    runner: Runner = run_systemctl,
    probe: Probe = run_probe,
    stop_hub: Callable[[], None] | None = None,
) -> dict[str, object]:
    """
    Write the unit file and, unless ``enable`` is False, enable and start it.

    A service that already runs is restarted so that it picks up the new
    unit and program. Otherwise a hub somebody started by hand is stopped
    first (``stop_hub``), because it would hold the port.

    Parameters
    ----------
    directory : pathlib.Path
        Unit directory; created if missing.
    executable : pathlib.Path
        Absolute path of the ``agent-canvas`` command.
    enable : bool
        Run ``daemon-reload`` and ``enable --now`` after writing.
    runner : Callable[[list[str]], None], optional
        Runs a systemctl command; tests pass a recorder.
    probe : Callable[[list[str]], bool], optional
        Runs a query command and tells whether it exited with 0.
    stop_hub : Callable[[], None] | None, optional
        Stops a hub that is running outside the service.

    Returns
    -------
    dict[str, object]
        ``{"unit": <path>, "enabled": <bool>}`` (requirements 5.7), plus a
        ``warning`` text when the command lies in a ``.venv``.

    Raises
    ------
    ServiceError
        If a systemctl command fails; the unit file stays in place.
    """
    text = render_unit(executable)
    directory.mkdir(parents=True, exist_ok=True)
    unit = directory / UNIT_NAME
    unit.write_text(text)
    if enable:
        runner(systemctl("daemon-reload"))
        if service_is_active(probe):
            runner(systemctl("enable", SERVICE_NAME))
            runner(systemctl("restart", SERVICE_NAME))
        else:
            if stop_hub is not None:
                stop_hub()
            runner(systemctl("enable", "--now", SERVICE_NAME))
    result: dict[str, object] = {"unit": str(unit), "enabled": enable}
    if warning := development_warning(executable):
        result["warning"] = warning
    return result
