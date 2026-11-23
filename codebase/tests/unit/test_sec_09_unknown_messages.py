"""An unknown message type or field is logged by name once, nothing more (P33.2)."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agent_canvas.hub import messages
from agent_canvas.hub.channel import WindowChannel
from agent_canvas.hub.routes.sockets import handle_shell_message

pytestmark = pytest.mark.unit

SECRET = "TOPSECRET"


@pytest.fixture
def notes(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):  # noqa: ANN201
    """Return the hub's notes of unknown messages, counted from a fresh start."""
    monkeypatch.setattr(messages, "_noted", set())
    caplog.set_level(logging.WARNING, logger="agent_canvas.hub.messages")
    return lambda: [
        r.getMessage() for r in caplog.records if messages.NOTE in r.getMessage()
    ]


def from_window(message: dict, svc: object = None) -> None:
    """Hand ``message`` to the hub as the window's socket does.

    In a fresh thread: browser tests leave an event loop running in this one.
    """
    coroutine = handle_shell_message(None, json.dumps(message), svc, None)
    with ThreadPoolExecutor(1) as pool:
        pool.submit(asyncio.run, coroutine).result()


def test_sec_09_an_unknown_type_from_the_window_is_logged_once_by_name(notes) -> None:  # noqa: ANN001
    for _ in range(2):
        from_window({"type": "no-such-type", "value": SECRET})
    from_window({"type": ["not", "a", "string"]})
    assert notes() == [
        "unknown message from a window: type 'no-such-type'",
        "unknown message from a window: type (not a string)",
    ]


def test_sec_09_an_unknown_field_is_logged_and_the_message_still_handled(notes) -> None:  # noqa: ANN001
    dismissed: list[str] = []
    svc = SimpleNamespace(
        asks=SimpleNamespace(dismiss=lambda _s, a: dismissed.append(a) or True)
    )
    message = {"type": "ask-dismiss", "session": "s1", "ask": "a1", "extra": SECRET}
    for _ in range(2):
        from_window(message, svc)
    assert dismissed == ["a1", "a1"]
    assert notes() == ["unknown message field from a window: 'ask-dismiss' has 'extra'"]


def test_sec_09_the_notes_stop_at_their_limit(notes) -> None:  # noqa: ANN001
    svc = SimpleNamespace(asks=SimpleNamespace(dismiss=lambda _s, _a: True))
    from_window({"type": "ask-dismiss", "session": SECRET, "odd": SECRET}, svc)
    for n in range(messages.MAX_NOTES + 5):
        from_window({"type": f"made-up-{n}", "value": SECRET})
    assert len(notes()) == messages.MAX_NOTES
    assert "unknown message field from a window: 'ask-dismiss' has 'odd'" in notes()
    assert all(SECRET not in line for line in notes())


def test_arc_04_a_window_message_the_table_lacks_is_logged_by_the_channel(
    notes,
) -> None:  # noqa: ANN001
    channel = WindowChannel(lambda: {"type": "hello"})
    channel.broadcast({"type": "listening", "session": "s1", "secret": SECRET})
    channel.broadcast({"type": "no-such-view", "home": SECRET})
    channel.broadcast({"type": "update", "url": "u", "version": 1, "html": SECRET})
    assert notes() == [
        "unknown message field to the windows: 'listening' has 'secret'",
        "unknown message to the windows: type 'no-such-view'",
    ]
