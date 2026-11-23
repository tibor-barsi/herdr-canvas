"""Resolve the configuration and state directories (requirements 5.1).

Environment overrides take precedence over the XDG base directories, which in
turn fall back to their specification defaults under the home directory.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "agent-canvas"


def _xdg_dir(variable: str, default_relative: str) -> Path:
    """Return an XDG base directory, honouring only non-empty absolute values."""
    value = os.environ.get(variable, "")
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / default_relative


def config_dir() -> Path:
    """
    Return the directory holding ``config.toml``.

    Returns
    -------
    pathlib.Path
        ``$AGENT_CANVAS_CONFIG_DIR`` if set, otherwise
        ``$XDG_CONFIG_HOME/agent-canvas`` (default ``~/.config/agent-canvas``).
    """
    override = os.environ.get("AGENT_CANVAS_CONFIG_DIR")
    if override:
        return Path(override)
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / APP_DIR_NAME


def state_dir() -> Path:
    """
    Return the directory holding the access key, registry and hub log.

    Returns
    -------
    pathlib.Path
        ``$AGENT_CANVAS_STATE_DIR`` if set, otherwise
        ``$XDG_STATE_HOME/agent-canvas`` (default
        ``~/.local/state/agent-canvas``). The directory is not created here.
    """
    override = os.environ.get("AGENT_CANVAS_STATE_DIR")
    if override:
        return Path(override)
    return _xdg_dir("XDG_STATE_HOME", ".local/state") / APP_DIR_NAME


def config_file() -> Path:
    """
    Return the path of the optional ``config.toml``.

    Returns
    -------
    pathlib.Path
        ``config_dir() / "config.toml"``; the file may not exist.
    """
    return config_dir() / "config.toml"


def keys_file() -> Path:
    """
    Return the path of the optional ``keys.toml`` (the owner's keyboard shortcuts).

    Returns
    -------
    pathlib.Path
        ``config_dir() / "keys.toml"``; the file may not exist.
    """
    return config_dir() / "keys.toml"


def keys_dir() -> Path:
    """
    Return the folder of the user's key profiles.

    Returns
    -------
    pathlib.Path
        ``config_dir() / "keys"``; a ``<name>.toml`` copied in is a selectable profile.
    """
    return config_dir() / "keys"


def make_private_dirs(folder: Path) -> None:
    """
    Create ``folder`` and its missing parents with mode 0700 (SEC-12).

    Folders that already exist keep their mode.

    Parameters
    ----------
    folder : pathlib.Path
        The folder to create.
    """
    if folder.is_dir():
        return
    make_private_dirs(folder.parent)
    folder.mkdir(mode=0o700, exist_ok=True)
