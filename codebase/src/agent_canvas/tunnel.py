"""The systemd user unit that tunnels the hub port over SSH (OPS-07, OPS-08).

For a hub that runs on another machine: the unit keeps ``ssh -L`` open on this
machine, with the same port number at both ends, because the hub accepts only
the Host headers ``127.0.0.1:<port>`` and ``localhost:<port>``.

Standard library only; the command line imports this module on demand.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from agent_canvas.service import (
    SERVICE_NAME,
    Probe,
    Runner,
    ServiceError,
    run_probe,
    run_systemctl,
    systemctl,
)

TUNNEL_NAME = "agent-canvas-tunnel"
TUNNEL_UNIT_NAME = f"{TUNNEL_NAME}.service"

# No leading "-" (ssh would read it as an option); no "%" (systemd specifier),
# whitespace, quotes or shell characters. Covers user@host, aliases, IPv4/IPv6.
_HOST_PATTERN = re.compile(r"[A-Za-z0-9_.@:][A-Za-z0-9_.@:-]*")
_SOCKET_PATTERN = re.compile(r"[A-Za-z0-9_./@:+=,-]+")


def render_tunnel_unit(ssh: Path, host: str, port: int, auth_socket: str | None) -> str:
    """
    Return the text of the SSH tunnel unit.

    Parameters
    ----------
    ssh : pathlib.Path
        Absolute path of the ``ssh`` program.
    host : str
        Host name or alias as ``ssh`` understands it (``user@host`` is fine).
    port : int
        Port used at both ends of the forward.
    auth_socket : str | None
        Value for ``SSH_AUTH_SOCK`` as a systemd path (``%t/...``), or None
        to leave the variable out; see :func:`agent_socket_setting`.

    Returns
    -------
    str
        Unit file content. The forward is ``-L <port>:127.0.0.1:<port>`` with
        no bind address: with ``GatewayPorts=no`` (set explicitly, so that a
        user-wide ``GatewayPorts yes`` cannot expose the port) ssh then listens
        on both ``127.0.0.1`` and ``::1``, so that ``localhost:<port>`` works
        whichever address the browser tries first. ``BatchMode`` makes ssh fail
        instead of asking for a password; the unit restarts it every 20 s.

    Raises
    ------
    ServiceError
        If ``ssh`` is not absolute, ``host`` is empty or has characters that
        could be read as an option or a systemd specifier, or ``port`` is not
        in 1-65535.
    """
    if not ssh.is_absolute():
        raise ServiceError(f"The ssh path must be absolute: {ssh}")
    if not _HOST_PATTERN.fullmatch(host):
        raise ServiceError(f"Not a usable ssh host name: {host!r}")
    if not 1 <= port <= 65535:
        raise ServiceError(f"The port must be between 1 and 65535, got {port}")
    environment = f'Environment="SSH_AUTH_SOCK={auth_socket}"\n' if auth_socket else ""
    return (
        "[Unit]\n"
        f"Description=agent-canvas hub tunnel to {host}\n"
        "\n"
        "[Service]\n"
        f"{environment}"
        f"ExecStart={ssh} -N -o ExitOnForwardFailure=yes "
        "-o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o BatchMode=yes "
        f"-o GatewayPorts=no -L {port}:127.0.0.1:{port} {host}\n"
        # Off the home network ssh fails at once; retry quietly.
        "Restart=always\n"
        "RestartSec=20\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def agent_socket_setting(environ: Mapping[str, str]) -> str | None:
    """
    Decide whether the ssh-agent socket can be handed to the unit.

    A systemd user service does not see the login shell's ``SSH_AUTH_SOCK``,
    yet a key with a passphrase needs the agent under ``BatchMode``. The
    socket is passed on only when it lies inside ``$XDG_RUNTIME_DIR`` (where
    gnome-keyring and the systemd ``ssh-agent`` user unit put it), because a
    path there is stable across logins and expressible as ``%t/...``.

    Parameters
    ----------
    environ : Mapping[str, str]
        Environment of the installing shell.

    Returns
    -------
    str | None
        ``%t/<path below the runtime dir>``, or None when there is no agent,
        it lies elsewhere (for example ``/tmp/ssh-XXXX/agent.N``, which changes
        at each login) or the path has characters that need quoting.
    """
    socket = environ.get("SSH_AUTH_SOCK", "")
    runtime = environ.get("XDG_RUNTIME_DIR", "")
    if not socket.startswith("/") or not runtime.startswith("/"):
        return None
    if ".." in Path(socket).parts or not _SOCKET_PATTERN.fullmatch(socket):
        return None
    prefix = runtime.rstrip("/") + "/"
    if not socket.startswith(prefix) or len(socket) == len(prefix):
        return None
    return f"%t/{socket[len(prefix) :]}"


def resolve_ssh(lookup: Callable[[str], str | None] = shutil.which) -> Path:
    """
    Find the absolute path of ``ssh``.

    Parameters
    ----------
    lookup : Callable[[str], str | None], optional
        Search on ``PATH``; default is :func:`shutil.which`.

    Returns
    -------
    pathlib.Path
        Absolute path of the program.

    Raises
    ------
    ServiceError
        If ``ssh`` is not installed.
    """
    found = lookup("ssh")
    if not found:
        raise ServiceError("Cannot find ssh on PATH; install the OpenSSH client.")
    return Path(os.path.abspath(found))


def hub_answers(port: int) -> bool:
    """
    Tell whether an agent-canvas hub answers ``/health`` on ``127.0.0.1:port``.

    Parameters
    ----------
    port : int
        TCP port.

    Returns
    -------
    bool
        False on a refused connection, a timeout or a foreign answer.
    """
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        connection.close()
    is_hub = isinstance(data, dict) and data.get("app") == "agent-canvas"
    return response.status == 200 and is_hub


def local_hub_warnings(
    port: int,
    probe: Probe = run_probe,
    hub_answers: Callable[[int], bool] = hub_answers,
) -> list[str]:
    """
    Name the local hubs that would hold the tunnel's port.

    Parameters
    ----------
    port : int
        Port of the tunnel.
    probe : Callable[[list[str]], bool], optional
        Runs a query command and tells whether it exited with 0.
    hub_answers : Callable[[int], bool], optional
        Tells whether a hub answers on the port.

    Returns
    -------
    list[str]
        Zero to two warnings. An active tunnel service is not looked at as a
        hub: on a reinstall it is what answers on the port.
    """
    warnings = []
    if probe(systemctl("is-enabled", "--quiet", SERVICE_NAME)):
        warnings.append(
            "The local hub service agent-canvas.service is enabled. It starts "
            f"a hub on port {port} that blocks the tunnel; run "
            "`systemctl --user disable --now agent-canvas` or give the local "
            "hub another port."
        )
    tunnel_running = probe(systemctl("is-active", "--quiet", TUNNEL_NAME))
    if not tunnel_running and hub_answers(port):
        warnings.append(
            f"A local hub answers on port {port}, so the tunnel cannot listen "
            "there; stop it with `agent-canvas stop`."
        )
    return warnings


def install_tunnel(
    directory: Path,
    ssh: Path,
    host: str,
    port: int,
    *,
    enable: bool,
    auth_socket: str | None,
    runner: Runner = run_systemctl,
    probe: Probe = run_probe,
) -> dict[str, object]:
    """
    Write the tunnel unit and, unless ``enable`` is False, enable and start it.

    A tunnel that already runs is restarted so that it picks up the new unit.

    Parameters
    ----------
    directory : pathlib.Path
        Unit directory; created if missing.
    ssh : pathlib.Path
        Absolute path of ``ssh``.
    host : str
        Host name or alias of the hub machine.
    port : int
        Port at both ends.
    enable : bool
        Run ``daemon-reload`` and ``enable --now`` after writing.
    auth_socket : str | None
        See :func:`render_tunnel_unit`.
    runner : Callable[[list[str]], None], optional
        Runs a systemctl command; tests pass a recorder.
    probe : Callable[[list[str]], bool], optional
        Runs a query command and tells whether it exited with 0.

    Returns
    -------
    dict[str, object]
        ``{"unit": <path>, "enabled": <bool>, "host": <host>, "port": <port>}``.

    Raises
    ------
    ServiceError
        If the arguments are unusable or a systemctl command fails; a written
        unit file stays in place.
    """
    text = render_tunnel_unit(ssh, host, port, auth_socket)
    directory.mkdir(parents=True, exist_ok=True)
    unit = directory / TUNNEL_UNIT_NAME
    unit.write_text(text)
    if enable:
        runner(systemctl("daemon-reload"))
        if probe(systemctl("is-active", "--quiet", TUNNEL_NAME)):
            runner(systemctl("enable", TUNNEL_NAME))
            runner(systemctl("restart", TUNNEL_NAME))
        else:
            runner(systemctl("enable", "--now", TUNNEL_NAME))
    return {"unit": str(unit), "enabled": enable, "host": host, "port": port}


def uninstall_tunnel(
    directory: Path, *, runner: Runner = run_systemctl
) -> dict[str, object]:
    """
    Stop and disable the tunnel service and remove its unit file.

    Parameters
    ----------
    directory : pathlib.Path
        Unit directory.
    runner : Callable[[list[str]], None], optional
        Runs a systemctl command; tests pass a recorder.

    Returns
    -------
    dict[str, object]
        ``{"unit": <path>, "removed": <bool>}``; ``removed`` is False, and
        systemctl is not called, when no unit file exists.

    Raises
    ------
    ServiceError
        If ``stop`` or ``disable`` fails; the unit file then stays.
    """
    unit = directory / TUNNEL_UNIT_NAME
    if not unit.is_file():
        return {"unit": str(unit), "removed": False}
    runner(systemctl("stop", TUNNEL_NAME))
    runner(systemctl("disable", TUNNEL_NAME))
    unit.unlink()
    runner(systemctl("daemon-reload"))
    return {"unit": str(unit), "removed": True}
