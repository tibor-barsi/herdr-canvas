"""One send takes the drafts of every page of the tab (COM-10, COM-11, 5.4)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import comments

pytestmark = pytest.mark.integration

PNG_A = b"\x89PNG\r\n\x1a\n" + b"picture-a"
PNG_B = b"\x89PNG\r\n\x1a\n" + b"picture-b"
SHOT = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"screenshot").decode()
SEND = {
    "delivery": "now", "message": "", "page": "a.html", "pages": ["b.html", "c.html"],
    "viewport": {"width": 10, "height": 10, "scroll_x": 0, "scroll_y": 0},
    "screenshot": SHOT, "screenshot_error": None,
}  # fmt: skip


def draft(page: str, text: str, picture: bytes | None = PNG_A) -> dict:
    return {
        "page": page, "page_version": 1, "kind": "point", "text": text,
        "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
        "target": {"canvas_id": None, "selector": "#fig", "text": None},
        "picture": base64.b64encode(picture).decode() if picture else None,
    }  # fmt: skip


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    client = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    client.get(hub.login_url(), follow_redirects=False)
    return client


@pytest.fixture
def tab(hub) -> dict:  # noqa: ANN001
    hub.add_session("t", {name: "<p>x</p>" for name in ("a.html", "b.html", "c.html")})
    hub.add_session("other", {"a.html": "<p>x</p>"})
    return {"id": "t", "folder": hub.sessions["t"].folder}


def save(owner, session: str, page: str, text: str = "note", **more) -> None:  # noqa: ANN001, ANN003
    answer = owner.post(
        f"/api/sessions/{session}/comments", json={**draft(page, text), **more}
    )
    assert answer.status_code == 200, answer.text


def post_send(hub, session: str = "t", **changes):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/{session}/send",
        headers=hub.key_headers,
        json={**SEND, **changes},
    )


def record(folder: Path, number: int) -> dict:
    return json.loads((folder / "history/sends" / f"{number:04d}.json").read_text())


def test_com_10_every_page_with_drafts_gets_its_own_linked_event(
    hub, owner, tab
) -> None:  # noqa: ANN001
    save(owner, "t", "a.html", "on a")
    save(owner, "t", "b.html", "on b", picture=base64.b64encode(PNG_B).decode())
    answer = post_send(hub, message="look", actions=[{"kind": "click", "time": "t"}])
    assert answer.status_code == 200, answer.text
    first, second = answer.json()["events"]
    assert answer.json()["event"] == first
    assert [first["page"], second["page"]] == ["a.html", "b.html"]
    assert [first["part"], second["part"]] == [[1, 2], [2, 2]]
    assert first["send_id"] == second["send_id"]
    assert first["message"] == "look" and len(first["actions"]) == 1
    assert first["screenshot"].endswith("history/sends/0001.png")
    assert first["screenshot_error"] is None
    assert second["message"] == "" and second["actions"] == []
    assert second["screenshot"] is None
    assert second["screenshot_error"] == "page not shown"
    assert [c["text"] for c in first["comments"]] == ["on a"]
    assert [c["text"] for c in second["comments"]] == ["on b"]
    sends = tab["folder"] / "history/sends"
    assert (sends / "0001.c1.png").read_bytes() == PNG_A
    assert (sends / "0002.c1.png").read_bytes() == PNG_B
    assert second["comments"][0]["picture"] == str((sends / "0002.c1.png").resolve())
    assert not (sends / "0002.png").exists()
    for number, event in ((1, first), (2, second)):
        stored = record(tab["folder"], number)
        assert stored["event"] == event["id"] and stored["page"] == event["page"]
        assert stored["send_id"] == first["send_id"] and stored["part"] == event["part"]
    assert record(tab["folder"], 2)["screenshot_error"] == "page not shown"


def test_com_10_the_events_reach_the_agent_in_order_and_all_comments_are_sent(
    hub, owner, tab
) -> None:  # noqa: ANN001
    save(owner, "t", "b.html")
    save(owner, "t", "a.html")
    post_send(hub)
    queued = hub.on_loop(lambda: hub.state.events.log("t").queued())
    assert [e["page"] for e in queued] == ["a.html", "b.html"]
    assert [e["seq"] for e in queued] == sorted(e["seq"] for e in queued)
    for page in ("a.html", "b.html"):
        [stored] = comments.load(tab["folder"], page)["comments"]
        assert stored["sent"] and stored["send_event"]


def test_com_10_unlisted_pages_and_pages_without_drafts_send_nothing(
    hub, owner, tab
) -> None:  # noqa: ANN001
    save(owner, "t", "a.html")
    save(owner, "t", "c.html", "not listed")
    save(owner, "other", "a.html", "other tab")
    answer = post_send(hub, pages=["b.html"])
    [event] = answer.json()["events"]
    assert event["part"] == [1, 1] and event["page"] == "a.html"
    for session, page in (("t", "c.html"), ("other", "a.html")):
        folder = hub.sessions[session].folder
        [stored] = comments.load(folder, page)["comments"]
        assert stored["sent"] is None
    assert not (tab["folder"] / "history/sends/0002.json").exists()


def test_com_10_the_active_page_leads_even_without_drafts_of_its_own(
    hub, owner, tab
) -> None:  # noqa: ANN001
    save(owner, "t", "b.html")
    first, second = post_send(hub, message="hello").json()["events"]
    assert (first["page"], first["part"], first["message"]) == (
        "a.html",
        [1, 2],
        "hello",
    )
    assert first["comments"] == [] and first["screenshot"]
    assert (second["page"], second["part"]) == ("b.html", [2, 2])


def test_com_11_a_send_with_nothing_on_any_page_is_refused(hub, tab) -> None:  # noqa: ANN001
    assert post_send(hub).status_code == 400
    assert not (tab["folder"] / "history").exists()


@pytest.mark.parametrize(
    "pages", [["../x.html"], "b.html", ["b.html", 3], ["notapage"]]
)
def test_com_11_bad_page_names_are_refused_and_nothing_is_taken(
    hub, owner, tab, pages
) -> None:  # noqa: ANN001
    save(owner, "t", "a.html")
    assert post_send(hub, pages=pages).status_code == 400
    [stored] = comments.load(tab["folder"], "a.html")["comments"]
    assert stored["sent"] is None


def test_com_10_a_failure_on_one_page_gives_the_drafts_of_all_back(
    hub, owner, tab, monkeypatch
) -> None:  # noqa: ANN001
    from agent_canvas.hub import sends

    save(owner, "t", "a.html")
    save(owner, "t", "b.html")
    real = sends.store_send
    calls = []

    def second_fails(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr("agent_canvas.hub.routes.sessions.store_send", second_fails)
    try:
        failed = post_send(hub)
    except httpx.HTTPError:
        failed = None
    assert failed is None or failed.status_code == 500
    for page in ("a.html", "b.html"):
        [stored] = comments.load(tab["folder"], page)["comments"]
        assert stored["sent"] is None and stored["send_event"] is None
    assert list((tab["folder"] / "history/sends").glob("*")) == []
    monkeypatch.undo()
    assert len(post_send(hub).json()["events"]) == 2
