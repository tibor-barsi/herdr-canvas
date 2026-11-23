"""Final acceptance (TST-03), scenarios 6, 7 and 9: comments, plans, questions.

A real nested ``claude -p --plugin-dir plugin/`` (default permission mode, the
allow rules of ``docs/install.md``) works against a temporary hub; headless
Chromium is the owner. The in-between states are polled while they last, not
inferred afterwards: the replies' arrival in the window (6), the home snapshot
while a card is open (7, 9) and the answered line after a reload (9).
First attempt ``haiku``, one retry with ``sonnet`` (see ``conftest.py``).
Run by hand: ``uv run pytest -m e2e -k scenario_9 -s``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from harness import (
    ClaudeRun,
    home_entry,
    lasso_path,
    open_first_tab,
    pick_kind,
    pump,
    session_events,
    wait_command_items,
    wait_listening,
)
from test_acceptance_claude import GUIDE, assert_no_denials, wait_for

from browser.pdf_fixtures import text_pdf
from browser.support import Studio
from browser.test_view_04_pdf_viewer import wait_text
from browser.test_view_07_pdf_comments import (
    go,
    point_on_page,
    pt,
    rect_on_page,
    reveal,
    scale,
    text_on_page,
)

pytestmark = [pytest.mark.e2e, pytest.mark.retry_once]


@pytest.fixture(autouse=True)
def claude_installed() -> None:
    """Fail (not skip) when the claude command is missing."""
    assert shutil.which("claude"), "the claude command is not installed"


ONE_COMMAND = (
    "Run every command as its own Bash call; never chain commands with ; or && "
    "or add echo, because a refused call leaves a permission need on the home page."
)


def session_folder(hub, session: str) -> Path:  # noqa: ANN001
    """The session's folder in the temporary project."""
    return hub.project_dir / hub.project_dir_name / session


def canvas(run: ClaudeRun, *args: str) -> str:
    """Run the CLI as the agent would, in the run's environment; return stdout."""
    done = subprocess.run(
        [sys.executable, "-m", "agent_canvas.cli", *args],
        env=run.environment, cwd=run.hub.project_dir, capture_output=True,
        text=True, timeout=60,
    )  # fmt: skip
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout


def sample_need(hub, session: str) -> tuple:  # noqa: ANN001
    """(state, need kind) of the session in the home snapshot."""
    entry = home_entry(hub, session) or {}
    return entry.get("state"), (entry.get("need") or {}).get("kind")


def seconds_of(stamp: str) -> float:
    """Epoch seconds of the hub's ``YYYY-MM-DDTHH:MM:SS.mmmZ`` stamps."""
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


# ---- Scenario 6 -----------------------------------------------------------------

PDF_NAME = "spec.pdf"
# QUESTION: the agent answers it fully and marks it done; CHANGE: asks for an edit
# of the PDF, which it cannot make, so it replies and leaves it open
COMMENTS_6 = {
    "text": "CHANGE: replace the word quick by slow in this line",
    "point": "QUESTION: what kind of text is at this spot?",
    "rect": "CHANGE: this block needs a heading",
    "lasso": "QUESTION: is there any text in this area?",
}


def prompt_6(pdf: Path) -> str:
    """Prompt of scenario 6 for the fixture PDF."""
    return f"""{GUIDE} {ONE_COMMAND} \
Show me the PDF {pdf} with `agent-canvas show --copy {pdf}`. \
Then listen for my comments: load Monitor with ToolSearch `select:Monitor` and start \
`agent-canvas watch --count 1 --timeout 540` under Monitor (timeout_ms 600000). When \
my comments arrive (one send with several numbered comments, most with a picture), \
answer EVERY comment with its own call `agent-canvas comment reply {PDF_NAME} N \
"your answer"`, one or two sentences about what it marks. A comment whose text \
starts with QUESTION: you can answer completely: add --done to that reply. A comment \
whose text starts with CHANGE: asks for an edit of the PDF, which you cannot make: \
reply that you noted it and do not use --done. After the last reply start the same \
watch again under Monitor and wait."""


OBSERVER = """() => {
  window.__seen = {};
  const record = () => document.querySelectorAll('#comment-panel .ent').forEach((e) =>
    e.querySelectorAll('.rp:not(.me) .rt').forEach((t) => {
      const key = e.dataset.n + '|' + t.textContent;
      if (!(key in window.__seen)) window.__seen[key] = Date.now();
    }));
  new MutationObserver(record).observe(document.getElementById('comment-panel'),
    {subtree: true, childList: true, characterData: true});
  record();
}"""


def lasso_on_page(studio, page: int, centre: tuple, radii: tuple, text: str) -> None:  # noqa: ANN001
    """Draw a lasso around ``centre`` points of ``page`` and save it with ``text``."""
    reveal(studio, page, (centre[0] - radii[0], centre[1] - radii[1],
                          centre[0] + radii[0], centre[1] + radii[1]))  # fmt: skip
    pick_kind(studio.owner, "lasso")
    factor = scale(studio)
    lasso_path(studio.owner, pt(studio, page, *centre),
               radii[0] * factor, radii[1] * factor, text)  # fmt: skip
    studio.page.wait_for_function(
        "document.querySelectorAll('#comment-panel .ent').length >= 4"
    )


def stored_comments(folder: Path) -> list[dict]:
    """Comments of the shown PDF as ``.comments/<page>.json`` holds them."""
    path = folder / ".comments" / f"{PDF_NAME}.json"
    return json.loads(path.read_text())["comments"] if path.is_file() else []


def agent_replies(comment: dict) -> list[dict]:
    """The agent's replies (not the owner's) of a stored comment."""
    return [r for r in comment["replies"] if r["from"] is not None]


def test_e2e_scenario_6_claude_comment_a_pdf(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    pdf = tmp_path / "fixtures" / PDF_NAME
    pdf.parent.mkdir()
    pdf.write_bytes(text_pdf(3))
    run = ClaudeRun(hub, tmp_path, claude_model)
    session = str(uuid.uuid4())
    folder = session_folder(hub, session)
    studio = Studio(owner, tmp_path)
    run.start(prompt_6(pdf), session)
    try:
        assert wait_for(run, owner, lambda: open_first_tab(owner), 200), run.report()
        owner.frame.wait_for_function(
            "window.acViewer && window.acViewer.mounted", timeout=120_000
        )
        wait_text(owner, 1)
        assert wait_listening(owner, run, session, 150), run.report()
        go(studio, 1)
        text_on_page(
            studio, "Line 3 of page 1", "Line 3 of page 1: the quick brown",
            COMMENTS_6["text"],
        )  # fmt: skip
        point_on_page(studio, 1, 300, 450, COMMENTS_6["point"])
        go(studio, 2)
        rect_on_page(studio, 2, (50, 150, 300, 200), COMMENTS_6["rect"])
        lasso_on_page(studio, 2, (400, 320), (70, 40), COMMENTS_6["lasso"])
        owner.page.click('.filters button[data-filter="all"]')
        owner.page.evaluate(OBSERVER)
        owner.page.click("#send-button")

        def replied() -> bool:
            found = stored_comments(folder)
            return len(found) == 4 and all(agent_replies(c) for c in found)

        assert wait_for(run, owner, replied, 180), (
            owner.page.inner_text("#send-notice"),
            owner.page.inner_text("#comment-count"),
            stored_comments(folder),
            run.report(),
        )
        pump(owner, 1500)
        seen = owner.page.evaluate("window.__seen")
        relistening = wait_for(run, owner, lambda: hub.listening(session), 90)
        listing = json.loads(
            canvas(run, "comment", "list", "--all", "--session", session)
        )["comments"]
        print(run.report(), f"\nSEEN IN WINDOW: {seen}\nLIST --all:\n{listing}")
    finally:
        run.finish(5)
    assert_no_denials(run)

    [event] = [e for e in session_events(hub, session) if e["kind"] == "send"]
    sent = json.loads(Path(event["send_file"]).read_text())["comments"]
    assert [c["kind"] for c in sent] == ["text", "point", "rect", "lasso"], sent
    assert [c["anchor"]["space"] for c in sent] == ["pdf-pt"] * 4, sent
    pages = [c["anchor"].get("p") or c["anchor"]["rects"][0]["p"] for c in sent]
    assert pages == [1, 1, 2, 2], sent
    for comment in sent:
        picture = Path(comment["picture"])
        if not picture.is_absolute():
            picture = Path(event["send_file"]).parent / picture
        assert picture.is_file(), comment

    stored = stored_comments(folder)
    by_text = {c["text"]: c for c in stored}
    assert set(by_text) == set(COMMENTS_6.values()), by_text.keys()
    for comment in stored:
        first = agent_replies(comment)[0]
        shown = seen.get(f"{comment['n']}|{first['text']}")
        assert shown is not None, (comment["n"], first, seen)
        late = shown / 1000 - seconds_of(first["at"])
        print(f"REPLY {comment['n']} SHOWN {late:.3f} s AFTER THE CALL")
        assert late <= 1.0, f"comment {comment['n']}: reply shown {late:.2f} s late"
    expected_done = {t for t in COMMENTS_6.values() if t.startswith("QUESTION:")}
    done = {t for t, c in by_text.items() if c["done"] and c["done"]["by"] == "agent"}
    assert expected_done and done == expected_done, (done, expected_done)
    assert {t for t, c in by_text.items() if c["done"]} == done
    listed_done = {c["text"] for c in listing if c["done"]}  # `list --all`: all four
    assert len(listing) == 4 and listed_done == done, listing
    assert relistening, "the agent did not wait again"


# ---- Scenario 7 -----------------------------------------------------------------

PLAN_STEPS = (
    "Add a header comment to fit.py",
    "Rename the variable q to flow",
    "Regenerate report.txt",
)


def prompt_7(fit: Path, report: Path) -> str:
    """Prompt of scenario 7 for the two fixture files."""
    steps = " ".join(f"{n}. {text}." for n, text in enumerate(PLAN_STEPS, 1))
    return f"""{GUIDE} {ONE_COMMAND} \
I want a change in my project: {steps} Change nothing yet. \
First write the plan as exactly these three numbered lines, in this order, to \
`plan.txt` in your session folder and send me an approval card with \
`agent-canvas ask "Apply this plan?" --approval --details-file <that plan.txt> \
--timeout 300` (Bash timeout 330000 ms). If I send it back, change the plan as I \
say, write it again and ask again with the same command. When I approve, do not \
edit any file (the change is simulated) and leave a result card with \
`agent-canvas result "Changed fit.py and report.txt" --file {fit} --file {report} \
--decision "Repeat run 15?" --choice Repeat --choice Keep`. Then start \
`agent-canvas watch --timeout 540` under Monitor (load it with ToolSearch \
`select:Monitor`, timeout_ms 600000). When my decision arrives, reply with one line \
`DECIDED: <my choice>`."""


def test_e2e_scenario_7_claude_plan_sent_back_approved_then_a_decision(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    fit, report = hub.project_dir / "fit.py", hub.project_dir / "report.txt"
    fit.write_text("q = 1\n")
    report.write_text("run 15\n")
    run = ClaudeRun(hub, tmp_path, claude_model)
    session = str(uuid.uuid4())
    run.start(prompt_7(fit, report), session)
    card = owner.page.locator("#ask-bar .ask-card")
    plans: list[str] = []
    ask_ids: list[str] = []
    needs: list[list[tuple]] = []

    def waiting_ask() -> dict | None:
        found = [a for a in hub.open_asks(session) if a["waiting"]]
        return found[0] if found else None

    def round_of_approval(previous: str | None) -> None:
        """Wait for a new approval card; note its plan and the home snapshot."""

        def shown() -> bool:
            open_first_tab(owner)
            ask = waiting_ask()
            return (
                ask is not None
                and ask["ask"] != previous
                and card.get_by_role("button", name="Approve", exact=True).count() == 1
            )

        assert wait_for(run, owner, shown, 200), run.report()
        ask_ids.append(waiting_ask()["ask"])
        plans.append(card.locator(".details").inner_text())
        samples = []
        for _ in range(8):  # the card stays open: the snapshot must say so, too
            pump(owner, 200)
            samples.append(sample_need(hub, session))
        needs.append(samples)

    try:
        round_of_approval(None)
        card.get_by_role("button", name="Send back…", exact=True).click()
        field = card.get_by_label("Reason for sending it back")
        field.fill("do step 2 first")
        field.press("Enter")
        round_of_approval(ask_ids[0])
        card.get_by_role("button", name="Approve", exact=True).click()
        result_card = owner.page.locator("#ask-bar .result-card")
        keep = result_card.get_by_role("button", name="Keep", exact=True)
        assert wait_for(run, owner, lambda: keep.count() == 1, 200), run.report()
        seen_before = len(run.results())
        keep.click()

        def decided() -> bool:
            later = run.results()[seen_before:]
            return any("decided: keep" in str(r.get("result")).lower() for r in later)

        wait_for(run, owner, decided, 150)
        after = [str(r.get("result")) for r in run.results()[seen_before:]]
    finally:
        run.finish(5)
    print(run.report(), f"\nPLANS: {plans}\nNEEDS: {needs}")
    assert_no_denials(run)

    events = session_events(hub, session)
    answers = [e for e in events if e["kind"] == "answer"]
    assert [a["value"].get("decision") for a in answers] == ["sent-back", "approved"]
    assert answers[0]["value"]["reason"] == "do step 2 first", answers
    assert len(set(ask_ids)) == 2, ask_ids
    steps = [line.strip().lower() for line in plans[1].splitlines() if line.strip()]
    assert "rename" in steps[0] and "flow" in steps[0], plans[1]
    for samples in needs:
        assert samples[-4:] == [("needs-you", "approval")] * 4, samples
    [decision] = [e for e in events if e["kind"] == "decision"]
    assert decision["value"] == "Keep", decision
    assert any("decided: keep" in text.lower() for text in after), after


# ---- Scenario 9 -----------------------------------------------------------------

PROMPT_9A = f"""{GUIDE} {ONE_COMMAND} \
Build me a dashboard page `page.html` (write it with your \
file tool into your session folder, then `agent-canvas show`) with, in this order: \
a canvas-ask (data-canvas-id "q-layout", form "one", question "Which layout?", \
options "wide" and "narrow", no default), a canvas-ask (data-canvas-id "q-ribs", \
form "number", question "How many ribs?", min 1, max 20, no default) and a canvas-do \
(data-canvas-id "w-clamp", title "Check the clamp", where "bench", one step with \
text "Tighten the clamp" and run "echo clamp-1", no default). Then wait for my two \
answers with `agent-canvas answers --wait q-layout q-ribs --timeout 300` (Bash \
timeout 330000 ms), in the foreground. When it returns, reply with one line `GOT: \
<both answers>` and stop; do not wait for anything else."""

PROMPT_9B = """I reported a problem on the Do w-clamp. Run `agent-canvas answers` and \
read the problem. Then rewrite the step of the Do in page.html: change its text to \
"Tighten the clamp by hand" and its run to "echo clamp-2" (same ids, same title), \
and wait for me with `agent-canvas answers --wait w-clamp --timeout 300` in the \
foreground (Bash timeout 330000 ms); do not end your turn before it returns. When it \
returns, run `agent-canvas answers` once more and reply \
with one line: `FINAL: <answer of q-layout>, <answer of q-ribs>, <status of \
w-clamp>`."""


def poll(owner, condition, seconds: float = 20) -> bool:  # noqa: ANN001
    """Poll ``condition`` while the browser runs, also when no agent is running."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        pump(owner, 100)
    return False


def ask_text(owner, card_id: str, selector: str) -> str:  # noqa: ANN001
    """Text of an element in a card's shadow root (``""`` while it is not there)."""
    return owner.frame.evaluate(
        """([id, s]) => { const e = document.querySelector(`[data-canvas-id=${id}]`);
          const t = e && e.shadowRoot && e.shadowRoot.querySelector(s);
          return t ? t.textContent : ''; }""",
        [card_id, selector],
    )


def cards_drawn(owner) -> bool:  # noqa: ANN001
    """Whether the frame has drawn the three cards of the dashboard."""
    try:
        return owner.frame.evaluate(
            """() => ['q-layout', 'q-ribs', 'w-clamp'].every((id) => {
              const e = document.querySelector(`[data-canvas-id=${id}]`);
              return e && e.renderIdle && e.shadowRoot.querySelector('.k'); })"""
        )
    except Exception:  # noqa: BLE001 - frame reloading
        return False


def items_of(folder: Path) -> dict:
    """The stored answer items of ``page.html`` by id (``{}`` before the first)."""
    path = folder / ".answers" / "page.html.json"
    return json.loads(path.read_text())["items"] if path.is_file() else {}


def listed(run: ClaudeRun, session: str) -> dict:
    """``answers`` output of the hub by item id."""
    out = json.loads(canvas(run, "answers", "--session", session))
    return {item["id"]: item for item in out["items"]}


def bash_commands(run: ClaudeRun) -> list[str]:
    """The Bash commands of the run's current stream, in order."""
    return [
        str(block["input"].get("command"))[:160]
        for event in run.events() if event.get("type") == "assistant"
        for block in event.get("message", {}).get("content", [])
        if block.get("type") == "tool_use" and block["name"] == "Bash"
    ]  # fmt: skip


def test_e2e_scenario_9_claude_two_questions_and_a_todo(
    owner, hub, tmp_path, claude_model
) -> None:  # noqa: ANN001
    run = ClaudeRun(hub, tmp_path, claude_model)
    session = str(uuid.uuid4())
    folder = session_folder(hub, session)
    run.start(PROMPT_9A, session)
    needs: list[tuple] = []
    layout_id = after_reload = wait_output = final = first_final = ""
    first_run_ended = False
    waited: dict = {}
    waiting_kinds: list[str] = []
    reopened_item: dict = {}

    def card(item: str):  # noqa: ANN202
        return owner.frame.locator(f"[data-canvas-id={item}]")

    def answered(item: str) -> bool:
        return "Answered" in ask_text(owner, item, ".said")

    try:
        assert wait_for(
            run, owner, lambda: open_first_tab(owner) and cards_drawn(owner), 200
        ), run.report()
        assert wait_listening(owner, run, session, 150), run.report()
        for _ in range(8):  # both Asks open: question, not todo
            pump(owner, 200)
            needs.append(sample_need(hub, session))
        waiting_kinds = hub.listener_kinds(session)

        layout = card("q-layout").locator(".opt").first
        layout_id = layout.get_attribute("data-id")
        layout.click()
        card("q-layout").locator("button.submit").click()
        assert wait_for(run, owner, lambda: answered("q-layout"), 30)
        owner.page.reload()
        owner.visit(session)
        assert wait_for(run, owner, lambda: cards_drawn(owner), 60)
        assert wait_for(run, owner, lambda: answered("q-layout"), 30)
        after_reload = ask_text(owner, "q-layout", ".said")
        assert run.running, "the agent ended before the second answer"

        card("q-ribs").locator("input[type=number]").fill("7")
        card("q-ribs").locator("button.submit").click()
        assert wait_for(run, owner, lambda: answered("q-ribs"), 30)
        first_run_ended = wait_for(run, owner, lambda: not run.running, 120)
        first_final = run.final()
        waited = wait_command_items(run.events(), "answers --wait")
        wait_output = json.dumps(waited)

        card("w-clamp").locator("button:text-is('Problem…')").click()
        card("w-clamp").locator("textarea").fill("The clamp slips")
        card("w-clamp").locator("button:text-is('Send')").click()
        assert poll(
            owner, lambda: items_of(folder).get("w-clamp", {}).get("state") == "problem"
        ), items_of(folder)

        run.start(PROMPT_9B, resume=session)
        done_button = card("w-clamp").locator("button:text-is('Done')")

        def reopened() -> bool:
            item = items_of(folder).get("w-clamp", {})
            problem = any("slips" in json.dumps(h) for h in item.get("history") or [])
            waits = ask_text(owner, "w-clamp", ".kt") == "waits for you"
            return (
                item.get("state") == "open" and problem and waits
                and done_button.count() == 1
            )  # fmt: skip

        assert poll(owner, reopened, 150), run.report()
        pump(owner, 1500)  # a second edit of the page would open the Do again
        assert reopened(), items_of(folder)
        reopened_item = items_of(folder)["w-clamp"]
        done_button.click()
        poll(owner, lambda: "FINAL:" in run.final(), 120)
        final = run.final()
    finally:
        run.finish(5)
        page_file = folder / "page.html"
        text = page_file.read_text() if page_file.is_file() else ""
        do_part = text[text.find("<canvas-do") :][:500]
        print(
            run.report(),
            f"\nBASH: {bash_commands(run)}",
            f"\nNEEDS: {needs}\nWAIT OUTPUT: {wait_output}"
            f"\nAFTER RELOAD: {after_reload}\nFINAL: {final}"
            f"\nDO ITEM: {items_of(folder).get('w-clamp')}"
            f"\nDO IN PAGE: {do_part}",
        )
    assert_no_denials(run)

    assert needs[-4:] == [("needs-you", "question")] * 4, needs
    assert waiting_kinds, "answers --wait was not counted as a listener"
    assert first_run_ended, "the first run was still running at the resume"
    assert "GOT:" in first_final, first_final
    assert {waited[i]["state"] for i in ("q-layout", "q-ribs")} == {"answered"}, waited
    assert layout_id in json.dumps(waited["q-layout"]["answer"]), waited
    assert "7" in json.dumps(waited["q-ribs"]["answer"]), waited
    assert after_reload.startswith("Answered"), after_reload
    assert reopened_item["state"] == "open", reopened_item
    items = listed(run, session)
    assert items["w-clamp"]["state"] == "done" and items["w-clamp"]["read"], items
    assert layout_id in final and "7" in final, final
