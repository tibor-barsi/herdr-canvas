"""The answer store and the page scan (ANS-01, ANS-03, ANS-04, ANS-05; 5.15)."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_canvas.hub import answers
from agent_canvas.hub.answers import AnswerStore
from agent_canvas.hub.watcher import PageHistory

pytestmark = pytest.mark.unit

PAGE = "page.html"


def run(awaitable):  # noqa: ANN001, ANN201
    """Run a coroutine in a thread of its own.

    A browser test earlier in the same worker may hold this thread's loop.
    """
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, awaitable).result()


def card(tag: str, item_id: str, config: dict, inner: str = "") -> str:
    """The markup an agent writes for one card."""
    body = json.dumps(config)
    return (
        f'<{tag} data-canvas-id="{item_id}">'
        f'<script type="application/json">{body}</script>{inner}</{tag}>'
    )


ASK = {"question": "Keep layout A?", "options": ["keep", "change"]}
DO = {
    "title": "Plug in the heater",
    "where": "bench",
    "steps": [{"text": "Plug", "run": "echo hi\necho two"}, {"text": "Look"}],
}
DECISION = {"text": "Use PETG"}


def page(*parts: str) -> str:
    return "<main>" + "".join(parts) + "</main>"


def default_page(question: str = ASK["question"], sibling: str = "x") -> str:
    ask = card("canvas-ask", "q1", {**ASK, "question": question})
    return page(
        f"<p>{sibling}</p>", ask, card("canvas-do", "w1", DO),
        card("canvas-decision", "d1", DECISION),
    )  # fmt: skip


class Notes:
    """Records the pages the store announced."""

    def __init__(self) -> None:
        self.pages: list[tuple[str, str]] = []

    def __call__(self, session_id: str, name: str) -> None:
        self.pages.append((session_id, name))


def make_store(folder: Path, notes: Notes | None = None, pages=(PAGE,)) -> AnswerStore:  # noqa: ANN001
    return AnswerStore(lambda sid: folder, lambda sid: list(pages), notes or Notes())


def save_page(folder: Path, html: str) -> None:
    assert PageHistory(folder).save(PAGE, html.encode()) is not None


def answer(store: AnswerStore, item_id: str = "q1", event: str = "evt_1", **extra):  # noqa: ANN001, ANN003, ANN201
    item = store.item_of("s", PAGE, item_id)
    fields = {"state": "answered", "value": {"answer": ["keep"]}, "event": event}
    fields |= {"time": "2026-11-10T10:00:00.000Z"} | extra
    store.record("s", PAGE, item, **fields)


# ---- the scan ----


def test_ans_04_scan_reads_the_three_item_kinds_in_page_order() -> None:
    found = answers.scan(default_page())
    assert list(found.items) == ["q1", "w1", "d1"]
    ask, do, decision = found.items.values()
    assert (ask.kind, ask.text, ask.form) == ("ask", "Keep layout A?", "one")
    assert (do.kind, do.text, do.steps) == ("do", "Plug in the heater", 2)
    assert (decision.kind, decision.text) == ("decision", "Use PETG")
    assert do.runs == ("echo hi\necho two",)


def test_ans_03_waits_follows_the_default_and_the_kind() -> None:
    text = page(
        card("canvas-ask", "a", ASK),
        card("canvas-ask", "b", {**ASK, "default": "keep"}),
        card("canvas-do", "c", DO),
        card("canvas-decision", "d", DECISION),
    )  # fmt: skip
    items = answers.scan(text).items
    assert {k: i.waits for k, i in items.items()} == {
        "a": True, "b": False, "c": True, "d": False,
    }  # fmt: skip
    assert items["b"].default == "keep"


def test_ans_04_scan_finds_a_card_inside_a_report_and_ignores_others() -> None:
    inner = card("canvas-ask", "inside", ASK)
    text = page(
        card("canvas-report", "r", {"title": "Plan"}, inner),
        '<canvas-ask><script type="application/json">{"question":"no id"}</script>'
        "</canvas-ask>",
        "<script>document.body.append(document.createElement('canvas-ask'))</script>",
        card("canvas-file", "f", {"path": "/data/run.csv"}),
    )  # fmt: skip
    found = answers.scan(text)
    assert list(found.items) == ["inside"]
    assert found.paths == ("/data/run.csv",)


def test_cnt_04_scan_finds_the_source_lines_of_source_cards_only_in_the_file() -> None:
    text = page(
        card("canvas-source", "s1", {"claim": "E = 70 GPa", "source": "Handbook p. 4"}),
        card("canvas-source", "s2", {"claim": "no source line"}),
        card("canvas-ask", "a", ASK),
        "<script>document.body.append(document.createElement('canvas-source'))</script>",
    )  # fmt: skip
    found = answers.scan(text)
    assert found.sources == ("Handbook p. 4",)
    assert list(found.items) == ["a"]


def test_ans_04_scan_takes_the_cards_own_config_not_a_childs_before_it() -> None:
    picture = (
        '<canvas-image data-canvas-id="p"><script type="application/json">'
        '{"src": "a.png"}</script></canvas-image><img src="b.png">'
    )
    config = json.dumps({**ASK, "question": "Use 3 mm?"})
    ask = (
        f'<canvas-ask data-canvas-id="q">{picture}'
        f'<script type="application/json">{config}</script></canvas-ask>'
    )
    do = (
        f'<canvas-do data-canvas-id="w"><div>{picture}</div>'
        f'<script type="application/json">{json.dumps(DO)}</script></canvas-do>'
    )
    found = answers.scan(page(ask, do)).items
    assert found["q"].text == "Use 3 mm?"
    assert found["w"].step_runs == ("echo hi\necho two", None)
    changed = ask.replace("3 mm", "5 mm")
    assert answers.scan(page(changed)).items["q"].key != found["q"].key


def test_ans_04_scan_ignores_a_card_inside_a_template() -> None:
    hidden = card("canvas-ask", "hidden", ASK)
    found = answers.scan(
        page(f"<template>{hidden}</template>", card("canvas-ask", "a", ASK))
    )
    assert list(found.items) == ["a"]


def test_ans_01_key_changes_with_the_question_not_with_a_sibling() -> None:
    first = answers.scan(default_page()).items["q1"].key
    assert answers.scan(default_page(sibling="other")).items["q1"].key == first
    assert answers.scan(default_page(question="Another?")).items["q1"].key != first
    assert first.startswith("sha256:")


def test_ans_01_a_form_left_out_equals_its_default() -> None:
    plain = answers.scan(page(card("canvas-ask", "a", {"question": "Q?"}))).items["a"]
    spelled = {"question": "Q?", "form": "text"}
    written = answers.scan(page(card("canvas-ask", "a", spelled))).items["a"]
    assert plain.key == written.key and plain.form == "text"


def test_ans_01_at_most_200_items_per_page() -> None:
    many = page(*(card("canvas-ask", f"q{n}", ASK) for n in range(250)))
    assert len(answers.scan(many).items) == answers.MAX_ITEMS


# ---- the store: answers survive and reopen ----


def test_ans_01_answered_item_survives_a_sibling_rewrite_and_a_restart(
    tmp_path: Path,
) -> None:
    save_page(tmp_path, default_page())
    answer(make_store(tmp_path))
    save_page(tmp_path, default_page(sibling="changed sibling"))
    for store in (make_store(tmp_path), make_store(tmp_path)):  # the second: restart
        entry = store.entries("s", PAGE)["q1"]
        assert (entry["state"], entry["event"]) == ("answered", "evt_1")
        assert entry["history"] == []


def test_ans_01_a_changed_question_opens_the_item_and_keeps_the_old_answer(
    tmp_path: Path,
) -> None:
    save_page(tmp_path, default_page())
    answer(make_store(tmp_path))
    save_page(tmp_path, default_page(question="Keep layout B?"))
    store = make_store(tmp_path)
    entry = store.entries("s", PAGE)["q1"]
    assert (entry["state"], entry["value"], entry["event"]) == ("open", None, None)
    assert [h["event"] for h in entry["history"]] == ["evt_1"]
    assert entry["key"] == store.item_of("s", PAGE, "q1").key
    assert store.public("s", PAGE) == {}
    [row] = [r for r in store.listing("s") if r["id"] == "q1"]
    assert (row["state"], row["waits"], row["answer"]) == ("open", True, None)
    stored = json.loads((tmp_path / ".answers" / "page.html.json").read_text())
    assert stored["schema"] == "agent-canvas/answers@1"
    assert stored["items"]["q1"]["history"][0]["value"] == {"answer": ["keep"]}


def test_ans_01_a_second_answer_moves_the_first_to_history_newest_first(
    tmp_path: Path,
) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    for number in range(1, 24):
        answer(store, event=f"evt_{number}")
    entry = store.entries("s", PAGE)["q1"]
    assert entry["event"] == "evt_23"
    assert len(entry["history"]) == answers.MAX_HISTORY
    assert entry["history"][0]["event"] == "evt_22"


def test_ans_01_the_file_is_written_whole_and_leaves_no_temporary(
    tmp_path: Path,
) -> None:
    save_page(tmp_path, default_page())
    answer(make_store(tmp_path))
    assert sorted(p.name for p in (tmp_path / ".answers").iterdir()) == [
        "page.html.json"
    ]


def test_ans_01_ticks_are_kept_and_reset_when_the_steps_change(tmp_path: Path) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    store.tick("s", PAGE, store.item_of("s", PAGE, "w1"), [1])
    assert store.public("s", PAGE)["w1"]["ticked"] == [1]
    changed = {**DO, "steps": [{"text": "Plug"}, {"text": "Look"}, {"text": "More"}]}
    save_page(tmp_path, page(card("canvas-do", "w1", changed)))
    assert make_store(tmp_path).public("s", PAGE) == {}


def test_ans_01_a_page_that_lost_an_item_keeps_its_answer(tmp_path: Path) -> None:
    save_page(tmp_path, default_page())
    answer(make_store(tmp_path))
    save_page(tmp_path, page("<p>nothing</p>"))
    assert make_store(tmp_path).entries("s", PAGE)["q1"]["state"] == "answered"


# ---- read receipt and listing ----


def test_ans_03_read_is_stamped_once_and_only_for_the_current_event(
    tmp_path: Path,
) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    answer(store, event="evt_1")
    answer(store, event="evt_2")
    assert store.mark_read("s", PAGE, "q1", "evt_1") is None
    stamp = store.mark_read("s", PAGE, "q1", "evt_2")
    assert stamp is not None
    assert store.mark_read("s", PAGE, "q1", "evt_2") is None
    assert store.entries("s", PAGE)["q1"]["read"] == stamp


def test_ans_04_listing_marks_answers_read_and_gives_the_same_list_twice(
    tmp_path: Path,
) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    answer(store)
    first = store.listing("s")
    assert first[0]["read"] is not None
    assert store.listing("s") == first
    assert [r["id"] for r in first] == ["q1", "w1", "d1"]
    assert set(first[0]) == {
        "page", "id", "kind", "text", "waits", "default", "state", "answer",
        "event", "time", "read",
    }  # fmt: skip


def test_ans_04_open_lists_only_open_ask_and_do(tmp_path: Path) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    assert [r["id"] for r in store.listing("s", open_only=True)] == ["q1", "w1"]
    answer(store)
    assert [r["id"] for r in store.listing("s", open_only=True)] == ["w1"]


def test_ans_04_only_shown_pages_are_listed(tmp_path: Path) -> None:
    save_page(tmp_path, default_page())
    PageHistory(tmp_path).save("other.html", default_page().encode())
    assert {r["page"] for r in make_store(tmp_path).listing("s")} == {PAGE}
    both = make_store(tmp_path, pages=(PAGE, "other.html"))
    assert {r["page"] for r in both.listing("s")} == {PAGE, "other.html"}
    assert {r["page"] for r in both.listing("s", page="other.html")} == {"other.html"}


def test_ans_04_listing_never_reads_a_draft_or_a_viewer_page(tmp_path: Path) -> None:
    save_page(tmp_path, default_page())
    PageHistory(tmp_path).save("page.draft.html", default_page().encode())
    store = make_store(tmp_path, pages=(PAGE, "page.draft.html", "notes.md"))
    assert {r["page"] for r in store.listing("s")} == {PAGE}


def test_ans_05_targets_are_the_waiting_items_or_the_named_ones(tmp_path: Path) -> None:
    ask = card("canvas-ask", "a", ASK)
    with_default = card("canvas-ask", "b", {**ASK, "default": "keep"})
    save_page(tmp_path, page(ask, with_default, card("canvas-do", "c", DO)))
    store = make_store(tmp_path)
    assert store.targets("s", [], None) == [(PAGE, "a"), (PAGE, "c")]
    assert store.targets("s", ["b"], None) == [(PAGE, "b")]
    with pytest.raises(answers.AnswerError):
        store.targets("s", ["nope"], None)


def test_ans_05_a_wait_ends_when_the_last_target_is_answered(tmp_path: Path) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    targets = [(PAGE, "q1"), (PAGE, "w1")]

    async def scenario() -> tuple[bool, bool]:
        waiting = asyncio.ensure_future(store.wait("s", targets, 5))
        await asyncio.sleep(0.05)
        answer(store, "q1")
        await asyncio.sleep(0.05)
        after_first = waiting.done()
        answer(store, "w1", state="done", event="evt_2")
        return after_first, await waiting

    assert run(scenario()) == (False, True)


def test_ans_05_a_wait_gives_up_at_the_timeout_and_leaves_no_waiter(
    tmp_path: Path,
) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    assert run(store.wait("s", [(PAGE, "q1")], 0.1)) is False
    assert store._waiters == []


def test_ans_05_a_later_do_ends_the_wait(tmp_path: Path) -> None:
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    answer(store, "w1", state="later")
    assert run(store.wait("s", [(PAGE, "w1")], 1)) is True
    [row] = [r for r in store.listing("s") if r["id"] == "w1"]
    assert (row["state"], row["waits"]) == ("later", False)


# ---- the scan is cached per page version ----


def test_ans_01_the_scan_is_cached_per_version_and_redone_for_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = answers.scan
    monkeypatch.setattr(answers, "scan", lambda text: calls.append(1) or real(text))
    save_page(tmp_path, default_page())
    store = make_store(tmp_path)
    for _ in range(3):
        store.scan_of("s", PAGE)
    assert len(calls) == 1
    save_page(tmp_path, page(card("canvas-ask", "fresh", ASK)))
    assert list(store.scan_of("s", PAGE).items) == ["fresh"]
    assert len(calls) == 2


def test_ans_02_a_changed_page_tells_the_windows_only_when_it_holds_answers(
    tmp_path: Path,
) -> None:
    notes = Notes()
    save_page(tmp_path, default_page())
    store = make_store(tmp_path, notes)
    store.page_changed("s", PAGE)
    assert notes.pages == []
    answer(store)
    notes.pages.clear()
    save_page(tmp_path, default_page(question="New?"))
    store.page_changed("s", PAGE)
    assert notes.pages == [("s", PAGE)]
    assert store.entries("s", PAGE)["q1"]["state"] == "open"
