"""The message tables between page, window and hub are complete and agree (P33.2).

Read from the sources: every type a sender writes or a handler compares has a row,
every row has a sender, and the window's and the hub's tables of the same direction
name the same types and fields (SEC-09, ARC-04).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_canvas.hub.messages import WINDOW_MESSAGES
from agent_canvas.hub.routes.sockets import SHELL_MESSAGES

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "src/agent_canvas"
STATIC = PACKAGE / "static"
# Every script outside vendor/ is scanned; these run in the page, others: window.
PAGE_SIDE = ("helper.js", "comments-layer.js", "blocks/", "kinds/", "kit/", "viewer/")
SCRIPTS = sorted(
    p.relative_to(STATIC).as_posix()
    for p in STATIC.rglob("*.js")
    if p.relative_to(STATIC).parts[0] != "vendor"
)
PAGE_FILES = tuple(name for name in SCRIPTS if name.startswith(PAGE_SIDE))
WINDOW_FILES = tuple(name for name in SCRIPTS if not name.startswith(PAGE_SIDE))
# Not messages: the HTML ``type`` of the buttons and inputs these files build
# (``h("button", {type: "button"})`` and the like).
NOT_MESSAGES = {
    "blocks/animation.js": {"button", "range"},
    "blocks/ask.js": {"button", "checkbox", "number", "text"},
    "blocks/buttons.js": {"button"},
    "blocks/choices.js": {"button"},
    "blocks/compare.js": {"range"},
    "blocks/decision.js": {"button", "text"},
    "blocks/do.js": {"button", "checkbox"},
    "blocks/document.js": {"button"},
    "blocks/file.js": {"button"},
    "blocks/image.js": {"button"},
    "blocks/model.js": {"button"},
    "blocks/plot.js": {"button", "text"},
    "blocks/progress.js": {"button"},
    "blocks/scene-list.js": {"button", "checkbox", "color", "range"},
    "blocks/scene.js": {"button", "range"},
    "blocks/source.js": {"button", "text"},
    "blocks/textbox.js": {"button"},
    "cards.js": {"button", "checkbox", "text"},
    "kinds/answer-area.js": {"button", "text"},
    "viewer/pdf.js": {"button"},
}
# The helper's answers to render.js, which takes them by request id, not by type.
RENDER_REPLIES = {"render-prepared", "render-audit-result"}
# Built by the hub for the command line's sockets (watch, ask, wait), not a window.
CLI_TYPES = {"event", "registered", "result"}
LITERAL = re.compile(r'\btype: "([a-z-]+)"')
TO_HUB_CALL = re.compile(r'sendToHub\(\{\s*type: "([a-z-]+)"')
COMPARED = re.compile(r'(?<!typeof )\b(?:message|data)\.type [!=]== "([a-z-]+)"')
ROW = re.compile(r'\["([a-z-]+)", \{(.*?)\}\]', re.S)
# The guard's limits and hidden list before P33.2 (ALLOWED_TYPES, HIDDEN_TYPES).
LIMITS = {
    "heartbeat": "MAX_MESSAGE_BYTES", "ready": "MAX_MESSAGE_BYTES",
    "report": "MAX_MESSAGE_BYTES", "reload": "MAX_MESSAGE_BYTES",
    "navigate": "MAX_MESSAGE_BYTES", "action": "MAX_MESSAGE_BYTES",
    "emit": "MAX_MESSAGE_BYTES", "key": "MAX_MESSAGE_BYTES", "drag-notice": "100",
    "capture-result": "MAX_SCREENSHOT_MESSAGE_BYTES",
    "comment-selection": "MAX_MESSAGE_BYTES", "comment-marker": "MAX_MESSAGE_BYTES",
    "comment-lost": "MAX_MESSAGE_BYTES",
    "comment-picture": "MAX_SCREENSHOT_MESSAGE_BYTES",
    "answer": "200 * 1024", "tick": "10 * 1024", "relay-open": "4 * 1024",
    "contents": "64 * 1024", "block-state": "1024", "scroll-pos": "200",
}  # fmt: skip
HIDDEN = {
    "heartbeat", "ready", "relay-open", "report", "reload", "block-state", "scroll-pos",
}  # fmt: skip


def source(name: str) -> str:
    """Return a static file's text."""
    return (STATIC / name).read_text()


def js_table(name: str, table: str) -> dict[str, dict]:
    """Parse ``const TABLE = new Map([...])`` of a static file: type -> row."""
    text = source(name)
    start = text.index(f"const {table} = new Map([")
    block = text[start : text.index("]);", start)]
    rows = {}
    for kind, body in ROW.findall(block):
        fields = re.search(r"fields: \[([^\]]*)\]", body)
        limit = re.search(r"limit: ([^,]+),", body)
        hidden = re.search(r"hidden: (true|false)", body)
        handle = re.search(r"handle: (\w+)", body)
        rows[kind] = {
            "fields": re.findall(r'"([^"]+)"', fields.group(1)),
            "limit": limit.group(1) if limit else None,
            "hidden": hidden.group(1) == "true" if hidden else None,
            "handle": handle.group(1) if handle else None,
        }
    assert len(rows) == len(re.findall(r'^\s*\["', block, re.M)) > 0, table
    return rows


def sent_types(names: tuple[str, ...]) -> tuple[set[str], set[str]]:
    """Return the types written as literals in ``names``: (to the hub, the rest)."""
    hub, other = set(), set()
    for name in names:
        text = source(name)
        calls = [m.span() for m in TO_HUB_CALL.finditer(text)]
        for m in LITERAL.finditer(text):
            if m.group(1) in NOT_MESSAGES.get(name, set()):
                continue
            inside = any(a <= m.start() < b for a, b in calls)
            (hub if inside else other).add(m.group(1))
    return hub, other


def test_sec_09_every_type_the_page_sends_has_a_row_in_the_window_tables() -> None:
    frame = js_table("shell.js", "FRAME_MESSAGES")
    private = js_table("shell.js", "PRIVATE_MESSAGES")
    _, sent = sent_types(PAGE_FILES)
    sent |= set(re.findall(r'sendAnswer\("([a-z-]+)"', source("helper.js")))
    assert sent - RENDER_REPLIES - set(frame) - set(private) == set()
    assert set(frame) | set(private) <= sent  # no row without a sender
    assert set(frame) & set(private) == set()


def test_sec_09_the_frame_table_keeps_todays_limits_and_hidden_list() -> None:
    frame = js_table("shell.js", "FRAME_MESSAGES")
    assert {kind: row["limit"] for kind, row in frame.items()} == LIMITS
    assert {kind for kind, row in frame.items() if row["hidden"]} == HIDDEN
    assert all(row["hidden"] is not None for row in frame.values())


def test_sec_09_every_type_the_window_sends_the_page_has_a_helper_row() -> None:
    parent = js_table("helper.js", "PARENT_MESSAGES")
    _, sent = sent_types(WINDOW_FILES)
    # ``relay-open`` is answered by the helper's private-channel listener.
    assert sent - {"relay-open"} == set(parent)


def test_arc_04_the_hub_has_a_row_for_every_type_the_window_sends() -> None:
    sent, _ = sent_types(WINDOW_FILES)
    assert sent == set(SHELL_MESSAGES)


def test_arc_04_the_window_and_the_hub_agree_on_what_the_hub_sends() -> None:
    from_hub = js_table("shell.js", "HUB_MESSAGES")
    built = set()
    for path in (PACKAGE / "hub").rglob("*.py"):
        built |= set(re.findall(r'"type": "([a-z-]+)"', path.read_text()))
    assert built - CLI_TYPES == set(WINDOW_MESSAGES) == set(from_hub)
    for kind, fields in WINDOW_MESSAGES.items():
        assert set(from_hub[kind]["fields"]) == set(fields), kind


def test_sec_09_every_type_a_handler_compares_is_a_table_row() -> None:
    parent = js_table("helper.js", "PARENT_MESSAGES")
    rows = set(parent)
    for table in ("FRAME_MESSAGES", "PRIVATE_MESSAGES", "HUB_MESSAGES"):
        rows |= set(js_table("shell.js", table))
    compared = set()
    for name in PAGE_FILES + WINDOW_FILES:
        compared |= set(COMPARED.findall(source(name)))
    assert compared
    assert compared - rows == set()
    # The comment layer handles exactly the helper's rows that go on to it.
    to_layer = {kind for kind, row in parent.items() if row["handle"] == "toLayer"}
    layer = set(COMPARED.findall(source("comments-layer.js")))
    assert layer == to_layer | {"comment-mode"}
