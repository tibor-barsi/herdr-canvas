"""Opening the owner's window (HUB-06, ``open`` command).

The hub runs the configured ``window_command`` when ``show`` or ``ask`` arrives
and no shell is connected. The command line is split with :mod:`shlex` and run
without a shell; ``{url}`` becomes a one-time login URL, in one argument. The
default command, ``chromium --app={url}``, leaves Chromium's own process
isolation untouched (PAGE-10 relies on site-per-process, the desktop default).

The window must outlive the hub: when the hub runs as a systemd service, a
browser started inside the service's control group dies with every restart of
the hub. So the command is started outside it, through ``systemd-run --user``
(or ``uwsm app``) when one is installed; the window then also gets the current
session environment (``WAYLAND_DISPLAY``) instead of the hub's (HUB-06).
"""

from __future__ import annotations

import asyncio
import shlex
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from agent_canvas.config import Config
from agent_canvas.hub.state import HubState

LAUNCH_INTERVAL_SECONDS = 10.0
# A command that fails to start (missing program, bad flags) exits at once;
# a window that stays up is still running after this grace period.
EXIT_GRACE_SECONDS = 0.3


def _which(name: str) -> str | None:
    """Find a program on ``PATH`` (tests replace this to stay off systemd)."""
    return shutil.which(name)


def launch_candidates(
    arguments: list[str],
    wrapper: str,
    which: Callable[[str], str | None] = _which,
) -> list[list[str]]:
    """
    Return the command lines to try, best first, to open the window (HUB-06).

    Parameters
    ----------
    arguments : list[str]
        The configured ``window_command``, split and with ``{url}`` filled in.
    wrapper : str
        Config ``window_wrapper``: ``auto`` (use ``systemd-run`` if found, else
        ``uwsm``), ``systemd-run``, ``uwsm`` or ``none``.
    which : Callable[[str], str | None], optional
        Program lookup; tests inject a fake one.

    Returns
    -------
    list[list[str]]
        The wrapped command (outside the hub's cgroup) when a wrapper applies,
        then always the plain command as a fallback.
    """
    program = Path(arguments[0]).name if arguments else ""
    if wrapper == "none" or program in ("systemd-run", "uwsm"):
        return [arguments]
    prefixes = {
        "systemd-run": ["--user", "--collect", "--quiet", "--"],
        "uwsm": ["app", "--"],
    }
    order = ["systemd-run", "uwsm"] if wrapper == "auto" else [wrapper]
    for name in order:
        if found := which(name):
            return [[found, *prefixes[name], *arguments], arguments]
    return [arguments]


class WindowLauncher:
    """
    Launch the owner window on demand, at most once per 10 s.

    Parameters
    ----------
    config : Config
        Effective configuration (``window_command``, ``open_window``).
    state : HubState
        Hub state: tells whether a shell is connected and mints login tokens.
    clock : Callable[[], float]
        Monotonic clock (tests inject a fake one).
    """

    def __init__(
        self, config: Config, state: HubState, clock: Callable[[], float]
    ) -> None:
        self._config = config
        self._state = state
        self._clock = clock
        self._last_launch: float | None = None
        self._last_status = "launch-failed"
        self._lock = asyncio.Lock()

    @property
    def launching(self) -> bool:
        """True while a window was launched but no shell has connected yet."""
        return not self._state.shells and self._last_status == "launched"

    async def ensure(self, *, force: bool = False) -> str:
        """
        Make sure a window is open or on its way.

        Parameters
        ----------
        force : bool, optional
            Ignore the 10 s limit (used by the explicit ``open`` command).

        Returns
        -------
        str
            ``connected`` (a shell is connected), ``launched``,
            ``launch-failed`` or ``disabled`` (``open_window = false``).
        """
        if self._state.shells:
            return "connected"
        if not self._config.open_window:
            return "disabled"
        async with self._lock:
            if self._state.shells:
                return "connected"
            recent = (
                self._last_launch is not None
                and self._clock() - self._last_launch < LAUNCH_INTERVAL_SECONDS
            )
            if recent and not force:
                return self._last_status
            self._last_launch = self._clock()
            self._last_status = await self._run()
            return self._last_status

    def login_url(self) -> str:
        """
        Issue a fresh single-use login URL (valid for 60 s).

        Returns
        -------
        str
            ``http://127.0.0.1:<port>/login?t=<token>``.
        """
        token = self._state.new_login_token()
        return f"http://127.0.0.1:{self._state.port}/login?t={token}"

    async def _run(self) -> str:
        """Run the window command once; return ``launched`` or ``launch-failed``."""
        url = self.login_url()
        try:
            arguments = [
                part.replace("{url}", url)
                for part in shlex.split(self._config.window_command)
            ]
            candidates = launch_candidates(
                arguments, self._config.window_wrapper, _which
            )
        except (ValueError, IndexError, TypeError):
            return "launch-failed"
        for candidate in candidates:
            if await self._start(candidate):
                return "launched"
        return "launch-failed"

    @staticmethod
    async def _start(arguments: list[str]) -> bool:
        """Start one command line detached; True if it runs or exited cleanly."""
        try:
            process = subprocess.Popen(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (ValueError, OSError):
            return False
        try:
            code = await asyncio.to_thread(process.wait, EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # Still running: a window. Reap it whenever it ends.
            threading.Thread(target=process.wait, daemon=True).start()
            return True
        return code == 0
