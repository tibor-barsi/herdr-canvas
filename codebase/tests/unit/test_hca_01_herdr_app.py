"""The Herdr app reader and its focus route (HCA-01), on recorded outputs."""

from __future__ import annotations

import asyncio
import json
import shutil
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_canvas.hub.herdr_app import HerdrApp
from agent_canvas.hub.herdr_app import _tree as herdr_tree
from agent_canvas.hub.routes import herdr as route

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).with_name("herdr_app_fixtures")
APP = """#!/bin/sh
cd "$(dirname "$0")"
case "$1" in
  ls|status) cat "$1.json" ;;
  do) echo "$2 $3" >> do.log ;;
esac
"""
CORE = """#!/bin/sh
cd "$(dirname "$0")"
echo "$@" >> hc.log
case "$1" in
  get) cat "hc_get_$(echo "$2" | tr / _).json" ;;
  machine) cat machines.json ;;
  exec) echo /remote/home ;;
  file) cat "remote$(echo "$5" | tr / _)" ;;
esac
"""


@pytest.fixture
def herdr(tmp_path: Path) -> HerdrApp:
    """A reader on fake commands, config, sessions and process folders."""
    bin_dir = tmp_path / "bin"
    shutil.copytree(FIXTURES, bin_dir)
    for name, text in (("herdr-app", APP), ("hc", CORE)):
        script = bin_dir / name
        script.write_text(text)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    config = tmp_path / "config"
    config.mkdir()
    (config / "view.json").write_text(
        json.dumps({"tabs": {"tb1": {"focused": "p2"}, "tb2": {"focused": "p3"}}})
    )
    (config / "shared.json").write_text(
        json.dumps({"space.colors": {"sp1": "ansi3", "sp2": "ansi9"}})
    )
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "4242.json").write_text(json.dumps({"sessionId": "sess-a"}))
    (tmp_path / "proc" / "4242").mkdir(parents=True)
    (bin_dir / "machines.json").write_text(json.dumps({"machines": []}))
    return HerdrApp(
        app=str(bin_dir / "herdr-app"),
        core=str(bin_dir / "hc"),
        config_dir=config,
        docs_path=bin_dir / "docs.json",
        sessions_dir=sessions,
        proc_dir=tmp_path / "proc",
        known_sessions=lambda: ["sess-a", "sess-b"],
    )


def test_hca_01_snapshot_follows_herdr_order_focus_and_colors(herdr: HerdrApp) -> None:
    """Spaces, tabs and panes come in Herdr's order with focus, colour and session."""
    snap = herdr.snapshot()
    assert snap["available"] is True
    assert snap["focus"] == {"space": "sp1", "tab": "tb1", "pane": "p1"}
    assert [s["id"] for s in snap["spaces"]] == ["sp1", "sp2"]
    assert [s["color"] for s in snap["spaces"]] == ["#e3814f", "#22a99a"]
    tab = snap["spaces"][0]["tabs"][0]
    tab.pop("tree")
    assert tab == {
        "id": "tb1",
        "name": "1",
        "active": True,
        "panes": [
            {
                "pane": "p1",
                "terminal": "t2",
                "name": "claude-code",
                "status": "working",
                "app": "claude-code",
                "focused": False,
                "session": "sess-a",
            },
            {
                "pane": "p2",
                "terminal": "t3",
                "name": "shell",
                "status": "idle",
                "app": None,
                "focused": True,
                "session": None,
            },
        ],
    }


def test_hca_01_tab_carries_its_split_tree(herdr: HerdrApp) -> None:
    """A tab gets its row/column tree; a tree naming other panes is left out."""
    tabs = herdr.snapshot()["spaces"][0]["tabs"]
    assert tabs[0]["tree"] == {
        "dir": "row",
        "weight": 1,
        "children": [
            {"pane": "p1", "weight": 1.0},
            {
                "dir": "column",
                "weight": 2.0,
                "children": [{"pane": "p2", "weight": 3.0}],
            },
        ],
    }
    assert "tree" not in tabs[1]


def test_hca_01_real_single_pane_document(herdr: HerdrApp) -> None:
    """The real core document of a one-pane tab reduces to one leaf."""
    root = json.loads((FIXTURES / "docs_real.json").read_text())["herdr-app"]["value"]
    tree = herdr_tree(root["spaces"][0]["tabs"][0]["root"])
    assert tree == {
        "dir": "row",
        "weight": 1,
        "children": [{"pane": "p76234a8347b52258276f561daa3f85ed", "weight": 1.0}],
    }


def test_hca_01_other_holds_unpaired_sessions(herdr: HerdrApp) -> None:
    """A terminal whose core lookup fails has no session; unpaired ones are in other."""
    snap = herdr.snapshot()
    assert snap["spaces"][0]["tabs"][1]["panes"][0]["session"] is None
    assert snap["other"] == ["sess-b"]


def test_hca_01_stale_pid_is_not_paired(herdr: HerdrApp, tmp_path: Path) -> None:
    """A pid with no process folder gives no session, so its session is in other."""
    (tmp_path / "proc" / "4242").rmdir()
    snap = herdr.snapshot()
    assert snap["spaces"][0]["tabs"][0]["panes"][0]["session"] is None
    assert snap["other"] == ["sess-a", "sess-b"]


def test_hca_01_pairing_is_cached_per_terminal(herdr: HerdrApp, tmp_path: Path) -> None:
    """While the pid lives, the core is not asked again."""
    herdr.snapshot()
    (tmp_path / "bin" / "hc_get_t2.json").unlink()
    snap = herdr.snapshot()
    assert snap["spaces"][0]["tabs"][0]["panes"][0]["session"] == "sess-a"


def test_hca_01_unavailable_herdr(herdr: HerdrApp, tmp_path: Path) -> None:
    """A failing or missing command gives available false and every session in other."""
    (tmp_path / "bin" / "ls.json").write_text("not json")
    assert herdr.snapshot() == {
        "available": False,
        "focus": None,
        "spaces": [],
        "other": ["sess-a", "sess-b"],
    }
    herdr.app = str(tmp_path / "missing")
    assert herdr.snapshot()["available"] is False


def test_hca_01_poll_reports_only_changes(herdr: HerdrApp) -> None:
    """The first poll changes the stored snapshot, the second does not."""
    assert herdr.poll() is True
    assert herdr.poll() is False


class _Request:
    def __init__(self, body: object) -> None:
        self.body = body

    async def json(self) -> object:
        return self.body


def _post(herdr: HerdrApp, body: object) -> tuple[int, list[str]]:
    svc = SimpleNamespace(herdr_app=herdr)
    coroutine = route.focus(_Request(body), svc, lambda view: None)
    # In a fresh thread: browser tests leave an event loop running in this one.
    with ThreadPoolExecutor(1) as pool:
        response = pool.submit(asyncio.run, coroutine).result()
    log = Path(herdr.app).with_name("do.log")
    return response.status_code, log.read_text().splitlines() if log.exists() else []


def test_hca_01_focus_terminal_selects_space_tab_and_pane(herdr: HerdrApp) -> None:
    """A terminal is shown by selecting its space and tab, then focusing its pane."""
    status, log = _post(herdr, {"terminal": "t4"})
    assert status == 200
    assert log == [
        'space.select {"id": "sp1"}',
        'tab.select {"id": "tb2"}',
        'pane.focus {"pane": "p3"}',
    ]


def test_hca_01_focus_tab_uses_its_focused_pane(herdr: HerdrApp) -> None:
    """A tab resolves to the pane view.json names as focused."""
    _, log = _post(herdr, {"tab": "tb1"})
    assert log[-1] == 'pane.focus {"pane": "p2"}'


def test_hca_01_focus_space_uses_its_active_tab(herdr: HerdrApp) -> None:
    """A space resolves to its active tab's focused pane."""
    _, log = _post(herdr, {"space": "sp1"})
    assert log[1:] == ['tab.select {"id": "tb1"}', 'pane.focus {"pane": "p2"}']


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({}, 400),
        ({"tab": "a", "space": "b"}, 400),
        ({"tab": 3}, 400),
        ({"tab": "x"}, 404),
    ],
)
def test_hca_01_focus_refuses_bad_requests(
    herdr: HerdrApp, body: object, code: int
) -> None:
    """Nothing or several keys, a non-string, or an unknown id run no command."""
    status, log = _post(herdr, body)
    assert (status, log) == (code, [])


def test_hca_01_focus_when_herdr_is_down(herdr: HerdrApp, tmp_path: Path) -> None:
    """With Herdr not running the route answers 503 and runs nothing."""
    (tmp_path / "bin" / "status.json").write_text("")
    status, log = _post(herdr, {"terminal": "t2"})
    assert (status, log) == (503, [])


def _add_remote(herdr: HerdrApp, tmp_path: Path, state: str = "connected") -> Path:
    """Add a remote space on machine ``rm`` with one claude pane; return the bin folder."""
    bin_dir = tmp_path / "bin"
    ls = json.loads((bin_dir / "ls.json").read_text())
    ls["spaces"].append(
        {
            "id": "rm/sp9",
            "name": "far",
            "machine": "rm",
            "active": False,
            "tabs": [
                {
                    "id": "rm/tb9",
                    "name": "1",
                    "active": True,
                    "terminals": [
                        {
                            "terminal": "rm/t1",
                            "pane": "rm/p9",
                            "status": "idle",
                            "app": "claude-code",
                            "name": None,
                        }
                    ],
                }
            ],
        }
    )
    (bin_dir / "ls.json").write_text(json.dumps(ls))
    machines = [
        {"name": "rm", "state": state, "temporary": False},
        {"name": "aa-tmp", "state": "connected", "temporary": True},
    ]
    (bin_dir / "machines.json").write_text(json.dumps({"machines": machines}))
    (bin_dir / "hc_get_rm_t1.json").write_text(json.dumps({"foreground": {"pid": 77}}))
    (bin_dir / "remote_remote_home_.claude_sessions_77.json").write_text(
        json.dumps({"sessionId": "sess-r"})
    )
    root = {"type": "row", "children": [{"type": "block", "id": "p9"}]}
    docs = {
        "herdr-app": {"value": {"spaces": [{"tabs": [{"id": "tb9", "root": root}]}]}}
    }
    name = "remote_remote_home_.local_state_herdr-core_default_docs.json"
    (bin_dir / name).write_text(json.dumps(docs))
    return bin_dir


def test_hca_01_remote_space_pairs_and_prefixes_tree(
    herdr: HerdrApp, tmp_path: Path
) -> None:
    """A remote space has its machine, a paired session and a tree with prefixed ids."""
    _add_remote(herdr, tmp_path)
    snap = herdr.snapshot()
    local, remote = snap["spaces"][0], snap["spaces"][2]
    assert local["machine"] is None
    assert remote["machine"] == "rm"
    tab = remote["tabs"][0]
    assert tab["panes"][0]["session"] == "sess-r"
    assert tab["tree"] == {
        "dir": "row",
        "weight": 1,
        "children": [{"pane": "rm/p9", "weight": 1}],
    }
    assert snap["other"] == ["sess-b"]
    assert snap["machines"] == [
        {"name": "rm", "state": "online", "detail": None, "other": []}
    ]


def test_hca_01_remote_color_is_keyed_by_prefixed_id(
    herdr: HerdrApp, tmp_path: Path
) -> None:
    """shared.json keys a remote space by its prefixed id."""
    _add_remote(herdr, tmp_path)
    colors = herdr.config_dir / "shared.json"
    colors.write_text(json.dumps({"space.colors": {"rm/sp9": "ansi5"}}))
    assert herdr.snapshot()["spaces"][2]["color"] == "#8b7cf6"


def test_hca_01_remote_session_file_is_read_once_per_pid(
    herdr: HerdrApp, tmp_path: Path
) -> None:
    """The session file is read again only when the terminal's pid changes."""
    bin_dir = _add_remote(herdr, tmp_path)
    herdr.snapshot()
    session_file = bin_dir / "remote_remote_home_.claude_sessions_77.json"
    session_file.write_text(json.dumps({"sessionId": "changed"}))
    assert herdr.snapshot()["spaces"][2]["tabs"][0]["panes"][0]["session"] == "sess-r"
    (bin_dir / "hc_get_rm_t1.json").write_text(json.dumps({"foreground": {"pid": 78}}))
    assert herdr.snapshot()["spaces"][2]["tabs"][0]["panes"][0]["session"] is None


def test_hca_01_disconnected_machine_makes_no_remote_reads(
    herdr: HerdrApp, tmp_path: Path
) -> None:
    """A machine Herdr does not call connected is offline and costs no remote call."""
    bin_dir = _add_remote(herdr, tmp_path, state="disconnected")
    snap = herdr.snapshot()
    tab = snap["spaces"][2]["tabs"][0]
    assert tab["panes"][0]["session"] is None
    assert "tree" not in tab
    assert snap["machines"][0]["state"] == "offline"
    calls = (bin_dir / "hc.log").read_text().splitlines()
    assert not [c for c in calls if c.startswith(("exec", "file", "get rm/"))]
