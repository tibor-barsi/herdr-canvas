"""Tests for config loading (HUB-02) and directory resolution (5.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_canvas.config import Config, ConfigError, load_config
from agent_canvas.paths import config_dir, config_file, state_dir

pytestmark = pytest.mark.unit


def write_config(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_hub_02_defaults(clean_env: Path) -> None:
    assert load_config() == Config(
        port=27463,
        window_command="chromium --app={url}",
        open_window=True,
        watch_max_minutes=30,
        ask_timeout_seconds=540,
        project_dir_name=".agent-canvas",
        window_wrapper="auto",
        show_audit=True,
    )


def test_hub_02_file_values(clean_env: Path) -> None:
    write_config(
        config_dir(),
        "port = 9000\nopen_window = false\nwatch_max_minutes = 5\n"
        'ask_timeout_seconds = 60\nwindow_command = "firefox {url}"\n',
    )
    config = load_config()
    assert config == Config(9000, "firefox {url}", False, 5, 60)


def test_hub_02_partial_file_keeps_other_defaults(clean_env: Path) -> None:
    write_config(config_dir(), "port = 9001\n")
    config = load_config()
    assert config.port == 9001
    assert config.ask_timeout_seconds == 540


def test_hub_02_env_over_file(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(config_dir(), 'port = 9000\nwindow_command = "from-file {url}"\n')
    monkeypatch.setenv("AGENT_CANVAS_PORT", "9100")
    monkeypatch.setenv("AGENT_CANVAS_WINDOW_COMMAND", "from-env {url}")
    config = load_config()
    assert config.port == 9100
    assert config.window_command == "from-env {url}"


def test_hub_02_config_dir_env_selects_file(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = tmp_path / "other-config"
    write_config(other, "port = 9200\n")
    monkeypatch.setenv("AGENT_CANVAS_CONFIG_DIR", str(other))
    assert load_config().port == 9200
    assert config_file() == other / "config.toml"


def test_hub_02_invalid_toml_names_the_file(clean_env: Path) -> None:
    path = write_config(config_dir(), "port = = 3\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config()
    assert str(path) in str(excinfo.value)


@pytest.mark.parametrize(
    "text",
    [
        'port = "high"\n',
        "port = 0\n",
        "port = 70000\n",
        "open_window = 1\n",
        "unknown_key = 1\n",
        "watch_max_minutes = -1\n",
        "project_dir_name = 3\n",
        'project_dir_name = ""\n',
        'project_dir_name = "/abs/canvas"\n',
        'project_dir_name = "../canvas"\n',
        'project_dir_name = "a/../b"\n',
        'project_dir_name = "."\n',
        'project_dir_name = "a//b"\n',
        'project_dir_name = "a/"\n',
        'project_dir_name = "a/b/c/d"\n',
        'project_dir_name = "a\\\\b"\n',
    ],
)
def test_hub_02_invalid_values_name_the_file(clean_env: Path, text: str) -> None:
    path = write_config(config_dir(), text)
    with pytest.raises(ConfigError) as excinfo:
        load_config()
    assert str(path) in str(excinfo.value)


def test_hub_02_project_dir_name_file_override(clean_env: Path) -> None:
    write_config(config_dir(), 'project_dir_name = "tools/canvas"\n')
    assert load_config().project_dir_name == "tools/canvas"


def test_hub_02_project_dir_name_error_names_the_key(clean_env: Path) -> None:
    write_config(config_dir(), 'project_dir_name = "../x"\n')
    with pytest.raises(ConfigError, match="project_dir_name"):
        load_config()


def test_hub_02_invalid_env_port_is_reported(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_CANVAS_PORT", "abc")
    with pytest.raises(ConfigError, match="AGENT_CANVAS_PORT"):
        load_config()


def test_hub_02_directories_follow_xdg(clean_env: Path) -> None:
    assert config_dir() == clean_env / "xdg-config" / "agent-canvas"
    assert state_dir() == clean_env / "xdg-state" / "agent-canvas"


def test_hub_02_directories_fall_back_to_home(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.delenv("XDG_STATE_HOME")
    assert config_dir() == clean_env / ".config" / "agent-canvas"
    assert state_dir() == clean_env / ".local" / "state" / "agent-canvas"


def test_hub_02_state_dir_env_override(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENT_CANVAS_STATE_DIR", str(tmp_path / "state"))
    assert state_dir() == tmp_path / "state"


def test_hub_06_window_wrapper_accepts_known_values_only(clean_env: Path) -> None:
    write_config(config_dir(), 'window_wrapper = "uwsm"\n')
    assert load_config().window_wrapper == "uwsm"
    write_config(config_dir(), 'window_wrapper = "bogus"\n')
    with pytest.raises(ConfigError, match="window_wrapper"):
        load_config()


def test_chk_15_show_audit_can_be_switched_off_by_file_or_environment(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert load_config().show_audit is True
    write_config(config_dir(), "show_audit = false\n")
    assert load_config().show_audit is False
    monkeypatch.setenv("AGENT_CANVAS_SHOW_AUDIT", "1")
    assert load_config().show_audit is True
    monkeypatch.setenv("AGENT_CANVAS_SHOW_AUDIT", "maybe")
    with pytest.raises(ConfigError, match="AGENT_CANVAS_SHOW_AUDIT"):
        load_config()

