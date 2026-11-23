"""Herdr's navigation keys move between spaces, tabs, cards and page tabs (herdr-canvas keys)."""

# ruff: noqa: E501

from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from .support import call
from .test_hcw_01_herdr_window import pane, session

pytestmark = pytest.mark.browser

TREE = {
    "dir": "row",
    "weight": 1,
    "children": [
        {"pane": "pt1", "weight": 1},
        {
            "dir": "column",
            "weight": 1,
            "children": [{"pane": "pt2", "weight": 1}, {"pane": "pt3", "weight": 1}],
        },
    ],
}
FOCUSED = "() => document.querySelector('.hv-card.focus')?.dataset.session"
ROW = "() => document.querySelector('.hv-row.on')?.title"
PILL = "() => document.querySelector('.hv-pill.on')?.textContent"


class World:
    """Two spaces, three tabs, a split of three cards and one session outside Herdr."""

    def __init__(self, owner, tmp_path: Path) -> None:  # noqa: ANN001
        while not owner.hub.state.shells:
            owner.page.wait_for_timeout(25)
        self.owner, self.page = owner, owner.page
        self.ids = {n: session(owner, tmp_path, n) for n in "abcdef"}
        a, b, c, d, e = (self.ids[n] for n in "abcde")
        self.sent: list[tuple[str, str]] = []
        self.herdr = {
            "available": True,
            "focus": {"space": "sp1", "tab": "tb1", "pane": "pt1"},
            "spaces": [
                {
                    "id": "sp1",
                    "name": "lab",
                    "color": "#22a99a",
                    "active": True,
                    "tabs": [
                        {
                            "id": "tb1",
                            "name": "rig",
                            "active": True,
                            "tree": TREE,
                            "panes": [
                                pane("t1", a, True),
                                pane("t2", b, False),
                                pane("t3", c, False),
                            ],
                        },
                        {
                            "id": "tb2",
                            "name": "bench",
                            "active": False,
                            "panes": [pane("t4", d, True)],
                        },
                    ],
                },
                {
                    "id": "sp2",
                    "name": "shop",
                    "color": "#e3814f",
                    "active": False,
                    "tabs": [
                        {
                            "id": "tb3",
                            "name": "main",
                            "active": True,
                            "panes": [pane("t5", e, True)],
                        },
                    ],
                },
            ],
            "other": [],
        }
        app = owner.hub.app.state.services.herdr_app
        app.snapshot = lambda: copy.deepcopy(self.herdr)
        app.focus = lambda _snapshot, key, value: self.sent.append((key, value)) or True
        self.page.wait_for_selector(".hv-row .hv-name >> text=lab")
        self.page.wait_for_function("(id) => activeId === id", arg=a)
        self.page.wait_for_function("keyMap.current('pane.go:right').length > 0")
        # The page frame must hold the forwarded keys before a key is pressed in it.
        self.page.wait_for_timeout(400)

    def press(self, key: str) -> None:
        self.page.keyboard.press(key)
        self.page.wait_for_timeout(120)

    def focused(self) -> str:
        return next(
            n for n, sid in self.ids.items() if sid == self.page.evaluate(FOCUSED)
        )


@pytest.fixture
def world(owner, tmp_path):  # noqa: ANN001, ANN201
    return World(owner, tmp_path)


def in_frame(world) -> None:  # noqa: ANN001
    """Put the keyboard focus inside the shown page, once its frame holds the keys."""
    world.owner.frame.wait_for_function("window.agentCanvas !== undefined")
    world.page.wait_for_timeout(500)
    world.owner.frame.locator("body").click()


def test_keys_01_cards_move_by_the_split_geometry(world) -> None:  # noqa: ANN001
    """a is left, b top right, c bottom right; the Herdr keys go where the cards are."""
    steps = [
        ("Alt+l", "b"),
        ("Alt+j", "c"),
        ("Alt+k", "b"),
        ("Alt+j", "c"),
        ("Alt+h", "a"),
        ("Alt+ArrowRight", "b"),
        ("Alt+ArrowDown", "c"),
        ("Alt+ArrowUp", "b"),
        ("Alt+ArrowLeft", "a"),
        ("Alt+h", "a"),
        ("Alt+k", "a"),
    ]
    for key, expected in steps:
        world.press(key)
        assert world.focused() == expected, key
    assert world.sent == [
        ("terminal", t) for t in ("t2", "t3", "t2", "t3", "t2", "t3", "t2")
    ]


def test_keys_02_the_card_keys_walk_the_cards_in_herdr_order_and_wrap(world) -> None:  # noqa: ANN001
    for key, expected in [("]", "b"), ("]", "c"), ("]", "a"), ("[", "c"), ("[", "b")]:
        world.press(key)
        assert world.focused() == expected, key


def test_keys_03_tabs_next_previous_and_by_number(world) -> None:  # noqa: ANN001
    for key, tab in [
        ("Control+PageDown", "bench"),
        ("Control+PageDown", "rig"),
        ("Control+PageUp", "bench"),
        ("Control+Tab", "rig"),
        ("Control+Shift+Tab", "bench"),
        ("Alt+]", "rig"),
        ("Alt+[", "bench"),
        ("Control+Alt+ArrowRight", "rig"),
        ("Control+Alt+ArrowLeft", "bench"),
        ("Alt+1", "rig"),
        ("Alt+2", "bench"),
        ("Control+1", "rig"),
        ("Control+2", "bench"),
    ]:
        world.press(key)
        assert world.page.evaluate(PILL) == tab, key
    assert ("tab", "tb2") in world.sent
    world.press("Alt+9")
    assert world.page.evaluate(PILL) == "bench"


def test_keys_04_spaces_include_not_in_herdr_and_wrap(world) -> None:  # noqa: ANN001
    for key, row in [
        ("Control+Alt+2", "shop"),
        ("Control+Alt+3", "Not in Herdr"),
        ("Control+Shift+PageDown", "lab"),
        ("Control+Shift+PageUp", "Not in Herdr"),
        ("Control+Alt+ArrowUp", "shop"),
        ("Control+Alt+ArrowDown", "Not in Herdr"),
        ("Control+Alt+1", "lab"),
    ]:
        world.press(key)
        assert world.page.evaluate(ROW) == row, key
    assert ("space", "sp2") in world.sent
    world.press("Control+Alt+3")
    assert world.page.evaluate(FOCUSED) == world.ids["f"]
    world.press(
        "Alt+]"
    )  # the tabs of that entry are its sessions; one session, one tab
    assert world.page.evaluate(FOCUSED) == world.ids["f"]


def test_keys_05_navigation_does_not_echo_back_to_herdr(world) -> None:  # noqa: ANN001
    world.press("Alt+l")
    world.press("Control+PageDown")
    count = len(world.sent)
    world.page.wait_for_timeout(1800)
    assert len(world.sent) == count


def from_frame(world, key: str, done) -> None:  # noqa: ANN001
    """Press ``key`` with the focus in the page frame until ``done()``; a new frame needs a moment for the keys."""
    for _ in range(8):
        in_frame(world)
        world.press(key)
        if done():
            return
    raise AssertionError(f"{key} from inside the frame did nothing")


def test_keys_06_the_keys_work_while_the_focus_is_inside_the_page_frame(world) -> None:  # noqa: ANN001
    from_frame(world, "Alt+l", lambda: world.focused() == "b")
    from_frame(world, "Alt+j", lambda: world.focused() == "c")
    from_frame(world, "Control+PageDown", lambda: world.page.evaluate(PILL) == "bench")
    from_frame(world, "Control+Alt+2", lambda: world.page.evaluate(ROW) == "shop")
    from_frame(
        world, "Control+Alt+3", lambda: world.page.evaluate(ROW) == "Not in Herdr"
    )


def test_keys_07_an_unbound_key_does_nothing(world) -> None:  # noqa: ANN001
    """The negative control: the same key with the action unbound changes nothing."""
    (Path(os.environ["AGENT_CANVAS_CONFIG_DIR"]) / "keys.toml").write_text(
        '[keys]\n"pane.go:right" = []\n"tab.next" = []\n'
    )
    world.page.reload()
    world.page.wait_for_function("keyMap.current('pane.go:right').length === 0")
    world.page.wait_for_selector(".hv-card")
    world.page.wait_for_timeout(500)
    first = world.page.evaluate(FOCUSED)
    world.press("Alt+l")
    world.press("Alt+ArrowRight")
    world.press("Control+PageDown")
    world.press("Control+Tab")
    assert world.page.evaluate(FOCUSED) == first
    assert world.page.evaluate(PILL) == "rig"
    world.press("Alt+j")  # a key that stays bound still works
    assert world.focused() in "ac"


def test_keys_08_page_tabs_of_a_card_move_with_the_page_keys(world) -> None:  # noqa: ANN001
    a = world.ids["a"]
    folder = world.owner.hub.state.session_of(a).folder
    (folder / "second.html").write_text("<p>second</p>")
    directory = folder.parent
    call(
        world.owner,
        "POST",
        f"/api/sessions/{a}/show",
        json={"project": str(directory), "name": "second.html"},
    )
    world.page.wait_for_selector(".hv-card.focus .hv-pt >> nth=1")
    shown = "() => document.querySelector('.hv-card.focus .hv-pt.on')?.textContent"
    first = world.page.evaluate(shown)
    world.press("Alt+.")
    second = world.page.evaluate(shown)
    assert second != first
    world.press("Alt+,")
    assert world.page.evaluate(shown) == first
