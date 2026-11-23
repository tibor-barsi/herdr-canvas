"""Answers on a real hub: routes, store, receipts, `answers` and its wait (ANS-01..06).

The owner's window is the cookie client and a scripted shell (no browser).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hooks import format_events
from shellfake import FakeShell

pytestmark = pytest.mark.integration

ASK = {"question": "Keep layout A?", "options": ["keep", "change"]}
DO = {
    "title": "Plug in the heater",
    "where": "bench",
    "steps": [{"text": "Plug", "run": "echo hi"}, {"text": "Look"}],
}


def card(tag: str, item_id: str, config: dict) -> str:
    body = json.dumps(config)
    return (
        f'<{tag} data-canvas-id="{item_id}">'
        f'<script type="application/json">{body}</script></{tag}>'
    )


def cards(sibling: str = "one", question: str = ASK["question"]) -> str:
    return (
        f"<main><p>{sibling}</p>"
        + card("canvas-ask", "q1", {**ASK, "question": question})
        + card("canvas-ask", "q2", {**ASK, "question": "Wider?", "default": "keep"})
        + card("canvas-do", "w1", DO)
        + card("canvas-decision", "d1", {"text": "Use PETG"})
        + "<script>document.body.append(document.createElement('canvas-ask'))</script>"
        + "</main>"
    )


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    fake = FakeShell(hub)
    yield fake
    fake.close()


@pytest.fixture
def owner(hub) -> httpx.Client:  # noqa: ANN001
    """The owner's window: the cookie and the shell origin."""
    client = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    client.get(hub.login_url(), follow_redirects=False)
    return client


class Shown:
    """A session showing ``page.html`` with cards."""

    def __init__(self, cli, hub, owner, shell, started: dict) -> None:  # noqa: ANN001
        self.cli, self.hub, self.owner, self.shell = cli, hub, owner, shell
        self.id = started["session"]
        self.folder = Path(started["folder"])
        self.processes: list[subprocess.Popen] = []

    def show(self, name: str, html: str) -> None:
        (self.folder / name).write_text(html)
        result = self.cli("show", name, "--session", self.id)
        assert result.code == 0, result.err

    def post(self, tail: str, body: dict, client: httpx.Client | None = None):  # noqa: ANN201
        client = client or self.owner
        return client.post(f"/api/sessions/{self.id}/answers/{tail}", json=body)

    def answer(self, item_id: str, value: dict, page: str = "page.html"):  # noqa: ANN201
        return self.post("answer", {"page": page, "id": item_id, "value": value})

    def answers(self, *args: str) -> dict:
        result = self.cli("answers", "--session", self.id, *args)
        assert result.code == 0, result.err
        return result.json

    def item(self, item_id: str, page: str = "page.html") -> dict:
        found = [i for i in self.answers("--page", page)["items"] if i["id"] == item_id]
        return found[0]

    def events(self) -> list[dict]:
        return self.hub.on_loop(lambda: self.hub.state.events.all(self.id))

    def delivered_via(self, event_id: str) -> str | None:
        for line in (self.folder / "events.jsonl").read_text().splitlines():
            record = json.loads(line)
            if record["record"] == "delivered" and record["id"] == event_id:
                return record["via"]
        return None

    def answers_message(self, page: str = "page.html") -> dict | None:
        found = [
            m for m in self.shell.messages
            if m.get("type") == "answers" and m["page"] == page
        ]  # fmt: skip
        return found[-1] if found else None

    def pushed(self, item_id: str, page: str = "page.html") -> dict:
        """Wait for the window to be told about an item and return what it got."""

        def told() -> bool:
            message = self.answers_message(page)
            return bool(message) and item_id in message["items"]

        self.hub.wait_for(told, 3)
        return self.answers_message(page)["items"][item_id]

    def read_of(self, item_id: str, page: str = "page.html") -> str | None:
        message = self.answers_message(page)
        return ((message or {}).get("items", {}).get(item_id) or {}).get("read")

    def spawn(self, *args: str) -> subprocess.Popen:
        process = spawn(self.cli, *args, "--session", self.id)
        self.processes.append(process)
        return process


def spawn(cli, *args: str) -> subprocess.Popen:  # noqa: ANN001
    return subprocess.Popen(
        [sys.executable, "-m", "agent_canvas.cli", *args],
        cwd=cli.cwd,
        env=cli.environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.fixture
def shown(cli, hub, owner, shell):  # noqa: ANN001, ANN201
    started = cli("session", "start").json
    page = Shown(cli, hub, owner, shell, started)
    page.show("page.html", cards())
    time.sleep(0.6)  # the first scan of the watcher and its pushes
    shell.messages.clear()
    yield page
    for process in page.processes:
        if process.poll() is None:
            process.kill()


KEEP = {"answer": ["keep"], "note": "but wider"}
DONE = {"status": "done", "ticked": [1, 2]}


# ---- ANS-01: the store ----


def test_ans_01_an_answer_makes_an_event_and_is_stored_per_page(shown) -> None:  # noqa: ANN001
    reply = shown.answer("q1", KEEP)
    assert reply.status_code == 200, reply.text
    [event] = [e for e in shown.events() if e["kind"] == "answer"]
    assert event["id"] == reply.json()["event"]
    assert (event["page"], event["state"], event["delivery"]) == (
        "page.html", "queued", "now",
    )  # fmt: skip
    assert event["target"]["canvas_id"] == "q1"
    assert event["value"] == {
        "question": "Keep layout A?", "form": "one", "answer": ["keep"],
        "other": None, "note": "but wider", "replaces": None,
    }  # fmt: skip
    stored = json.loads((shown.folder / ".answers" / "page.html.json").read_text())
    assert stored["items"]["q1"]["event"] == event["id"]
    assert stored["items"]["q1"]["state"] == "answered"


def test_ans_01_the_answers_file_is_not_served_to_the_page(shown, hub) -> None:  # noqa: ANN001
    shown.answer("q1", KEEP)
    token = hub.state.session_of(shown.id).page_token
    base = f"http://localhost:{hub.port}/s/{token}"
    assert httpx.get(f"{base}/page.html").status_code == 200
    assert httpx.get(f"{base}/.answers/page.html.json").status_code == 404


def test_ans_01_answer_survives_a_sibling_rewrite_and_a_hub_restart(shown, hub) -> None:  # noqa: ANN001
    shown.answer("q1", KEEP)
    shown.show("page.html", cards(sibling="two"))
    assert shown.item("q1")["state"] == "answered"
    hub.restart()
    assert shown.item("q1")["state"] == "answered"
    assert shown.item("q1")["answer"]["answer"] == ["keep"]


def test_ans_01_a_changed_question_opens_the_item_with_the_old_answer_in_history(
    shown,  # noqa: ANN001
) -> None:
    shown.answer("q1", KEEP)
    shown.show("page.html", cards(question="Keep layout B?"))
    row = shown.item("q1")
    assert (row["state"], row["answer"], row["waits"]) == ("open", None, True)
    stored = json.loads((shown.folder / ".answers" / "page.html.json").read_text())
    [past] = stored["items"]["q1"]["history"]
    assert past["value"]["answer"] == ["keep"]


def test_ans_01_a_second_answer_replaces_the_first(shown) -> None:  # noqa: ANN001
    first = shown.answer("q1", KEEP).json()["event"]
    second = shown.answer("q1", {"answer": ["change"]}).json()["event"]
    by_id = {e["id"]: e for e in shown.events()}
    assert by_id[second]["value"]["replaces"] == first
    assert shown.item("q1")["answer"]["answer"] == ["change"]
    assert shown.item("q1")["event"] == second


# ---- the three kinds of answer ----


def test_ans_06_a_do_gives_a_todo_event_and_a_decision_a_change_event(shown) -> None:  # noqa: ANN001
    todo = shown.answer("w1", DONE).json()
    change = shown.answer("d1", {"reason": "use ABS"}).json()
    by_id = {e["id"]: e for e in shown.events()}
    assert by_id[todo["event"]]["kind"] == "todo"
    assert by_id[todo["event"]]["value"] == {
        "title": "Plug in the heater", "status": "done", "ticked": [1, 2],
        "note": None, "replaces": None,
    }  # fmt: skip
    assert by_id[change["event"]]["kind"] == "change"
    assert by_id[change["event"]]["value"] == {
        "decision": "Use PETG", "reason": "use ABS", "replaces": None,
    }  # fmt: skip
    assert (shown.item("w1")["state"], shown.item("d1")["state"]) == ("done", "changed")


@pytest.mark.parametrize(
    ("item", "value"),
    [
        ("w1", {"status": "problem"}),
        ("w1", {"status": "problem", "note": "  "}),
        ("w1", {"status": "maybe"}),
        ("w1", {"status": "done", "ticked": [3]}),
        ("d1", {"reason": ""}),
        ("d1", {"reason": "x" * 301}),
        ("q1", {"note": "no answer"}),
        ("q1", {"answer": ["keep"], "note": 5}),
    ],
)
def test_ans_02_a_value_the_card_cannot_have_sent_is_refused_without_an_event(
    shown,
    item,
    value,  # noqa: ANN001
) -> None:
    assert shown.answer(item, value).status_code == 400
    assert shown.events() == [] or all(e["kind"] == "send" for e in shown.events())
    assert shown.item(item)["state"] == "open"


def test_ans_02_a_problem_with_a_note_is_a_problem(shown) -> None:  # noqa: ANN001
    shown.answer("w1", {"status": "problem", "note": "no power"})
    assert shown.item("w1")["state"] == "problem"
    [event] = [e for e in shown.events() if e["kind"] == "todo"]
    assert event["value"]["note"] == "no power"


def test_ans_02_later_stops_waiting(shown) -> None:  # noqa: ANN001
    assert shown.item("w1")["waits"] is True
    shown.answer("w1", {"status": "later"})
    assert (shown.item("w1")["state"], shown.item("w1")["waits"]) == ("later", False)


def test_ans_02_ticks_are_stored_without_an_event(shown) -> None:  # noqa: ANN001
    reply = shown.post("tick", {"page": "page.html", "id": "w1", "ticked": [2, 1, 1]})
    assert reply.json()["ticked"] == [1, 2]
    assert shown.events() == []
    assert shown.pushed("w1")["ticked"] == [1, 2]
    assert shown.item("w1")["state"] == "open"
    bad = shown.post("tick", {"page": "page.html", "id": "q1", "ticked": [1]})
    assert bad.status_code == 400  # only a Do has steps
    assert shown.post(
        "tick", {"page": "page.html", "id": "w1", "ticked": [9]}
    ).status_code == 400  # fmt: skip


# ---- ANS-02 / SEC-09: only the owner, only the page's own items ----


def test_sec_09_the_key_cannot_answer_and_the_cookie_cannot_list(shown, hub) -> None:  # noqa: ANN001
    agent = httpx.Client(base_url=hub.base_url, headers=hub.key_headers)
    assert shown.answer("q1", KEEP).status_code == 200
    forged = shown.post(
        "answer", {"page": "page.html", "id": "q2", "value": KEEP}, agent
    )
    assert forged.status_code == 403
    listed = shown.owner.get(f"/api/sessions/{shown.id}/answers")
    assert listed.status_code in (401, 403)
    assert agent.get(f"/api/sessions/{shown.id}/answers").status_code == 200


def test_sec_09_an_answer_touches_only_the_page_it_names(shown) -> None:  # noqa: ANN001
    other = cards().replace("Keep layout A?", "Another?").replace('"q1"', '"o1"')
    shown.show("other.html", other)
    reply = shown.answer("o1", KEEP, page="page.html")
    assert reply.status_code == 404  # o1 is an item of other.html
    assert shown.answer("o1", KEEP, page="other.html").status_code == 200
    assert shown.item("q1")["state"] == "open"
    assert shown.item("o1", "other.html")["state"] == "answered"
    shown.shell.messages.clear()
    shown.answer("q2", KEEP)
    shown.pushed("q2")
    pages = {m["page"] for m in shown.shell.messages if m["type"] == "answers"}
    assert pages == {"page.html"}


@pytest.mark.parametrize(
    "body",
    [
        {"page": "page.html", "id": "script-made", "value": KEEP},
        {"page": "nothing.html", "id": "q1", "value": KEEP},
        {"page": "../page.html", "id": "q1", "value": KEEP},
        {"page": "page.draft.html", "id": "q1", "value": KEEP},
        {"page": "page.html", "id": "q1"},
        {"page": 4, "id": "q1", "value": KEEP},
    ],
)
def test_sec_09_a_forged_answer_naming_nothing_real_creates_no_event(
    shown, body
) -> None:  # noqa: ANN001
    assert shown.post("answer", body).status_code in (400, 404)
    assert [e for e in shown.events() if e["kind"] != "send"] == []


def test_ans_02_a_window_asks_for_a_pages_items_and_gets_only_that_page(shown) -> None:  # noqa: ANN001
    shown.show("other.html", cards().replace('"q1"', '"o1"'))
    shown.answer("q1", KEEP)
    shown.shell.messages.clear()
    shown.shell.send({"type": "answers-get", "session": shown.id, "page": "other.html"})
    shown.hub.wait_for(lambda: shown.answers_message("other.html"))
    assert shown.answers_message("other.html")["items"] == {}
    shown.shell.send({"type": "answers-get", "session": shown.id, "page": "page.html"})
    shown.hub.wait_for(lambda: shown.answers_message("page.html"))
    assert set(shown.answers_message("page.html")["items"]) == {"q1"}


def test_ans_02_a_rewrite_that_reopens_an_item_is_pushed(shown) -> None:  # noqa: ANN001
    shown.answer("q1", KEEP)
    shown.shell.messages.clear()
    shown.show("page.html", cards(question="Keep layout B?"))
    shown.hub.wait_for(lambda: shown.answers_message())
    assert shown.answers_message()["items"] == {}


# ---- ANS-03: the read receipt ----


def test_ans_03_an_answer_is_unread_until_pending_delivers_it(shown) -> None:  # noqa: ANN001
    shown.answer("q1", KEEP)
    assert shown.pushed("q1")["read"] is None
    assert shown.cli("pending", "--session", shown.id).code == 0
    shown.hub.wait_for(lambda: shown.read_of("q1"), 1)


def test_ans_03_listing_marks_read_but_leaves_the_event_queued(shown) -> None:  # noqa: ANN001
    event = shown.answer("w1", DONE).json()["event"]
    assert shown.pushed("w1")["read"] is None
    row = shown.item("w1")
    assert row["read"] is not None
    shown.hub.wait_for(lambda: shown.read_of("w1"), 1)
    assert shown.hub.event_state(shown.id, event) == "queued"
    peeked = shown.cli("pending", "--peek", "--session", shown.id).json
    assert [e["id"] for e in peeked["events"]] == [event]


def test_ans_03_a_replaced_answer_that_is_delivered_late_does_not_mark_the_new_one(
    shown,  # noqa: ANN001
) -> None:
    first = shown.answer("q1", KEEP).json()["event"]
    shown.answer("q1", {"answer": ["change"]})
    shown.hub.on_loop(
        lambda: shown.hub.state.events.log(shown.id).mark_delivered(first, "pending")
    )
    assert shown.pushed("q1")["read"] is None


# ---- ANS-04: answers ----


def test_ans_04_the_list_has_the_shape_of_5_7_and_is_the_same_twice(shown) -> None:  # noqa: ANN001
    shown.answer("q1", KEEP)
    first, second = shown.answers(), shown.answers()
    assert first == second
    assert first["session"] == shown.id
    assert [i["id"] for i in first["items"]] == ["q1", "q2", "w1", "d1"]
    q1, q2, w1, d1 = first["items"]
    assert set(q1) == {
        "page", "id", "kind", "text", "waits", "default", "state", "answer",
        "event", "time", "read",
    }  # fmt: skip
    assert (q1["kind"], q1["state"], q1["waits"]) == ("ask", "answered", False)
    assert q1["answer"]["note"] == "but wider" and q1["read"] is not None
    assert (q2["waits"], q2["default"], q2["state"]) == (False, "keep", "open")
    assert (w1["kind"], w1["waits"], w1["text"]) == ("do", True, "Plug in the heater")
    assert (d1["kind"], d1["waits"]) == ("decision", False)


def test_ans_04_open_lists_open_ask_and_do_only(shown) -> None:  # noqa: ANN001
    assert [i["id"] for i in shown.answers("--open")["items"]] == ["q1", "q2", "w1"]
    shown.answer("q1", KEEP)
    assert [i["id"] for i in shown.answers("--open")["items"]] == ["q2", "w1"]


def test_ans_04_a_card_made_by_a_script_and_a_draft_are_not_listed(shown) -> None:  # noqa: ANN001
    (shown.folder / "page.draft.html").write_text(cards().replace('"q1"', '"draft-q"'))
    (shown.folder / "unshown.html").write_text(cards().replace('"q1"', '"hidden-q"'))
    time.sleep(0.6)
    ids = {i["id"] for i in shown.answers()["items"]}
    assert ids == {"q1", "q2", "w1", "d1"}


def test_ans_04_page_limits_the_list(shown) -> None:  # noqa: ANN001
    shown.show("other.html", cards().replace('"q1"', '"o1"'))
    both = {i["page"] for i in shown.answers()["items"]}
    assert both == {"page.html", "other.html"}
    only = {i["page"] for i in shown.answers("--page", "other.html")["items"]}
    assert only == {"other.html"}


def test_ans_04_an_unknown_session_exits_5(cli) -> None:  # noqa: ANN001
    assert cli("answers", "--session", "nobody").code == 5


# ---- ANS-05: answers --wait ----


def wait_listening(shown) -> None:  # noqa: ANN001
    shown.hub.wait_for(lambda: "answers" in shown.hub.listener_kinds(shown.id))


def test_ans_05_a_wait_for_two_items_ends_with_the_second_and_consumes(shown) -> None:  # noqa: ANN001
    process = shown.spawn("answers", "--wait", "q1", "w1", "--timeout", "30")
    wait_listening(shown)
    assert shown.hub.listening(shown.id)
    first = shown.answer("q1", KEEP).json()["event"]
    time.sleep(0.5)
    assert process.poll() is None  # one of two is not enough
    second = shown.answer("w1", DONE).json()["event"]
    out, err = process.communicate(timeout=20)
    assert process.returncode == 0, err
    result = json.loads(out)
    assert [i["id"] for i in result["items"]] == ["q1", "w1"]
    assert all(i["read"] and i["state"] != "open" for i in result["items"])
    assert {shown.delivered_via(first), shown.delivered_via(second)} == {"answers"}
    pending = shown.cli("pending", "--session", shown.id).json
    assert pending["events"] == []
    shown.hub.wait_for(lambda: not shown.hub.listening(shown.id))


def test_ans_05_the_tab_light_is_green_while_a_wait_runs(shown) -> None:  # noqa: ANN001
    process = shown.spawn("answers", "--wait", "q1", "--timeout", "30")
    wait_listening(shown)

    def lights() -> list[bool]:
        return [
            m["listening"] for m in shown.shell.messages if m["type"] == "listening"
        ]

    shown.hub.wait_for(lambda: lights() == [True])
    shown.answer("q1", KEEP)
    process.communicate(timeout=20)
    shown.hub.wait_for(lambda: lights() == [True, False])


def test_ans_05_a_wait_with_no_ids_waits_for_the_items_that_wait(shown) -> None:  # noqa: ANN001
    process = shown.spawn("answers", "--wait", "--timeout", "30")
    wait_listening(shown)
    shown.answer("q1", KEEP)
    shown.answer("q2", KEEP)  # has a default: not waited for
    time.sleep(0.5)
    assert process.poll() is None
    shown.answer("w1", {"status": "later"})
    out, err = process.communicate(timeout=20)
    assert process.returncode == 0, err
    assert [i["id"] for i in json.loads(out)["items"]] == ["q1", "w1"]


def test_ans_05_a_wait_that_runs_out_exits_6_and_gives_up_its_listener(shown) -> None:  # noqa: ANN001
    answered = shown.answer("q1", KEEP).json()["event"]
    run = shown.cli(
        "answers", "--wait", "q1", "w1", "--timeout", "1", "--session", shown.id
    )
    assert run.code == 6
    body = run.json
    assert body["status"] == "timeout"
    assert {i["id"]: i["state"] for i in body["items"]} == {
        "q1": "answered",
        "w1": "open",
    }
    shown.hub.wait_for(lambda: not shown.hub.listening(shown.id))
    assert (
        shown.hub.event_state(shown.id, answered) == "queued"
    )  # a timeout consumes nothing


def test_ans_05_a_wait_that_is_killed_gives_up_its_listener(shown) -> None:  # noqa: ANN001
    process = shown.spawn("answers", "--wait", "q1", "--timeout", "60")
    wait_listening(shown)
    process.kill()
    process.communicate(timeout=10)
    shown.hub.wait_for(lambda: not shown.hub.listening(shown.id))
    assert shown.hub.listener_kinds(shown.id) == []


def test_ans_05_a_wait_for_an_unknown_id_exits_1_without_a_listener(shown) -> None:  # noqa: ANN001
    run = shown.cli(
        "answers", "--wait", "nope", "--timeout", "5", "--session", shown.id
    )
    assert run.code == 1
    assert "nope" in run.json["message"]
    assert not shown.hub.listening(shown.id)


def test_ans_05_an_item_answered_before_the_wait_ends_it_at_once(shown) -> None:  # noqa: ANN001
    shown.answer("q1", KEEP)
    run = shown.cli("answers", "--wait", "q1", "--timeout", "5", "--session", shown.id)
    assert run.code == 0
    assert run.json["items"][0]["answer"]["answer"] == ["keep"]


# ---- ANS-06 and CLI-06: every route ----


def test_ans_06_pending_returns_all_three_kinds_and_the_hook_prints_one_line_each(
    shown,  # noqa: ANN001
) -> None:
    shown.answer("q1", KEEP)
    shown.answer("w1", {"status": "problem", "note": "no power"})
    shown.answer("d1", {"reason": "use ABS"})
    events = shown.cli("pending", "--session", shown.id).json["events"]
    assert [e["kind"] for e in events] == ["answer", "todo", "change"]
    assert format_events(events).splitlines()[1:] == [
        "answer q1 (page.html): keep · note: but wider",
        "todo w1 (page.html): problem · no power",
        "change d1 (page.html): use ABS",
    ]


def test_ans_06_a_watch_prints_the_three_kinds(shown) -> None:  # noqa: ANN001
    process = shown.spawn("watch", "--count", "3", "--timeout", "30")
    shown.hub.wait_for(lambda: "watch" in shown.hub.listener_kinds(shown.id))
    shown.answer("q1", KEEP)
    shown.answer("w1", DONE)
    shown.answer("d1", {"reason": "use ABS"})
    out, _ = process.communicate(timeout=20)
    lines = [json.loads(line) for line in out.splitlines()]
    assert [(line["kind"], line["target"]["canvas_id"]) for line in lines[:3]] == [
        ("answer", "q1"), ("todo", "w1"), ("change", "d1"),
    ]  # fmt: skip
    shown.hub.wait_for(lambda: shown.read_of("q1"), 2)


@pytest.mark.parametrize(
    ("item", "value", "kind"),
    [
        ("q1", KEEP, "answer"),
        ("w1", DONE, "todo"),
        ("d1", {"reason": "use ABS"}, "change"),
    ],
)
def test_cli_06_ask_block_returns_the_answer_event_of_a_card(
    shown,
    item,
    value,
    kind,  # noqa: ANN001
) -> None:
    process = shown.spawn(
        "ask", "Waiting for the card", "--block", item, "--timeout", "30"
    )
    shown.hub.wait_for_ask(shown.id)
    event = shown.answer(item, value).json()["event"]
    out, err = process.communicate(timeout=20)
    assert process.returncode == 0, err
    result = json.loads(out)
    assert (result["status"], result["event"]["id"]) == ("answered", event)
    assert (result["event"]["kind"], result["event"]["delivery"]) == (kind, "ask")
    assert result["event"]["state"] == "delivered"
    shown.hub.wait_for(lambda: shown.read_of(item), 2)


# ---- DO-02: the text to copy comes from the page file ----


def copy(shown, step: int | str, item: str = "w1", client=None):  # noqa: ANN001, ANN201
    return (client or shown.owner).get(
        f"/api/sessions/{shown.id}/answers/copy",
        params={"page": "page.html", "id": item, "step": step},
    )


def test_do_02_the_hub_gives_the_run_text_of_a_step_from_the_page_file(shown) -> None:  # noqa: ANN001
    reply = copy(shown, 1)
    assert (reply.status_code, reply.json()) == (200, {"text": "echo hi"})
    shown.show("page.html", cards().replace("echo hi", "echo changed"))
    shown.hub.wait_for(
        lambda: copy(shown, 1).json() == {"text": "echo changed"}, timeout=15
    )  # the current version


@pytest.mark.parametrize(
    ("step", "item"),
    [(2, "w1"), (0, "w1"), (3, "w1"), ("x", "w1"), (1, "q1"), (1, "nope")],
)
def test_do_02_a_step_without_run_or_a_forged_name_copies_nothing(
    shown, step, item
) -> None:  # noqa: ANN001
    reply = copy(shown, step, item)
    assert reply.status_code == 404 and "text" not in reply.json()


def test_do_02_only_the_owners_window_may_ask_for_the_text(shown) -> None:  # noqa: ANN001
    anonymous = httpx.Client(base_url=shown.hub.base_url)
    assert copy(shown, 1, client=anonymous).status_code in (401, 403)


# ---- CNT-03, CNT-04: file paths and source lines written in the page file ----

FILE_PATH = "/data/run 4/result.csv"
SOURCE_LINE = "ISO 527-1:2019, table 2 <https://example.org/iso>"


def with_cards() -> str:
    return (
        cards()
        + card("canvas-file", "f1", {"path": FILE_PATH})
        + card("canvas-source", "s1", {"claim": "E = 70 GPa", "source": SOURCE_LINE})
    )


def copy_what(shown, kind: str, text: str, client=None):  # noqa: ANN001, ANN201
    return (client or shown.owner).get(
        f"/api/sessions/{shown.id}/answers/copy",
        params={"page": "page.html", "kind": kind, "text": text},
    )


def test_cnt_03_the_hub_gives_a_file_path_and_a_source_line_written_in_the_page(
    shown,  # noqa: ANN001
) -> None:
    shown.show("page.html", with_cards())
    assert copy_what(shown, "path", FILE_PATH).json() == {"text": FILE_PATH}
    assert copy_what(shown, "source", SOURCE_LINE).json() == {"text": SOURCE_LINE}


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("path", "/etc/passwd"),
        ("path", SOURCE_LINE),
        ("source", FILE_PATH),
        ("source", "echo forged"),
        ("do", FILE_PATH),
        ("path", ""),
    ],
)
def test_cnt_03_a_text_not_written_in_the_page_as_that_kind_copies_nothing(
    shown, kind, text
) -> None:  # noqa: ANN001
    shown.show("page.html", with_cards())
    reply = copy_what(shown, kind, text)
    assert reply.status_code == 404 and "text" not in reply.json()


def test_cnt_03_the_text_must_be_in_the_current_version_of_the_page(shown) -> None:  # noqa: ANN001
    shown.show("page.html", with_cards())
    shown.show("page.html", with_cards().replace(FILE_PATH, "/data/other.csv"))
    shown.hub.wait_for(
        lambda: copy_what(shown, "path", FILE_PATH).status_code == 404, timeout=15
    )
    assert copy_what(shown, "path", FILE_PATH).status_code == 404
    assert copy_what(shown, "path", "/data/other.csv").status_code == 200


def test_cnt_03_only_the_owners_window_may_ask_for_a_path(shown) -> None:  # noqa: ANN001
    shown.show("page.html", with_cards())
    anonymous = httpx.Client(base_url=shown.hub.base_url)
    assert copy_what(shown, "path", FILE_PATH, client=anonymous).status_code in (
        401,
        403,
    )


def test_cnt_03_the_answers_message_names_the_session_folder(shown) -> None:  # noqa: ANN001
    shown.shell.send({"type": "answers-get", "session": shown.id, "page": "page.html"})
    shown.hub.wait_for(lambda: shown.answers_message() is not None, 3)
    assert shown.answers_message()["folder"] == str(shown.folder)


def test_hub_09_an_answer_sent_twice_with_one_request_id_is_stored_once(shown) -> None:  # noqa: ANN001
    body = {"page": "page.html", "id": "q1", "value": KEEP, "request_id": "r-1"}
    first = shown.post("answer", body).json()
    again = shown.post("answer", body).json()
    assert again == first
    assert len([e for e in shown.events() if e["kind"] == "answer"]) == 1


def test_ans_01_an_answer_to_a_question_that_changed_since_is_refused(shown) -> None:  # noqa: ANN001
    seen = {**ASK, "question": "Keep layout A?"}
    shown.show("page.html", cards(question="Keep layout B?"))
    body = {"page": "page.html", "id": "q1", "value": KEEP, "seen": seen}
    refused = shown.post("answer", body)
    assert refused.status_code == 409 and "changed" in refused.json()["message"]
    assert [e for e in shown.events() if e["kind"] == "answer"] == []
    assert shown.item("q1")["state"] == "open"


def test_ans_01_an_answer_to_the_question_the_owner_saw_is_stored(shown) -> None:  # noqa: ANN001
    body = {"page": "page.html", "id": "q1", "value": KEEP, "seen": ASK}
    assert shown.post("answer", body).status_code == 200
    assert shown.item("q1")["state"] == "answered"


def test_sec_09_an_answer_or_tick_body_over_the_limit_is_refused_unread(shown) -> None:  # noqa: ANN001
    huge = {"answer": ["x" * 300_000]}
    for tail, body in (
        ("answer", {"page": "page.html", "id": "q1", "value": huge}),
        (
            "tick",
            {"page": "page.html", "id": "w1", "ticked": [1], "pad": "x" * 300_000},
        ),
    ):
        assert shown.post(tail, body).status_code == 413
    assert [e for e in shown.events() if e["kind"] != "send"] == []


# ---- ANS-07: the Options box with a submit button (#19) ----

OPTIONS = [{"id": "a", "title": "Part"}, {"id": "b", "title": "Material"}]
CHOICES = {"mode": "multi", "options": OPTIONS, "submit": "Use this"}


def choices_page() -> str:
    return (
        card("canvas-choices", "c1", CHOICES)
        + card("canvas-choices", "c2", {"options": OPTIONS})
        + card("canvas-ask", "q1", ASK)
    )


def pick(shown, item_id: str, value: list[str]) -> None:  # noqa: ANN001
    shown.shell.send({
        "type": "event", "session": shown.id, "kind": "choice", "value": value,
        "page": "page.html", "target": {"canvas_id": item_id},
    })  # fmt: skip
    shown.hub.wait_for(lambda: any(e["kind"] == "choice" for e in shown.events()), 3)
    time.sleep(0.3)


def stored(shown) -> dict:  # noqa: ANN001
    path = shown.folder / ".answers" / "page.html.json"
    return json.loads(path.read_text())["items"] if path.exists() else {}


def test_ans_07_a_forged_answer_to_an_options_box_is_refused(shown) -> None:  # noqa: ANN001
    shown.show("page.html", choices_page())
    reply = shown.answer("c1", {"reason": "forged"})  # a value the value check accepts
    assert reply.status_code == 400
    assert "choice event" in reply.json()["message"]
    assert not [e for e in shown.events() if e["kind"] == "answer"]


def test_ans_07_a_choice_event_for_an_ask_or_a_submitless_box_stores_nothing(
    shown,  # noqa: ANN001
) -> None:
    shown.show("page.html", choices_page())
    pick(shown, "q1", ["keep"])
    pick(shown, "c2", ["a"])
    assert stored(shown) == {}


def test_ans_07_a_choice_event_is_stored_and_a_changed_option_list_opens_it_again(
    shown,  # noqa: ANN001
) -> None:
    shown.show("page.html", choices_page())
    pick(shown, "c1", ["a"])
    assert shown.item("c1")["state"] == "answered"
    assert shown.item("c1")["answer"] == ["a"]
    assert shown.item("c1")["kind"] == "choices"
    shown.show("page.html", choices_page().replace("Material", "Date"))
    assert shown.item("c1")["state"] == "open"
    shown.hub.restart()
    assert shown.item("c1")["state"] == "open"
