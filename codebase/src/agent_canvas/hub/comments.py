"""The comment store: ``.comments/<page>.json`` of a session folder (COM-04, 5.13).

Every function takes the session folder; the hub is the only writer.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from agent_canvas.files_safe import COMMENTS_DIR, HISTORY_PAGES, write_safely
from agent_canvas.hub.registry import now_iso
from agent_canvas.paths_safe import UnsafePathError, validate_page_name

SCHEMA = "agent-canvas/comments@1"
KINDS = ("text", "point", "rect", "lasso")
MAX_COMMENTS = 200
MAX_TEXT = 4000
MAX_QUOTE = 1000
MAX_INSIDE = 500
MAX_POINTS = 200
MAX_PICTURE_ERROR = 300
MAX_PICTURE_BYTES = 10 * 1024 * 1024
SOURCE_LINE_CHARS = 40
MARKDOWN_SUFFIXES = (".md", ".markdown")
IGNORED_MARKS = "*_`#"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# What the agent does not get with a comment (5.3).
AGENT_HIDDEN = ("seen", "read", "anchored_version")

_lock = threading.RLock()


class CommentError(ValueError):
    """
    A comment request the store refuses.

    Parameters
    ----------
    message : str
        Reason, shown to the owner.
    status : int, optional
        HTTP status the route answers. Default is 400.
    usage : bool, optional
        True when the CLI treats the request as a usage error (exit 2, RPL-02).
    """

    def __init__(self, message: str, status: int = 400, usage: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.usage = usage


def _path(folder: Path, page: str) -> Path:
    try:
        validate_page_name(page)
    except UnsafePathError as error:
        raise CommentError(str(error)) from error
    return folder / COMMENTS_DIR / f"{page}.json"


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a temporary file and a rename; an error leaves the old file."""
    path.parent.mkdir(mode=0o700, exist_ok=True)  # SEC-12
    write_safely(path, data)


def _save(folder: Path, page: str, document: dict[str, Any]) -> None:
    text = json.dumps(document, indent=2) + "\n"
    _write_atomic(_path(folder, page), text.encode())


def load(folder: Path, page: str) -> dict[str, Any]:
    """
    Read the comments document of a page (an empty one if there is none).

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    page : str
        Page name.

    Returns
    -------
    dict[str, Any]
        The document of 5.13: ``schema``, ``page``, ``next``, ``comments``.
    """
    path = _path(folder, page)
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {"schema": SCHEMA, "page": page, "next": 1, "comments": []}


def _owner_sent(record: dict[str, Any]) -> list[str]:
    """Return the times of the owner's sent entries: the comment, its sent replies."""
    times = [record["sent"]] if record["sent"] is not None else []
    return times + [
        r["sent"] for r in record["replies"] if r["from"] is None and r["sent"]
    ]


def _agent_replies(record: dict[str, Any]) -> list[str]:
    return [r["at"] for r in record["replies"] if r["from"] is not None]


def status(record: dict[str, Any]) -> str:
    """
    Return the status of a comment, the only definition of it (COM-08).

    Parameters
    ----------
    record : dict[str, Any]
        A comment record of 5.13.

    Returns
    -------
    str
        The first that holds: ``draft`` (not sent, or an owner reply not sent),
        ``done``, ``answered`` (the agent's newest reply is later than the
        owner's newest sent entry), ``seen`` (seen after that entry), ``sent``.
    """
    unsent_reply = any(
        r["from"] is None and r["sent"] is None for r in record["replies"]
    )
    if record["sent"] is None or unsent_reply:
        return "draft"
    if record["done"] is not None:
        return "done"
    newest = max(_owner_sent(record))
    if max(_agent_replies(record), default="") > newest:
        return "answered"
    if max(record["seen"], default="") > newest:
        return "seen"
    return "sent"


def open(record: dict[str, Any]) -> bool:
    """
    Tell whether a comment still waits for the agent (COM-08, A-55).

    True when it is sent, not done, and the owner's newest sent entry is newer
    than both the agent's newest reply and ``last_done``.
    """
    if record["sent"] is None or record["done"] is not None:
        return False
    newest = max(_owner_sent(record))
    answered = max(_agent_replies(record), default="")
    return newest > max(answered, record["last_done"] or "")


def unread(record: dict[str, Any]) -> bool:
    """Tell whether the agent replied or marked done after the owner's last read."""
    read = record["read"] or ""
    latest = max(_agent_replies(record), default="")
    done = record["done"]
    if done is not None and done["by"] == "agent":
        latest = max(latest, done["at"])
    return latest > read


def with_status(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the records of a document with ``status`` and ``unread`` (5.14)."""
    return [
        {**c, "status": status(c), "unread": unread(c)} for c in document["comments"]
    ]


def unsent(folder: Path) -> dict[str, int]:
    """Count the drafts on the session's existing pages (R-16): comments and files."""
    with _lock:
        per_page = [
            sum(1 for c in with_status(load(folder, name)) if c["status"] == "draft")
            for name in pages(folder)
            if (folder / name).is_file()
        ]
    return {"comments": sum(per_page), "files": sum(1 for n in per_page if n)}


def _text(value: Any, limit: int, name: str) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise CommentError(f"{name} must be text of at most {limit} characters.")
    return value


def _picture(value: Any) -> bytes:
    if not isinstance(value, str):
        raise CommentError("picture must be a base64 PNG.")
    if len(value) > MAX_PICTURE_BYTES * 4 // 3 + 8:
        raise CommentError("picture is larger than 10 MB.")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise CommentError("picture is not valid base64.") from error
    if len(data) > MAX_PICTURE_BYTES:
        raise CommentError("picture is larger than 10 MB.")
    if not data.startswith(PNG_SIGNATURE):
        raise CommentError("picture is not a PNG.")
    return data


def _clean(fields: Any) -> dict[str, Any]:
    """Validate the fields of a new comment against the limits of A-74."""
    if not isinstance(fields, dict):
        raise CommentError("The comment must be an object.")
    if fields.get("kind") not in KINDS:
        raise CommentError(f"kind must be one of {', '.join(KINDS)}.")
    anchor = fields.get("anchor")
    if not isinstance(anchor, dict):
        raise CommentError("anchor must be an object.")
    if "quote" in anchor:
        _text(anchor["quote"], MAX_QUOTE, "anchor.quote")
    if len(anchor.get("points") or ()) > MAX_POINTS:
        raise CommentError(f"A lasso has at most {MAX_POINTS} points.")
    for name in ("target", "data"):
        if fields.get(name) is not None and not isinstance(fields[name], dict):
            raise CommentError(f"{name} must be an object or null.")
    version = fields.get("page_version")
    if version is not None and (
        not isinstance(version, int) or isinstance(version, bool)
    ):
        raise CommentError("page_version must be a number or null.")
    inside = fields.get("text_inside")
    if inside is not None:
        _text(inside, MAX_INSIDE, "text_inside")
    error = fields.get("picture_error")
    if error is not None:
        _text(error, MAX_PICTURE_ERROR, "picture_error")
    return {
        "picture_error": error,
        "kind": fields["kind"],
        "text": _text(fields.get("text"), MAX_TEXT, "text"),
        "page_version": version,
        "anchor": anchor,
        "target": fields.get("target"),
        "text_inside": inside,
        "data": fields.get("data"),
    }


def _source_line(folder: Path, page: str, clean: dict[str, Any]) -> int | None:
    """Return the 1-based line of the comment's quote in a Markdown source (ANC-09)."""
    suffix = Path(page).suffix
    if suffix.lower() not in MARKDOWN_SUFFIXES:
        return None
    quote = clean["anchor"].get("quote")
    if clean["kind"] != "text" or not isinstance(quote, str):
        quote = (clean["text_inside"] or "")[:SOURCE_LINE_CHARS]
    version = clean["page_version"]
    saved = folder / HISTORY_PAGES / f"{Path(page).stem}.{version or 0:04d}{suffix}"
    try:
        source = (saved if saved.is_file() else folder / page).read_text(
            errors="replace"
        )
    except OSError:
        return None

    def kept(text: str) -> list[str]:
        return [c for c in text if not c.isspace() and c not in IGNORED_MARKS]

    found = [
        (char, number)
        for number, line in enumerate(source.splitlines(), 1)
        for char in kept(line)
    ]
    needle = "".join(kept(quote))
    at = "".join(char for char, _ in found).find(needle)
    return found[at][1] if needle and at >= 0 else None


def create(folder: Path, page: str, fields: Any) -> dict[str, Any]:
    """
    Store a new draft comment under the next number of its page (COM-04).

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    page : str
        Page name.
    fields : dict
        ``kind``, ``text``, ``anchor``, ``page_version`` and optionally
        ``target``, ``text_inside``, ``data``, ``picture`` (base64 PNG) and
        ``picture_error`` (why there is no picture, COM-12).

    Returns
    -------
    dict[str, Any]
        The stored record (5.13).

    Raises
    ------
    CommentError
        When a limit of A-74 is exceeded or a field is malformed (status 400).
    """
    clean = _clean(fields)
    picture = _picture(fields["picture"]) if fields.get("picture") is not None else None
    with _lock:
        document = load(folder, page)
        if len(document["comments"]) >= MAX_COMMENTS:
            raise CommentError(f"A page holds at most {MAX_COMMENTS} comments.")
        number = document["next"]
        relative = None
        if picture is not None:
            relative = f"{COMMENTS_DIR}/{page}.{number}.png"
            _write_atomic(folder / relative, picture)
        record = {
            "n": number,
            "id": f"cmt_{secrets.token_hex(8)}",
            "kind": clean["kind"],
            "text": clean["text"],
            "created": now_iso(),
            "edited": None,
            "page_version": clean["page_version"],
            "sent": None,
            "delivery": None,
            "send_event": None,
            "seen": [],
            "read": None,
            "anchor": clean["anchor"],
            "target": clean["target"],
            "text_inside": clean["text_inside"],
            "data": clean["data"],
            "source_line": _source_line(folder, page, clean),
            "picture": relative,
            "picture_error": clean["picture_error"] if picture is None else None,
            "lost": False,
            "anchored_version": clean["page_version"],
            "replies": [],
            "done": None,
            "last_done": None,
        }
        document["comments"].append(record)
        document["next"] = number + 1
        try:
            _save(folder, page, document)
        except BaseException:
            if relative is not None:
                (folder / relative).unlink(missing_ok=True)
            raise
        return record


def delete(folder: Path, page: str, number: int) -> None:
    """
    Delete a draft comment and its picture (COM-09); ``next`` is unchanged.

    Raises
    ------
    CommentError
        404 for an unknown number, 409 for a comment already sent.
    """
    with _lock:
        document = load(folder, page)
        found = next((c for c in document["comments"] if c["n"] == number), None)
        if found is None:
            raise CommentError("No such comment.", 404)
        if found["sent"] is not None:
            raise CommentError("A sent comment cannot be deleted.", 409)
        document["comments"].remove(found)
        _save(folder, page, document)
        if found["picture"]:
            (folder / found["picture"]).unlink(missing_ok=True)


def _find(document: dict[str, Any], number: int) -> dict[str, Any]:
    found = next((c for c in document["comments"] if c["n"] == number), None)
    if found is None:
        raise CommentError("No such comment.", 404)
    return found


def _change(folder: Path, page: str, number: int, apply: Any) -> dict[str, Any]:
    """Load, let ``apply(record)`` change one comment, save, return the record."""
    with _lock:
        document = load(folder, page)
        record = _find(document, number)
        apply(record)
        _save(folder, page, document)
        return record


def _must_be_sent(record: dict[str, Any]) -> None:
    if record["sent"] is None:
        raise CommentError("The comment is not sent yet.", 409)


def edit(folder: Path, page: str, number: int, text: str) -> dict[str, Any]:
    """
    Change the text of a draft comment (A-49).

    Raises
    ------
    CommentError
        400 for a bad text, 404 for an unknown number, 409 for a sent comment.
    """
    _text(text, MAX_TEXT, "text")

    def apply(record: dict[str, Any]) -> None:
        if record["sent"] is not None:
            raise CommentError("A sent comment cannot be edited.", 409)
        record.update(text=text, edited=now_iso())

    return _change(folder, page, number, apply)


def reply(
    folder: Path,
    page: str,
    number: int,
    text: str,
    author: str | None = None,
    done: bool = False,
) -> dict[str, Any]:
    """
    Add a reply to a sent comment; an owner reply (``author`` None) clears done.

    An agent's reply leaves a done comment done (A-55); with ``done`` the agent
    also marks it done, in the same write. An owner reply stays unsent, which
    makes the comment a draft, until a send takes it (COM-11).

    Raises
    ------
    CommentError
        400 for a bad text, 404 for an unknown number, 409 for a draft comment.
    """
    _text(text, MAX_TEXT, "text")

    def apply(record: dict[str, Any]) -> None:
        _must_be_sent(record)
        record["replies"].append(
            {"from": author, "text": text, "at": now_iso(), "sent": None}
        )
        if author is None:
            record["done"] = None
        elif done:
            _mark_done(record, "agent")

    return _change(folder, page, number, apply)


def _mark_done(record: dict[str, Any], by: str) -> None:
    if record["done"] is None:
        stamp = now_iso()
        record.update(done={"at": stamp, "by": by}, last_done=stamp)


def set_done(folder: Path, page: str, number: int, by: str) -> dict[str, Any]:
    """
    Mark a sent comment done by ``"owner"`` or ``"agent"``; ``last_done`` follows.

    Raises
    ------
    CommentError
        404 for an unknown number, 409 for a draft comment.
    """

    def apply(record: dict[str, Any]) -> None:
        _must_be_sent(record)
        _mark_done(record, by)

    return _change(folder, page, number, apply)


def reopen(folder: Path, page: str, number: int) -> dict[str, Any]:
    """Clear done; ``last_done`` stays, so the agent is not asked again yet."""
    return _change(folder, page, number, lambda record: record.update(done=None))


def mark_read(folder: Path, page: str, number: int) -> dict[str, Any]:
    """Set ``read`` to now: the owner selected the comment."""
    return _change(folder, page, number, lambda r: r.update(read=now_iso()))


def set_lost(
    folder: Path, page: str, number: int, lost: bool, anchored_version: int | None
) -> dict[str, Any]:
    """Store the result of finding the anchor again and the version it was in."""
    return _change(
        folder,
        page,
        number,
        lambda r: r.update(lost=lost, anchored_version=anchored_version),
    )


def set_lost_many(
    folder: Path,
    page: str,
    reports: list[tuple[int, bool]],
    anchored_version: int | None,
) -> bool:
    """
    Store the changes of ``lost`` the window found after a page change (ANC-06).

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    page : str
        Page name.
    reports : list[tuple[int, bool]]
        Comment number and whether its anchor is lost. A number without a
        comment (deleted meanwhile) is skipped, and so is a report that
        repeats what is stored.
    anchored_version : int | None
        The page version the anchors were looked for in.

    Returns
    -------
    bool
        True when a record changed.
    """
    with _lock:
        document = load(folder, page)
        by_number = {c["n"]: c for c in document["comments"]}
        changes = [
            (by_number[n], lost)
            for n, lost in reports
            if n in by_number and by_number[n]["lost"] != lost
        ]
        for record, lost in changes:
            record.update(lost=lost, anchored_version=anchored_version)
        if changes:
            _save(folder, page, document)
        return bool(changes)


def take_unsent(
    folder: Path,
    page: str,
    delivery: str,
    send_event: str | None,
    stamp: str | None = None,
) -> list[dict[str, Any]]:
    """
    Mark the drafts and unsent owner replies of a page sent and return them (COM-11).

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    page : str
        Page name.
    delivery : str
        ``now`` or ``next-message``.
    send_event : str | None
        Id of the event the send created.
    stamp : str | None, optional
        The ``sent`` time to set, the event's time (5.3); default now.

    Returns
    -------
    list[dict[str, Any]]
        The records that had a draft or an unsent owner reply, now sent, in
        number order; empty when there was none. A reply taken here carries
        the ``send_event`` so that a failed send can undo it.
    """
    with _lock:
        document = load(folder, page)
        taken = [
            c
            for c in document["comments"]
            if c["sent"] is None
            or any(r["from"] is None and r["sent"] is None for r in c["replies"])
        ]
        if not taken:
            return []
        stamp = stamp or now_iso()
        for record in taken:
            if record["sent"] is None:
                record.update(sent=stamp, delivery=delivery, send_event=send_event)
            for reply in record["replies"]:
                if reply["from"] is None and reply["sent"] is None:
                    reply.update(sent=stamp, send_event=send_event)
        _save(folder, page, document)
        return taken


def restore_drafts(folder: Path, page: str, send_event: str) -> None:
    """Make the comments and owner replies taken by a failed send drafts again."""
    with _lock:
        document = load(folder, page)
        for record in document["comments"]:
            if record["send_event"] == send_event:
                record.update(sent=None, delivery=None, send_event=None)
            for reply in record["replies"]:
                if reply.get("send_event") == send_event:
                    reply.pop("send_event")
                    reply["sent"] = None
        _save(folder, page, document)


def stamp_seen(folder: Path, page: str, numbers: list[int]) -> None:
    """Add the time to the ``seen`` of comments an event just delivered (COM-11)."""
    with _lock:
        document = load(folder, page)
        stamp = now_iso()
        found = [c for c in document["comments"] if c["n"] in numbers]
        for record in found:
            record["seen"].append(stamp)
        if found:
            _save(folder, page, document)


def visible_replies(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the replies the agent may see: its own and the owner's sent ones."""
    return [r for r in record["replies"] if r["from"] is not None or r["sent"]]


def pages(folder: Path) -> list[str]:
    """Return the names of the pages that have a comments file, sorted."""
    directory = folder / COMMENTS_DIR
    if not directory.is_dir():
        return []
    return sorted(p.name[: -len(".json")] for p in directory.glob("*.json"))


def listing(
    folder: Path,
    page: str | None = None,
    *,
    mark_seen: bool = False,
    include_all: bool = False,
) -> list[dict[str, Any]]:
    """
    Return the sent comments for the agent (RPL-01), by default the open ones.

    Parameters
    ----------
    folder : pathlib.Path
        Session folder.
    page : str | None, optional
        Only this page; default every page.
    mark_seen : bool, optional
        Add the time to the ``seen`` of each listed comment.
    include_all : bool, optional
        Also the comments that are not open (answered, done).

    Returns
    -------
    list[dict[str, Any]]
        Records with ``page``, the page's absolute ``path``, ``status``,
        ``open`` and an absolute ``picture``, without ``seen``, ``read`` and
        ``anchored_version``. Drafts never appear, nor the owner's unsent replies
        (``status`` and ``open`` are those of the sent part).
    """
    found: list[dict[str, Any]] = []
    with _lock:
        for name in [page] if page is not None else pages(folder):
            document = load(folder, name)
            listed = [
                c
                for c in document["comments"]
                if c["sent"] is not None and (include_all or open(c))
            ]
            if mark_seen and listed:
                stamp = now_iso()
                for record in listed:
                    record["seen"].append(stamp)
                _save(folder, name, document)
            for full in listed:
                record = {
                    **full,
                    "replies": visible_replies(full),
                }
                shown = {k: v for k, v in record.items() if k not in AGENT_HIDDEN}
                if record["picture"]:
                    shown["picture"] = str(folder / record["picture"])
                found.append(
                    {"page": name, "path": str(folder / name), **shown,
                     "status": status(record), "open": open(record)}
                )  # fmt: skip
    return found
