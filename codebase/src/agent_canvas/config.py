"""Hub configuration: defaults, ``config.toml`` and environment overrides.

Precedence, lowest to highest: built-in defaults, ``config.toml``,
``AGENT_CANVAS_*`` environment variables (requirement HUB-02).
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from agent_canvas.files_safe import write_safely
from agent_canvas.paths import config_file, keys_dir, keys_file

DEFAULT_PROJECT_DIR_NAME = ".agent-canvas"
MAX_PROJECT_DIR_SEGMENTS = 3
MAX_KEYS_FILE_BYTES = 64 * 1024
DEFAULT_PROFILE = "herdr"
SHIPPED_PROFILES = Path(__file__).parent / "keyprofiles"
WINDOW_WRAPPERS = ("auto", "systemd-run", "uwsm", "none")


class ConfigError(Exception):
    """Raised when the configuration file or environment is invalid."""


@dataclass(frozen=True)
class Config:
    """
    Settings of the hub and its clients.

    Attributes
    ----------
    port : int
        TCP port of the hub on 127.0.0.1.
    window_command : str
        Command template that opens the canvas window; ``{url}`` is replaced.
    open_window : bool
        Whether ``show`` opens a window automatically.
    watch_max_minutes : int
        Upper bound for one ``watch`` call, in minutes.
    ask_timeout_seconds : int
        Default time an ``ask`` waits for an answer, in seconds.
    project_dir_name : str
        Per-project session folder, relative to the project root (HUB-07).
        Claude Code refuses tool writes below ``.claude/``, so the default is
        ``.agent-canvas``; at most 3 segments, no ``..``, not absolute.
    window_wrapper : str
        How the window command is started outside the hub's service group:
        ``auto`` (``systemd-run --user``, else ``uwsm app``, else directly),
        ``systemd-run``, ``uwsm`` or ``none`` (HUB-06).
    show_audit : bool
        Whether ``show`` runs the automatic page checks (CHK-15); env
        ``AGENT_CANVAS_SHOW_AUDIT`` (``0``, ``false`` or ``no`` turn it off).
    herdr_command : str
        The ``herdr`` executable that opens an agent's pane (HERDR-02).
    follow_state : str
        Beside mode: state folder of another hub whose ``sessions.json`` is
        followed read-only; also turns the purge of archived pages off. Env
        ``AGENT_CANVAS_FOLLOW_STATE``; empty means off.
    """

    port: int = 27463
    window_command: str = "chromium --app={url}"
    open_window: bool = True
    watch_max_minutes: int = 30
    ask_timeout_seconds: int = 540
    project_dir_name: str = DEFAULT_PROJECT_DIR_NAME
    window_wrapper: str = "auto"
    show_audit: bool = True
    herdr_command: str = "herdr"
    follow_state: str = ""


def load_config() -> Config:
    """
    Load the configuration from defaults, the config file and the environment.

    Returns
    -------
    Config
        The effective configuration.

    Raises
    ------
    ConfigError
        If the config file is not valid TOML, contains an unknown key or a
        value of the wrong type or range (the message names the file), or if
        an environment override is invalid (the message names the variable).
    """
    config = Config()
    path = config_file()
    if path.is_file():
        config = replace(config, **_read_file_values(path))
    return _apply_environment(config)


def _read_file_values(path: Path) -> dict[str, Any]:
    """Parse and validate ``path``; return the keys it sets."""
    try:
        with path.open("rb") as handle:
            values = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"Invalid TOML in config file {path}: {error}") from error
    except OSError as error:
        raise ConfigError(f"Cannot read config file {path}: {error}") from error
    defaults = {field.name: getattr(Config(), field.name) for field in fields(Config)}
    for key, value in values.items():
        problem = _value_problem(key, value, defaults)
        if problem:
            raise ConfigError(f"Invalid config file {path}: {problem}")
    return values


def _value_problem(key: str, value: Any, defaults: dict[str, Any]) -> str | None:
    """Return a description of what is wrong with ``key = value``, or None."""
    if key not in defaults:
        return f"unknown key '{key}'"
    expected = type(defaults[key])
    # bool is a subclass of int, so the exact type must match.
    if type(value) is not expected:
        return f"'{key}' must be of type {expected.__name__}"
    if key == "project_dir_name":
        return _project_dir_name_problem(value)
    if key == "window_wrapper" and value not in WINDOW_WRAPPERS:
        return f"'window_wrapper' must be one of {', '.join(WINDOW_WRAPPERS)}"
    if key == "port" and not 1 <= value <= 65535:
        return "'port' must be between 1 and 65535"
    if expected is int and key != "port" and value <= 0:
        return f"'{key}' must be positive"
    return None


def _project_dir_name_problem(value: str) -> str | None:
    """Return why ``value`` is not a usable ``project_dir_name``, or None."""
    segments = value.split("/")
    if value.startswith("/") or "\\" in value or "\0" in value:
        return "'project_dir_name' must be a relative path without backslash or NUL"
    if any(part in ("", ".", "..") for part in segments):
        return "'project_dir_name' must not have empty, '.' or '..' segments"
    if len(segments) > MAX_PROJECT_DIR_SEGMENTS:
        return f"'project_dir_name' has more than {MAX_PROJECT_DIR_SEGMENTS} segments"
    return None


def _apply_environment(config: Config) -> Config:
    """Apply the ``AGENT_CANVAS_*`` environment overrides."""
    port_text = os.environ.get("AGENT_CANVAS_PORT")
    if port_text:
        try:
            port = int(port_text)
        except ValueError as error:
            raise ConfigError(
                f"AGENT_CANVAS_PORT must be an integer, got '{port_text}'"
            ) from error
        if not 1 <= port <= 65535:
            raise ConfigError(f"AGENT_CANVAS_PORT out of range: {port}")
        config = replace(config, port=port)
    command = os.environ.get("AGENT_CANVAS_WINDOW_COMMAND")
    if command:
        config = replace(config, window_command=command)
    follow = os.environ.get("AGENT_CANVAS_FOLLOW_STATE")
    if follow:
        config = replace(config, follow_state=follow)
    audit = os.environ.get("AGENT_CANVAS_SHOW_AUDIT")
    if audit:
        config = replace(config, show_audit=_audit_switch(audit))
    return config


def _audit_switch(text: str, name: str = "AGENT_CANVAS_SHOW_AUDIT") -> bool:
    """Parse the 0/1 environment switch ``name``."""
    lowered = text.strip().lower()
    if lowered in ("0", "false", "no", "off"):
        return False
    if lowered in ("1", "true", "yes", "on"):
        return True
    raise ConfigError(f"{name} must be 0 or 1, got '{text}'")


def _read_keys_toml(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read a key file; a file that cannot be read gives ``{}`` and a message."""
    if not path.is_file():
        return {}, []
    try:
        if path.stat().st_size > MAX_KEYS_FILE_BYTES:
            return {}, ["the file is larger than 64 KB"]
        return tomllib.loads(path.read_text(encoding="utf-8")), []
    except (OSError, ValueError) as error:
        return {}, [str(error)]


def _profiles() -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read the shipped profiles and the keys folder; a user file wins a name."""
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for folder, shipped in ((SHIPPED_PROFILES, True), (keys_dir(), False)):
        for path in sorted(folder.glob("*.toml")):
            values, errors = _read_keys_toml(path)
            keys, description = values.get("keys", {}), values.get("description", "")
            if not errors and not isinstance(keys, dict):
                errors = ["[keys] must be a table"]
            if not errors and not isinstance(description, str):
                errors = ["description must be a string"]
            problems += [f"profile {path.name}: {error}" for error in errors]
            if not errors:
                found[path.stem] = {
                    "name": path.stem,
                    "description": description,
                    "shipped": shipped,
                    "keys": keys,
                }
    return found, problems


def load_keys() -> dict[str, Any]:
    """
    Read the key profiles and the owner's ``keys.toml`` for the window (KMAP-02).

    The window checks the action names and the keys; this only reads the files.
    A file that cannot be read gives no keys and a message, never an error.

    Returns
    -------
    dict
        ``profile`` (the chosen name), ``profiles`` (name, description and
        ``shipped`` of each), ``defaults`` (keys of the chosen profile; actions it
        does not name keep the ``herdr`` profile's keys), ``keys`` (the owner's
        own changes in ``keys.toml``) and ``problems`` (messages to show).
    """
    found, problems = _profiles()
    values, errors = _read_keys_toml(keys_file())
    problems += errors
    profile, keys = values.get("profile", DEFAULT_PROFILE), values.get("keys", {})
    if not isinstance(profile, str):
        problems.append("profile must be a string")
        profile = DEFAULT_PROFILE
    if not isinstance(keys, dict):
        problems.append("[keys] must be a table")
        keys = {}
    if profile not in found:
        problems.append(f'profile "{profile}" is unknown')
        profile = DEFAULT_PROFILE
    base = found.get(DEFAULT_PROFILE, {}).get("keys", {})
    defaults = {**base, **found.get(profile, {}).get("keys", {})}
    listed = [
        {k: v for k, v in found[name].items() if k != "keys"}
        for name in sorted(found, key=lambda n: (n != DEFAULT_PROFILE, n))
    ]
    return {
        "profile": profile,
        "profiles": listed,
        "defaults": defaults,
        "keys": keys,
        "problems": problems,
    }


def _quoted(text: str) -> str:
    return json.dumps(text)


def save_keys(
    profile: str | None = None, keys: dict[str, list[str]] | None = None
) -> None:
    """
    Write the owner's ``keys.toml``: the chosen profile and the owner's own changes.

    A shipped profile is never edited; the owner's changes live in this file.
    What is not given is kept from the file as it is now.

    Parameters
    ----------
    profile : str, optional
        Name of the profile to choose.
    keys : dict, optional
        Action name to its list of keys; replaces all the owner's changes.
    """
    current = load_keys()
    profile = current["profile"] if profile is None else profile
    changes = current["keys"] if keys is None else keys
    lines = [
        "# Written by the key overview (?). The profile is chosen there; [keys] holds",
        "# your own changes on top of it (an action with [] has no key).",
        f"profile = {_quoted(profile)}",
        "",
        "[keys]",
    ]
    for action, value in sorted(changes.items()):
        listed = value if isinstance(value, list) else [value]
        lines.append(f"{_quoted(action)} = [{', '.join(_quoted(k) for k in listed)}]")
    keys_file().parent.mkdir(parents=True, exist_ok=True)
    write_safely(keys_file(), "\n".join(lines) + "\n")
