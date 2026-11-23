"""What changed between two versions of a page, by element id (NEW-02)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any

VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
SPACES = re.compile(r"\s+")


class _Node:
    def __init__(
        self, tag: str, attrs: dict[str, str | None], in_svg: bool = False
    ) -> None:
        self.tag = tag
        self.attrs = attrs
        self.in_svg = in_svg
        self.children: list[_Node | str] = []

    @property
    def ident(self) -> str | None:
        if self.in_svg:
            return None
        return self.attrs.get("data-canvas-id") or self.attrs.get("id") or None


class _Tree(HTMLParser):
    """Parse leniently into nodes; text is whitespace-normalised, comments dropped."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(self._node(tag, attrs))

    def _node(self, tag: str, attrs: list[tuple[str, str | None]]) -> _Node:
        parent = self.stack[-1]
        return _Node(tag, dict(attrs), parent.in_svg or parent.tag == "svg")

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        if text := SPACES.sub(" ", data).strip():
            self.stack[-1].children.append(text)


def _markup(node: _Node) -> str:
    """Serialise a node without its descendants that have an id."""
    attrs = "".join(f' {k}="{v}"' for k, v in node.attrs.items())
    inner = ""
    for child in node.children:
        if isinstance(child, str):
            inner += child
        elif not child.ident:
            inner += _markup(child)
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


def _elements(html: str) -> tuple[dict[str, str], str]:
    """Return the own markup of each id and the markup outside all of them."""
    tree = _Tree()
    tree.feed(html)
    tree.close()
    found: dict[str, str] = {}
    seen: dict[str, int] = {}

    def walk(node: _Node) -> None:
        for child in node.children:
            if isinstance(child, str):
                continue
            if child.ident:
                seen[child.ident] = seen.get(child.ident, 0) + 1
                found[f"{child.ident}\0{seen[child.ident]}"] = _markup(child)
            walk(child)

    walk(tree.root)
    return found, _markup(tree.root)


def _ids(keys: Iterable[str]) -> list[str]:
    """Return the ids of position keys (``id`` + NUL + n), each once, in order."""
    return list(dict.fromkeys(key.split("\0")[0] for key in keys))


def diff(old: str, new: str) -> dict[str, Any]:
    """
    Compare two versions of an HTML page by element id (NEW-02).

    An element's id is its ``data-canvas-id``, else its ``id``. An element is
    changed when its own markup differs after whitespace normalisation;
    descendants that have an id of their own count for themselves only. Ids
    inside an ``<svg>`` belong to the picture. An id used twice is compared by
    position.

    Parameters
    ----------
    old, new : str
        The two versions of the page.

    Returns
    -------
    dict[str, Any]
        ``added``, ``changed`` (ids in the new version's order), ``removed``
        (old order) and ``outside``: whether anything outside the elements
        with an id changed.
    """
    before, outside_before = _elements(old)
    after, outside_after = _elements(new)
    return {
        "added": _ids(i for i in after if i not in before),
        "changed": _ids(i for i in after if i in before and after[i] != before[i]),
        "removed": _ids(i for i in before if i not in after),
        "outside": outside_before != outside_after,
    }


def compare(page: str, old: bytes, new: bytes) -> dict[str, Any]:
    """
    Compare two versions of a page of any type (NEW-02, NEW-03).

    An HTML page is compared by element id; a Markdown file, PDF or picture has
    no elements and counts as changed outside them when its bytes differ.
    """
    if page.lower().endswith(".html"):
        return diff(old.decode("utf-8", "replace"), new.decode("utf-8", "replace"))
    return {"added": [], "changed": [], "removed": [], "outside": old != new}


def count(result: dict[str, Any]) -> int:
    """
    Return the number of changes the line over the page names (NEW-03).

    Each added or changed id gets a mark and counts once; everything that gets no
    mark (removed ids, changes outside the elements with an id) counts once together.
    """
    other = result["outside"] or bool(result["removed"])
    return len(result["added"]) + len(result["changed"]) + (1 if other else 0)
