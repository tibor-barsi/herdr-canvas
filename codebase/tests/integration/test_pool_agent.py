"""Agent side of pooled pages: commands, tools, hook text (POOL-04, -05, -10, -11)."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mcp import Client

from agent_canvas.hooks import format_events
from agent_canvas.mcp_server import create_server

pytestmark = pytest.mark.integration

SPELLINGS = ("project page", "project-page", "project_page", "--project-page")
PAGE = "<title>Dash</title><p>x</p>"


@pytest.fixture
def repo(home: Path) -> Path:
    path = home / "proj"
    path.mkdir(exist_ok=True)
    (path / ".git").mkdir()
    return path


@pytest.fixture
def mcp_env(hub, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENT_CANVAS_PORT", str(hub.port))
    monkeypatch.delenv("AGENT_CANVAS_SESSION", raising=False)
    monkeypatch.setenv("AGENT_CANVAS_PROJECT", str(repo))


def call(name: str, /, **arguments):  # noqa: ANN003, ANN201
    """Call one MCP tool on a fresh loop in a worker thread; return its JSON."""

    async def main():  # noqa: ANN202
        async with Client(create_server()) as client:
            return await client.call_tool(name, arguments)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(asyncio.run, main()).result()
    return json.loads(result.content[0].text)


def test_pool_10_the_project_page_flag_is_an_unknown_option(cli, repo: Path) -> None:  # noqa: ANN001
    shown = cli("session", "path", "--session", "s-one", cwd=repo)
    assert shown.code == 0, shown.err
    for args in (
        ("show", "dash", "--project-page"),
        ("page", "list", "--project-page"),
        ("comment", "list", "--project-page"),
        ("session", "path", "--project-page"),
    ):
        refused = cli(*args, "--session", "s-one", cwd=repo)
        assert refused.code != 0, args
        assert "unrecognized arguments: --project-page" in refused.err, args
    assert cli("guide", "project-pages").code != 0


def test_pool_11_new_writes_the_tagged_draft_and_a_page_write_refuses_an_existing_name(
    cli,  # noqa: ANN001
    repo: Path,
) -> None:
    found = cli("session", "path", "--session", "s-one", cwd=repo).json
    folder, tag = Path(found["folder"]), found["tag"]
    made = cli("new", "dash", "--template", "cards", "--session", "s-one", cwd=repo)
    assert made.code == 0, made.err
    assert made.json["page"] == f"dash.{tag}.draft.html"
    assert (folder / f"dash.{tag}.draft.html").is_file()
    assert not (folder / "dash.draft.html").exists()
    # A draft of one's own may be rewritten with force.
    assert (
        cli(
            "new",
            "dash",
            "--template",
            "cards",
            "--force",
            "--session",
            "s-one",
            cwd=repo,
        ).code
        == 0
    )
    # A page write refuses an existing name, even with force.
    (folder / "dash.html").write_text(PAGE)
    for extra in ((), ("--force",)):
        refused = cli(
            "new", "dash", "--template", "cards", "--no-draft", *extra,
            "--session", "s-one", cwd=repo,
        )  # fmt: skip
        assert refused.code != 0, extra
        assert "already exists" in refused.err
    assert (folder / "dash.html").read_text() == PAGE
    # Positive control: a free name is written.
    free = cli(
        "new",
        "other",
        "--template",
        "cards",
        "--no-draft",
        "--session",
        "s-one",
        cwd=repo,
    )
    assert free.code == 0, free.err
    assert (folder / "other.html").is_file()


def test_pool_11_the_mcp_new_page_writes_the_tagged_draft(mcp_env, repo: Path) -> None:  # noqa: ANN001
    found = call("session_start")
    folder = Path(found["folder"])
    tag = call("session_path", session=found["session"])["tag"]
    made = call("new_page", name="dash", template="cards", session=found["session"])
    assert made["page"] == f"dash.{tag}.draft.html"
    assert (folder / made["page"]).is_file()
    (folder / "dash.html").write_text(PAGE)
    refused = call(
        "new_page", name="dash", template="cards", draft=False, force=True,
        session=found["session"],
    )  # fmt: skip
    assert "already exists" in json.dumps(refused)
    assert (folder / "dash.html").read_text() == PAGE


def test_pool_04_page_pin_and_unpin_by_command_and_mcp(
    cli, mcp_env, repo: Path
) -> None:  # noqa: ANN001
    folder = Path(cli("session", "path", "--session", "s-one", cwd=repo).json["folder"])
    (folder / "dash.html").write_text(PAGE)
    (folder / "plan.html").write_text(PAGE)
    for name in ("dash", "plan"):
        assert cli("show", name, "--session", "s-one", "--no-audit", cwd=repo).code == 0

    def pinned(session: str) -> dict[str, bool]:
        rows = cli("page", "list", "--session", session, cwd=repo).json["pages"]
        return {row["name"]: row["pinned"] for row in rows}

    assert pinned("s-one") == {"dash.html": False, "plan.html": False}
    pin = cli("page", "pin", "dash.html", "--session", "s-one", cwd=repo)
    assert pin.code == 0, pin.err
    assert pinned("s-one") == {"dash.html": True, "plan.html": False}
    # Another session of the project sees the pin, and unpins by the tool.
    other = call("session_start")["session"]
    assert pinned(other)["dash.html"] is True
    done = call("page", action="unpin", name="dash.html", session=other)
    assert done.get("pinned") is False, done
    assert pinned("s-one")["dash.html"] is False
    call("page", action="pin", name="plan.html", session=other)
    assert pinned("s-one") == {"dash.html": False, "plan.html": True}
    assert cli("page", "unpin", "plan.html", "--session", "s-one", cwd=repo).code == 0
    assert pinned("s-one")["plan.html"] is False
    # The name without .html works as in show (A-1080).
    short = cli("page", "pin", "dash", "--session", "s-one", cwd=repo)
    assert short.code == 0, short.err
    assert short.json["page"] == "dash.html"
    assert pinned("s-one") == {"dash.html": True, "plan.html": False}
    unpinned = call("page", action="unpin", name="dash", session=other)
    assert unpinned["page"] == "dash.html"
    assert pinned("s-one")["dash.html"] is False


def test_pool_05_the_hook_text_names_the_page_and_the_reply_command_no_marker() -> None:
    comment = {
        "number": 1, "kind": "point", "text": "units?", "state": "sent",
        "anchor": {"space": "page-px", "x": 1, "y": 2},
        "target": {"canvas_id": None, "selector": "#fig", "text": None},
    }  # fmt: skip
    event = {
        "id": "evt_1", "seq": 1, "kind": "send", "page": "dash.html", "page_version": 3,
        "message": "see", "comments": [comment], "actions": [], "marks": [],
        "screenshot": None, "screenshot_error": "none",
        "time": "2026-11-24T10:00:00+00:00", "delivery": "next-message",
    }  # fmt: skip
    answer = {
        "id": "evt_2", "seq": 2, "kind": "answer", "page": "dash.html",
        "target": {"canvas_id": "q-1"}, "value": {"answer": ["a"]},
        "delivery": "next-message",
    }  # fmt: skip
    text = format_events([event, answer])
    # Positive controls: the page and the plain reply command are named.
    assert "dash.html" in text
    assert 'agent-canvas comment reply dash.html N "text" [--done]' in text
    assert "q-1 (dash.html)" in text
    flagged = format_events([{**event, "project_page": True}])
    for spelling in SPELLINGS:
        assert spelling not in text.lower(), spelling
        assert spelling not in flagged.lower(), spelling
