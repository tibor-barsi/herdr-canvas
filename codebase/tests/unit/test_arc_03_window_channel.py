"""The window channel batches views and keeps the order of messages (ARC-03)."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from agent_canvas.hub.channel import WindowChannel

pytestmark = pytest.mark.unit


class FakeClock:
    """A timer source that only moves when the test advances it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.timers: list[tuple[float, Callable[[], None]]] = []

    def call_later(self, delay: float, function: Callable[[], None]) -> None:
        """Start a timer that fires ``delay`` seconds from now."""
        self.timers.append((self.now + delay, function))

    async def advance(self, milliseconds: float) -> None:
        """Move time forward, fire due timers in order, let the sends run."""
        self.now += milliseconds / 1000
        for timer in sorted(self.timers, key=lambda t: t[0]):
            if timer[0] <= self.now + 1e-9:
                self.timers.remove(timer)
                timer[1]()
        await settle()


class FakeWindow:
    """A window that records what it is sent, or fails when told to."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        """Record ``message`` or raise like a closed socket."""
        if self.fail:
            raise RuntimeError("closed")
        self.messages.append(message)


async def settle() -> None:
    """Let every scheduled send finish."""
    for _ in range(10):
        await asyncio.sleep(0)


class Views:
    """A channel with counting builders for ``tabs`` (0 ms) and ``home`` (200 ms)."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.builds = {"tabs": 0, "home": 0}
        self.channel = WindowChannel(
            {"type": "hello"}.copy, call_later=self.clock.call_later
        )
        self.channel.register("tabs", self.builder("tabs"), 0)
        self.channel.register("home", self.builder("home"), 200)

    def builder(self, view: str) -> Callable[[bool], dict[str, Any]]:
        """Return a builder that counts its calls and numbers its messages."""

        def build(initial: bool) -> dict[str, Any]:
            self.builds[view] += 1
            return {"type": view, "n": self.builds[view]}

        return build


def run(test: Callable[[], Any]) -> Callable[[], None]:
    """Run an async test body on a fresh loop in its own thread."""

    @functools.wraps(test)
    def wrapper() -> None:
        with ThreadPoolExecutor(1) as pool:
            pool.submit(asyncio.run, test()).result()

    return wrapper


def types(window: FakeWindow) -> list[str]:
    """Message types a window got."""
    return [m["type"] for m in window.messages]


@run
async def test_arc_03_twenty_publishes_in_a_batch_give_one_build_and_one_send() -> None:
    """20 ``home`` publishes within 100 ms: one build, one send at 200 ms."""
    views, window = Views(), FakeWindow()
    views.channel.windows.add(window)
    for _ in range(20):
        views.channel.publish("home")
        await views.clock.advance(5)
    await views.clock.advance(99)
    assert window.messages == []
    await views.clock.advance(1)
    await views.clock.advance(500)
    assert views.builds["home"] == 1
    assert types(window) == ["home"]


@run
async def test_arc_03_two_publishes_250_ms_apart_give_two_sends() -> None:
    """A change after the batch ended starts a new batch."""
    views, window = Views(), FakeWindow()
    views.channel.windows.add(window)
    views.channel.publish("home")
    await views.clock.advance(250)
    views.channel.publish("home")
    await views.clock.advance(250)
    assert views.builds["home"] == 2
    assert types(window) == ["home", "home"]


@run
async def test_arc_03_tabs_are_sent_at_once() -> None:
    """``tabs`` has no batch: sent without the clock moving."""
    views, window = Views(), FakeWindow()
    views.channel.windows.add(window)
    views.channel.publish("tabs")
    await settle()
    assert types(window) == ["tabs"]


@run
async def test_arc_03_a_new_window_gets_hello_tabs_home_then_the_batch() -> None:
    """A window added during a pending batch is greeted before the batch arrives."""
    views, old, new = Views(), FakeWindow(), FakeWindow()
    views.channel.windows.add(old)
    views.channel.publish("home")
    await views.clock.advance(50)
    await views.channel.add(new)
    assert types(new) == ["hello", "tabs", "home"]
    await views.clock.advance(150)
    assert types(new) == ["hello", "tabs", "home", "home"]
    assert types(old) == ["home"]


@run
async def test_arc_03_a_view_that_builds_nothing_sends_nothing() -> None:
    """The ``home`` stub returns None until P14.3: windows get no ``home``."""
    channel = WindowChannel(lambda: {"type": "hello"})
    channel.register("home", lambda initial: None, 0)
    window = FakeWindow()
    await channel.add(window)
    channel.publish("home")
    await settle()
    assert types(window) == ["hello"]


@run
async def test_arc_03_a_failing_window_is_dropped_and_the_others_get_the_message() -> (
    None
):
    """A send error neither reaches the publisher nor stops the other windows."""
    views, good, bad = Views(), FakeWindow(), FakeWindow(fail=True)
    views.channel.windows.update({good, bad})
    views.channel.publish("tabs")
    await settle()
    assert types(good) == ["tabs"]
    assert views.channel.windows == {good}


@run
async def test_arc_03_an_unknown_view_raises_key_error() -> None:
    """Publishing a view nobody registered is a programming error."""
    with pytest.raises(KeyError):
        Views().channel.publish("nothing")


def test_arc_03_a_batched_publish_from_another_thread_is_sent() -> None:
    """A watcher thread may publish a batched view; it is sent, never wedged."""

    async def body() -> list[str]:
        loop = asyncio.get_running_loop()
        channel = WindowChannel({"type": "hello"}.copy, get_loop=lambda: loop)
        channel.register("home", lambda initial: {"type": "home"}, 20)
        window = FakeWindow()
        channel.windows.add(window)
        await loop.run_in_executor(None, channel.publish, "home")
        await asyncio.sleep(0.1)
        await loop.run_in_executor(None, channel.publish, "home")
        await asyncio.sleep(0.1)
        await settle()
        return types(window)

    with ThreadPoolExecutor(1) as pool:
        assert pool.submit(asyncio.run, body()).result() == ["home", "home"]


@run
async def test_arc_03_a_failing_builder_is_raised_when_a_window_is_added() -> None:
    """A bug in a view builder is not swallowed as if the window had closed."""
    channel = WindowChannel({"type": "hello"}.copy)
    channel.register("tabs", lambda initial: 1 / 0, 0)
    with pytest.raises(ZeroDivisionError):
        await channel.add(FakeWindow())
