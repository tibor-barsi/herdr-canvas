"""The MCP server started by ``agent-canvas mcp`` (requirements 6.10).

Seventeen tools mirror the CLI. Each tool does what the command does through the
shared :class:`~agent_canvas.client.HubClient` and returns the command's JSON
as text content; the screenshot of every ``send`` event is added as an image
block (MCP-03). Errors become ``isError`` results carrying the error object
of 5.5 (MCP-02). Nothing but the protocol may reach stdout.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, ImageContent, TextContent
from pydantic import Field

from agent_canvas.answers import wait_answers
from agent_canvas.ask import ask_once, build_ask_spec
from agent_canvas.client import HubClient, client_from_environment, resolve_project
from agent_canvas.guide_text import core_text
from agent_canvas.output import CliError
from agent_canvas.paths_safe import InvalidSessionId, resolve_session_id
from agent_canvas.result import send_result
from agent_canvas.templates import describe_templates, new_page_result
from agent_canvas.watch import collect_events

DEFAULT_TIMEOUT_S = 300
MAX_TIMEOUT_S = 1500  # below Claude Code's 30-minute stdio timeout (MCP-05)
DEFAULT_MAX_EVENTS = 10
MAX_IMAGES = 3
MAX_RESULT_IMAGES = 6
LOOK_TIMEOUT_S = 90  # the window gets 10 s, then a headless browser starts

INSTRUCTIONS = (
    "Pass your session id as `session` (Claude Code: from the SessionStart "
    "context; other agents: call `session_start` once). The tools `session_path`, "
    "`look` and `show` do what the commands below do; `wait_for_feedback` "
    "listens like `watch`.\n\n" + core_text()
)

Session = Annotated[
    str | None,
    Field(
        description="Session id; may be omitted only if AGENT_CANVAS_SESSION is set."
    ),
]
TimeoutS = Annotated[
    int | float,
    Field(
        description=(
            f"Seconds to wait (default {DEFAULT_TIMEOUT_S}, at most {MAX_TIMEOUT_S})."
        )
    ),
]

NO_SESSION_MESSAGE = (
    "No session id. Pass `session`: in Claude Code it is the id in the "
    "SessionStart context ('Your agent-canvas session id is ...'); other "
    "agents get one from the `session_start` tool. AGENT_CANVAS_SESSION in the "
    "server's environment is the fallback."
)


def create_server() -> MCPServer:
    """
    Build the MCP server with its tools.

    Returns
    -------
    mcp.server.mcpserver.MCPServer
        The server; :func:`main` runs it on stdio.
    """
    server = MCPServer("agent-canvas", instructions=INSTRUCTIONS)

    @server.tool()
    async def session_start(
        agent: str | None = None, title: str | None = None, project: str | None = None
    ) -> CallToolResult:
        """Create a session and return its id and folder; pass the id as `session`."""

        def work() -> dict[str, Any]:
            body = _creation_body(project, agent)
            body["title"] = title
            return _client().request("POST", "/api/sessions", body)

        return await _run(work)

    @server.tool()
    async def session_path(session: Session = None) -> CallToolResult:
        """Return the page folder (created if needed) and your draft `tag`.

        Write drafts there as `NAME.TAG.draft.html`; pages belong to the project.
        """

        def work() -> dict[str, Any]:
            sid = _session(session)
            return _client().request(
                "POST", f"/api/sessions/{sid}/path", _creation_body(None, None)
            )

        return await _run(work)

    @server.tool()
    async def session_set_title(title: str, session: Session = None) -> CallToolResult:
        """Set the title shown on the session's tab."""

        def work() -> dict[str, Any]:
            sid = _session(session)
            return _client().request(
                "POST", f"/api/sessions/{sid}/title", {"title": title}
            )

        return await _run(work)

    @server.tool()
    async def session_end(session: Session = None) -> CallToolResult:
        """Mark the session ended (dismisses its open questions)."""

        def work() -> dict[str, Any]:
            sid = _session(session)
            return _client().request("POST", f"/api/sessions/{sid}/end", {})

        return await _run(work)

    @server.tool()
    async def show(
        session: Session = None,
        page: str | None = None,
        title: str | None = None,
        publish: bool = False,
        audit: bool = True,
        kind: Literal["single-use", "transitional", "long-term"] | None = None,
    ) -> CallToolResult:
        """Show a page of the page folder (default page.html) in the window.

        `kind` sets how long the page stays: `single-use` for a question, choice
        or plan (3 days after it is answered), `transitional` for work in
        progress (30 days, the default), `long-term` for a dashboard (never).

        With `publish`, the page is first replaced by your private draft
        NAME.TAG.draft.html (write the draft, `look` at it, then publish). The JSON
        has `audit`: a summary line and the error and warning findings of the
        automatic page checks (or "pending" if they took longer than ~4 s);
        `audit` false skips them. For a PDF, Markdown file or picture `audit` is
        null and `viewer_error` is null or the reason the file could not be shown
        (`pdf-corrupt`, `pdf-password`, `image-undecodable`, `image-too-large`).
        """

        def work() -> dict[str, Any]:
            sid = _session(session)
            body = _creation_body(None, None)
            body.update(name=page, title=title)
            if publish:
                body["publish"] = True
            if not audit:
                body["audit"] = False
            if kind:
                body["kind"] = kind
            return _client().request("POST", f"/api/sessions/{sid}/show", body)

        return await _run(work)

    @server.tool()
    async def page(
        action: Literal["kind", "archive", "restore", "extend", "pin", "unpin", "list"],
        name: str | None = None,
        kind: Literal["single-use", "transitional", "long-term"] | None = None,
        archived: bool = False,
        session: Session = None,
    ) -> CallToolResult:
        """Set the kind of a page; archive, restore, extend, pin, unpin; list pages.

        `kind` sets the kind of page `name` (the owner's choice wins);
        `archive` takes it off its tab (files stay), `restore` it, `extend` its
        lifetime, `pin` it so it shows in the card of every session of the
        project (`unpin` undoes that), or `list` the project's pages with their
        expiry and pins (`archived` adds the archived ones). `show` or a new
        version also restores a page.
        """

        def work() -> dict[str, Any]:
            path = f"/api/sessions/{_session(session)}/pages"
            if action == "list":
                return _client().request(
                    "GET", path + ("?archived=1" if archived else "")
                )
            body = {"action": action, "name": name, "kind": kind}
            return _client().request("POST", path, body)

        return await _run(work)

    @server.tool()
    async def new_page(
        name: str | None = None,
        template: str | None = None,
        session: Session = None,
        force: bool = False,
        draft: bool = True,
    ) -> CallToolResult:
        """Write a page from a template into the page folder.

        Templates: compare, results, run, geometry, cards. By default your private
        draft `name`.TAG.draft.html is written (`look` at it, then `show` with
        `publish`); `force` overwrites a draft. With `draft` false, `name`.html is
        written, and never over a page that exists.
        Without `name` and `template` the templates are listed.
        """

        def work() -> dict[str, Any]:
            if name is None and template is None:
                return describe_templates()
            if not name or not template:
                raise CliError("usage", "new_page needs `name` and `template`.")
            sid = _session(session)
            client = _client()
            answer = client.request(
                "POST", f"/api/sessions/{sid}/path", _creation_body(None, None)
            )
            return new_page_result(
                Path(answer["folder"]), name, template, force, draft, answer["tag"]
            )

        return await _run(work)

    @server.tool()
    async def look(
        session: Session = None,
        page: str | None = None,
        draft: bool = False,
        section: str | None = None,
        full: bool = False,
        width: int | None = None,
        height: int | None = None,
        scheme: Literal["light", "dark"] | None = None,
        audit: bool = True,
    ) -> CallToolResult:
        """Render a page (or with `draft` its private draft) and return the picture.

        The picture is what the owner will see, at the size and colour scheme of
        the owner's window unless `width`, `height` or `scheme` are given.
        `section` crops to the element with that `id` or `data-canvas-id`; `full`
        captures the whole page height instead of the visible part. The JSON has
        `errors` the page raised while rendering and `audit`: the findings of the
        automatic page checks (`rule`, `severity`, `message`, `where`, `bbox`, and
        for the most severe a `crop` PNG path) with their `counts`; `audit` false
        skips the checks. For a PDF, Markdown file or picture `audit` is null and
        `viewer_error` is null or the reason the file could not be shown
        (`pdf-corrupt`, `pdf-password`, `image-undecodable`, `image-too-large`).
        """

        def work() -> dict[str, Any]:
            sid = _session(session)
            body = {
                "page": page, "draft": draft, "section": section, "full": full,
                "width": width, "height": height, "scheme": scheme,
                "audit": audit,
            }  # fmt: skip
            return _client().request(
                "POST", f"/api/sessions/{sid}/look", body, timeout=LOOK_TIMEOUT_S
            )

        return await _run(work, look_image=True)

    @server.tool()
    async def ask(
        question: str,
        session: Session = None,
        choices: list[str] | None = None,
        multi: bool = False,
        text: bool = False,
        block: str | None = None,
        approval: bool = False,
        details: str | None = None,
        timeout_s: TimeoutS = DEFAULT_TIMEOUT_S,
    ) -> CallToolResult:
        """Ask the owner a question and wait; `timeout` and `dismissed` are results.

        `approval` shows Approve / Send back (value `{"decision": ...}`).
        """

        def work() -> dict[str, Any]:
            sid = _session(session)
            spec = build_ask_spec(
                question, choices or [], multi, text, block, approval, details
            )
            seconds, note = _clamp(timeout_s)
            client = _client()
            # An unknown id creates the session here, as the CLI does (SES-03).
            client.request(
                "POST", f"/api/sessions/{sid}/path", _creation_body(None, None)
            )
            result, _ = ask_once(client, sid, spec, seconds)
            return _with_note(result, note)

        return await _run(work, images=True)

    @server.tool()
    async def result(
        summary: str,
        session: Session = None,
        files: list[str] | None = None,
        decision: str | None = None,
        choices: list[str] | None = None,
    ) -> CallToolResult:
        """Leave a result card for the owner at the end of a job; does not wait.

        `files` are absolute paths; `decision` is one question with 2 to 6
        `choices`, answered as a `decision` event (see `wait_for_feedback`).
        """

        def work() -> dict[str, Any]:
            return send_result(
                _client(),
                _session(session),
                _creation_body(None, None),
                summary,
                files or [],
                decision,
                choices or [],
            )

        return await _run(work)

    @server.tool()
    async def wait_for_feedback(
        session: Session = None,
        timeout_s: TimeoutS = DEFAULT_TIMEOUT_S,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> CallToolResult:
        """Wait as a listener for feedback; returns {events, ended_reason}."""

        def work() -> dict[str, Any]:
            sid = _session(session)
            seconds, note = _clamp(timeout_s)
            if max_events < 1:
                raise CliError("usage", "max_events must be at least 1.")
            found = collect_events(_client().open_watch(sid), seconds, max_events)
            reason = "events" if found else "timeout"
            return _with_note({"events": found, "ended_reason": reason}, note)

        return await _run(work, images=True)

    @server.tool()
    async def pending(session: Session = None, peek: bool = False) -> CallToolResult:
        """Return the queued feedback and mark it delivered (peek leaves it queued)."""

        def work() -> dict[str, Any]:
            sid = _session(session)
            body = {"peek": peek, "via": "mcp"}
            return _client().request("POST", f"/api/sessions/{sid}/pending", body)

        return await _run(work, images=True)

    @server.tool()
    async def comments(
        session: Session = None,
        page: str | None = None,
        all: bool = False,
    ) -> CallToolResult:
        """List the owner's sent comments (open ones; `all` adds answered and done)."""

        def work() -> dict[str, Any]:
            query = {"page": page, "all": "1" if all else None}
            tail = urlencode({k: v for k, v in query.items() if v})
            path = f"/api/sessions/{_session(session)}/comments"
            return _client().request("GET", path + ("?" + tail if tail else ""))

        return await _run(work, images=True)

    @server.tool()
    async def answers(
        session: Session = None,
        page: str | None = None,
        open: bool = False,  # noqa: A002 - the tool's parameter name (ANS-04)
        wait: bool = False,
        ids: list[str] | None = None,
        timeout_s: TimeoutS | None = None,
    ) -> CallToolResult:
        """List the answers to Ask, Do, Decision and Options box items on shown pages.

        Consumes nothing; `open` keeps open Ask and Do items. With `wait`, block
        until each of `ids` (none: each item waiting now) is answered; a
        `timeout` status is a result, not an error.
        """

        def work() -> dict[str, Any]:
            sid = _session(session)
            client = _client()
            if not wait:
                if timeout_s is not None:
                    raise CliError("usage", "timeout_s needs wait.")
                query = {"page": page, "open": "1" if open else None}
                tail = urlencode({k: v for k, v in query.items() if v})
                path = f"/api/sessions/{sid}/answers" + (f"?{tail}" if tail else "")
                return client.request("GET", path)
            if open:
                raise CliError("usage", "open does not combine with wait.")
            seconds, note = _clamp(
                DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
            )
            result, _ = wait_answers(client, sid, ids or [], page, seconds)
            return _with_note(result, note)

        return await _run(work)

    async def reply_to_comment(
        page: str,
        n: int,
        text: str,
        session: Session = None,
        done: bool = False,
        from_: Annotated[str | None, Field(alias="from")] = None,
    ) -> CallToolResult:
        def work() -> dict[str, Any]:
            body = {"page": page, "n": n, "text": text, "done": done, "from": from_}
            path = f"/api/sessions/{_session(session)}/comments/reply"
            return _client().request("POST", path, body)

        return await _run(work)

    # `from` is a Python keyword: the library passes the argument under that
    # name, so the tool takes keywords and hands them on as `from_`.
    async def comment_reply(**arguments: Any) -> CallToolResult:
        """Answer comment `n` of `page`; `done` also closes it."""
        arguments["from_"] = arguments.pop("from", None)
        return await reply_to_comment(**arguments)

    comment_reply.__signature__ = inspect.signature(reply_to_comment, eval_str=True)  # type: ignore[attr-defined]
    server.tool()(comment_reply)

    @server.tool()
    async def comment_done(
        page: str,
        n: list[int],
        session: Session = None,
    ) -> CallToolResult:
        """Mark the comments `n` of `page` done."""

        def work() -> dict[str, Any]:
            path = f"/api/sessions/{_session(session)}/comments/done"
            return _client().request("POST", path, {"page": page, "n": n})

        return await _run(work)

    @server.tool()
    async def cleanup(
        older_than: str | None = None,
        delete_session: str | None = None,
        project: str | None = None,
        yes: bool = False,
        force: bool = False,
    ) -> CallToolResult:
        """Delete history by age (`older_than`, e.g. 30d) or for one session."""

        def work() -> dict[str, Any]:
            body = {
                "older_than": older_than,
                "session": delete_session,
                "project": project,
                "yes": yes,
                "force": force,
            }
            return _client().request("POST", "/api/cleanup", body)

        return await _run(work)

    return server


def main() -> int:
    """
    Serve the tools on stdio until the client closes the connection.

    Returns
    -------
    int
        Exit code 0.
    """
    create_server().run("stdio")
    return 0


# ---- helpers --------------------------------------------------------------


def _client() -> HubClient:
    """Hub client for the server's environment."""
    return client_from_environment()


def _session(argument: str | None) -> str:
    """Resolve the session: argument, else ``AGENT_CANVAS_SESSION`` (MCP-06)."""
    if not argument and not os.environ.get("AGENT_CANVAS_SESSION"):
        raise CliError("no-session", NO_SESSION_MESSAGE)
    try:
        return resolve_session_id(argument, os.environ)
    except InvalidSessionId as error:
        raise CliError("no-session", str(error)) from error


def _creation_body(project: str | None, agent: str | None) -> dict[str, Any]:
    """Project and agent fields for calls that may create a session."""
    environment = dict(os.environ)
    return {
        "project": resolve_project(project, environment, Path.cwd()),
        "agent": agent or environment.get("AGENT_CANVAS_AGENT") or "agent",
    }


def _clamp(timeout_s: float) -> tuple[float, str | None]:
    """Limit ``timeout_s`` to 1500 s and return a note saying so (MCP-05)."""
    if timeout_s <= 0:
        raise CliError("usage", "timeout_s must be above 0.")
    if timeout_s > MAX_TIMEOUT_S:
        return MAX_TIMEOUT_S, (
            f"timeout_s was clamped to {MAX_TIMEOUT_S} s (asked for {timeout_s:g})."
        )
    return timeout_s, None


def _with_note(result: dict[str, Any], note: str | None) -> dict[str, Any]:
    """Add the clamp note to a result when there is one."""
    return {**result, "note": note} if note else result


async def _run(
    work: Callable[[], dict[str, Any]],
    images: bool = False,
    look_image: bool = False,
) -> CallToolResult:
    """Run blocking ``work`` in a thread and wrap its outcome as a tool result."""
    try:
        result = await asyncio.to_thread(work)
    except CliError as error:
        body = {"error": error.code, "message": error.message}
        return CallToolResult(content=[_text(body)], is_error=True)
    blocks = [_text(result)]
    if images:
        blocks.extend(_images(result))
    if look_image:
        blocks.extend(_png_blocks([result.get("png")]))
    return CallToolResult(content=blocks)


def _text(payload: dict[str, Any]) -> TextContent:
    """Wrap ``payload`` as a JSON text block."""
    return TextContent(type="text", text=json.dumps(payload))


def _png_blocks(paths: list[Any]) -> list[ImageContent]:
    """Image blocks for the readable PNG files among ``paths``."""
    blocks: list[ImageContent] = []
    for path in paths:
        try:
            data = Path(path).read_bytes()
        except (OSError, TypeError):
            continue  # the path stays in the JSON; the agent can see why
        blocks.append(
            ImageContent(
                type="image",
                data=base64.b64encode(data).decode("ascii"),
                mime_type="image/png",
            )
        )
    return blocks


def _images(result: dict[str, Any]) -> list[ImageContent]:
    """Image blocks: comment pictures first, then screenshots of ``send`` events.

    Listed comments (``comments`` tool) give pictures only. At most
    ``MAX_IMAGES`` screenshots and ``MAX_RESULT_IMAGES`` images in all (A-50).
    """
    found = list(result.get("events") or [])
    if isinstance(result.get("event"), dict):
        found.append(result["event"])
    sends = [e for e in found if e.get("kind") == "send"]
    pictures = [c.get("picture") for e in sends for c in e.get("comments") or []]
    pictures += [c.get("picture") for c in result.get("comments") or []]
    screenshots = [e.get("screenshot") for e in sends]
    blocks = _png_blocks([p for p in pictures if p])
    blocks += _png_blocks([p for p in screenshots if p])[:MAX_IMAGES]
    return blocks[:MAX_RESULT_IMAGES]
