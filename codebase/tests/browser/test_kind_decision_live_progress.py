# ruff: noqa: E501, F811
"""Decision, Live and the progress of long jobs (KIND-07, KIND-08, CNT-07).

Real hub, real owner window (headless). The agent side is played through the hub's
own API (``answers``) and by writing files into the session folder.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from .support import block, call
from .test_look_window import headless, look  # noqa: F401

pytestmark = pytest.mark.browser

DECISION = {"text": "I chose PETG", "why": "Tough enough for snap fits.", "ref": "d-1"}
NOW = "2026-11-10T12:00:00.000Z"


def shadow(owner, card_id: str, script: str):  # noqa: ANN001, ANN201
    """Evaluate ``script`` (a function of the shadow root) on the card ``card_id``."""
    return owner.frame.evaluate(
        f"(id) => ({script})(document.querySelector(`[data-canvas-id=${{id}}]`).shadowRoot)",
        card_id,
    )


def wait_shadow(owner, card_id: str, script: str) -> None:  # noqa: ANN001
    owner.frame.wait_for_function(
        f"(id) => ({script})(document.querySelector(`[data-canvas-id=${{id}}]`).shadowRoot)",
        arg=card_id,
    )


def inner(owner, card_id: str, selector: str):  # noqa: ANN001, ANN201
    return owner.frame.locator(f"[data-canvas-id={card_id}]").locator(selector)


def changes(made) -> list[dict]:  # noqa: ANN001
    return [e for e in made.events if e["kind"] == "change"]


def clock_text(owner, iso: str) -> str:  # noqa: ANN001
    """``HH:MM`` of ``iso`` in the browser's time zone, as the cards write it."""
    return owner.page.evaluate(
        """(iso) => { const t = new Date(iso);
          return String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0'); }""",
        iso,
    )


@pytest.fixture
def decided(owner, make):  # noqa: ANN001, ANN201
    made = make(block("canvas-decision", "d1", DECISION))
    inner(owner, "d1", "button").first.wait_for()
    return made


def open_field(owner):  # noqa: ANN001, ANN201
    inner(
        owner,
        "d1",
        "button",
    ).first.click()
    field = inner(owner, "d1", "input")
    field.wait_for()
    return field


def line_of(owner) -> str:  # noqa: ANN001
    return inner(owner, "d1", ".answer").inner_text()


# ---- KIND-07: Decision and Change ----------------------------------------------------------


def test_kind_07_the_decision_reads_you_may_change_it_with_why_folded_and_change(
    owner,
    decided,  # noqa: ANN001
) -> None:
    head = shadow(owner, "d1", "(r) => r.querySelector('.kh').textContent")
    assert "Decision" in head and "you may change it" in head
    assert inner(owner, "d1", ".q").inner_text() == "I chose PETG"
    assert not shadow(owner, "d1", "(r) => r.querySelector('details.why').open")
    assert inner(owner, "d1", "button").first.inner_text() == "Change…"
    assert inner(owner, "d1", "input").count() == 0


def test_kind_07_change_sends_a_change_event_and_the_card_shows_the_stored_line(
    owner,
    decided,  # noqa: ANN001
) -> None:
    field = open_field(owner)
    field.fill("use PLA")
    field.press("Enter")
    [event] = decided.wait_events(1)
    assert event["target"]["canvas_id"] == "d1" and event["page"] == "page.html"
    assert event["value"]["reason"] == "use PLA"
    assert event["value"]["decision"] == "I chose PETG"
    stamp = clock_text(owner, event["time"])
    inner(owner, "d1", ".change-line").wait_for()
    assert line_of(owner).startswith(f"Change asked {stamp}: use PLA")
    assert "not read by the agent yet" in line_of(owner)
    assert inner(owner, "d1", "input").count() == 0  # the field closed


def test_kind_07_the_agent_reading_the_change_turns_the_receipt_to_read(
    owner, decided
) -> None:  # noqa: ANN001
    field = open_field(owner)
    field.fill("use PLA")
    field.press("Enter")
    inner(owner, "d1", ".change-line").wait_for()
    call(owner, "GET", f"/api/sessions/{decided.sid}/answers")
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=d1]').shadowRoot.textContent.includes('read by the agent 1')"
        " || document.querySelector('[data-canvas-id=d1]').shadowRoot.textContent.includes('read by the agent 0')"
        " || document.querySelector('[data-canvas-id=d1]').shadowRoot.textContent.includes('read by the agent 2')"
    )
    assert "not read" not in line_of(owner)


def test_kind_07_after_a_reload_the_change_line_is_still_shown(owner, decided) -> None:  # noqa: ANN001
    field = open_field(owner)
    field.fill("use PLA")
    field.press("Enter")
    inner(owner, "d1", ".change-line").wait_for()
    before = line_of(owner)
    owner.page.reload()
    owner.visit(decided.sid)
    inner(owner, "d1", ".change-line").wait_for()
    assert line_of(owner) == before
    assert len(changes(decided)) == 1  # the reload made no second change


def test_kind_07_an_empty_reason_sends_nothing(owner, decided) -> None:  # noqa: ANN001
    field = open_field(owner)
    field.press("Enter")
    field.fill("   ")
    field.press("Enter")
    inner(owner, "d1", "button.primary").click()
    owner.page.wait_for_timeout(500)
    assert changes(decided) == []
    assert inner(owner, "d1", "input").count() == 1  # still open for the reason


def test_kind_07_escape_closes_the_field_without_an_event(owner, decided) -> None:  # noqa: ANN001
    field = open_field(owner)
    field.fill("never mind")
    field.press("Escape")
    assert inner(owner, "d1", "input").count() == 0
    assert inner(owner, "d1", "button").first.inner_text() == "Change…"
    owner.page.wait_for_timeout(300)
    assert changes(decided) == []


def test_kind_07_the_field_takes_at_most_300_characters(owner, decided) -> None:  # noqa: ANN001
    field = open_field(owner)
    assert field.get_attribute("maxlength") == "300"
    field.focus()
    owner.page.keyboard.insert_text("x" * 320)
    assert len(field.input_value()) == 300


def test_kind_07_a_second_change_replaces_the_first(owner, decided) -> None:  # noqa: ANN001
    field = open_field(owner)
    field.fill("use PLA")
    field.press("Enter")
    inner(owner, "d1", ".change-line").wait_for()
    field = open_field(owner)
    field.fill("use ABS")
    field.press("Enter")
    first, second = decided.wait_events(2)
    assert second["value"]["replaces"] == first["id"]
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=d1]').shadowRoot.textContent.includes('use ABS')"
    )


def test_kind_07_a_rewrite_of_the_page_keeps_the_open_field_and_its_text(
    owner, decided
) -> None:  # noqa: ANN001
    field = open_field(owner)
    field.fill("half a reason")
    decided.rewrite("<p id='added'>more</p>" + block("canvas-decision", "d1", DECISION))
    owner.frame.wait_for_selector("#added", state="attached")
    owner.page.wait_for_timeout(300)
    assert inner(owner, "d1", "input").input_value() == "half a reason"


def test_kind_07_the_decision_text_is_text_never_html(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-decision", "d1", {"text": "<b>bold</b> choice"}))
    inner(owner, "d1", ".q").wait_for()
    assert inner(owner, "d1", ".q").inner_text() == "<b>bold</b> choice"
    assert inner(owner, "d1", ".q b").count() == 0


# ---- KIND-08: Live, its age and the stale mark -------------------------------------------


def live_page(updated: str, **extra) -> str:  # noqa: ANN003
    config = {"title": "Job and limits", "updated": updated, **extra}
    return block("canvas-live", "l1", config)


def iso_before(seconds: int) -> str:
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (base - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def live_words(owner) -> str:  # noqa: ANN001
    return shadow(owner, "l1", "(r) => r.querySelector('.kt').textContent")


def is_stale(owner) -> bool:  # noqa: ANN001
    return shadow(
        owner, "l1", "(r) => r.querySelector('.k').classList.contains('stale')"
    )


@pytest.fixture
def clocked(owner):  # noqa: ANN001, ANN201
    """The page clock stands still at ``NOW``, so ages sit exactly on the boundaries."""
    owner.page.clock.set_fixed_time(NOW)
    return owner


def test_kind_08_the_age_reads_updated_two_min_ago_and_goes_stale_at_601_seconds(
    clocked,  # noqa: ANN001
    make,  # noqa: ANN001
) -> None:
    owner = clocked
    make(live_page(iso_before(120)))
    inner(owner, "l1", ".kt").wait_for()
    assert live_words(owner) == "updated 2 min ago" and not is_stale(owner)
    make(live_page(iso_before(600)), name="beta")
    inner(owner, "l1", ".kt").wait_for()
    assert live_words(owner) == "updated 10 min ago" and not is_stale(
        owner
    )  # 600 s is not older
    make(live_page(iso_before(601)), name="gamma")
    inner(owner, "l1", ".kt").wait_for()
    assert is_stale(owner)
    assert live_words(owner) == f"stale since {clock_text(owner, iso_before(1))}"


def test_kind_08_stale_after_sets_the_limit(clocked, make) -> None:  # noqa: ANN001
    owner = clocked
    make(live_page(iso_before(45), stale_after=30))
    inner(owner, "l1", ".kt").wait_for()
    assert is_stale(owner)
    assert live_words(owner) == f"stale since {clock_text(owner, iso_before(15))}"


def test_kind_08_the_age_refreshes_each_minute_without_a_push(owner, make) -> None:  # noqa: ANN001
    owner.page.clock.install(time=NOW)  # ticking, so that run_for moves the timers
    made = make(live_page(iso_before(100)))
    inner(owner, "l1", ".kt").wait_for()
    assert live_words(owner) == "updated 1 min ago"
    owner.page.clock.run_for(60_000)
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=l1]').shadowRoot.querySelector('.kt').textContent === 'updated 2 min ago'"
    )
    owner.page.clock.run_for(8 * 60_000)  # age 10 min 40 s
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=l1]').shadowRoot.querySelector('.k').classList.contains('stale')"
    )
    assert made.events == []  # nothing was pushed or sent


def test_kind_08_a_live_card_without_updated_reads_updating(owner, make) -> None:  # noqa: ANN001
    make(block("canvas-live", "l1", {"title": "Job"}))
    inner(owner, "l1", ".kt").wait_for()
    assert live_words(owner) == "updating" and not is_stale(owner)


def test_kind_08_a_bad_updated_time_gives_the_error_box(owner, make) -> None:  # noqa: ANN001
    make(live_page("yesterday-ish"))
    inner(owner, "l1", ".block-error").wait_for()
    assert "updated" in inner(owner, "l1", ".block-error").inner_text()


def test_kind_08_a_progress_inside_rewritten_20_times_is_never_removed(
    clocked, make
) -> None:  # noqa: ANN001
    owner = clocked

    def page(i: int) -> str:
        progress = block(
            "canvas-progress", "run", {"value": i, "max": 20, "label": "Build"}
        )
        card = block(
            "canvas-live",
            "l1",
            {"title": "Job", "updated": iso_before(30 + i)},
            progress,
        )
        return card

    made = make(page(0))
    owner.frame.wait_for_selector("canvas-progress [role=progressbar]")
    owner.frame.evaluate(
        """() => { window.__removed = 0;
          const el = document.querySelector('canvas-progress'); el.__mark = 1;
          new MutationObserver((records) => { for (const r of records) for (const n of r.removedNodes)
            if (n === el) window.__removed += 1; }).observe(document.body, {childList: true, subtree: true});
        }"""
    )
    for i in range(1, 21):
        made.rewrite(page(i))
        owner.page.wait_for_timeout(120)
    owner.frame.wait_for_function(
        "document.querySelector('canvas-progress').shadowRoot.querySelector('[role=progressbar]').getAttribute('aria-valuenow') === '20'"
    )
    assert owner.frame.evaluate(
        "[window.__removed, document.querySelector('canvas-progress').__mark]"
    ) == [0, 1]
    assert inner(owner, "run", "[role=progressbar]").count() == 1


# ---- CNT-07: progress of a long job ---------------------------------------------------------

JOB = {"value": 3, "max": 10, "label": "Solving", "status": "running"}
LOG = "\n".join(f"line {n}" for n in range(1, 9)) + "\n"


def progress_page(**extra) -> str:  # noqa: ANN003
    return block("canvas-progress", "job", {**JOB, **extra})


def log_text(owner) -> str:  # noqa: ANN001
    return shadow(owner, "job", "(r) => r.querySelector('.log-text').textContent")


def test_cnt_07_started_and_eta_show_as_start_and_expected_end(owner, make) -> None:  # noqa: ANN001
    started, eta = "2026-11-10T08:05:00", "2026-11-10T09:40:00"
    make(progress_page(started=started, eta=eta))
    inner(owner, "job", "[role=progressbar]").wait_for()
    text = inner(owner, "job", ".block").inner_text()
    assert "Started" in text and "08:05" in text
    assert "expected end" in text and "09:40" in text


def test_cnt_07_without_the_long_job_keys_nothing_extra_is_shown(owner, make) -> None:  # noqa: ANN001
    make(progress_page())
    inner(owner, "job", "[role=progressbar]").wait_for()
    text = inner(owner, "job", ".block").inner_text()
    assert "Started" not in text and "Log" not in text and "Stop" not in text


def test_cnt_07_the_log_shows_its_last_five_lines_folded(owner, make) -> None:  # noqa: ANN001
    make(progress_page(log="run.log"), files={"run.log": LOG})
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=job]').shadowRoot.querySelector('.log-text').textContent !== ''"
    )
    assert log_text(owner).split("\n") == [f"line {n}" for n in range(4, 9)]
    assert not shadow(owner, "job", "(r) => r.querySelector('details.log').open")


def test_cnt_07_a_change_of_the_log_file_refreshes_the_lines_without_a_reload(
    owner, make
) -> None:  # noqa: ANN001
    made = make(progress_page(log="run.log"), files={"run.log": LOG})
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=job]').shadowRoot.querySelector('.log-text').textContent.includes('line 8')"
    )
    owner.frame.evaluate("window.__probe = 1")
    (made.folder / "run.log").write_text(LOG + "line 9\nline 10\n")
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=job]').shadowRoot.querySelector('.log-text').textContent.endsWith('line 10')"
    )
    assert log_text(owner).split("\n") == [f"line {n}" for n in range(6, 11)]
    assert owner.frame.evaluate("window.__probe") == 1  # same document


@pytest.mark.parametrize(
    "path",
    [
        "../secret.log",
        "/etc/passwd",
        "http://example.invalid/x.log",
        "%2e%2e/secret.log",
    ],
)
def test_cnt_07_a_log_outside_the_session_folder_is_never_read(
    owner, make, path
) -> None:  # noqa: ANN001
    requested: list[str] = []
    owner.page.on("request", lambda request: requested.append(request.url))
    make(progress_page(log=path))
    inner(owner, "job", ".block-error").wait_for()
    assert "session folder" in inner(owner, "job", ".block-error").inner_text()
    owner.page.wait_for_timeout(300)
    assert not [
        u for u in requested if "secret" in u or "passwd" in u or "invalid" in u
    ], requested


def test_cnt_07_stop_asks_first_and_sends_only_after_yes(owner, make) -> None:  # noqa: ANN001
    made = make(progress_page(stop=True))
    inner(owner, "job", "button.danger").first.wait_for()
    inner(owner, "job", "button.danger").first.click()
    assert "Stop the run?" in inner(owner, "job", ".block").inner_text()
    owner.page.wait_for_timeout(300)
    assert made.events == []  # asking is not stopping
    inner(owner, "job", "text=Keep running").click()
    owner.page.wait_for_timeout(300)
    assert made.events == []
    inner(owner, "job", "button.danger").first.click()
    inner(owner, "job", "text=Yes, stop").click()
    [event] = made.wait_events(1)
    assert event["kind"] == "button" and event["value"] == "stop"
    assert event["target"]["canvas_id"] == "job"
    owner.page.wait_for_timeout(300)
    assert len(made.events) == 1


@pytest.mark.parametrize(
    "extra", [{}, {"stop": True, "status": "done"}, {"stop": True, "status": "failed"}]
)
def test_cnt_07_there_is_no_stop_unless_asked_for_and_running(
    owner, make, extra
) -> None:  # noqa: ANN001
    make(progress_page(**extra))
    inner(owner, "job", "[role=progressbar]").wait_for()
    assert not inner(owner, "job", "text=Stop").first.is_visible()


def test_cnt_07_a_long_job_rewrite_adds_and_removes_no_node(owner, make) -> None:  # noqa: ANN001
    keys = {
        "started": "2026-11-10T08:05:00",
        "eta": "2026-11-10T09:40:00",
        "log": "run.log",
        "stop": True,
    }
    made = make(progress_page(**keys, detail="step 3"), files={"run.log": LOG})
    inner(owner, "job", "[role=progressbar]").wait_for()
    owner.frame.wait_for_function(
        "document.querySelector('[data-canvas-id=job]').shadowRoot.querySelector('.log-text').textContent !== ''"
    )
    owner.frame.evaluate(
        """() => { window.__changes = 0;
          new MutationObserver((records) => { for (const r of records)
            if (r.type === 'childList') window.__changes += 1; })
            .observe(document.querySelector('canvas-progress').shadowRoot, {childList: true, subtree: true});
        }"""
    )
    for i in range(4, 12):
        made.rewrite(progress_page(**keys, value=i, detail=f"step {i}"))
        owner.page.wait_for_timeout(150)
    owner.frame.wait_for_function(
        "document.querySelector('canvas-progress').shadowRoot.querySelector('[role=progressbar]').getAttribute('aria-valuenow') === '11'"
    )
    assert owner.frame.evaluate("window.__changes") == 0


# ---- the look: contrast in light and dark ---------------------------------------------------


def long_job_page() -> str:
    now = datetime.now(UTC)

    def iso(**ago: int) -> str:
        return (now - timedelta(**ago)).isoformat().replace("+00:00", "Z")

    job = block(
        "canvas-progress",
        "job",
        {"value": 6, "max": 10, "label": "Print job 14", "status": "running",
         "detail": "layer 312 of 520", "started": iso(hours=2), "eta": iso(hours=-1),
         "log": "run.log", "stop": True},
    )  # fmt: skip
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<link rel="stylesheet" href="/static/kit/kit.css"></head><body><div class="page">'
        + block("canvas-decision", "d1", DECISION)
        + block(
            "canvas-live",
            "l1",
            {"title": "Fresh", "text": "Printer link", "updated": iso(minutes=2)},
            job,
        )
        + block(
            "canvas-live",
            "l2",
            {"title": "Stale", "text": "Scale reading", "updated": iso(minutes=30)},
        )
        + "</div></body></html>"
    )


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_kind_07_08_cnt_07_the_cards_pass_the_contrast_check_in_either_mode(
    owner,
    make,
    headless,
    scheme: str,  # noqa: ANN001, F811
) -> None:
    made = make(long_job_page(), files={"run.log": LOG})
    owner.frame.wait_for_function(
        "[...document.querySelectorAll('canvas-decision,canvas-live,canvas-progress')]"
        ".every((e) => e.renderIdle && e.shadowRoot && e.shadowRoot.querySelector('.k, .block'))"
    )
    result = look(owner, made.sid, width=900, height=900, scheme=scheme, full=True)
    assert result["scheme"] == scheme, result
    findings = result["audit"]["findings"]
    assert [f for f in findings if f["rule"] == "contrast"] == [], findings
    if os.environ.get("KINDS_LOOK_DIR"):
        target = Path(os.environ["KINDS_LOOK_DIR"])
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(result["png"], target / f"long-jobs-{scheme}.png")
