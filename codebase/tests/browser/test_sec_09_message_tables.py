"""The window's guard and dispatch read one message table per direction (P33.2)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

SPY_FRAME = """() => {
  const spied = window.__spied = [];
  for (const [type, row] of FRAME_MESSAGES) row.handle = () => spied.push(type);
  for (const [type, row] of PRIVATE_MESSAGES) row.handle = () => spied.push(type);
  return [...FRAME_MESSAGES.keys()];
}"""
POST_ALL = "(all) => { for (const t of all) parent.postMessage({type: t}, '*'); }"
ALL_SPIED = "(n) => new Set(window.__spied).size >= n && window.__guard.dropped.private"


def test_sec_09_each_frame_row_the_guard_lets_through_reaches_its_own_handler(
    make, owner
) -> None:  # noqa: ANN001
    make("<p>tables</p>")
    page = owner.page
    types = page.evaluate(SPY_FRAME)
    dropped = page.evaluate("({...window.__guard.dropped})")
    owner.frame.evaluate(
        POST_ALL,
        [*types, "not-a-type", "copy"],
    )
    page.wait_for_function(
        ALL_SPIED,
        arg=len(types),
    )
    page.wait_for_timeout(200)
    assert sorted(set(page.evaluate("window.__spied"))) == sorted(types)
    after = page.evaluate("window.__guard.dropped")
    assert after["type"] == dropped["type"] + 1  # not-a-type
    assert after["private"] == dropped["private"] + 1  # copy outside its channel


def test_sec_09_the_private_channel_dispatches_through_its_own_table(
    make, owner
) -> None:  # noqa: ANN001
    make("<p>tables</p>")
    got = owner.page.evaluate(
        """() => {
          const got = [];
          for (const [type, row] of PRIVATE_MESSAGES) row.handle = () => got.push(type);
          for (const type of ["copy", "open-file", "nope"]) privateMessage({type});
          return got;
        }"""
    )
    assert got == ["copy", "open-file"]


def test_arc_04_each_hub_message_reaches_the_handler_of_its_row(make, owner) -> None:  # noqa: ANN001
    make("<p>tables</p>")
    got, types = owner.page.evaluate(
        """() => {
          const got = [];
          for (const [type, row] of HUB_MESSAGES) row.handle = () => got.push(type);
          const types = [...HUB_MESSAGES.keys()];
          for (const type of [...types, "not-a-type"]) {
            const data = JSON.stringify({type});
            socket.dispatchEvent(new MessageEvent("message", {data}));
          }
          return [got, types];
        }"""
    )
    assert len(types) == 13
    assert got == types


# ---- step b: unknown types and fields are logged by name, once -------------------

NOTE = "agent-canvas: unknown message"
SECRET = "TOPSECRET"


def notes_of(page) -> list[str]:  # noqa: ANN001
    """Collect the console's notes of unknown messages (all frames of the page)."""
    lines: list[str] = []
    page.on("console", lambda m: lines.append(m.text) if NOTE in m.text else None)
    return lines


def test_sec_09_an_unknown_frame_message_is_logged_once_and_still_dropped(
    make, owner
) -> None:  # noqa: ANN001
    notes = notes_of(owner.page)
    make("<p>tables</p>")
    page = owner.page
    before = page.evaluate("({...window.__guard.dropped, ...window.__guard.accepted})")
    owner.frame.evaluate(
        """(secret) => {
          for (let i = 0; i < 2; i++) {
            parent.postMessage({type: "no-such-type", value: secret}, "*");
            parent.postMessage({type: "scroll-pos", x: 0, y: 1, extra: secret}, "*");
            parent.postMessage({type: "odd\\u202e\\u2028name"}, "*");
          }
        }""",
        SECRET,
    )
    page.wait_for_function(
        "(n) => (window.__guard.accepted['scroll-pos'] || 0) >= n + 2",
        arg=before.get("scroll-pos", 0),
    )
    page.wait_for_timeout(300)
    assert page.evaluate("window.__guard.dropped.type") == before["type"] + 4
    assert notes == [
        f'{NOTE} from the page: type "no-such-type"',
        f'{NOTE} field from the page: "scroll-pos" has "extra"',
        f'{NOTE} from the page: type "odd??name"',  # direction mark and line break
    ]


def test_sec_09_a_page_script_cannot_flood_the_console_with_unknown_types(
    make, owner
) -> None:  # noqa: ANN001
    notes = notes_of(owner.page)
    make("<p>tables</p>")
    owner.frame.evaluate(
        "for (let i = 0; i < 60; i++) parent.postMessage({type: 'made-up-' + i}, '*')"
    )
    owner.page.wait_for_timeout(500)
    # The page used its budget up; a mismatch with the hub is still written.
    owner.page.evaluate(
        "(data) => socket.dispatchEvent(new MessageEvent('message', {data}))",
        '{"type": "hub-x"}',
    )
    owner.page.wait_for_timeout(200)
    assert len([n for n in notes if "from the page" in n]) == 20
    assert notes[-1] == f'{NOTE} from the hub: type "hub-x"'


def test_sec_09_the_page_logs_an_unknown_type_or_field_from_the_window(
    make, owner
) -> None:  # noqa: ANN001
    notes = notes_of(owner.page)
    make("<p>tables</p>")
    owner.page.evaluate(
        """(secret) => {
          for (let i = 0; i < 2; i++) {
            postToFrame({type: "no-such-type", value: secret});
            postToFrame({type: "highlight", ids: [], extra: secret});
            postToFrame({type: "odd\\u202e\\u2028name"});
          }
        }""",
        SECRET,
    )
    owner.page.wait_for_timeout(500)
    assert notes == [
        f'{NOTE} from the window: type "no-such-type"',
        f'{NOTE} field from the window: "highlight" has "extra"',
        f'{NOTE} from the window: type "odd??name"',  # direction mark and line break
    ]


def test_arc_04_the_window_logs_unknown_hub_messages(make, owner) -> None:  # noqa: ANN001
    notes = notes_of(owner.page)
    made = make("<p>tables</p>")
    owner.page.evaluate(
        """([session, secret]) => {
          const hub = (message) => socket.dispatchEvent(
            new MessageEvent("message", {data: JSON.stringify(message)}));
          for (let i = 0; i < 2; i++) {
            hub({type: "no-such-type", value: secret});
            hub({type: "send-state", session, send: null, extra: secret});
          }
        }""",
        [made.sid, SECRET],
    )
    owner.page.wait_for_timeout(300)
    assert notes == [
        f'{NOTE} from the hub: type "no-such-type"',
        f'{NOTE} field from the hub: "send-state" has "extra"',
    ]
