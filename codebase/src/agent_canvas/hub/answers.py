"""The answer store: cards read from page sources, answers kept per page (5.15).

The hub reads the six card tags from a page's current version (A-85) and keeps
the latest answer of each Ask, Do, Decision and Options box (with a submit
button) in ``.answers/<page>.json`` (ANS-01). An item's key is the hash of its
key fields; a changed key under the same id makes the item open again and moves
the old answer to its history.
Everything here runs on the hub's event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from agent_canvas.files_safe import ANSWERS_DIR, write_safely
from agent_canvas.hub.registry import now_iso
from agent_canvas.hub.watcher import PageHistory, is_page_name
from agent_canvas.paths_safe import UnsafePathError, validate_page_name

SCHEMA = "agent-canvas/answers@1"
MAX_ITEMS = 200
MAX_HISTORY = 20
ITEM_KINDS = {
    "canvas-ask": "ask", "canvas-do": "do", "canvas-decision": "decision",
    "canvas-choices": "choices",
}  # fmt: skip
CARD_TAGS = (*ITEM_KINDS, "canvas-report", "canvas-alert", "canvas-live")
POINT_CHILDREN = ("canvas-plot", "canvas-image", "canvas-model", "canvas-scene")
TRACKED_TAGS = (*CARD_TAGS, "canvas-file", "canvas-source", *POINT_CHILDREN)
VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta source track wbr".split()
)
TEXT_FIELD = {"ask": "question", "do": "title", "decision": "text", "choices": "submit"}
KEY_FIELDS = {
    "ask": ("question", "form", "options"),
    "do": ("title", "steps", "run"),
    "decision": ("text",),
    "choices": ("options",),
}
READ_KINDS = ("answer", "todo", "change", "choice")
NEED_KINDS = ("ask", "do")
OPEN = "open"


class AnswerError(ValueError):
    """A request names no such page or item, or its value is not acceptable."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Item:
    """
    One Ask, Do, Decision or Options box found in a page's source.

    Attributes
    ----------
    id, kind : str
        ``data-canvas-id`` and ``ask``, ``do``, ``decision`` or ``choices``.
    key : str
        ``sha256:`` hash of the key fields (ANS-01).
    text : str
        The question, title or decision text.
    form : str | None
        An Ask's form, with the default of ASK-01 filled in.
    default : Any
        An Ask's ``default`` (``None`` when it has none).
    waits : bool
        True when the agent waits for it while it is open (A-85).
    runs : tuple[str, ...]
        The ``run`` texts of a Do (DO-02).
    steps : int
        Number of steps of a Do.
    step_runs : tuple[str | None, ...]
        The ``run`` text of each step by position (None: the step has none);
        a Do with one ``run`` and no steps has that text as step 1.
    """

    id: str
    kind: str
    key: str
    text: str
    form: str | None
    default: Any
    waits: bool
    runs: tuple[str, ...]
    steps: int
    step_runs: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class Scan:
    """The items, file paths and source lines of a page (DO-02, CNT-03, CNT-04)."""

    items: dict[str, Item]
    paths: tuple[str, ...]
    sources: tuple[str, ...] = ()


class _Collector(HTMLParser):
    """Collect the tracked tags with their ``data-canvas-id`` and JSON config."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[dict[str, Any]] = []
        self._open: list[dict[str, Any]] = []
        self._stack: list[str] = []
        self._json: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if (
            tag == "script"
            and self._open
            and len(self._stack) == self._open[-1]["depth"]
        ):
            if (values.get("type") or "").lower() == "application/json":
                self._json = []
        if tag in VOID_TAGS:
            return
        self._stack.append(tag)
        if tag in TRACKED_TAGS and "template" not in self._stack:
            entry = {
                "tag": tag,
                "id": values.get("data-canvas-id"),
                "config": None,
                "depth": len(self._stack),
            }
            self.found.append(entry)
            self._open.append(entry)

    def handle_data(self, data: str) -> None:
        if self._json is not None:
            self._json.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._stack:
            del self._stack[len(self._stack) - 1 - self._stack[::-1].index(tag) :]
        if tag == "script" and self._json is not None:
            entry = self._open[-1]
            if entry["config"] is None:
                try:
                    entry["config"] = json.loads("".join(self._json))
                except ValueError:
                    entry["config"] = {}
                asks = [e for e in self._open[:-1] if e["tag"] == "canvas-ask"]
                if entry["tag"] in POINT_CHILDREN and asks:
                    asks[-1].setdefault("child", entry["config"])
            self._json = None
        elif tag in TRACKED_TAGS:
            for position in range(len(self._open) - 1, -1, -1):
                if self._open[position]["tag"] == tag:
                    del self._open[position:]
                    break


def scan(source: str) -> Scan:
    """
    Read the Ask, Do, Decision and Options box items and the file paths.

    Cards made by page scripts are not in the source and so not found (A-85).

    Parameters
    ----------
    source : str
        The page's HTML.

    Returns
    -------
    Scan
        Items by id in page order (the first of a repeated id wins) and paths.
    """
    collector = _Collector()
    collector.feed(source)
    collector.close()
    items: dict[str, Item] = {}
    paths: list[str] = []
    sources: list[str] = []
    for entry in collector.found:
        config = entry["config"] if isinstance(entry["config"], dict) else {}
        if entry["tag"] == "canvas-ask" and "child" in entry:
            config = {**config, "_child": entry["child"]}
        if entry["tag"] == "canvas-file":
            if isinstance(config.get("path"), str):
                paths.append(config["path"])
            continue
        if entry["tag"] == "canvas-source":
            if isinstance(config.get("source"), str):
                sources.append(config["source"])
            continue
        kind, item_id = ITEM_KINDS.get(entry["tag"]), entry["id"]
        if kind == "choices" and not isinstance(config.get("submit"), str):
            continue  # live selection without a submit button has no answer (#19)
        if kind and item_id and item_id not in items and len(items) < MAX_ITEMS:
            items[item_id] = _item(item_id, kind, config)
    return Scan(items, tuple(paths), tuple(sources))


def _item(item_id: str, kind: str, config: dict[str, Any]) -> Item:
    fields: dict[str, Any] = {name: config.get(name) for name in KEY_FIELDS[kind]}
    if kind == "ask" and config.get("form") == "point" and "_child" in config:
        fields["_child"] = config["_child"]
    if kind == "ask" and fields["form"] is None:
        fields["form"] = "one" if config.get("options") else "text"
    digest = hashlib.sha256(
        json.dumps([kind, fields], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    steps = config.get("steps") if isinstance(config.get("steps"), list) else []
    runs = [
        s["run"] for s in steps if isinstance(s, dict) and isinstance(s.get("run"), str)
    ]
    if isinstance(config.get("run"), str):
        runs.append(config["run"])
    text = config.get(TEXT_FIELD[kind])
    return Item(
        id=item_id,
        kind=kind,
        key=f"sha256:{digest}",
        text=text if isinstance(text, str) else "",
        form=fields.get("form") if kind == "ask" else None,
        default=config.get("default") if kind == "ask" else None,
        waits=kind == "do" or (kind == "ask" and config.get("default") is None),
        runs=tuple(runs),
        steps=len(steps) or (1 if "run" in config else 0),
        step_runs=_step_runs(config, steps),
    )


def _step_runs(config: dict[str, Any], steps: list[Any]) -> tuple[str | None, ...]:
    if not steps:
        return (config["run"],) if isinstance(config.get("run"), str) else ()
    return tuple(
        s["run"] if isinstance(s, dict) and isinstance(s.get("run"), str) else None
        for s in steps
    )


def _blank(item: Item) -> dict[str, Any]:
    return {
        "kind": item.kind, "key": item.key, "state": OPEN, "value": None,
        "event": None, "time": None, "read": None, "ticked": [], "history": [],
    }  # fmt: skip


class AnswerStore:
    """
    The answers of all sessions' pages.

    Parameters
    ----------
    folder_of : Callable[[str], pathlib.Path]
        Session folder of a registered session id (KeyError if unknown).
    pages_of : Callable[[str], list[str]]
        The shown pages of a session.
    on_change : Callable[[str, str], None]
        Called with ``(session_id, page)`` after the stored items of a page
        changed, so the windows get the new ``answers`` message.
    """

    def __init__(
        self,
        folder_of: Callable[[str], Path],
        pages_of: Callable[[str], list[str]],
        on_change: Callable[[str, str], None],
    ) -> None:
        self._folder_of = folder_of
        self._pages_of = pages_of
        self._on_change = on_change
        self._scans: dict[tuple[str, str], tuple[int, Scan]] = {}
        self._waiters: list[asyncio.Future[None]] = []

    # ---- scan ---------------------------------------------------------------

    def scan_of(self, session_id: str, page: str) -> Scan | None:
        """Return the scan of a page's current version, cached per version."""
        try:
            validate_page_name(page)
        except UnsafePathError:
            return None
        if not is_page_name(page):
            return None
        latest = PageHistory(self._folder_of(session_id)).latest(page)
        if latest is None:
            return None
        version, content = latest
        cached = self._scans.get((session_id, page))
        if cached is None or cached[0] != version:
            cached = (version, scan(content.decode("utf-8", "replace")))
            self._scans[(session_id, page)] = cached
        return cached[1]

    def item_of(self, session_id: str, page: str, item_id: str) -> Item:
        """Return an item of a page, or raise 404."""
        found = self.scan_of(session_id, page)
        if found is None:
            raise AnswerError("No such page.", 404)
        if item_id not in found.items:
            raise AnswerError("No such Ask, Do, Decision or Options box here.", 404)
        return found.items[item_id]

    @staticmethod
    def key_of(kind: str, config: Any) -> str:
        """Return the key (ANS-01) of an item of ``kind`` with config ``config``."""
        return _item("", kind, config if isinstance(config, dict) else {}).key

    # ---- stored entries -----------------------------------------------------

    def entries(self, session_id: str, page: str) -> dict[str, dict[str, Any]]:
        """Return the stored entries of a page, reopened where the key changed."""
        document = self._load(session_id, page)
        if self._reconcile(session_id, page, document):
            self._save(session_id, page, document)
        return document["items"]

    def latest_event(self, session_id: str, page: str, item_id: str) -> str | None:
        """Return the id of the item's current answer event, if it has one."""
        return (self.entries(session_id, page).get(item_id) or {}).get("event")

    def record(
        self,
        session_id: str,
        page: str,
        item: Item,
        *,
        state: str,
        value: Any,
        event: str,
        time: str,
        ticked: list[int] | None = None,
        not_from_owner: str | None = None,
    ) -> None:
        """
        Store a new answer of ``item``; the answer it replaces goes to history.

        ``not_from_owner`` is the event's mark of an answer the window relayed
        with no action of the owner (SEC-09); it is listed with the answer.
        """
        document = self._load(session_id, page)
        self._reconcile(session_id, page, document)
        entry = document["items"].get(item.id) or _blank(item)
        _to_history(entry)
        entry.update(state=state, value=value, event=event, time=time, read=None)
        if not_from_owner:
            entry["not_from_owner"] = not_from_owner
        if ticked is not None:
            entry["ticked"] = ticked
        document["items"][item.id] = entry
        self._save(session_id, page, document)
        self._changed(session_id, page)

    def tick(
        self,
        session_id: str,
        page: str,
        item: Item,
        ticked: list[int],
        no_gesture: bool = False,
    ) -> None:
        """
        Store the ticked steps of a Do (DO-01).

        Steps newly ticked with ``no_gesture`` are kept as the page's ticks
        until they are unticked (SEC-09); see :meth:`page_ticks`.
        """
        document = self._load(session_id, page)
        self._reconcile(session_id, page, document)
        entry = document["items"].get(item.id) or _blank(item)
        before = set(entry["ticked"])
        by_page = set(entry.get("page_ticks", [])) & before & set(ticked)
        if no_gesture:
            by_page |= set(ticked) - before
        entry["ticked"] = ticked
        entry.pop("page_ticks", None)
        if by_page:
            entry["page_ticks"] = sorted(by_page)
        document["items"][item.id] = entry
        self._save(session_id, page, document)
        self._changed(session_id, page)

    def page_ticks(
        self, session_id: str, page: str, item_id: str, ticked: list[int]
    ) -> list[int]:
        """Return the steps of ``ticked`` that the page's script ticked (SEC-09)."""
        entry = self.entries(session_id, page).get(item_id) or {}
        by_page = set(entry.get("page_ticks", [])) & set(entry.get("ticked", []))
        return sorted(by_page & set(ticked))

    def mark_read(
        self, session_id: str, page: str, item_id: str, event: str
    ) -> str | None:
        """Stamp ``read`` when ``event`` is the item's current answer (ANS-03)."""
        document = self._load(session_id, page)
        entry = document["items"].get(item_id)
        if entry is None or entry["event"] != event or entry["read"] is not None:
            return None
        entry["read"] = now_iso()
        self._save(session_id, page, document)
        self._changed(session_id, page)
        return entry["read"]

    def page_changed(self, session_id: str, page: str) -> None:
        """Reopen the items a new version of ``page`` changed; tell the windows."""
        if self.entries(session_id, page):
            self._changed(session_id, page)

    def public(self, session_id: str, page: str) -> dict[str, dict[str, Any]]:
        """Return the ``items`` of the ``answers`` message (5.16)."""
        entries = self.entries(session_id, page)
        return {
            item_id: {k: e[k] for k in ("state", "value", "time", "read", "ticked")}
            for item_id, e in entries.items()
            if e["state"] != OPEN or e["ticked"]
        }

    # ---- listing and waiting -----------------------------------------------

    def listing(
        self,
        session_id: str,
        page: str | None = None,
        open_only: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List the items of the shown pages (ANS-04) and mark their answers read.

        Nothing is consumed: the answer events stay queued (ANS-03).
        """
        rows = self._rows(session_id, page)
        if open_only:
            rows = [r for r in rows if r["state"] == OPEN and r["kind"] in NEED_KINDS]
        return self._read(session_id, rows)

    def targets(
        self, session_id: str, ids: list[str], page: str | None
    ) -> list[tuple[str, str]]:
        """
        Resolve the items a wait covers (ANS-05) as ``(page, id)`` pairs.

        With no ids: every item that waits now. A named id must exist.
        """
        rows = self._rows(session_id, page)
        if not ids:
            return [(r["page"], r["id"]) for r in rows if r["waits"]]
        found: list[tuple[str, str]] = []
        for wanted in ids:
            matches = [(r["page"], r["id"]) for r in rows if r["id"] == wanted]
            if not matches:
                raise AnswerError(f"No Ask, Do, Decision or Options box {wanted!r}.")
            found += matches
        return found

    def open_boxes(self, session_id: str) -> list[dict[str, Any]]:
        """List the open Ask and Do boxes of the session's pages (P33.3)."""
        keys = ("page", "id", "kind", "text", "waits", "default")
        return [
            {k: r[k] for k in keys}
            for r in self._rows(session_id, None)
            if r["state"] == OPEN and r["kind"] in NEED_KINDS
        ]

    def rows_of(
        self, session_id: str, targets: list[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        """Return the listing rows of ``targets`` and mark their answers read."""
        wanted = set(targets)
        rows = [
            r for r in self._rows(session_id, None) if (r["page"], r["id"]) in wanted
        ]
        return self._read(session_id, rows)

    async def wait(
        self, session_id: str, targets: list[tuple[str, str]], timeout: float
    ) -> bool:
        """Wait until every target left the open state; False at the timeout."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        def done() -> bool:
            wanted = set(targets)
            rows = {}
            for name in {p for p, _ in targets}:
                found = self.scan_of(session_id, name)
                entries = self.entries(session_id, name)
                for item in found.items.values() if found else ():
                    rows[(name, item.id)] = (entries.get(item.id) or {}).get(
                        "state", OPEN
                    )
            return all(rows.get(t, OPEN) != OPEN for t in wanted)

        while not done():
            left = deadline - loop.time()
            if left <= 0:
                return False
            future: asyncio.Future[None] = loop.create_future()
            self._waiters.append(future)
            try:
                await asyncio.wait_for(future, left)
            except TimeoutError:
                pass
            finally:
                self._waiters.remove(future)
        return True

    # ---- internals ---------------------------------------------------------

    def _rows(self, session_id: str, page: str | None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name in self._pages_of(session_id):
            found = self.scan_of(session_id, name) if page in (None, name) else None
            if found is None:
                continue
            entries = self.entries(session_id, name)
            rows += [_row(name, i, entries.get(i.id)) for i in found.items.values()]
        return rows

    def _read(
        self, session_id: str, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Stamp the unread answers among ``rows`` as read (ANS-03)."""
        for row in rows:
            if row["event"] and row["read"] is None:
                stamp = self.mark_read(session_id, row["page"], row["id"], row["event"])
                row["read"] = stamp or row["read"]
        return rows

    def _changed(self, session_id: str, page: str) -> None:
        for future in self._waiters:
            if not future.done():
                future.set_result(None)
        self._on_change(session_id, page)

    def _path(self, session_id: str, page: str) -> Path:
        validate_page_name(page)
        return self._folder_of(session_id) / ANSWERS_DIR / f"{page}.json"

    def _load(self, session_id: str, page: str) -> dict[str, Any]:
        try:
            return json.loads(self._path(session_id, page).read_text())
        except FileNotFoundError:
            return {"schema": SCHEMA, "page": page, "items": {}}

    def _save(self, session_id: str, page: str, document: dict[str, Any]) -> None:
        path = self._path(session_id, page)
        path.parent.mkdir(mode=0o700, exist_ok=True)  # SEC-12
        write_safely(path, json.dumps(document, indent=2) + "\n")

    def _reconcile(self, session_id: str, page: str, document: dict[str, Any]) -> bool:
        """Reopen stored items whose key changed in the page; True if any did."""
        found = self.scan_of(session_id, page)
        changed = False
        for item_id, entry in document["items"].items():
            item = found.items.get(item_id) if found else None
            if item is None or item.key == entry["key"]:
                continue
            _to_history(entry)
            entry.update(_blank(item) | {"history": entry["history"]})
            changed = True
        return changed


def _to_history(entry: dict[str, Any]) -> None:
    """Move the entry's current answer to the front of its history (at most 20)."""
    if entry["event"] is None:
        return
    past = {k: entry[k] for k in ("key", "value", "event", "time")}
    if mark := entry.pop("not_from_owner", None):
        past["not_from_owner"] = mark
    entry["history"] = [past, *entry["history"]][:MAX_HISTORY]


def _is_open(item: Item, entry: dict[str, Any] | None) -> bool:
    """Whether the stored entry leaves the item open; a changed key reopens it."""
    return entry is None or entry["key"] != item.key or entry["state"] == OPEN


def _row(page: str, item: Item, entry: dict[str, Any] | None) -> dict[str, Any]:
    state = entry["state"] if entry else OPEN
    waits = item.waits and state == OPEN
    return {
        "page": page, "id": item.id, "kind": item.kind, "text": item.text,
        "waits": waits, "default": item.default, "state": state,
        "answer": entry["value"] if entry else None,
        "event": entry["event"] if entry else None,
        "time": entry["time"] if entry else None,
        "read": entry["read"] if entry else None,
    } | ({"not_from_owner": entry["not_from_owner"]}
         if entry and entry.get("not_from_owner") else {})  # fmt: skip
