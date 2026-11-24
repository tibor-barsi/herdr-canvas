"""The MCP server against a real hub (MCP-01 to MCP-06)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from mcp import Client, ClientSession, StdioServerParameters, stdio_client

from agent_canvas.hub import clock
from agent_canvas.mcp_server import create_server
from helpers import own_draft

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"
TOOLS = {
    "session_start": ({"agent", "title", "project"}, set()),
    "session_path": ({"session"}, set()),
    "session_set_title": ({"session", "title"}, {"title"}),
    "session_end": ({"session"}, set()),
    "show": (
        {"session", "page", "title", "publish", "audit", "kind"},
        set(),
    ),
    "page": (
        {"session", "action", "name", "kind", "archived"},
        {"action"},
    ),
    "ask": (
        {
            "session",
            "question",
            "choices",
            "multi",
            "text",
            "block",
            "approval",
            "details",
            "timeout_s",
        },
        {"question"},
    ),
    "result": ({"session", "summary", "files", "decision", "choices"}, {"summary"}),
    "wait_for_feedback": ({"session", "timeout_s", "max_events"}, set()),
    "pending": ({"session", "peek"}, set()),
    "new_page": ({"session", "name", "template", "force", "draft"}, set()),
    "look": (
        {
            "session",
            "page",
            "draft",
            "section",
            "full",
            "width",
            "height",
            "scheme",
            "audit",
        },
        set(),
    ),
    "cleanup": (
        {"older_than", "delete_session", "project", "yes", "force"},
        set(),
    ),
    "comments": ({"session", "page", "all"}, set()),
    "comment_reply": (
        {"session", "page", "n", "text", "done", "from"},
        {"page", "n", "text"},
    ),
    "comment_done": ({"session", "page", "n"}, {"page", "n"}),
    "answers": (
        {"session", "page", "open", "wait", "ids", "timeout_s"},
        set(),
    ),
}
# `session` is a parameter of each tool but never required by the schema: the
# environment can stand in for it (MCP-06).


@pytest.fixture(autouse=True)
def mcp_env(hub, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """Point the in-process server at the test hub; no session in the env."""
    monkeypatch.setenv("AGENT_CANVAS_PORT", str(hub.port))
    monkeypatch.delenv("AGENT_CANVAS_SESSION", raising=False)
    (home / "proj").mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_CANVAS_PROJECT", str(home / "proj"))


def in_thread(coroutine):  # noqa: ANN001, ANN201
    """
    Run a coroutine on a fresh event loop in a worker thread.

    The browser tests leave Playwright's sync API with a running loop in the
    main thread; ``asyncio.run`` cannot start there.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def run(coroutine_function):  # noqa: ANN001, ANN201
    """Run ``coroutine_function(client)`` with an in-process client."""

    async def main():  # noqa: ANN202
        async with Client(create_server()) as client:
            return await coroutine_function(client)

    return in_thread(main())


def call(name: str, /, **arguments):  # noqa: ANN003, ANN201
    async def action(client):  # noqa: ANN001, ANN202
        return await client.call_tool(name, arguments)

    return run(action)


def payload(result) -> dict:  # noqa: ANN001
    """The JSON of the first (text) block of a tool result."""
    assert result.content[0].type == "text"
    return json.loads(result.content[0].text)


def images(result) -> list[bytes]:  # noqa: ANN001
    return [base64.b64decode(b.data) for b in result.content if b.type == "image"]


def send(hub, session: str, message: str = "why this peak?") -> dict:  # noqa: ANN001
    body = {
        "delivery": "now", "message": message, "page": "page.html", "actions": [],
        "actions_dropped": 0, "marks": [],
        "viewport": {"width": 1280, "height": 800, "scroll_x": 0, "scroll_y": 0},
        "screenshot": base64.b64encode(PNG).decode(), "screenshot_error": None,
        "screenshot_warnings": [],
    }  # fmt: skip
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{session}/send",
        headers=hub.key_headers,
        json=body,
    )
    assert answer.status_code == 200, answer.text
    return answer.json()["event"]


def new_session() -> str:
    """Create a session with a page through the tool and return its id."""
    data = payload(call("session_start"))
    (Path(data["folder"]) / "page.html").write_text("<p>x</p>")
    # Showing the page makes the session a toucher of it, so it takes its feedback.
    call("show", session=data["session"], page="page.html", audit=False)
    return data["session"]


@pytest.fixture
def session(hub) -> str:  # noqa: ANN001
    return new_session()


# ---- MCP-01 ---------------------------------------------------------------


def test_mcp_01_lists_exactly_the_seventeen_tools_with_schemas() -> None:
    async def action(client):  # noqa: ANN001, ANN202
        return (await client.list_tools()).tools

    tools = {t.name: t for t in run(action)}
    assert set(tools) == set(TOOLS)
    for name, (properties, required) in TOOLS.items():
        schema = tools[name].input_schema
        assert set(schema.get("properties", {})) == properties, name
        assert set(schema.get("required", [])) == required, name
        assert tools[name].description, name


def test_mcp_01_the_stdio_server_speaks_mcp_without_stray_output(
    hub, home, tmp_path
) -> None:  # noqa: ANN001
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "AGENT_CANVAS_PORT": str(hub.port),
        "AGENT_CANVAS_STATE_DIR": str(hub.state_dir),
        "AGENT_CANVAS_CONFIG_DIR": str(hub.config_dir),
        "AGENT_CANVAS_PROJECT": str(home / "proj"),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agent_canvas.cli", "mcp"],
        env=environment,
    )

    async def action() -> tuple[set[str], dict]:
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                started = await session.call_tool("session_start", {"title": "T"})
                return names, json.loads(started.content[0].text)

    names, started = in_thread(action())
    assert names == set(TOOLS)
    assert Path(started["folder"]).is_dir()


# ---- MCP-02 ---------------------------------------------------------------


def test_mcp_02_session_start_returns_the_id_and_folder(hub) -> None:  # noqa: ANN001
    result = call("session_start", agent="opencode", title="Bracket")
    assert result.is_error is False
    data = payload(result)
    assert set(data) == {"session", "folder", "tag"}
    assert Path(data["folder"]).is_dir()
    own = hub.state.session_of(data["session"]).folder  # not the pool's folder
    meta = json.loads((own / "session.json").read_text())
    assert (meta["agent"], meta["title"]) == ("opencode", "Bracket")


def test_mcp_02_tools_return_what_the_cli_prints(cli, hub, session) -> None:  # noqa: ANN001
    cases = [
        ("session_path", {"session": session}, ("session", "path")),
        ("session_set_title", {"session": session, "title": "T"},
         ("session", "set", "--title", "T")),
        ("show", {"session": session}, ("show", "--session", session)),
        ("pending", {"session": session, "peek": True},
         ("pending", "--peek", "--session", session)),
    ]  # fmt: skip
    for name, arguments, command in cases:
        extra = [] if "--session" in command else ["--session", session]
        expected = cli(*command, *extra)
        assert expected.code == 0, (name, expected.err)
        result = call(name, **arguments)
        assert result.is_error is False, name
        assert payload(result) == expected.json, name


def test_mcp_02_session_end_matches_the_cli(cli, hub, session) -> None:  # noqa: ANN001
    result = call("session_end", session=session)
    assert payload(result) == {"session": session, "state": "ended"}
    assert cli("session", "end", "--session", session).json == payload(result)


def test_mcp_02_errors_are_is_error_with_the_error_object(hub, session) -> None:  # noqa: ANN001
    result = call("show", session=session, page="missing.html")
    assert result.is_error is True
    data = payload(result)
    assert data["error"] == "failed" and ".agent-canvas" in data["message"]


def test_mcp_02_unknown_session_is_a_no_session_error(hub) -> None:  # noqa: ANN001
    result = call("pending", session="nobody")
    assert result.is_error is True and payload(result)["error"] == "no-session"


def test_mcp_02_ask_timeout_is_a_normal_result(hub, session) -> None:  # noqa: ANN001
    result = call("ask", session=session, question="Which?", choices=["A", "B"],
                  timeout_s=1)  # fmt: skip
    assert result.is_error is False
    data = payload(result)
    assert data["status"] == "timeout" and data["event"] is None


def test_mcp_02_ask_dismissed_is_a_normal_result(hub, session) -> None:  # noqa: ANN001
    def dismiss() -> None:
        ask = hub.wait_for_ask(session)
        hub.dismiss_ask(session, ask["ask"])

    threading.Thread(target=dismiss, daemon=True).start()
    result = call("ask", session=session, question="Which?", timeout_s=20)
    assert result.is_error is False
    assert payload(result)["status"] == "dismissed"


def test_mcp_02_ask_answered_returns_the_event(hub, session) -> None:  # noqa: ANN001
    def answer() -> None:
        ask = hub.wait_for_ask(session)
        hub.answer_ask(session, ask["ask"], ["B"])

    threading.Thread(target=answer, daemon=True).start()
    result = call("ask", session=session, question="Which?", choices=["A", "B"],
                  timeout_s=20)  # fmt: skip
    data = payload(result)
    assert data["status"] == "answered" and data["event"]["value"] == ["B"]


def test_mcp_02_ask_usage_errors_are_reported(hub, session) -> None:  # noqa: ANN001
    result = call("ask", session=session, question="Which?", multi=True)
    assert result.is_error is True and payload(result)["error"] == "usage"


def test_mcp_02_cleanup_is_a_dry_run_unless_yes_is_given(hub, session) -> None:  # noqa: ANN001
    folder = Path(payload(call("session_path", session=session))["folder"])
    folder = folder / "history" / "pages"
    folder.mkdir(parents=True, exist_ok=True)
    old_page = folder / "page.0001.html"
    old_page.write_text("x")
    os.utime(old_page, (1, 1))
    result = call("cleanup", older_than="30d")
    assert result.is_error is False
    assert payload(result)["dry_run"] is True and old_page.exists()
    assert payload(result)["deleted"] == [str(old_page)]
    done = call("cleanup", older_than="30d", yes=True)
    assert payload(done)["dry_run"] is False and not old_page.exists()


def test_mcp_02_cleanup_delete_session_and_errors(hub, session) -> None:  # noqa: ANN001
    result = call("cleanup", delete_session="nope")
    assert result.is_error is True and payload(result)["error"] == "no-session"
    neither = call("cleanup")
    assert neither.is_error is True and payload(neither)["error"] == "failed"


# ---- MCP-03 ---------------------------------------------------------------


def test_mcp_03_pending_returns_text_and_the_screenshot_image(hub, session) -> None:  # noqa: ANN001
    event = send(hub, session)
    result = call("pending", session=session)
    kinds = [b.type for b in result.content]
    assert kinds == ["text", "image"]
    assert result.content[1].mime_type == "image/png"
    assert images(result) == [PNG]
    assert payload(result)["events"][0]["id"] == event["id"]


def test_mcp_03_at_most_three_images_the_rest_by_path(hub, session) -> None:  # noqa: ANN001
    for number in range(4):
        send(hub, session, f"note {number}")
    result = call("pending", session=session)
    assert len(images(result)) == 3
    events = payload(result)["events"]
    assert len(events) == 4 and all(e["screenshot"] for e in events)


def test_mcp_03_events_without_a_screenshot_add_no_image(hub, session) -> None:  # noqa: ANN001
    hub.create_event(session, "send", message="m", screenshot=None,
                     screenshot_error="capture failed")  # fmt: skip
    result = call("pending", session=session)
    assert [b.type for b in result.content] == ["text"]


# ---- MCP-04 ---------------------------------------------------------------


def test_mcp_04_wait_for_feedback_listens_and_returns_a_browser_send(
    hub, session
) -> None:  # noqa: ANN001
    seen: dict = {}

    def owner() -> None:
        hub.wait_for(lambda: hub.listening(session))
        seen["listening"] = True
        seen["event"] = send(hub, session)

    threading.Thread(target=owner, daemon=True).start()
    result = call("wait_for_feedback", session=session, timeout_s=20)
    data = payload(result)
    assert seen["listening"] is True
    assert data["ended_reason"] == "events"
    assert [e["id"] for e in data["events"]] == [seen["event"]["id"]]
    assert images(result) == [PNG]
    assert hub.event_state(session, seen["event"]["id"]) == "delivered"
    assert not hub.listening(session)


def test_mcp_04_timeout_gives_an_empty_result(hub, session) -> None:  # noqa: ANN001
    result = call("wait_for_feedback", session=session, timeout_s=1)
    assert result.is_error is False
    assert payload(result) == {"events": [], "ended_reason": "timeout"}


def test_mcp_04_max_events_leaves_the_rest_queued(hub, session) -> None:  # noqa: ANN001
    ids = [hub.create_event(session, "custom", value={"name": "n", "value": i})["id"]
           for i in range(3)]  # fmt: skip
    result = call("wait_for_feedback", session=session, timeout_s=5, max_events=2)
    data = payload(result)
    assert [e["id"] for e in data["events"]] == ids[:2]
    assert hub.event_state(session, ids[2]) == "queued"
    log = (hub.state.session_of(session).folder / "events.jsonl").read_text()
    assert '"via":"mcp"' in log


# ---- MCP-05 ---------------------------------------------------------------


def test_mcp_05_wait_for_feedback_clamps_and_says_so(hub, session) -> None:  # noqa: ANN001
    hub.create_event(session, "custom", value={"name": "n", "value": 1})
    result = call("wait_for_feedback", session=session, timeout_s=99999)
    data = payload(result)
    assert data["ended_reason"] == "events"
    assert "1500" in data["note"]


def test_mcp_05_ask_clamps_and_says_so(hub, session) -> None:  # noqa: ANN001
    def dismiss() -> None:
        hub.dismiss_ask(session, hub.wait_for_ask(session)["ask"])

    threading.Thread(target=dismiss, daemon=True).start()
    result = call("ask", session=session, question="Which?", timeout_s=99999)
    assert "1500" in payload(result)["note"]


def test_mcp_05_the_default_timeouts_are_300_seconds() -> None:
    from agent_canvas import mcp_server

    assert mcp_server.DEFAULT_TIMEOUT_S == 300 and mcp_server.MAX_TIMEOUT_S == 1500


def test_mcp_05_no_note_when_the_timeout_is_in_range(hub, session) -> None:  # noqa: ANN001
    assert "note" not in payload(
        call("wait_for_feedback", session=session, timeout_s=1)
    )


# ---- MCP-06 ---------------------------------------------------------------


def test_mcp_06_the_argument_wins_over_the_environment(
    hub, session, monkeypatch
) -> None:  # noqa: ANN001
    other = new_session()
    monkeypatch.setenv("AGENT_CANVAS_SESSION", other)
    assert payload(call("session_path", session=session))["session"] == session


def test_mcp_06_the_environment_is_the_fallback(hub, session, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENT_CANVAS_SESSION", session)
    result = call("session_path")
    assert result.is_error is False and payload(result)["session"] == session


def test_mcp_06_without_a_session_the_error_says_how_to_get_one(hub) -> None:  # noqa: ANN001
    result = call("show")
    assert result.is_error is True
    data = payload(result)
    assert data["error"] == "no-session"
    assert "SessionStart" in data["message"] and "session_start" in data["message"]


# ---- KIT-04 ---------------------------------------------------------------


def test_kit_04_new_page_writes_a_template_and_refuses_to_overwrite(session) -> None:  # noqa: ANN001
    from agent_canvas.templates import TEMPLATES

    made = call(
        "new_page", session=session, name="via-mcp", template="results", draft=False
    )
    assert made.is_error is False
    data = payload(made)
    assert Path(data["path"]).name == "via-mcp.html" and data["template"] == "results"
    assert data["draft"] is False
    assert "canvas-plot" in Path(data["path"]).read_text()
    again = call(
        "new_page", session=session, name="via-mcp", template="results", draft=False
    )
    assert again.is_error is True and payload(again)["error"] == "failed"
    forced = call(
        "new_page", session=session, name="via-mcp", template="run", force=True,
        draft=False,
    )  # fmt: skip
    assert forced.is_error is True and "already exists" in payload(forced)["message"]
    assert "canvas-plot" in Path(data["path"]).read_text()
    listing = payload(call("new_page"))["templates"]
    assert [t["name"] for t in listing] == list(TEMPLATES)
    bad = call("new_page", session=session, name="../x", template="run")
    assert bad.is_error is True and payload(bad)["error"] == "usage"


def test_draft_04_new_page_writes_a_draft_by_default(session) -> None:  # noqa: ANN001
    data = payload(call("new_page", session=session, name="idea", template="compare"))
    assert data["draft"] is True and data["page"] == own_draft(session, "idea")
    assert Path(data["path"]).name == own_draft(session, "idea")
    assert not (Path(data["path"]).parent / "idea.html").exists()


# ---- LOOK-08 --------------------------------------------------------------


def test_look_08_look_returns_the_json_and_the_picture(hub, session) -> None:  # noqa: ANN001
    from shellfake import FakeHeadless

    hub.app.state.looks.headless = FakeHeadless()
    folder = Path(payload(call("session_path", session=session))["folder"])
    (folder / own_draft(session)).write_text("<p>draft</p>")
    result = call("look", session=session, draft=True, width=320, height=200)
    assert result.is_error is False
    data = payload(result)
    assert data["source"] == "headless" and data["draft"] is True
    assert (data["width"], data["height"]) == (320, 200)
    [picture] = images(result)
    assert picture == Path(data["png"]).read_bytes()
    assert [b.mime_type for b in result.content if b.type == "image"] == ["image/png"]


def test_look_08_a_failed_look_is_an_error_result_without_an_image(
    hub, session
) -> None:  # noqa: ANN001
    from shellfake import FakeHeadless

    hub.app.state.looks.headless = FakeHeadless(error="no browser here")
    result = call("look", session=session)
    assert result.is_error is True and images(result) == []
    assert "agent-canvas open" in payload(result)["message"]
    missing = call("look", session=session, draft=True)
    assert (
        missing.is_error is True and own_draft(session) in payload(missing)["message"]
    )


def test_look_08_show_publishes_a_draft(session, hub) -> None:  # noqa: ANN001
    folder = Path(payload(call("session_path", session=session))["folder"])
    (folder / own_draft(session)).write_text("<p>better</p>")
    result = call("show", session=session, page="page.html", publish=True)
    assert result.is_error is False and payload(result)["page"] == "page.html"
    assert (folder / "page.html").read_text() == "<p>better</p>"
    missing = call("show", session=session, page="other.html", publish=True)
    assert (
        missing.is_error is True
        and own_draft(session, "other") in payload(missing)["message"]
    )


def test_chk_14_look_has_the_findings_in_the_text_and_still_one_image(
    hub, session
) -> None:  # noqa: ANN001
    from shellfake import FakeHeadless

    raw = {
        "findings": [
            {
                "rule": "overlap", "severity": "warn", "message": "Text overlaps.",
                "where": "#a", "bbox": {"x": 4, "y": 4, "w": 30, "h": 20},
            }
        ]
    }  # fmt: skip
    hub.app.state.looks.headless = FakeHeadless(audit=raw)
    result = call("look", session=session, width=320, height=200)
    data = payload(result)
    assert data["audit"]["counts"] == {"error": 0, "warn": 1, "info": 0}
    [finding] = data["audit"]["findings"]
    assert finding["rule"] == "overlap" and Path(finding["crop"]).is_file()
    assert len(images(result)) == 1
    skipped = call("look", session=session, width=320, height=200, audit=False)
    assert payload(skipped)["audit"] is None


def test_chk_15_show_accepts_the_audit_switch(hub, session) -> None:  # noqa: ANN001
    (hub.state.session_of(session).folder / "page.html").write_text("<p>x</p>")
    result = call("show", session=session, page="page.html", audit=False)
    assert result.is_error is False and payload(result)["audit"] is None


# ---- MCP-03 (comments), COM-11 ----------------------------------------------


def comment_pictures(count: int) -> list[bytes]:
    return [b"\x89PNG\r\n\x1a\n" + b"comment-%d" % n for n in range(count)]


def send_with_comments(hub, session: str, count: int) -> dict:  # noqa: ANN001
    """The owner saves ``count`` comments with pictures, then sends them."""
    owner = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    owner.get(hub.login_url(), follow_redirects=False)
    for number, picture in enumerate(comment_pictures(count)):
        answer = owner.post(
            f"/api/sessions/{session}/comments",
            json={
                "page": "page.html", "page_version": 1, "kind": "point",
                "text": f"note {number}", "target": None,
                "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
                "picture": base64.b64encode(picture).decode(),
            },
        )  # fmt: skip
        assert answer.status_code == 200, answer.text
    return send(hub, session)


def seen(session: str) -> list[str]:
    from agent_canvas.hub import comments

    folder = Path(payload(call("session_path", session=session))["folder"])
    return [comments.status(c) for c in comments.load(folder, "page.html")["comments"]]


def test_mcp_03_comment_pictures_come_before_the_screenshot(hub, session) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 2)
    result = call("pending", session=session)
    assert images(result) == [*comment_pictures(2), PNG]


def test_mcp_03_at_most_six_images_in_all_screenshots_at_most_three(
    hub, session
) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 8)
    result = call("pending", session=session)
    assert images(result) == comment_pictures(8)[:6]
    for number in range(4):
        send(hub, session, f"later {number}")
    mixed = call("pending", session=session)
    assert images(mixed) == [PNG] * 3


def test_mcp_03_wait_for_feedback_orders_the_images_the_same_way(hub, session) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 1)
    result = call("wait_for_feedback", session=session, timeout_s=10)
    assert images(result) == [*comment_pictures(1), PNG]


def test_com_11_pending_through_mcp_stamps_the_comment_seen(hub, session) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 1)
    call("pending", session=session, peek=True)
    assert seen(session) == ["sent"]
    call("pending", session=session)
    assert seen(session) == ["seen"]


def test_com_11_wait_for_feedback_through_mcp_stamps_the_comment_seen(
    hub, session
) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 1)
    call("wait_for_feedback", session=session, timeout_s=10)
    assert seen(session) == ["seen"]


# ---- MCP-03 (comments tool), RPL-01, RPL-02, RPL-06 -------------------------


def test_mcp_03_comments_tool_returns_the_pictures_at_most_six(hub, session) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 8)
    result = call("comments", session=session)
    listed = payload(result)["comments"]
    assert [c["n"] for c in listed] == list(range(1, 9))
    assert images(result) == comment_pictures(8)[:6]


def test_rpl_01_comments_tool_filters_open_and_all(hub, session) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 2)
    assert (
        payload(
            call("comment_reply", session=session, page="page.html", n=1, text="ok")
        )["replies"]
        == 1
    )
    assert [c["n"] for c in payload(call("comments", session=session))["comments"]] == [
        2
    ]
    everything = call("comments", session=session, page="page.html", all=True)
    assert [c["n"] for c in payload(everything)["comments"]] == [1, 2]
    assert len(images(everything)) == 2


def test_rpl_02_comment_reply_and_done_tools(hub, session) -> None:  # noqa: ANN001
    from agent_canvas.hub import comments

    send_with_comments(hub, session, 3)
    reply = call(
        "comment_reply", session=session, page="page.html", n=1, text="fixed",
        done=True, **{"from": "Reviewer"},
    )  # fmt: skip
    assert payload(reply) == {"page": "page.html", "n": 1, "replies": 1, "done": True}
    done = call("comment_done", session=session, page="page.html", n=[2, 3])
    assert payload(done) == {"page": "page.html", "done": [2, 3]}
    assert seen(session) == ["done", "done", "done"]
    folder = Path(payload(call("session_path", session=session))["folder"])
    first = comments.load(folder, "page.html")["comments"][0]
    assert first["replies"][0]["from"] == "Reviewer"


def test_rpl_02_comment_tools_report_errors_as_error_results(hub, session) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 1)
    bad = call(
        "comment_reply",
        session=session,
        page="page.html",
        n=1,
        text="t",
        **{"from": "Owner"},
    )
    assert bad.is_error is True and payload(bad)["error"] == "usage"
    unknown = call("comment_reply", session=session, page="page.html", n=7, text="t")
    assert unknown.is_error is True and payload(unknown)["error"] == "failed"


def test_rpl_06_wait_for_feedback_returns_three_comments_with_pictures(
    hub, session
) -> None:  # noqa: ANN001
    send_with_comments(hub, session, 3)
    result = call("wait_for_feedback", session=session, timeout_s=10)
    [event] = payload(result)["events"]
    assert [c["n"] for c in event["comments"]] == [1, 2, 3]
    assert images(result) == [*comment_pictures(3), PNG]


# ---- ANS-04, ANS-05 (answers tool) ---------------------------------------------


def shown_ask(hub, session: str) -> httpx.Client:  # noqa: ANN001
    """Show a page with one Ask and return the owner's client."""
    folder = Path(payload(call("session_path", session=session))["folder"])
    ask = (
        '<canvas-ask data-canvas-id="q1"><script type="application/json">'
        '{"question": "Keep it?", "options": ["yes", "no"]}</script></canvas-ask>'
    )
    (folder / "page.html").write_text(ask)
    assert (
        call("show", session=session, page="page.html", audit=False).is_error is False
    )
    owner = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    owner.get(hub.login_url(), follow_redirects=False)
    return owner


def test_ans_04_answers_tool_lists_and_waits(hub, session) -> None:  # noqa: ANN001
    owner = shown_ask(hub, session)
    listed = payload(call("answers", session=session, open=True))["items"]
    assert [(i["id"], i["state"], i["waits"]) for i in listed] == [("q1", "open", True)]

    late = call("answers", session=session, wait=True, ids=["q1"], timeout_s=1)
    assert late.is_error is False
    assert payload(late)["status"] == "timeout"

    body = {"page": "page.html", "id": "q1", "value": {"answer": ["yes"]}}
    owner.post(f"/api/sessions/{session}/answers/answer", json=body)
    done = payload(call("answers", session=session, wait=True, ids=["q1"], timeout_s=5))
    assert done["items"][0]["answer"]["answer"] == ["yes"]
    assert payload(call("pending", session=session))["events"] == []


def test_life_07_mcp_pending_returns_reminders_and_peek_stamps_nothing(
    hub,
    session,
    monkeypatch,  # noqa: ANN001
) -> None:
    show = call(
        "show", session=session, page="page.html", kind="single-use", audit=False
    )
    assert show.is_error is False
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(3 * 24 * 3600 + 60))

    def named(**arguments) -> list[str]:  # noqa: ANN003
        found = payload(call("pending", session=session, **arguments))
        return [r["page"] for r in found["reminders"]]

    assert named(peek=True) == ["page.html"]
    assert named(peek=True) == ["page.html"]
    assert named() == ["page.html"]
    assert named() == []


def test_ans_05_mcp_answers_refuses_timeout_without_wait(hub, session) -> None:  # noqa: ANN001
    bad = call("answers", session=session, timeout_s=5)
    assert bad.is_error is True and payload(bad)["error"] == "usage"
    assert payload(bad)["message"] == "timeout_s needs wait."


def test_ans_05_mcp_answers_refuses_open_with_wait(hub, session) -> None:  # noqa: ANN001
    bad = call("answers", session=session, wait=True, open=True)
    assert bad.is_error is True and payload(bad)["error"] == "usage"
    assert payload(bad)["message"] == "open does not combine with wait."


def test_ans_05_mcp_answers_wait_alone_keeps_the_default_time(hub, session) -> None:  # noqa: ANN001
    seen = {}

    def fake(client, sid, ids, page, seconds):  # noqa: ANN001, ANN202
        seen["seconds"] = seconds
        return {"status": "timeout"}, 6

    with patch("agent_canvas.mcp_server.wait_answers", fake):
        result = call("answers", session=session, wait=True)
    assert result.is_error is False and seen["seconds"] == 300


def test_ans_04_mcp_answers_open_alone_still_lists(hub, session) -> None:  # noqa: ANN001
    result = call("answers", session=session, open=True)
    assert result.is_error is False and payload(result)["items"] == []
