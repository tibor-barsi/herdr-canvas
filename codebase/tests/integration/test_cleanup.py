"""``cleanup`` through the CLI against a real hub (CLI-11, SEC-08)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DAY = 86400
OLD = time.time() - 60 * DAY


def stamp(days_ago: float) -> str:
    """ISO time ``days_ago`` days back, in the format of 5.3."""
    moment = time.time() - days_ago * DAY
    text = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(moment))
    return f"{text}.000Z"


def put(path: Path, content: str = "x" * 10, *, age_days: float = 0) -> Path:
    """Write a file whose modification time is ``age_days`` days back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    moment = time.time() - age_days * DAY
    os.utime(path, (moment, moment))
    return path


def event_line(event_id: str, seq: int, age_days: float) -> str:
    record = {
        "record": "event", "type": "event", "id": event_id, "session": "s",
        "seq": seq, "time": stamp(age_days), "kind": "send", "page": "page.html",
        "page_version": None, "target": None, "value": None, "delivery": "now",
        "state": "queued", "message": "", "actions": [], "marks": [],
        "screenshot": None, "screenshot_error": None, "send_file": None,
    }  # fmt: skip
    return json.dumps(record)


def delivered_line(event_id: str, age_days: float) -> str:
    record = {
        "record": "delivered",
        "id": event_id,
        "time": stamp(age_days),
        "via": "pending",
    }
    return json.dumps(record)


def start(cli, *args: str) -> tuple[str, Path]:
    done = cli("session", "start", *args)
    assert done.code == 0, done.err
    return done.json["session"], Path(done.json["folder"])


def start_own(cli) -> tuple[str, Path]:
    """Start a session; return its id and its own folder, which ``--session`` cleans."""
    sid, pool = start(cli)
    own = pool.parent / sid  # not the pool: --session never touches it (A-1005)
    assert (own / "session.json").is_file()
    return sid, own


def populate(folder: Path) -> dict[str, Path]:
    """A session with old and new history, an old page and a three-event log."""
    files = {
        "old_version": put(folder / "history/pages/page.0001.html", age_days=60),
        "new_version": put(folder / "history/pages/page.0002.html", age_days=1),
        "old_send": put(folder / "history/sends/0001.json", "{}", age_days=60),
        "old_png": put(folder / "history/sends/0001.png", "png", age_days=60),
        "queued_send": put(
            folder / "history/sends/0002.json",
            json.dumps({"event": "evt_oldqueued"}),
            age_days=60,
        ),
        "queued_png": put(folder / "history/sends/0002.png", "png", age_days=60),
        "page": put(folder / "page.html", "<p>current</p>", age_days=60),
        "asset": put(folder / "assets/data.csv", "1,2", age_days=60),
    }
    lines = [
        event_line("evt_olddone", 1, 60),
        delivered_line("evt_olddone", 60),
        event_line("evt_oldqueued", 2, 60),
        event_line("evt_new", 3, 1),
    ]
    # The hub's watcher saves the new page as the next history version; wait for
    # it so that it cannot appear in the middle of a test. It watches pools only.
    deadline = time.monotonic() + 10
    watched = folder.name.startswith("pool-")
    while watched and not (folder / "history/pages/page.0003.html").exists():
        assert time.monotonic() < deadline, "the hub did not save the page"
        time.sleep(0.02)
    files["events"] = put(folder / "events.jsonl", "\n".join(lines) + "\n", age_days=0)
    return files


def event_ids(folder: Path) -> list[str]:
    lines = (folder / "events.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    return [r["id"] for r in records if r["record"] == "event"]


# ---- dry run and --yes -----------------------------------------------------


def test_cli_11_dry_run_is_the_default_and_deletes_nothing(cli) -> None:
    _, folder = start(cli)
    files = populate(folder)
    before = sorted(p for p in folder.rglob("*") if p.is_file())
    result = cli("cleanup", "--older-than", "30d")
    assert result.code == 0, result.err
    data = result.json
    assert set(data) == {"dry_run", "deleted", "bytes", "kept_queued"}
    assert data["dry_run"] is True
    assert str(files["old_version"]) in data["deleted"]
    assert str(files["new_version"]) not in data["deleted"]
    assert data["bytes"] > 0
    assert sorted(p for p in folder.rglob("*") if p.is_file()) == before
    assert len(event_ids(folder)) == 3


def test_cli_11_yes_deletes_exactly_the_listed_paths(cli) -> None:
    _, folder = start(cli)
    populate(folder)
    listed = cli("cleanup", "--older-than", "30d").json
    before = {p for p in folder.rglob("*") if p.is_file()}
    done = cli("cleanup", "--older-than", "30d", "--yes").json
    assert done["dry_run"] is False
    assert done["deleted"] == listed["deleted"] and done["bytes"] == listed["bytes"]
    after = {p for p in folder.rglob("*") if p.is_file()}
    gone = {str(p) for p in before - after}
    # events.jsonl is listed because lines were cut from it, but it still exists
    assert gone == set(done["deleted"]) - {str(folder / "events.jsonl")}
    assert str(folder / "events.jsonl") in done["deleted"]


def test_cli_11_older_than_cuts_old_event_lines_and_keeps_the_rest(cli) -> None:
    _, folder = start(cli)
    populate(folder)
    cli("cleanup", "--older-than", "30d", "--yes")
    assert event_ids(folder) == ["evt_oldqueued", "evt_new"]
    kept = (folder / "events.jsonl").read_text()
    assert "delivered" not in kept


def test_cli_11_pages_and_assets_survive_older_than(cli) -> None:
    _, folder = start(cli)
    files = populate(folder)
    cli("cleanup", "--older-than", "30d", "--yes")
    assert files["page"].is_file() and files["asset"].is_file()
    assert files["new_version"].is_file()
    assert not files["old_version"].exists()


def test_cli_11_age_units(cli) -> None:
    _, folder = start(cli)
    put(folder / "history/pages/page.0001.html", age_days=0.5)  # 12 h old
    assert cli("cleanup", "--older-than", "2d").json["deleted"] == []
    assert len(cli("cleanup", "--older-than", "6h").json["deleted"]) == 1


# ---- queued events ---------------------------------------------------------


def test_cli_11_queued_send_survives_without_force(cli) -> None:
    _, folder = start(cli)
    files = populate(folder)
    data = cli("cleanup", "--older-than", "30d", "--yes").json
    assert data["kept_queued"] == ["evt_oldqueued"]
    assert files["queued_send"].is_file() and files["queued_png"].is_file()
    assert not files["old_send"].exists() and not files["old_png"].exists()
    assert "evt_oldqueued" in event_ids(folder)


def test_cli_11_queued_send_is_deleted_with_force(cli) -> None:
    _, folder = start(cli)
    files = populate(folder)
    data = cli("cleanup", "--older-than", "30d", "--yes", "--force").json
    assert data["kept_queued"] == []
    assert not files["queued_send"].exists() and not files["queued_png"].exists()
    assert event_ids(folder) == ["evt_new"]


def test_cli_11_kept_queued_event_is_still_delivered_afterwards(cli) -> None:
    sid, folder = start(cli)
    populate(folder)
    cli("cleanup", "--older-than", "30d", "--yes")
    cli("show", "page.html", "--session", sid)  # the pool's inbox serves who touched it
    pending = cli("pending", "--session", sid).json["events"]
    assert [e["id"] for e in pending] == ["evt_oldqueued", "evt_new"]


# ---- --session -------------------------------------------------------------


def test_cli_11_session_on_an_active_session_keeps_its_pages(cli) -> None:
    sid, folder = start_own(cli)
    files = populate(folder)
    data = cli("cleanup", "--session", sid, "--yes", "--force").json
    assert data["dry_run"] is False
    assert files["page"].is_file() and files["asset"].is_file()
    assert (folder / "session.json").is_file()
    assert not (folder / "history/pages/page.0002.html").exists()
    assert not (folder / "events.jsonl").exists()
    ids = [s["id"] for s in cli("session", "list").json["sessions"]]
    assert sid in ids


def test_cli_11_session_without_force_keeps_queued_events(cli) -> None:
    sid, folder = start_own(cli)
    files = populate(folder)
    data = cli("cleanup", "--session", sid, "--yes").json
    assert set(data["kept_queued"]) == {"evt_oldqueued", "evt_new"}
    assert files["queued_send"].is_file()
    assert not files["new_version"].exists()
    assert event_ids(folder) == ["evt_oldqueued", "evt_new"]


def test_cli_11_session_dry_run_changes_nothing(cli) -> None:
    sid, folder = start_own(cli)
    populate(folder)
    cli("session", "end", "--session", sid)
    before = sorted(folder.rglob("*"))
    data = cli("cleanup", "--session", sid, "--force").json
    assert data["dry_run"] is True and str(folder) in data["deleted"]
    assert sorted(folder.rglob("*")) == before


def test_cli_11_session_on_an_ended_session_removes_folder_and_entry(cli) -> None:
    sid, folder = start_own(cli)
    populate(folder)
    cli("session", "end", "--session", sid)
    data = cli("cleanup", "--session", sid, "--yes", "--force").json
    assert not folder.exists()
    assert str(folder) in data["deleted"]
    state_dir = Path(cli.environment["AGENT_CANVAS_STATE_DIR"])
    assert sid not in json.loads((state_dir / "sessions.json").read_text())
    listed = cli("session", "list", "--all").json["sessions"]
    assert sid not in [s["id"] for s in listed]
    assert cli("session", "end", "--session", sid).code == 5


def test_cli_11_ended_session_with_a_kept_queued_event_stays(cli) -> None:
    sid, folder = start_own(cli)
    populate(folder)
    cli("session", "end", "--session", sid)
    data = cli("cleanup", "--session", sid, "--yes").json
    assert data["kept_queued"]
    assert folder.is_dir() and (folder / "page.html").is_file()


def test_cli_11_hub_keeps_serving_after_a_session_is_removed(cli) -> None:
    sid, folder = start(cli)
    cli("session", "end", "--session", sid)
    cli("cleanup", "--session", sid, "--yes")
    assert cli("status").code == 0
    other, _ = start(cli)
    assert cli("pending", "--session", other).json["events"] == []


# ---- --project and errors ----------------------------------------------------


def test_cli_11_project_limits_the_scope(cli, home: Path) -> None:
    _, folder = start(cli)
    put(folder / "history/pages/page.0001.html", age_days=60)
    elsewhere = home / "other"
    elsewhere.mkdir()
    done = cli("session", "start", "--project", str(elsewhere))
    other_folder = Path(done.json["folder"])
    put(other_folder / "history/pages/page.0001.html", age_days=60)
    data = cli("cleanup", "--older-than", "30d", "--project", str(elsewhere)).json
    assert len(data["deleted"]) == 1
    assert data["deleted"][0].startswith(str(other_folder))
    assert len(cli("cleanup", "--older-than", "30d").json["deleted"]) == 2


def test_cli_11_session_of_another_project_is_not_found(cli, home: Path) -> None:
    sid, _ = start(cli)
    elsewhere = home / "other"
    elsewhere.mkdir()
    result = cli("cleanup", "--session", sid, "--project", str(elsewhere))
    assert result.code == 5 and result.json["error"] == "no-session"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--older-than", "30d", "--session", "x"],
        ["--older-than", "soon"],
        ["--older-than", "0d"],
        ["--older-than", "-3d"],
    ],
    ids=["neither", "both", "bad-age", "zero-age", "negative-age"],
)
def test_cli_11_usage_errors_exit_2(cli, args: list[str]) -> None:
    result = cli("cleanup", *args)
    assert result.code == 2 and result.json["error"] == "usage"


def test_cli_11_unknown_and_malformed_sessions_exit_5(cli) -> None:
    assert cli("cleanup", "--session", "nope").code == 5
    assert cli("cleanup", "--session", "../x").code == 5


def test_sec_08_cleanup_does_not_follow_a_history_symlink(cli, tmp_path: Path) -> None:
    sid, folder = start_own(cli)
    outside = tmp_path / "outside"
    put(outside / "pages/page.0001.html", age_days=60)
    (folder / "history").symlink_to(outside)
    cli("session", "end", "--session", sid)
    data = cli("cleanup", "--session", sid, "--yes", "--force").json
    assert (outside / "pages/page.0001.html").is_file()
    assert all(not p.startswith(str(outside)) for p in data["deleted"])


def test_ses_10_cleanup_yes_forgets_old_reserved_ids_only(cli, hub) -> None:  # noqa: ANN001
    registry = hub.app.state.registry
    registry.reserve("old-one", str(cli.cwd), "claude-code")
    time.sleep(1.2)
    registry.reserve("new-one", str(cli.cwd), "claude-code")
    assert cli("cleanup", "--older-than", "1s").code == 0  # dry run keeps both
    assert registry.is_reserved("old-one")
    assert cli("cleanup", "--older-than", "1s", "--yes").code == 0
    assert not registry.is_reserved("old-one") and registry.is_reserved("new-one")


# ---- .comments/ and .answers/ (revisions 12 and 13) -------------------------


def put_state(folder: Path) -> list[Path]:
    """Old comment and answer files, as the stores keep them."""
    return [
        put(folder / ".comments/page.html.json", "{}", age_days=60),
        put(folder / ".comments/page.html.1.png", "png", age_days=60),
        put(folder / ".answers/page.html.json", "{}", age_days=60),
    ]


def test_cli_11_older_than_never_touches_comments_or_answers(cli) -> None:
    _, folder = start(cli)
    populate(folder)
    state = put_state(folder)
    data = cli("cleanup", "--older-than", "1d", "--yes").json
    assert all(p.is_file() for p in state)
    assert not any(".comments" in d or ".answers" in d for d in data["deleted"])


def test_cli_11_session_deletes_comments_and_answers_and_lists_them(cli) -> None:
    sid, folder = start_own(cli)
    files = populate(folder)
    state = put_state(folder)
    dry = cli("cleanup", "--session", sid).json
    assert {str(p) for p in state} <= set(dry["deleted"])
    assert all(p.is_file() for p in state)
    done = cli("cleanup", "--session", sid, "--yes", "--force").json
    assert {str(p) for p in state} <= set(done["deleted"])
    assert not any(p.exists() for p in state)
    assert files["page"].is_file()


def test_cli_11_session_does_not_follow_a_comments_or_answers_symlink(
    cli, tmp_path: Path
) -> None:
    sid, folder = start_own(cli)
    outside = tmp_path / "outside"
    keep = [put(outside / "a.json", "{}", age_days=60), put(outside / "b.json")]
    (folder / ".comments").symlink_to(outside)
    (folder / ".answers").symlink_to(outside)
    data = cli("cleanup", "--session", sid, "--yes", "--force").json
    assert all(p.is_file() for p in keep)
    assert all(not d.startswith(str(outside)) for d in data["deleted"])
