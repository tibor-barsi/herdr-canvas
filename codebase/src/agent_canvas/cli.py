"""Command-line entry point of agent-canvas.

Kept free of heavy imports so that short commands stay fast (NFR-04).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn

from agent_canvas import __version__
from agent_canvas.output import CliError, emit_error, emit_result

LOOK_TIMEOUT_SECONDS = 90  # window 10 s + a headless browser start and render


class _Parser(argparse.ArgumentParser):
    """Argument parser whose errors become ``usage`` errors (exit 2, JSON)."""

    def error(self, message: str) -> NoReturn:
        """Raise a usage error instead of printing text and exiting."""
        raise CliError("usage", message)


def _port(text: str) -> int:
    """Parse ``--port`` (1-65535)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {text!r}") from None
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"port out of range: {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for the ``agent-canvas`` command.
    """
    parser = _Parser(
        prog="agent-canvas",
        description="Local canvas where coding agents show pages and get feedback.",
    )
    parser.add_argument(
        "--version", action="version", version=f"agent-canvas {__version__}"
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    session_option = _Parser(add_help=False)
    session_option.add_argument("--session", metavar="ID", help="session id")
    creating = _Parser(add_help=False, parents=[session_option])
    creating.add_argument("--agent", help="agent name (default: agent)")
    creating.add_argument("--project", metavar="DIR", help="project directory")
    project_page = _Parser(add_help=False)
    project_page.add_argument(
        "--project-page",
        action="store_true",
        help="act on the pages of this session's project, shared by its sessions",
    )

    hub = commands.add_parser("hub", help="run the hub in the foreground")
    hub.add_argument("--port", type=_port, help="port to listen on")
    hub.set_defaults(handler=_cmd_hub)
    stop = commands.add_parser("stop", help="stop the running hub")
    stop.set_defaults(handler=_cmd_stop)
    status = commands.add_parser("status", help="show hub status")
    status.set_defaults(handler=_cmd_status)
    open_ = commands.add_parser("open", help="open the canvas window")
    open_.add_argument(
        "--print-url",
        action="store_true",
        help="print a fresh single-use login URL instead of opening a window",
    )
    open_.set_defaults(handler=_cmd_open)
    _add_session_commands(commands, session_option, creating)
    show = commands.add_parser(
        "show",
        help="show a page, PDF, Markdown file or picture "
        "(viewer_error says why a file could not be shown)",
        parents=[creating, project_page],
    )
    show.add_argument("name", nargs="?", help="page name (default page.html)")
    show.add_argument("--title", help="set the session title")
    show.add_argument("--copy", metavar="SRC", help="copy SRC into the session first")
    show.add_argument(
        "--publish",
        action="store_true",
        help="first replace the page by its draft NAME.draft.html",
    )
    show.add_argument(
        "--no-audit", action="store_true", help="skip the automatic page checks"
    )
    show.add_argument(
        "--kind",
        metavar="KIND",
        help="single-use, transitional or long-term: how long the page stays",
    )
    show.set_defaults(handler=_cmd_show)
    page = commands.add_parser("page", help="set what the canvas knows of a page")
    page_actions = page.add_subparsers(dest="action", metavar="<action>", required=True)
    page_kind = page_actions.add_parser(
        "kind", help="set the kind of a page", parents=[session_option, project_page]
    )
    page_kind.add_argument("name", help="page name")
    page_kind.add_argument("kind", help="single-use, transitional or long-term")
    page_kind.set_defaults(handler=_cmd_page_kind)
    for action, text in (
        ("archive", "take a page off its tab (files stay)"),
        ("restore", "bring an archived page back"),
        ("extend", "restart the lifetime of a page"),
    ):
        page_change = page_actions.add_parser(
            action, help=text, parents=[session_option]
        )
        page_change.add_argument("name", help="page name")
        page_change.set_defaults(handler=_cmd_page_change, page_action=action)
    page_list = page_actions.add_parser(
        "list",
        help="list the pages with kind and expiry",
        parents=[session_option, project_page],
    )
    page_list.add_argument(
        "--archived", action="store_true", help="include archived pages"
    )
    page_list.set_defaults(handler=_cmd_page_list)
    look = commands.add_parser(
        "look",
        help="render a page or its draft to a PNG and print where it is "
        "(viewer_error says why a PDF, Markdown file or picture could not be shown)",
        parents=[session_option, project_page],
    )
    look.add_argument("name", nargs="?", help="page name (default: the active page)")
    look.add_argument("--draft", action="store_true", help="render NAME.draft.html")
    look.add_argument(
        "--section", metavar="ID", help="crop to this id or data-canvas-id"
    )
    look.add_argument(
        "--full", action="store_true", help="capture the whole page height"
    )
    look.add_argument(
        "--width", type=int, help="viewport width (default: the window's)"
    )
    look.add_argument(
        "--height", type=int, help="viewport height (default: the window's)"
    )
    look.add_argument(
        "--scheme",
        choices=["light", "dark"],
        help="colour scheme (default: the window's)",
    )
    look.add_argument(
        "--no-audit", action="store_true", help="skip the automatic page checks"
    )
    look.set_defaults(handler=_cmd_look)
    new = commands.add_parser(
        "new",
        help="write a page from a template into the session folder",
        parents=[creating],
    )
    new.add_argument("name", nargs="?", help="page name (.html is added)")
    new.add_argument("--template", help="template name (see --list)")
    new.add_argument("--list", action="store_true", help="list the templates")
    new.add_argument("--force", action="store_true", help="overwrite an existing file")
    new.add_argument(
        "--draft",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="write NAME.draft.html, a private draft (default); "
        "--no-draft writes NAME.html",
    )
    new.set_defaults(handler=_cmd_new)
    watch = commands.add_parser(
        "watch", help="stream feedback events as JSON Lines", parents=[session_option]
    )
    watch.add_argument(
        "--timeout", type=float, help="seconds, cut to the limit (default: the limit)"
    )
    watch.add_argument("--count", type=int, help="stop after N events")
    watch.set_defaults(handler=_cmd_watch)
    ask = commands.add_parser(
        "ask", help="ask the owner a question and wait", parents=[creating]
    )
    ask.add_argument("question", help="the question shown on the card")
    ask.add_argument(
        "--choice",
        action="append",
        default=[],
        metavar="LABEL",
        help="an answer button",
    )
    ask.add_argument("--multi", action="store_true", help="allow several choices")
    ask.add_argument("--text", action="store_true", help="add a text field")
    ask.add_argument("--block", metavar="ID", help="wait on this data-canvas-id")
    ask.add_argument(
        "--approval",
        action="store_true",
        help="an approval card: Approve and Send back (answer: decision)",
    )
    details = ask.add_mutually_exclusive_group()
    details.add_argument(
        "--details", help="text of the approval card (4000 characters)"
    )
    details.add_argument(
        "--details-file", metavar="PATH", help="read the details from a file"
    )
    ask.add_argument("--timeout", type=float, help="seconds (default: ask_timeout)")
    ask.set_defaults(handler=_cmd_ask)
    result = commands.add_parser(
        "result",
        help="leave a result card for the owner (does not wait)",
        parents=[creating],
    )
    result.add_argument("summary", help="what was done (at most 2000 characters)")
    result.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="PATH",
        help="a file the card offers (at most 20)",
    )
    result.add_argument("--decision", help="the one decision left, as a question")
    result.add_argument(
        "--choice",
        action="append",
        default=[],
        metavar="LABEL",
        help="a button of the decision (2 to 6)",
    )
    result.set_defaults(handler=_cmd_result)
    pending = commands.add_parser(
        "pending",
        help="return queued events and reminders of expired pages",
        parents=[session_option],
    )
    pending.add_argument("--peek", action="store_true", help="leave them queued")
    pending.set_defaults(handler=_cmd_pending)
    answers = commands.add_parser(
        "answers",
        help="list the answers to the cards in the shown pages, or wait for them",
        parents=[session_option, project_page],
    )
    answers.add_argument("--page", metavar="P", help="only this page")
    answers.add_argument("--open", action="store_true", help="only open Ask and Do")
    answers.add_argument(
        "--wait",
        nargs="*",
        metavar="ID",
        help="wait until each ID (none: each waiting item) is answered; exit 6 at "
        "the timeout",
    )
    answers.add_argument("--timeout", type=float, help="seconds (default: ask_timeout)")
    answers.set_defaults(handler=_cmd_answers)
    comment = commands.add_parser(
        "comment", help="read, answer and close the owner's comments"
    )
    comment_actions = comment.add_subparsers(
        dest="action", metavar="<action>", required=True
    )
    comment_list = comment_actions.add_parser(
        "list", help="list sent comments", parents=[session_option, project_page]
    )
    comment_list.add_argument("page", nargs="?", help="only this page")
    comment_list.add_argument(
        "--all",
        action="store_true",
        help="also the comments that are not open (answered, done)",
    )
    comment_list.set_defaults(handler=_cmd_comment_list)
    comment_reply = comment_actions.add_parser(
        "reply", help="answer a comment", parents=[session_option, project_page]
    )
    comment_reply.add_argument("page")
    comment_reply.add_argument("n", type=int, help="comment number")
    comment_reply.add_argument("text")
    comment_reply.add_argument("--done", action="store_true", help="also mark it done")
    comment_reply.add_argument(
        "--from", dest="author", metavar="NAME", help="reply as NAME (default: agent)"
    )
    comment_reply.set_defaults(handler=_cmd_comment_reply)
    comment_done = comment_actions.add_parser(
        "done", help="mark comments done", parents=[session_option, project_page]
    )
    comment_done.add_argument("page")
    comment_done.add_argument("n", type=int, nargs="+", help="comment numbers")
    comment_done.set_defaults(handler=_cmd_comment_done)
    guide = commands.add_parser("guide", help="print the agent guideline (Markdown)")
    guide.add_argument(
        "topic",
        nargs="?",
        choices=["blocks", "project-pages"],
        help="blocks: the block reference; project-pages: shared project pages",
    )
    guide.set_defaults(handler=_cmd_guide)
    mcp = commands.add_parser("mcp", help="run the MCP server on stdio")
    mcp.set_defaults(handler=_cmd_mcp)
    hook = commands.add_parser("hook", help="run a Claude Code hook (JSON on stdin)")
    hook.add_argument(
        "name",
        choices=[
            "session-start",
            "user-prompt-submit",
            "session-end",
            "stop",
        ],
        help="the hook to run",
    )
    hook.set_defaults(handler=_cmd_hook)
    _add_operations_commands(commands)
    return parser


def _add_operations_commands(commands: Any) -> None:
    """Add ``cleanup`` and ``install-service``."""
    cleanup = commands.add_parser(
        "cleanup",
        help="delete history by age or for one session (dry run unless --yes)",
    )
    cleanup.add_argument("--older-than", metavar="AGE", help="for example 30d, 12h")
    cleanup.add_argument("--session", metavar="ID", help="clean this session")
    cleanup.add_argument("--project", metavar="DIR", help="only this project")
    cleanup.add_argument("--yes", action="store_true", help="really delete")
    cleanup.add_argument(
        "--force", action="store_true", help="also delete queued events"
    )
    cleanup.set_defaults(handler=_cmd_cleanup)
    service = commands.add_parser(
        "install-service", help="install the hub as a systemd user service"
    )
    service.add_argument("--print", action="store_true", help="print the unit only")
    service.add_argument(
        "--no-enable", action="store_true", help="write the unit, do not enable it"
    )
    service.set_defaults(handler=_cmd_install_service)
    tunnel = commands.add_parser(
        "install-tunnel",
        help="install a systemd user service that forwards the hub port over SSH",
    )
    tunnel.add_argument("host", metavar="HOST", help="ssh host name of the hub machine")
    tunnel.add_argument(
        "--port", type=_port, help="port on both ends (default: the configured port)"
    )
    tunnel.add_argument("--print", action="store_true", help="print the unit only")
    tunnel.add_argument(
        "--no-enable", action="store_true", help="write the unit, do not enable it"
    )
    tunnel.set_defaults(handler=_cmd_install_tunnel)
    untunnel = commands.add_parser(
        "uninstall-tunnel", help="stop and remove the SSH tunnel service"
    )
    untunnel.set_defaults(handler=_cmd_uninstall_tunnel)


def _add_session_commands(
    commands: Any, session_option: argparse.ArgumentParser, creating: Any
) -> None:
    """Add ``session start|path|set|end|list``."""
    session = commands.add_parser("session", help="manage sessions")
    actions = session.add_subparsers(dest="action", metavar="<action>", required=True)
    start = actions.add_parser("start", help="create a new session")
    start.add_argument("--agent", help="agent name (default: agent)")
    start.add_argument("--title", help="session title")
    start.add_argument("--project", metavar="DIR", help="project directory")
    start.set_defaults(handler=_cmd_session_start)
    path = actions.add_parser(
        "path", help="print the session folder", parents=[creating]
    )
    path.add_argument(
        "--project-page",
        action="store_true",
        help="print the folder of the pages of this session's project",
    )
    path.set_defaults(handler=_cmd_session_path)
    set_ = actions.add_parser(
        "set", help="set the session title", parents=[session_option]
    )
    set_.add_argument("--title", required=True, help="new title")
    set_.set_defaults(handler=_cmd_session_set)
    end = actions.add_parser("end", help="end the session", parents=[session_option])
    end.set_defaults(handler=_cmd_session_end)
    listing = actions.add_parser("list", help="list sessions")
    listing.add_argument("--all", action="store_true", help="include ended and hidden")
    listing.add_argument("--project", metavar="DIR", help="only this project")
    listing.set_defaults(handler=_cmd_session_list)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the command line.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Arguments without the program name. Default is ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code (requirements 5.5).
    """
    try:
        arguments = build_parser().parse_args(argv)
        handler: Callable[[argparse.Namespace], int] | None = getattr(
            arguments, "handler", None
        )
        if handler is None:
            build_parser().print_help()
            return 0
        return handler(arguments)
    except CliError as error:
        return emit_error(error)


# ---- command handlers ---------------------------------------------------------


def _client() -> Any:
    """Build a hub client from the environment (imports lazily)."""
    from agent_canvas.client import client_from_environment

    return client_from_environment()


def _session_id(arguments: argparse.Namespace) -> str:
    """Resolve the session id or raise a ``no-session`` error (SES-02)."""
    from agent_canvas.paths_safe import InvalidSessionId, resolve_session_id

    try:
        return resolve_session_id(arguments.session, os.environ)
    except InvalidSessionId as error:
        raise CliError("no-session", str(error)) from error


def _project_page(caller: str) -> dict[str, Any]:
    """Ask the hub for the project pages of the caller's project (PROJ-02)."""
    path = f"/api/sessions/{caller}/project-page"
    return _client().request("POST", path, {})


def _target_id(arguments: argparse.Namespace) -> str:
    """Return the session to act on: the caller, or its project pages (PROJ-03)."""
    caller = _session_id(arguments)
    return _project_page(caller)["session"] if arguments.project_page else caller


def _creation_body(arguments: argparse.Namespace) -> dict[str, Any]:
    """Project and agent fields for commands that may create a session."""
    from agent_canvas.client import resolve_project

    return {
        "project": resolve_project(arguments.project, dict(os.environ), Path.cwd()),
        "agent": arguments.agent or os.environ.get("AGENT_CANVAS_AGENT") or "agent",
    }


def _cmd_hub(arguments: argparse.Namespace) -> int:
    """Run the hub in the foreground (imports the server stack lazily)."""
    from dataclasses import replace

    from agent_canvas.config import ConfigError, load_config
    from agent_canvas.hub.app import run_hub
    from agent_canvas.hub.auth import KeyFileError
    from agent_canvas.hub.registry import RegistryError
    from agent_canvas.paths import state_dir

    try:
        config = load_config()
        if arguments.port:
            config = replace(config, port=arguments.port)
        run_hub(config, state_dir())
    except (ConfigError, KeyFileError, RegistryError) as error:
        raise CliError("failed", str(error)) from error
    return 0


def _cmd_stop(arguments: argparse.Namespace) -> int:
    """Stop the hub: through systemd if the service runs, else over the API."""
    from agent_canvas.service import stop_service

    if stop_service():  # a running service would restart a hub that only exits
        return emit_result({"stopped": True, "via": "systemd"})
    return emit_result({"stopped": _client().stop(), "via": "api"})


def _cmd_status(arguments: argparse.Namespace) -> int:
    """Print the hub status."""
    return emit_result(_client().request("GET", "/api/status"))


def _cmd_open(arguments: argparse.Namespace) -> int:
    """Open the window, or with ``--print-url`` print a login URL (CLI-18)."""
    if arguments.print_url:
        answer = _client().request("POST", "/api/open", {"print_url": True})
        sys.stdout.write(f"{answer['url']}\n")
        sys.stdout.flush()
        return 0
    return emit_result(_client().request("POST", "/api/open", {}))


def _cmd_session_start(arguments: argparse.Namespace) -> int:
    """Create a session with a fresh id."""
    body = _creation_body(arguments)
    body["title"] = arguments.title
    return emit_result(_client().request("POST", "/api/sessions", body))


def _cmd_session_path(arguments: argparse.Namespace) -> int:
    """Print the session folder, creating the session if unknown."""
    session_id = _session_id(arguments)
    if arguments.project_page:
        return emit_result(_project_page(session_id))
    body = _creation_body(arguments)
    return emit_result(
        _client().request("POST", f"/api/sessions/{session_id}/path", body)
    )


def _cmd_session_set(arguments: argparse.Namespace) -> int:
    """Set the session title."""
    session_id = _session_id(arguments)
    body = {"title": arguments.title}
    return emit_result(
        _client().request("POST", f"/api/sessions/{session_id}/title", body)
    )


def _cmd_session_end(arguments: argparse.Namespace) -> int:
    """Mark the session ended."""
    session_id = _session_id(arguments)
    return emit_result(_client().request("POST", f"/api/sessions/{session_id}/end", {}))


def _cmd_session_list(arguments: argparse.Namespace) -> int:
    """List sessions."""
    from urllib.parse import urlencode

    query: dict[str, str] = {}
    if arguments.all:
        query["all"] = "1"
    if arguments.project:
        query["project"] = str((Path.cwd() / arguments.project).resolve())
    path = "/api/sessions" + (f"?{urlencode(query)}" if query else "")
    return emit_result({"sessions": _client().request("GET", path)})


def _cmd_show(arguments: argparse.Namespace) -> int:
    """Register and show a page."""
    session_id = _target_id(arguments)
    body = _creation_body(arguments)
    body.update(name=arguments.name, title=arguments.title)
    if arguments.project_page:
        body["by"] = _session_id(arguments)
    if arguments.publish:
        body["publish"] = True
    if arguments.no_audit:
        body["audit"] = False
    if arguments.copy:
        body["copy"] = str((Path.cwd() / arguments.copy).resolve())
    if arguments.kind:
        body["kind"] = arguments.kind
    return emit_result(
        _client().request("POST", f"/api/sessions/{session_id}/show", body)
    )


def _cmd_page_kind(arguments: argparse.Namespace) -> int:
    """Set a page's kind (LIFE-01)."""
    body = {"action": "kind", "name": arguments.name, "kind": arguments.kind}
    path = f"/api/sessions/{_target_id(arguments)}/pages"
    return emit_result(_client().request("POST", path, body))


def _cmd_page_change(arguments: argparse.Namespace) -> int:
    """Archive, restore or extend a page (LIFE-04, LIFE-05)."""
    body = {"action": arguments.page_action, "name": arguments.name}
    path = f"/api/sessions/{_session_id(arguments)}/pages"
    return emit_result(_client().request("POST", path, body))


def _cmd_page_list(arguments: argparse.Namespace) -> int:
    """List the session's pages (LIFE-05)."""
    path = f"/api/sessions/{_target_id(arguments)}/pages"
    if arguments.archived:
        path += "?archived=1"
    return emit_result(_client().request("GET", path))


def _cmd_look(arguments: argparse.Namespace) -> int:
    """Render a page or draft and print the PNG's path (LOOK-01)."""
    session_id = _target_id(arguments)
    body = {
        "page": arguments.name,
        "draft": arguments.draft,
        "section": arguments.section,
        "full": arguments.full,
        "width": arguments.width,
        "height": arguments.height,
        "scheme": arguments.scheme,
        "audit": not arguments.no_audit,
    }
    return emit_result(
        _client().request(
            "POST",
            f"/api/sessions/{session_id}/look",
            body,
            timeout=LOOK_TIMEOUT_SECONDS,
        )
    )


def _cmd_new(arguments: argparse.Namespace) -> int:
    """Write a page from a template (KIT-03), or list the templates."""
    from agent_canvas.templates import describe_templates, new_page_result

    if arguments.list:
        return emit_result(describe_templates())
    if not arguments.name or not arguments.template:
        raise CliError("usage", "new needs NAME and --template (or --list).")
    session_id = _session_id(arguments)
    client = _client()
    # An unknown id creates the session here, as in `show` (SES-03).
    path = f"/api/sessions/{session_id}/path"
    folder = client.request("POST", path, _creation_body(arguments))["folder"]
    return emit_result(
        new_page_result(
            Path(folder),
            arguments.name,
            arguments.template,
            arguments.force,
            arguments.draft,
        )
    )


def _cmd_pending(arguments: argparse.Namespace) -> int:
    """Return (and mark delivered) the queued events (CLI-09)."""
    session_id = _session_id(arguments)
    body = {"peek": arguments.peek}
    return emit_result(
        _client().request("POST", f"/api/sessions/{session_id}/pending", body)
    )


def _cmd_answers(arguments: argparse.Namespace) -> int:
    """List the cards' answers, or wait for named ones (ANS-04, ANS-05)."""
    from urllib.parse import urlencode

    session_id = _target_id(arguments)
    if arguments.wait is None:
        if arguments.timeout is not None:
            raise CliError("usage", "--timeout needs --wait.")
        query = {"page": arguments.page, "open": "1" * arguments.open}
        tail = urlencode({k: v for k, v in query.items() if v})
        path = f"/api/sessions/{session_id}/answers" + (f"?{tail}" if tail else "")
        return emit_result(_client().request("GET", path))
    from agent_canvas.answers import wait_answers
    from agent_canvas.config import ConfigError, load_config

    if arguments.open:
        raise CliError("usage", "--open does not combine with --wait.")
    try:
        timeout = arguments.timeout or load_config().ask_timeout_seconds
    except ConfigError as error:
        raise CliError("failed", str(error)) from error
    if timeout <= 0:
        raise CliError("usage", "--timeout must be above 0.")
    result, code = wait_answers(
        _client(), session_id, arguments.wait, arguments.page, timeout
    )
    return emit_result(result, code)


def _cmd_comment_list(arguments: argparse.Namespace) -> int:
    """List the session's sent comments; drafts never appear (RPL-01)."""
    from urllib.parse import urlencode

    session_id = _target_id(arguments)
    query = {
        k: v for k, v in (("page", arguments.page), ("all", "1" * arguments.all)) if v
    }
    path = f"/api/sessions/{session_id}/comments"
    if query:
        path += "?" + urlencode(query)
    return emit_result(_client().request("GET", path))


def _cmd_comment_reply(arguments: argparse.Namespace) -> int:
    """Answer a comment, optionally marking it done (RPL-02)."""
    body = {
        "page": arguments.page,
        "n": arguments.n,
        "text": arguments.text,
        "done": arguments.done,
        "from": arguments.author,
    }
    path = f"/api/sessions/{_target_id(arguments)}/comments/reply"
    return emit_result(_client().request("POST", path, body))


def _cmd_comment_done(arguments: argparse.Namespace) -> int:
    """Mark comments done (RPL-02)."""
    body = {"page": arguments.page, "n": arguments.n}
    path = f"/api/sessions/{_target_id(arguments)}/comments/done"
    return emit_result(_client().request("POST", path, body))


def _cmd_watch(arguments: argparse.Namespace) -> int:
    """Stream events until the timeout or count (CLI-07)."""
    from agent_canvas.config import ConfigError, load_config
    from agent_canvas.reconnect import reconnect
    from agent_canvas.watch import run_watch

    session_id = _session_id(arguments)
    try:
        limit = load_config().watch_max_minutes * 60
    except ConfigError as error:
        raise CliError("failed", str(error)) from error
    timeout = limit if arguments.timeout is None else min(arguments.timeout, limit)
    if not timeout > 0:
        raise CliError("usage", "--timeout must be above 0 s.")
    if arguments.count is not None and arguments.count < 1:
        raise CliError("usage", "--count must be at least 1.")
    client = _client()
    socket = client.open_watch(session_id)

    def reopen() -> Any:
        return reconnect(lambda: client.open_watch(session_id, start=False))

    return run_watch(socket, timeout, arguments.count, reopen)


def _ask_spec(arguments: argparse.Namespace) -> dict[str, Any]:
    """Build the ask request from the arguments, or raise a usage error."""
    from agent_canvas.ask import build_ask_spec

    details = arguments.details
    if arguments.details_file is not None:
        try:
            details = Path(arguments.details_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CliError("usage", f"Cannot read --details-file: {error}") from error
    return build_ask_spec(
        arguments.question,
        arguments.choice,
        arguments.multi,
        arguments.text,
        arguments.block,
        arguments.approval,
        details,
    )


def _cmd_ask(arguments: argparse.Namespace) -> int:
    """Show a question card (or highlight a block) and wait (CLI-04 to CLI-06)."""
    from agent_canvas.ask import run_ask
    from agent_canvas.config import ConfigError, load_config

    session_id = _session_id(arguments)
    spec = _ask_spec(arguments)
    try:
        timeout = arguments.timeout or load_config().ask_timeout_seconds
    except ConfigError as error:
        raise CliError("failed", str(error)) from error
    if arguments.timeout is not None and arguments.timeout <= 0:
        raise CliError("usage", "--timeout must be above 0.")
    client = _client()
    # An unknown id creates the session here, as in `show` (SES-03).
    path = f"/api/sessions/{session_id}/path"
    client.request("POST", path, _creation_body(arguments))
    return run_ask(client, session_id, spec, timeout)


def _cmd_result(arguments: argparse.Namespace) -> int:
    """Store the result card of the session (RES-01)."""
    from agent_canvas.result import send_result

    answer = send_result(
        _client(),
        _session_id(arguments),
        _creation_body(arguments),
        arguments.summary,
        arguments.file,
        arguments.decision,
        arguments.choice,
    )
    return emit_result(answer)


def _cmd_cleanup(arguments: argparse.Namespace) -> int:
    """Delete history by age or for one session (CLI-11)."""
    from agent_canvas.hub.cleanup import CleanupError, parse_age

    if (arguments.older_than is None) == (arguments.session is None):
        raise CliError("usage", "Give exactly one of --older-than and --session.")
    if arguments.older_than is not None:
        try:
            parse_age(arguments.older_than)
        except CleanupError as error:
            raise CliError("usage", str(error)) from error
    body = {
        "older_than": arguments.older_than,
        "session": arguments.session,
        "project": (
            str((Path.cwd() / arguments.project).resolve())
            if arguments.project
            else None
        ),
        "yes": arguments.yes,
        "force": arguments.force,
    }
    return emit_result(_client().request("POST", "/api/cleanup", body))


def _cmd_install_service(arguments: argparse.Namespace) -> int:
    """Write the systemd user unit and enable it (OPS-02)."""
    from agent_canvas.service import (
        ServiceError,
        install_service,
        render_unit,
        resolve_executable,
        unit_directory,
    )

    try:
        executable = resolve_executable()
        if arguments.print:
            sys.stdout.write(render_unit(executable))
            sys.stdout.flush()
            return 0
        result = install_service(
            unit_directory(),
            executable,
            enable=not arguments.no_enable,
            stop_hub=lambda: _client().stop(),
        )
    except ServiceError as error:
        raise CliError("failed", str(error)) from error
    return emit_result(result)


def _cmd_install_tunnel(arguments: argparse.Namespace) -> int:
    """Write the SSH tunnel unit and enable it (OPS-07)."""
    from agent_canvas.config import ConfigError, load_config
    from agent_canvas.service import ServiceError, unit_directory
    from agent_canvas.tunnel import (
        agent_socket_setting,
        install_tunnel,
        local_hub_warnings,
        render_tunnel_unit,
        resolve_ssh,
    )

    try:
        port = arguments.port or load_config().port
        ssh = resolve_ssh()
        auth_socket = agent_socket_setting(os.environ)
        if arguments.print:
            sys.stdout.write(render_tunnel_unit(ssh, arguments.host, port, auth_socket))
            sys.stdout.flush()
            return 0
        # Before installing: afterwards the tunnel itself answers on the port.
        for warning in local_hub_warnings(port):
            sys.stderr.write(f"warning: {warning}\n")
        result = install_tunnel(
            unit_directory(),
            ssh,
            arguments.host,
            port,
            enable=not arguments.no_enable,
            auth_socket=auth_socket,
        )
    except (ConfigError, ServiceError) as error:
        raise CliError("failed", str(error)) from error
    return emit_result(result)


def _cmd_uninstall_tunnel(arguments: argparse.Namespace) -> int:
    """Stop, disable and remove the SSH tunnel unit (OPS-08)."""
    from agent_canvas.service import ServiceError, unit_directory
    from agent_canvas.tunnel import uninstall_tunnel

    try:
        result = uninstall_tunnel(unit_directory())
    except ServiceError as error:
        raise CliError("failed", str(error)) from error
    return emit_result(result)


def _cmd_guide(arguments: argparse.Namespace) -> int:
    """Print the guideline (the plugin skill body, CLI-13) or the block reference."""
    from agent_canvas.guide_text import blocks_text, guide_text, project_pages_text

    topics = {"blocks": blocks_text, "project-pages": project_pages_text}
    sys.stdout.write(topics.get(arguments.topic, guide_text)())
    sys.stdout.flush()
    return 0


def _cmd_mcp(arguments: argparse.Namespace) -> int:
    """Serve the MCP tools on stdio (imports the MCP SDK lazily, NFR-04)."""
    from agent_canvas.mcp_server import main as serve

    return serve()


def _cmd_hook(arguments: argparse.Namespace) -> int:
    """Run a Claude Code hook; it never fails the prompt (PLG-04 to PLG-06)."""
    from agent_canvas.hooks import main as run

    return run(arguments.name)


if __name__ == "__main__":
    sys.exit(main())
