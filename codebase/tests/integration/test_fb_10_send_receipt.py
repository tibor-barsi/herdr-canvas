"""The window learns of each send and of its delivery from the hub (FB-10)."""

from __future__ import annotations

import httpx
import pytest

from shellfake import FakeShell

pytestmark = pytest.mark.integration

SEND = {
    "delivery": "now", "message": "look", "page": None,
    "viewport": {"width": 1, "height": 1, "scroll_x": 0, "scroll_y": 0},
    "screenshot": None, "screenshot_error": "none",
}  # fmt: skip


def post(hub, path: str, **body: object) -> dict:  # noqa: ANN001
    answer = httpx.post(hub.base_url + path, json=body, headers=hub.key_headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def pushed_send(shell: FakeShell, sid: str) -> dict | None:
    """The newest ``send-state`` push for ``sid``, else the send of its last tab."""
    for message in reversed(list(shell.messages)):
        if message.get("type") == "send-state" and message["session"] == sid:
            return message["send"]
        if message.get("type") == "tabs":
            return next(t["send"] for t in message["sessions"] if t["id"] == sid)
    return None


def test_fb_10_a_send_and_its_delivery_each_tell_the_window(hub) -> None:  # noqa: ANN001
    project = hub.project_dir / "p"
    project.mkdir()
    sid = post(hub, "/api/sessions", project=str(project), agent="claude")["session"]
    shell = FakeShell(hub)
    try:
        hub.wait_for(lambda: "tabs" in shell.types())
        assert pushed_send(shell, sid) is None
        first = post(hub, f"/api/sessions/{sid}/send", **SEND)["event"]
        hub.wait_for(
            lambda: (pushed_send(shell, sid) or {}).get("time") == first["time"]
        )
        assert pushed_send(shell, sid) == {
            "time": first["time"], "delivery": "now", "read": None,
        }  # fmt: skip
        post(hub, f"/api/sessions/{sid}/pending")
        hub.wait_for(lambda: pushed_send(shell, sid)["read"] is not None)
        second = post(hub, f"/api/sessions/{sid}/send", **SEND)["event"]
        hub.wait_for(lambda: pushed_send(shell, sid)["time"] == second["time"])
        assert pushed_send(shell, sid)["read"] is None
    finally:
        shell.close()


def test_fb_10_an_unread_send_is_in_the_tabs_after_a_hub_restart(hub) -> None:  # noqa: ANN001
    project = hub.project_dir / "p"
    project.mkdir()
    sid = post(hub, "/api/sessions", project=str(project), agent="claude")["session"]
    sent = post(hub, f"/api/sessions/{sid}/send", **SEND)["event"]
    hub.restart()
    shell = FakeShell(hub)
    try:
        hub.wait_for(lambda: "tabs" in shell.types())
        assert pushed_send(shell, sid) == {
            "time": sent["time"], "delivery": "now", "read": None,
        }  # fmt: skip
    finally:
        shell.close()
