"""The Herdr desktop app as the hub sees it: spaces, tabs, panes and their sessions."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

CALL_TIMEOUT = 2.0
DEFAULT_COLOR = "ansi6"
COLORS = {
    "ansi1": "#d9649a",
    "ansi2": "#3fae6a",
    "ansi3": "#e3814f",
    "ansi4": "#5b8def",
    "ansi5": "#8b7cf6",
    "ansi6": "#22a99a",
}
FOCUS_KEYS = {"space": "space", "tab": "tab", "pane": "focused_pane"}


def _tree(node: Any, prefix: str = "") -> dict[str, Any] | None:
    """Reduce a core layout node to ``{pane, weight}`` leaves and ``{dir, weight, children}``."""
    if not isinstance(node, dict):
        return None
    weight = (node.get("size") or {}).get("weight", 1)
    if node.get("type") == "block":
        return {"pane": prefix + node["id"], "weight": weight}
    if node.get("type") not in ("row", "column"):
        return None
    children = [_tree(c, prefix) for c in node.get("children", [])]
    if not children or None in children:
        return None
    return {"dir": node["type"], "weight": weight, "children": children}


def _leaves(tree: dict[str, Any]) -> list[str]:
    if "pane" in tree:
        return [tree["pane"]]
    return [p for c in tree["children"] for p in _leaves(c)]


class HerdrApp:
    """
    Reads the Herdr app's state and focuses its panes.

    Commands and folders are parameters so that tests use fake scripts and
    temporary folders.

    Parameters
    ----------
    app : str
        The window's command (``herdr-app``).
    core : str
        The core's command (``hc``).
    config_dir : pathlib.Path
        Herdr's config folder (``view.json``, ``shared.json``).
    docs_path : pathlib.Path
        The core's ``docs.json``, which holds each tab's split tree.
    sessions_dir : pathlib.Path
        Claude Code's ``sessions`` folder.
    proc_dir : pathlib.Path
        Where a live process has a folder named by its pid.
    known_sessions : Callable[[], list[str]]
        The canvas sessions the hub knows.
    """

    def __init__(
        self,
        app: str = "herdr-app",
        core: str = "hc",
        config_dir: Path = Path.home() / ".config" / "herdr-app",
        docs_path: Path = Path.home() / ".local/state/herdr-core/default/docs.json",
        sessions_dir: Path = Path.home() / ".claude" / "sessions",
        proc_dir: Path = Path("/proc"),
        known_sessions: Callable[[], list[str]] = list,
    ) -> None:
        self.app = app
        self.core = core
        self.config_dir = config_dir
        self.docs_path = docs_path
        self.sessions_dir = sessions_dir
        self.proc_dir = proc_dir
        self.known_sessions = known_sessions
        self.last: dict[str, Any] = {
            "available": False,
            "focus": None,
            "spaces": [],
            "other": [],
        }  # the snapshot the windows were last sent
        self._pids: dict[str, int] = {}  # terminal -> pid of its foreground program
        self._homes: dict[str, str] = {}  # machine -> its home folder
        self._remote: dict[
            str, tuple[int, str | None]
        ] = {}  # terminal -> (pid, session)

    def snapshot(self) -> dict[str, Any]:
        """Return the ``herdr`` view; ``available`` is false if Herdr is silent."""
        try:
            tree = self._json([self.app, "ls"])
            status = self._json([self.app, "status"])
        except (OSError, subprocess.SubprocessError, ValueError):
            known = self.known_sessions()
            return {"available": False, "focus": None, "spaces": [], "other": known}
        view = self._read(self.config_dir / "view.json").get("tabs", {})
        colors = self._read(self.config_dir / "shared.json").get("space.colors", {})
        roots = self._roots(self._read(self.docs_path))
        machines = self._machines()
        online = {m["name"] for m in machines if m["state"] == "online"}
        remote_roots: dict[str, Any] = {}
        paired: set[str] = set()
        spaces = []
        for space in tree.get("spaces", []):
            machine = space.get("machine")
            if machine in online and machine not in remote_roots:
                remote_roots[machine] = self._remote_roots(machine)
            tabs = []
            for tab in space.get("tabs", []):
                focused = view.get(tab["id"], {}).get("focused")
                panes = []
                for t in tab.get("terminals", []):
                    if machine is None:
                        session = self._session(t["terminal"], t.get("app"))
                    elif machine in online:
                        session = self._remote_session(
                            machine, t["terminal"], t.get("app")
                        )
                    else:
                        session = None
                    if session:
                        paired.add(session)
                    panes.append(
                        {
                            "pane": t["pane"],
                            "terminal": t["terminal"],
                            "name": t.get("name") or t.get("app") or t["terminal"],
                            "status": t.get("status"),
                            "app": t.get("app"),
                            "focused": t["pane"] == focused,
                            "session": session,
                        }
                    )
                entry = {
                    "id": tab["id"],
                    "name": tab.get("name"),
                    "active": bool(tab.get("active")),
                    "panes": panes,
                }
                node = roots if machine is None else remote_roots.get(machine, {})
                split = _tree(
                    node.get(tab["id"]), "" if machine is None else f"{machine}/"
                )
                if split and set(_leaves(split)) == {p["pane"] for p in panes}:
                    entry["tree"] = split
                tabs.append(entry)
            token = colors.get(space["id"], DEFAULT_COLOR)
            spaces.append(
                {
                    "id": space["id"],
                    "machine": machine,
                    "name": space.get("name"),
                    "color": COLORS.get(token, COLORS[DEFAULT_COLOR]),
                    "active": bool(space.get("active")),
                    "tabs": tabs,
                }
            )
        return {
            "available": True,
            "focus": {key: status.get(name) for key, name in FOCUS_KEYS.items()},
            "spaces": spaces,
            "machines": machines,
            "other": [s for s in self.known_sessions() if s not in paired],
        }

    def paired(self) -> set[str]:
        """Return the sessions the panes of the last snapshot hold."""
        return {
            pane["session"]
            for space in self.last["spaces"]
            for tab in space["tabs"]
            for pane in tab["panes"]
            if pane["session"]
        }

    def poll(self) -> bool:
        """Read the snapshot into ``last``; True when it changed."""
        current = self.snapshot()
        changed = current != self.last
        self.last = current
        return changed

    def focus(self, snapshot: dict[str, Any], key: str, value: str) -> bool:
        """
        Show a space and tab and focus a pane in Herdr.

        A tab resolves to its focused pane, a space to its active tab's.

        Parameters
        ----------
        snapshot : dict
            A current ``herdr`` snapshot.
        key : str
            ``"terminal"``, ``"tab"`` or ``"space"``.
        value : str
            The terminal address, tab id or space id.

        Returns
        -------
        bool
            False when the snapshot has no such target or it has no pane.
        """
        for space in snapshot["spaces"]:
            for tab in space["tabs"]:
                if key == "space" and not (space["id"] == value and tab["active"]):
                    continue
                if key == "tab" and tab["id"] != value:
                    continue
                for pane in tab["panes"]:
                    if key == "terminal" and pane["terminal"] != value:
                        continue
                    if key == "terminal" or pane["focused"]:
                        self._show(space["id"], tab["id"], pane["pane"])
                        return True
        return False

    def _show(self, space: str, tab: str, pane: str) -> None:
        # The doc does not say that pane.focus also selects its space and tab.
        for name, args in (
            ("space.select", {"id": space}),
            ("tab.select", {"id": tab}),
            ("pane.focus", {"pane": pane}),
        ):
            self._run([self.app, "do", name, json.dumps(args)])

    def _session(self, terminal: str, app: str | None) -> str | None:
        if not app:
            return None
        pid = self._pids.get(terminal)
        if pid is None or not (self.proc_dir / str(pid)).exists():
            self._pids.pop(terminal, None)
            try:
                pid = self._json([self.core, "get", terminal, "--json"])["foreground"][
                    "pid"
                ]
            except (
                OSError,
                subprocess.SubprocessError,
                ValueError,
                KeyError,
                TypeError,
            ):
                return None
            if not (self.proc_dir / str(pid)).exists():
                return None
            self._pids[terminal] = pid
        return self._read(self.sessions_dir / f"{pid}.json").get("sessionId")

    @staticmethod
    def _roots(docs: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Return the split root of every tab of a ``docs.json``, by prefixed tab id."""
        spaces = docs.get("herdr-app", {}).get("value", {})
        return {
            prefix + t["id"]: t.get("root")
            for s in spaces.get("spaces", [])
            for t in s.get("tabs", [])
        }

    def _machines(self) -> list[dict[str, Any]]:
        """Return the non-temporary Herdr machines, online when Herdr says connected."""
        try:
            listed = self._json([self.core, "machine", "ls", "--json"])["machines"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return []
        return [
            {
                "name": m["name"],
                "state": "online" if m.get("state") == "connected" else "offline",
                "detail": None,
                "other": [],
            }
            for m in sorted(listed, key=lambda m: m["name"])
            if not m.get("temporary")
        ]

    def _home(self, machine: str) -> str | None:
        if machine not in self._homes:
            try:
                home = self._run(
                    [self.core, "exec", "--on", machine, "printenv", "HOME"]
                )
            except (OSError, subprocess.SubprocessError):
                return None
            self._homes[machine] = home.strip()
        return self._homes[machine]

    def _remote_file(self, machine: str, path: str) -> dict[str, Any]:
        try:
            data = self._json([self.core, "file", "read", "--on", machine, path])
        except (OSError, subprocess.SubprocessError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _remote_roots(self, machine: str) -> dict[str, Any]:
        home = self._home(machine)
        if not home:
            return {}
        docs = self._remote_file(
            machine, f"{home}/.local/state/herdr-core/default/docs.json"
        )
        return self._roots(docs, f"{machine}/")

    def _remote_session(
        self, machine: str, terminal: str, app: str | None
    ) -> str | None:
        """Pair a remote terminal; the pid the core reports is current, so only a new pid reads the file."""
        if not app:
            return None
        try:
            pid = self._json([self.core, "get", terminal, "--json"])["foreground"][
                "pid"
            ]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return None
        if self._remote.get(terminal, (None,))[0] != pid:
            home = self._home(machine)
            if not home:
                return None
            data = self._remote_file(machine, f"{home}/.claude/sessions/{pid}.json")
            self._remote[terminal] = (pid, data.get("sessionId"))
        return self._remote[terminal][1]

    def _run(self, argv: list[str]) -> str:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=CALL_TIMEOUT, check=True
        ).stdout

    def _json(self, argv: list[str]) -> dict[str, Any]:
        return json.loads(self._run(argv))

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}
