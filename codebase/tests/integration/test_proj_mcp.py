"""The MCP tools take ``project_page`` (PROJ-03, #87)."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mcp import Client

from agent_canvas.mcp_server import create_server

pytestmark = pytest.mark.integration

WITH_FLAG = {
    "session_path",
    "show",
    "page",
    "look",
    "comments",
    "comment_reply",
    "comment_done",
    "answers",
}


@pytest.fixture(autouse=True)
def mcp_env(hub, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """Point the in-process server at the test hub; no session in the env."""
    monkeypatch.setenv("AGENT_CANVAS_PORT", str(hub.port))
    monkeypatch.delenv("AGENT_CANVAS_SESSION", raising=False)
    (home / "proj").mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_CANVAS_PROJECT", str(home / "proj"))


def run(action):  # noqa: ANN001, ANN201
    """Run ``action(client)`` on a fresh event loop in a worker thread."""

    async def main():  # noqa: ANN202
        async with Client(create_server()) as client:
            return await action(client)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, main()).result()


def call(name: str, /, **arguments):  # noqa: ANN003, ANN201
    async def action(client):  # noqa: ANN001, ANN202
        return await client.call_tool(name, arguments)

    return run(action)


def payload(result) -> dict:  # noqa: ANN001
    assert result.content[0].type == "text"
    return json.loads(result.content[0].text)


def test_proj_03_project_page_is_an_optional_boolean_of_exactly_these_tools() -> None:
    async def action(client):  # noqa: ANN001, ANN202
        return (await client.list_tools()).tools

    tools = {t.name: t for t in run(action)}
    flagged = {
        n for n, t in tools.items() if "project_page" in t.input_schema["properties"]
    }
    assert flagged == WITH_FLAG
    for name in flagged:
        schema = tools[name].input_schema
        assert schema["properties"]["project_page"]["type"] == "boolean", name
        assert "project_page" not in schema.get("required", []), name


def test_proj_03_two_sessions_share_a_page_through_the_tools() -> None:
    first = payload(call("session_start"))["session"]
    second = payload(call("session_start"))["session"]
    folder = payload(call("session_path", session=first, project_page=True))
    assert Path(folder["folder"]).name == "project"
    assert folder["session"].startswith("project-")
    (Path(folder["folder"]) / "plan.html").write_text("<title>Plan</title><p>x</p>")
    shown = payload(
        call("show", session=first, page="plan.html", audit=False, project_page=True)
    )
    assert shown["session"] == folder["session"]
    listing = payload(call("page", action="list", session=second, project_page=True))
    (row,) = listing["pages"]
    assert row["updated_by"]["session"] == first and row["kind"] == "long-term"
    own = payload(call("page", action="list", session=second))
    assert own["pages"] == []
    assert (
        payload(call("comments", session=second, project_page=True))["session"]
        == (folder["session"])
    )
    assert payload(call("comments", session=second))["session"] == second
    assert (
        payload(call("answers", session=second, project_page=True))["session"]
        == (folder["session"])
    )
    assert payload(call("answers", session=second))["session"] == second
    kind = payload(
        call(
            "page",
            action="kind",
            name="plan.html",
            kind="single-use",
            session=second,
            project_page=True,
        )
    )
    assert kind["session"] == folder["session"] and kind["kind"] == "single-use"
