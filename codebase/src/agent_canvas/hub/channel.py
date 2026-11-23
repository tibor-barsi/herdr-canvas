"""The window channel: owns the window connections and every push to them (ARC-03)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from agent_canvas.hub.messages import WINDOW_MESSAGES, note_unknown

Message = dict[str, Any]
# ``initial`` is True when the view is built for a window that just connected.
Builder = Callable[[bool], "Message | None"]
CallLater = Callable[[float, Callable[[], None]], Any]


@dataclass
class _View:
    build: Builder
    batch_ms: int
    pending: bool = False


class WindowChannel:
    """
    The window connections and the named views pushed to them.

    Parameters
    ----------
    hello : Callable[[], dict]
        Builds the ``hello`` message every new window gets first.
    get_loop : Callable[[], asyncio.AbstractEventLoop | None], optional
        The hub's loop, for pushes started from another thread.
    call_later : Callable[[float, Callable[[], None]], Any], optional
        Starts a timer (seconds, function); default is the running loop's.
    """

    def __init__(
        self,
        hello: Callable[[], Message],
        get_loop: Callable[[], asyncio.AbstractEventLoop | None] = lambda: None,
        call_later: CallLater | None = None,
    ) -> None:
        self._hello = hello
        self._get_loop = get_loop
        self._call_later = call_later or self._loop_call_later
        self.windows: set[Any] = set()
        self._views: dict[str, _View] = {}
        self._lock = asyncio.Lock()  # keeps the order of messages across tasks
        self._tasks: set[asyncio.Future[Any]] = set()

    def register(self, view: str, build: Builder, batch_ms: int) -> None:
        """
        Register a view; windows get ``build(initial)``, ``None`` sends nothing.

        Parameters
        ----------
        view : str
            Name of the view.
        build : Callable[[bool], dict | None]
            Builds the message; the flag says it is for a newly added window.
        batch_ms : int
            0 sends at once; otherwise the first change starts a batch of this
            length and one send at its end covers every change within it.
        """
        self._views[view] = _View(build, batch_ms)

    def publish(self, view: str) -> None:
        """Send ``view`` to every window now or batched; KeyError if unknown."""
        entry = self._views[view]
        if entry.batch_ms == 0:
            self._send_view(entry)
        elif not entry.pending:
            self._call_later(entry.batch_ms / 1000, lambda: self._flush(entry))
            entry.pending = True

    def broadcast(self, message: Message) -> None:
        """Send a message that is not a view to every window; safe from any thread."""
        _note_unknown(message)
        self._start(self._send_all(message))

    async def add(self, window: Any) -> None:
        """
        Greet a new window with ``hello`` and the current views, then include it.

        A window that cannot be greeted is not added.
        """
        async with self._lock:
            messages = [self._hello()]
            messages += [
                m for e in self._views.values() if (m := e.build(True)) is not None
            ]
            for message in messages:
                _note_unknown(message)
            try:
                for message in messages:
                    await window.send_json(message)
            except Exception:  # noqa: BLE001 - a broken window is just not added
                return
            self.windows.add(window)

    def discard(self, window: Any) -> None:
        """Forget a window that closed."""
        self.windows.discard(window)

    async def send_to(self, window: Any, message: Message) -> None:
        """Send to one window in order with the broadcasts; its error is raised."""
        _note_unknown(message)
        async with self._lock:
            await window.send_json(message)

    def _flush(self, entry: _View) -> None:
        entry.pending = False
        self._send_view(entry)

    def _send_view(self, entry: _View) -> None:
        message = entry.build(False)
        if message is not None:
            self.broadcast(message)

    async def _send_all(self, message: Message) -> None:
        async with self._lock:
            for window in list(self.windows):
                try:
                    await window.send_json(message)
                except Exception:  # noqa: BLE001 - never reaches the publisher
                    self.windows.discard(window)

    def _start(self, work: Coroutine[Any, Any, None]) -> None:
        try:
            task: asyncio.Future[Any] = asyncio.get_running_loop().create_task(work)
        except RuntimeError:
            loop = self._get_loop()
            if loop is None:
                work.close()
                return
            task = asyncio.run_coroutine_threadsafe(work, loop)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _loop_call_later(self, delay: float, function: Callable[[], None]) -> Any:
        try:
            return asyncio.get_running_loop().call_later(delay, function)
        except RuntimeError:  # another thread: hand the timer to the hub's loop
            loop = self._get_loop()
            if loop is None:
                raise
            return loop.call_soon_threadsafe(loop.call_later, delay, function)


def _note_unknown(message: Message) -> None:
    """Log a type or field of a window message that ``WINDOW_MESSAGES`` lacks."""
    note_unknown("to the windows", message, WINDOW_MESSAGES.get(message.get("type")))
