"""Send id, part and comments on every send (P20.3: COM-10, COM-11 slices; 5.3, 5.4)."""

from __future__ import annotations

import base64
import json
import re

import httpx
import pytest

from agent_canvas.hub.sends import list_sends

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"
SEND_ID = re.compile(r"^snd_[0-9a-f]{16}$")
RECORD_KEYS = {
    "schema", "event", "session", "page", "page_version", "created", "send_id",
    "part", "delivery", "message", "actions", "actions_dropped",
    "comments", "viewport", "screenshot", "screenshot_error", "screenshot_warnings",
}  # fmt: skip
EVENT_KEYS = {
    "type", "id", "session", "seq", "time", "kind", "send_id", "part", "page",
    "page_version", "target", "value", "delivery", "state", "message", "actions",
    "comments", "screenshot", "screenshot_error", "send_file",
}  # fmt: skip


def message_only(**changes) -> dict:  # noqa: ANN003
    base = {
        "delivery": "now", "message": "why this peak?", "page": "page.html",
        "actions": [], "actions_dropped": 0, "marks": [],
        "viewport": {"width": 800, "height": 600, "scroll_x": 0, "scroll_y": 0},
        "screenshot": base64.b64encode(PNG).decode(), "screenshot_error": None,
        "screenshot_warnings": [],
    }  # fmt: skip
    base.update(changes)
    return base


def post_send(hub, payload: dict) -> dict:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/send", headers=hub.key_headers, json=payload
    )
    assert answer.status_code == 200, answer.text
    return answer.json()["event"]


@pytest.fixture
def session(hub):  # noqa: ANN001, ANN201
    hub.add_session("a", {"page.html": "<p>x</p>"})
    return hub.sessions["a"]


def test_com_10_message_only_send_gives_one_event_with_id_and_part(
    hub, session
) -> None:
    event = post_send(hub, message_only())
    assert SEND_ID.match(event["send_id"])
    assert event["part"] == [1, 1] and event["comments"] == []
    assert EVENT_KEYS <= set(event)
    lines = (session.folder / "events.jsonl").read_text().splitlines()
    sends = [json.loads(x) for x in lines if json.loads(x)["kind"] == "send"]
    assert [e["id"] for e in sends] == [event["id"]]


def test_com_11_record_has_the_shape_of_5_4_and_the_same_ids(hub, session) -> None:
    event = post_send(hub, message_only())
    path = session.folder / "history" / "sends" / "0001.json"
    record = json.loads(path.read_text())
    assert set(record) == RECORD_KEYS
    assert record["send_id"] == event["send_id"] and record["part"] == [1, 1]
    assert record["comments"] == [] and "marks" not in record
    assert record["schema"] == "agent-canvas/send@1"


def test_com_10_send_ids_are_distinct_per_send(hub, session) -> None:
    ids = {post_send(hub, message_only())["send_id"] for _ in range(3)}
    assert len(ids) == 3
    assert {r["send_id"] for r in list_sends(session.folder)} == ids


def test_com_11_marks_of_an_old_shell_are_dropped_and_logged(
    hub, session, caplog
) -> None:
    mark = {
        "id": 1, "type": "box", "colour": "#e5484d", "points": [[1, 2], [3, 4]],
        "bbox": [1, 2, 2, 2], "text": None, "target": None,
    }  # fmt: skip
    with caplog.at_level("WARNING"):
        event = post_send(hub, message_only(marks=[mark]))
    [record] = list_sends(session.folder)
    assert "marks" not in record and "marks" not in event
    assert record["message"] == "why this peak?" and record["screenshot"] == "0001.png"
    assert event["screenshot"] and event["comments"] == []
    assert "dropped 1 marks" in caplog.text


def test_com_11_a_record_from_before_revision_12_reads_as_it_is(hub, session) -> None:
    directory = session.folder / "history" / "sends"
    directory.mkdir(parents=True, exist_ok=True)
    old = {
        "schema": "agent-canvas/send@1", "event": "evt_old", "session": "a",
        "page": "page.html", "page_version": 1, "created": "2026-10-20T10:06:01.120Z",
        "delivery": "now", "message": "old", "actions": [], "actions_dropped": 0,
        "marks": [],
        "viewport": {"width": 1, "height": 1, "scroll_x": 0, "scroll_y": 0},
        "screenshot": None, "screenshot_error": "x", "screenshot_warnings": [],
    }  # fmt: skip
    (directory / "0001.json").write_text(json.dumps(old))
    [read] = list_sends(session.folder)
    assert read == {"number": 1, **old}
    event = post_send(hub, message_only())
    assert event["send_file"].endswith("0002.json")
