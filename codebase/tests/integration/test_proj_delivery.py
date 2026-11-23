"""Delivery of comments and card answers on project pages (PROJ-07 to PROJ-11, #88)."""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest
from tests.integration.test_cli_watch import Watching

from agent_canvas.hooks import format_events
from agent_canvas.hub import comments

pytestmark = pytest.mark.integration

PAGE = "dashboard.html"
COMMENT = {
    "page": PAGE, "page_version": 1, "kind": "point", "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
    "target": {"canvas_id": None, "selector": "#fig", "text": None},
}  # fmt: skip
SEND = {
    "delivery": "now", "message": "", "page": PAGE,
    "viewport": {"width": 10, "height": 10, "scroll_x": 0, "scroll_y": 0},
    "screenshot": None, "screenshot_error": "none",
}  # fmt: skip


@pytest.fixture
def repo(home: Path) -> Path:
    """A git repository below the fake home."""
    path = home / "proj"
    path.mkdir(exist_ok=True)
    (path / ".git").mkdir()
    return path


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    client = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    client.get(hub.login_url(), follow_redirects=False)
    return client


LISTENERS: dict[str, object] = {}


def agent_event(hub, session: str, name: str, cwd: Path) -> None:  # noqa: ANN001
    """Make ``session`` listen (a prompt) or stop listening (its end)."""
    events = hub.app.state.events
    if name == "SessionEnd":
        hub.on_loop(lambda: events.remove_listener(LISTENERS.pop(session)))
    else:
        LISTENERS[session] = hub.on_loop(lambda: events.add_listener(session, "ask"))


def project_page(cli, repo: Path, updater: str = "A", *others: str) -> dict:  # noqa: ANN001
    """Make the sessions known; ``updater`` shows the project page; return its ids."""
    for session in (updater, *others):
        assert cli("session", "path", "--session", session, cwd=repo).code == 0
    found = cli("session", "path", "--session", updater, "--project-page", cwd=repo)
    (Path(found.json["folder"]) / PAGE).write_text(
        '<title>Dashboard</title><canvas-ask data-canvas-id="q1">'
        '<script type="application/json">{"question": "Keep?", '
        '"options": ["keep", "change"]}</script></canvas-ask>'
    )
    shown = show(cli, updater, repo)
    assert shown.code == 0, shown.err
    return found.json


def show(cli, session: str, repo: Path, page: str = PAGE):  # noqa: ANN001, ANN201
    """Show a page of the project as ``session``, which becomes its updater."""
    return cli(
        "show", page, "--session", session, "--project-page", "--no-audit", cwd=repo
    )


def comment_and_send(hub, owner: httpx.Client, project: str) -> str:  # noqa: ANN001
    """The owner comments on the project page and sends it; return the event id."""
    base = f"/api/sessions/{project}"
    assert owner.post(f"{base}/comments", json=COMMENT).status_code == 200
    sent = httpx.post(f"{hub.base_url}{base}/send", json=SEND, headers=hub.key_headers)
    assert sent.status_code == 200, sent.text
    return sent.json()["event"]["id"]


def answer_card(owner: httpx.Client, project: str) -> str:
    """The owner answers the page's card; return the event id."""
    given = owner.post(
        f"/api/sessions/{project}/answers/answer",
        json={"page": PAGE, "id": "q1", "value": {"answer": ["keep"]}},
    )
    assert given.status_code == 200, given.text
    return given.json()["event"]


def pending(cli, session: str, repo: Path) -> list[dict]:  # noqa: ANN001
    answer = cli("pending", "--session", session, cwd=repo)
    assert answer.code == 0, answer.err
    return answer.json["events"]


def test_proj_07_the_running_updater_gets_the_event_and_another_session_does_not(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A", "B")["session"]
    agent_event(hub, "A", "UserPromptSubmit", repo)
    sent, answered = comment_and_send(hub, owner, project), answer_card(owner, project)
    assert pending(cli, "B", repo) == []
    taken = pending(cli, "A", repo)
    assert [e["id"] for e in taken] == [sent, answered]
    assert all(e["project_page"] and e["session"] == project for e in taken)


def test_proj_07_after_the_updater_ends_another_session_gets_the_event(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A", "B")["session"]
    agent_event(hub, "A", "UserPromptSubmit", repo)
    sent = comment_and_send(hub, owner, project)
    assert pending(cli, "B", repo) == []
    agent_event(hub, "A", "SessionEnd", repo)
    assert [e["id"] for e in pending(cli, "B", repo)] == [sent]
    assert pending(cli, "A", repo) == []


def test_proj_07_with_no_session_running_the_event_waits_for_a_later_session(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A")["session"]
    sent = comment_and_send(hub, owner, project)
    assert hub.event_state(project, sent) == "queued"
    assert cli("session", "path", "--session", "C", cwd=repo).code == 0
    assert [e["id"] for e in pending(cli, "C", repo)] == [sent]
    assert hub.event_state(project, sent) == "delivered"


def test_proj_08_two_pickups_at_the_same_moment_give_the_event_to_exactly_one(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A", "B", "C")["session"]
    sent = comment_and_send(hub, owner, project)
    results: dict[str, list[dict]] = {}
    start = threading.Barrier(2)

    def pick(session: str) -> None:
        start.wait()
        answer = httpx.post(
            f"{hub.base_url}/api/sessions/{session}/pending",
            json={},
            headers=hub.key_headers,
        )
        results[session] = answer.json()["events"]

    threads = [threading.Thread(target=pick, args=(s,)) for s in ("B", "C")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    got = [e["id"] for events in results.values() for e in events]
    assert sorted(results) == ["B", "C"] and got == [sent]


def test_proj_09_a_reserved_session_takes_an_inbox_item_and_gets_no_folder(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A")["session"]
    sent = comment_and_send(hub, owner, project)
    reserved = httpx.post(
        f"{hub.base_url}/api/sessions/R/reserve",
        json={"project": str(repo), "agent": "claude-code"},
        headers=hub.key_headers,
    )
    assert reserved.status_code == 200, reserved.text
    assert [e["id"] for e in pending(cli, "R", repo)] == [sent]
    assert not (repo / ".agent-canvas" / "R").exists()
    assert hub.event_state(project, sent) == "delivered"


def test_proj_10_a_now_event_reaches_the_updaters_watch_and_turns_the_comment_seen(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    found = project_page(cli, repo, "A")
    watch = Watching(cli, "--session", "A", "--count", "1", "--timeout", "20")
    try:
        hub.wait_for(lambda: hub.listening("A"), timeout=15)
        sent = comment_and_send(hub, owner, found["session"])
        event = watch.line(timeout=15)
        assert event["id"] == sent and event["project_page"] is True
        watch.rest(timeout=15)
        hub.wait_for(lambda: hub.event_state(found["session"], sent) == "delivered")
    finally:
        if watch.process.poll() is None:
            watch.process.kill()
        watch.process.wait()
    (stored,) = comments.load(Path(found["folder"]), PAGE)["comments"]
    assert stored["seen"]


def test_proj_10_an_inbox_event_is_not_pushed_to_a_watch(cli, hub, owner, repo) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A", "B")["session"]
    watch = Watching(cli, "--session", "B", "--count", "1", "--timeout", "60")
    try:
        hub.wait_for(lambda: hub.listening("B"), timeout=15)
        sent = comment_and_send(hub, owner, project)  # A, the updater, is not running
        assert show(cli, "B", repo).code == 0
        answered = answer_card(owner, project)  # B, now the updater, is watching
        assert watch.line(timeout=15)["id"] == answered  # the inbox event never came
        watch.rest(timeout=15)  # let the watch acknowledge before it is reaped
    finally:
        if watch.process.poll() is None:
            watch.process.kill()
        watch.process.wait()
    hub.wait_for(lambda: hub.event_state(project, answered) == "delivered", timeout=15)
    assert hub.event_state(project, sent) == "queued"
    assert [e["id"] for e in pending(cli, "B", repo)] == [sent]


def test_proj_07_cleanup_without_force_keeps_a_waiting_project_event(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A")["session"]
    sent = comment_and_send(hub, owner, project)
    cleaned = cli("cleanup", "--session", project, "--yes", cwd=repo)
    assert cleaned.code != 0  # the project session is never cleaned (A-969)
    assert hub.event_state(project, sent) == "queued"
    assert [e["id"] for e in pending(cli, "A", repo)] == [sent]


def test_proj_11_the_hook_text_names_the_project_page_and_the_reply_flag(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A")["session"]
    comment_and_send(hub, owner, project)
    answer_card(owner, project)
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/A/pending",
        json={"via": "hook"},
        headers=hub.key_headers,
    )
    text = format_events(answer.json()["events"])
    assert f"(project page {PAGE})" in text
    assert f"(project page {PAGE}, version" in text
    assert f"agent-canvas comment reply --project-page {PAGE} N" in text
    plain = format_events(
        [{**e, "project_page": False} for e in answer.json()["events"]]
    )
    assert f"({PAGE})" in plain and "--project-page" not in plain


def test_proj_07_an_event_without_a_page_goes_to_the_active_pages_updater(
    cli, hub, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A", "B")["session"]
    agent_event(hub, "A", "UserPromptSubmit", repo)
    made = hub.create_event(project, "custom", delivery="next-message")["id"]
    assert pending(cli, "B", repo) == []
    assert [e["id"] for e in pending(cli, "A", repo)] == [made]


def test_proj_07_an_event_on_a_page_without_an_updater_goes_to_the_inbox(
    cli, hub, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A", "B")["session"]
    agent_event(hub, "A", "UserPromptSubmit", repo)
    made = hub.create_event(project, "custom", page="other.html")["id"]
    assert [e["id"] for e in pending(cli, "B", repo)] == [made]


def test_proj_07_a_new_updater_takes_an_event_queued_under_the_old_one(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A", "B")["session"]
    for session in ("A", "B"):
        agent_event(hub, session, "UserPromptSubmit", repo)
    sent = comment_and_send(hub, owner, project)
    assert show(cli, "B", repo).code == 0
    assert pending(cli, "A", repo) == []
    assert [e["id"] for e in pending(cli, "B", repo)] == [sent]


def test_proj_07_a_session_of_another_project_never_takes_this_projects_events(
    cli, hub, owner, repo, home
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A")["session"]
    other = home / "other"
    (other / ".git").mkdir(parents=True)
    assert cli("session", "path", "--session", "X", cwd=other).code == 0
    agent_event(hub, "X", "UserPromptSubmit", other)
    sent = comment_and_send(hub, owner, project)
    assert pending(cli, "X", other) == []
    assert hub.event_state(project, sent) == "queued"
    assert [e["id"] for e in pending(cli, "A", repo)] == [sent]


def test_proj_07_pending_and_watch_on_the_project_id_are_refused_and_take_nothing(
    cli, hub, owner, repo
) -> None:  # noqa: ANN001
    project = project_page(cli, repo, "A")["session"]
    sent = comment_and_send(hub, owner, project)
    watched = cli("watch", "--session", project, "--timeout", "5", cwd=repo)
    assert watched.code == 5, (watched.out, watched.err)
    picked = cli("pending", "--session", project, cwd=repo)
    assert picked.code == 5 and picked.json["error"] == "no-session"
    assert hub.event_state(project, sent) == "queued"
    assert [e["id"] for e in pending(cli, "A", repo)] == [sent]


def test_proj_07_own_events_still_come_when_the_project_log_cannot_be_read(
    cli, hub, repo
) -> None:  # noqa: ANN001
    folder = Path(project_page(cli, repo, "A", "B")["folder"])
    own = hub.create_event("B", "custom")["id"]
    (folder / "events.jsonl").write_bytes(b"\xff\xfe not utf-8\n")
    assert [e["id"] for e in pending(cli, "B", repo)] == [own]
    assert hub.event_state("B", own) == "delivered"
    assert (folder / "events.jsonl").read_bytes() == b"\xff\xfe not utf-8\n"
