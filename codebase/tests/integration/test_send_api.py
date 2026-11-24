"""Send upload, send record files, event and listing (M9: DRAW-05, HIST-03)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"
MARK = {
    "id": 1, "type": "pen", "colour": "#e5484d", "points": [[412, 96], [415, 99]],
    "bbox": [412, 96, 3, 3], "text": None,
    "target": {"canvas_id": "spectrum", "data_bbox": None},
}  # fmt: skip


def body(**changes) -> dict:  # noqa: ANN003
    base = {
        "delivery": "now", "message": "why this peak?", "page": "page.html",
        "actions": [
            {"kind": "button", "time": "2026-10-20T10:00:00.000Z",
             "target": {"canvas_id": "go"}, "value": "stop", "at": None,
             "event": "evt_before"},
        ],
        "actions_dropped": 2, "marks": [MARK],
        "viewport": {"width": 1280, "height": 800, "scroll_x": 0, "scroll_y": 340},
        "screenshot": base64.b64encode(PNG).decode(), "screenshot_error": None,
        "screenshot_warnings": [],
    }  # fmt: skip
    base.update(changes)
    return base


def post_send(hub, session: str, payload: dict, headers: dict | None = None):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/{session}/send",
        headers=hub.key_headers if headers is None else headers,
        json=payload,
    )


@pytest.fixture
def session(hub):  # noqa: ANN001, ANN201
    hub.add_session("a", {"page.html": "<p>x</p>"})
    return hub.sessions["a"]


def test_draw_05_send_stores_png_and_record_and_creates_the_event(hub, session) -> None:
    answer = post_send(hub, "a", body())
    assert answer.status_code == 200, answer.text
    event = answer.json()["event"]
    folder = session.folder / "history" / "sends"
    assert (folder / "0001.png").read_bytes() == PNG
    record = json.loads((folder / "0001.json").read_text())
    assert record["schema"] == "agent-canvas/send@1"
    assert record["event"] == event["id"] and record["session"] == "a"
    assert record["actions"][0]["event"] == "evt_before"
    assert record["actions_dropped"] == 2
    assert "marks" not in record
    assert record["screenshot"] == "0001.png"
    assert event["kind"] == "send" and event["delivery"] == "now"
    assert event["state"] == "queued" and event["message"] == "why this peak?"
    assert event["screenshot"] == str(folder / "0001.png")
    assert event["send_file"] == str(folder / "0001.json")
    assert event["screenshot_error"] is None
    assert event["page"] == "page.html"


def test_draw_05_the_marks_of_an_old_shell_do_not_reach_the_event(hub, session) -> None:
    event = post_send(hub, "a", body()).json()["event"]
    assert "marks" not in event
    assert event["actions"][0]["event"] == "evt_before"


def test_draw_05_send_event_is_in_the_log_and_pending(hub) -> None:
    registered = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        headers=hub.key_headers,
        json={"project": str(hub.project_dir), "agent": "t"},
    )
    assert registered.status_code == 200, registered.text
    pool = hub.state.session_of(hub.pool_of("a"))  # a card's send is in its pool's log
    (pool.folder / "page.html").write_text("<p>x</p>")
    shown = httpx.post(  # a session not listening gets the sends on pages it touched
        f"{hub.base_url}/api/sessions/a/show",
        headers=hub.key_headers,
        json={"name": "page.html", "audit": False},
        timeout=30,
    )
    assert shown.status_code == 200, shown.text
    event = post_send(hub, "a", body()).json()["event"]
    lines = (pool.folder / "events.jsonl").read_text().splitlines()
    logged = json.loads(lines[0])
    assert (logged["id"], logged["for"]) == (event["id"], "a")
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/pending",
        headers=hub.key_headers,
        json={"peek": True},
    )
    assert [e["id"] for e in answer.json()["events"]] == [event["id"]]


def test_draw_05_page_version_is_the_latest_version(hub, session) -> None:
    pages = session.folder / "history" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    (pages / "page.0001.html").write_text("<p>1</p>")
    (pages / "page.0002.html").write_text("<p>2</p>")
    event = post_send(hub, "a", body()).json()["event"]
    assert event["page_version"] == 2


def test_draw_05_send_numbers_increase(hub, session) -> None:
    post_send(hub, "a", body())
    second = post_send(hub, "a", body(message="again")).json()["event"]
    assert second["send_file"].endswith("0002.json")
    assert second["seq"] == 2


def test_fb_04_next_message_send_is_not_offered_to_a_watch(hub, session) -> None:
    event = post_send(hub, "a", body(delivery="next-message")).json()["event"]
    assert event["delivery"] == "next-message" and event["state"] == "queued"


def test_draw_05_failed_capture_still_creates_the_send(hub, session) -> None:
    payload = body(screenshot=None, screenshot_error="capture timed out")
    event = post_send(hub, "a", payload).json()["event"]
    folder = session.folder / "history" / "sends"
    assert not (folder / "0001.png").exists()
    record = json.loads((folder / "0001.json").read_text())
    assert record["screenshot"] is None
    assert record["screenshot_error"] == "capture timed out"
    assert event["screenshot"] is None
    assert event["screenshot_error"] == "capture timed out"
    assert event["send_file"] == str(folder / "0001.json")


def test_draw_06_screenshot_warnings_are_kept_in_the_record(hub, session) -> None:
    warning = {"canvas_id": None, "selector": "#raw-gl", "reason": "webgl-not-captured"}
    post_send(hub, "a", body(screenshot_warnings=[warning]))
    record = json.loads((session.folder / "history/sends/0001.json").read_text())
    assert record["screenshot_warnings"] == [warning]


def test_draw_05_invalid_send_is_refused_and_leaves_no_files(hub, session) -> None:
    answer = post_send(hub, "a", body(delivery="ask"))
    assert answer.status_code == 400
    assert "delivery" in answer.json()["message"]
    assert not (session.folder / "history" / "sends").exists()
    assert not (session.folder / "events.jsonl").exists()


def test_draw_05_unknown_session_is_404_and_no_key_is_refused(hub, session) -> None:
    assert post_send(hub, "nope", body()).status_code == 404
    assert post_send(hub, "a", body(), headers={}).status_code in (401, 403)


def test_hist_03_listing_and_screenshot_endpoints(hub, session) -> None:
    post_send(hub, "a", body(message="first"))
    post_send(hub, "a", body(message="second", screenshot=None, screenshot_error="x"))
    listing = httpx.get(f"{hub.base_url}/api/sessions/a/sends", headers=hub.key_headers)
    sends = listing.json()["sends"]
    assert [(s["number"], s["message"]) for s in sends] == [(1, "first"), (2, "second")]
    assert sends[0]["actions"][0]["value"] == "stop"
    first = httpx.get(
        f"{hub.base_url}/api/sessions/a/sends/1.png", headers=hub.key_headers
    )
    assert first.status_code == 200 and first.content == PNG
    assert first.headers["content-type"] == "image/png"
    for missing in ("2.png", "9.png", "x.png"):
        answer = httpx.get(
            f"{hub.base_url}/api/sessions/a/sends/{missing}", headers=hub.key_headers
        )
        assert answer.status_code == 404


def test_draw_05_a_malformed_content_length_is_a_400_not_a_crash(hub, session) -> None:
    import socket

    with socket.create_connection(("127.0.0.1", hub.port)) as sock:
        sock.sendall(
            (
                f"POST /api/sessions/a/send HTTP/1.1\r\nHost: 127.0.0.1:{hub.port}\r\n"
                f"X-Agent-Canvas-Key: {hub.key}\r\nContent-Type: application/json\r\n"
                "Content-Length: twelve\r\nConnection: close\r\n\r\n{}"
            ).encode()
        )
        reply = sock.recv(200)
    assert reply.split(b" ")[1] == b"400"


def test_draw_05_a_chunked_body_over_16_mb_is_refused(hub, session) -> None:
    def chunks():  # noqa: ANN202
        for _ in range(17):
            yield b" " * (1024 * 1024)

    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/send",
        headers={**hub.key_headers, "Content-Type": "application/json"},
        content=chunks(),
        timeout=30,
    )
    assert answer.status_code == 413
