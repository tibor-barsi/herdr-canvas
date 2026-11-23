"""KMAP-01, KMAP-02: the key map is the only place of shortcut keys; the key file is read safely."""

# ruff: noqa: E501

from __future__ import annotations

import re
from pathlib import Path

import pytest

import agent_canvas
from agent_canvas.config import load_keys, save_keys

pytestmark = pytest.mark.unit

STATIC = Path(agent_canvas.__file__).parent / "static"
MAP = "keymap.js"
# Keys that are no shortcuts (A-870): (file, key name) pairs; Enter, Space and Tab are free everywhere.
FREE = {"Enter", " ", "Tab"}
ALLOWED = {
    ("comments.js", "Escape"),
    ("files.js", "Escape"),
    ("shell.js", "Escape"),
    ("shell.js", "ArrowLeft"),
    ("shell.js", "ArrowRight"),
}
COMPARE = re.compile(r"""\b(?:\w+\.)?key\s*(?:===?|!==?)\s*(["'])(.*?)\1""")
NAMED = re.compile(r'"(Escape|ContextMenu|F10|Home|End|Arrow(?:Up|Down|Left|Right))"')
LOOKUP = re.compile(
    r"""\bswitch\s*\(\s*\w*\.?key\s*\)|\.includes\(\s*\w*\.?key\s*\)|\.includes\((?:key|lower)\)|\blower\s*===|"\[\]\?"|"tprlx\"|\bkey\.toLowerCase\(\)"""
)


def scripts(folder: Path = STATIC) -> list[Path]:
    """The shell and helper scripts, without the key map and the vendored libraries."""
    return [path for path in sorted(folder.glob("*.js")) if path.name != MAP]


def shortcut_literals(folder: Path = STATIC) -> list[str]:
    """Return ``file: line`` for each shortcut key written outside the map."""
    found = []
    for path in scripts(folder):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = re.sub(r"typeof [\w.]+", "", line)
            names = {m.group(2) for m in COMPARE.finditer(line)} | set(
                NAMED.findall(line)
            )
            bad = [n for n in names if n not in FREE and (path.name, n) not in ALLOWED]
            if bad or LOOKUP.search(line):
                found.append(f"{path.name}:{number}: {line.strip()}")
    return found


def test_kmap_01_no_shortcut_key_is_written_outside_the_map() -> None:
    assert len(scripts()) > 10
    assert shortcut_literals() == []


SYNTHETIC = [
    'if (key === "q") run();',
    'if (event.key == "ArrowUp") go();',
    "switch (e.key) { case 'q': run(); }",
    'if ("qz".includes(event.key)) run();',
    'if (["q", "z"].includes(key)) run();',
]


@pytest.mark.parametrize("line", SYNTHETIC)
def test_kmap_01_the_scan_sees_each_form_of_a_key_written_into_a_handler(
    tmp_path: Path, line: str
) -> None:
    """The scan fails when a shortcut literal comes back (a check that can fail)."""
    (tmp_path / "probe.js").write_text(line + '\nif (event.key === "Enter") ok();\n')
    assert len(shortcut_literals(tmp_path)) == 1


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENT_CANVAS_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_kmap_02_no_file_gives_the_herdr_profile_and_no_changes(
    config_dir: Path,
) -> None:
    answer = load_keys()
    assert (
        answer["profile"] == "herdr"
        and answer["keys"] == {}
        and answer["problems"] == []
    )
    assert [p["name"] for p in answer["profiles"]] == ["herdr", "vim"]
    assert answer["defaults"]["tab.next"][0] == "Ctrl+PageDown"


def test_kmap_02_the_file_gives_profile_and_changes(config_dir: Path) -> None:
    (config_dir / "keys.toml").write_text(
        'profile = "vim"\n[keys]\n"tab.next" = "n"\n"pane.next" = ["k", "ArrowUp"]\n'
    )
    answer = load_keys()
    assert answer["profile"] == "vim"
    assert answer["keys"] == {"tab.next": "n", "pane.next": ["k", "ArrowUp"]}
    assert "J" in answer["defaults"]["pane.go:down"]
    assert (
        answer["defaults"]["tab.next"][0] == "Ctrl+PageDown"
    )  # not named by vim: the herdr key


def test_kmap_02_a_broken_file_gives_a_problem_not_an_error(config_dir: Path) -> None:
    (config_dir / "keys.toml").write_text("[keys\nbroken")
    answer = load_keys()
    assert answer["keys"] == {} and answer["profile"] == "herdr"
    assert len(answer["problems"]) == 1


def test_kmap_02_a_file_over_64_kb_is_ignored_with_a_problem(config_dir: Path) -> None:
    (config_dir / "keys.toml").write_text(
        "# " + "x" * 70000 + '\n[keys]\n"tab.next" = "n"\n'
    )
    answer = load_keys()
    assert answer["keys"] == {} and answer["problems"] == [
        "the file is larger than 64 KB"
    ]


def test_kmap_02_wrong_types_are_reported(config_dir: Path) -> None:
    (config_dir / "keys.toml").write_text('profile = 3\nkeys = "x"\n')
    assert len(load_keys()["problems"]) == 2


def test_kmap_05_a_profile_file_in_the_keys_folder_is_selectable(
    config_dir: Path,
) -> None:
    (config_dir / "keys").mkdir()
    (config_dir / "keys" / "mine.toml").write_text(
        'description = "my keys"\n[keys]\n"tab.next" = ["n"]\n'
    )
    (config_dir / "keys.toml").write_text('profile = "mine"\n')
    answer = load_keys()
    assert answer["profile"] == "mine" and answer["problems"] == []
    assert answer["defaults"]["tab.next"] == ["n"]
    assert (
        answer["defaults"]["tab.prev"][0] == "Ctrl+PageUp"
    )  # not named: the herdr key
    mine = next(p for p in answer["profiles"] if p["name"] == "mine")
    assert mine == {"name": "mine", "description": "my keys", "shipped": False}


@pytest.mark.parametrize(
    "text",
    ["[keys\nbroken", 'keys = "x"\n', "description = 3\n", "# " + "x" * 70000],
)
def test_kmap_05_a_bad_profile_file_is_named_in_a_problem_and_left_out(
    config_dir: Path, text: str
) -> None:
    (config_dir / "keys").mkdir()
    (config_dir / "keys" / "bad.toml").write_text(text)
    answer = load_keys()
    assert len(answer["problems"]) == 1 and "bad.toml" in answer["problems"][0]
    assert [p["name"] for p in answer["profiles"]] == ["herdr", "vim"]
    assert answer["profile"] == "herdr"


def test_kmap_05_an_unknown_profile_falls_back_to_herdr_with_a_problem(
    config_dir: Path,
) -> None:
    (config_dir / "keys.toml").write_text('profile = "nope"\n')
    answer = load_keys()
    assert answer["profile"] == "herdr"
    assert answer["problems"] == ['profile "nope" is unknown']


def test_kmap_05_saving_writes_profile_and_changes_and_keeps_what_is_not_given(
    config_dir: Path,
) -> None:
    save_keys(keys={"tab.next": ["n", "Alt+x"], "tab.prev": []})
    assert load_keys()["keys"] == {"tab.next": ["n", "Alt+x"], "tab.prev": []}
    save_keys(profile="vim")
    answer = load_keys()
    assert answer["profile"] == "vim" and answer["keys"]["tab.next"] == ["n", "Alt+x"]
    assert answer["problems"] == []
    save_keys(keys={})
    assert load_keys()["keys"] == {} and load_keys()["profile"] == "vim"
