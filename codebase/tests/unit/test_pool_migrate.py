"""The migration of old session folders into the pool (POOL-09, #2).

The old session folders are made with the hub's own registry, comment, answer and
page-history code, so the data cannot agree with the migration and disagree with the
hub.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from tests.registry_env import make_env

from agent_canvas.hub import clock, comments, migrate
from agent_canvas.hub.answers import AnswerStore
from agent_canvas.hub.lifetime import DEFAULT_KIND
from agent_canvas.hub.migrate import LOG_NAME, apply_migration, plan_migration
from agent_canvas.hub.registry import _new_entry
from agent_canvas.hub.watcher import PageHistory

pytestmark = pytest.mark.unit

POOL_NAME = "pool-0a1b2c3d"
FILE_TIME = 5_000
ASK = (
    '<canvas-ask data-canvas-id="q1"><script type="application/json">'
    '{"question": "Keep it?", "options": ["keep", "change"]}</script></canvas-ask>'
)
MOVED = {
    ("sess-b", "plan.html"),
    ("sess-a", "ok.html"),
    ("sess-c", "other.html"),
    ("sess-b", "dashboard.html"),
    ("sess-a", "keep.html"),
    ("sess-c", "tie.html"),
    ("sess-a", "arch.html"),
    ("sess-a", "notes.md"),
    ("sess-b", "Report.HTML"),
    ("sess-b", "old.html"),
    ("sess-a", "other-data.html"),
    ("sess-s", "sub.html"),
    ("project", "shared.html"),
}


def stamp(seconds: int) -> str:
    return clock.iso(seconds)


class World:
    """Sessions of one project made through the hub's own code, plus strangers."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.env = make_env(tmp_path, monkeypatch)
        self.root = tmp_path
        self.project = self.env.project
        (self.project / ".git").mkdir()
        self.canvas = self.project / ".agent-canvas"
        self.pool = self.canvas / POOL_NAME
        self.records: dict[str, dict[str, Any]] = {}
        self.build()
        self.pool.mkdir()

    def folder(self, sid: str) -> Path:
        meta = self.env.registry.get(sid)
        assert meta is not None
        return self.env.registry.folder_of(meta)

    def page(  # noqa: PLR0913
        self,
        sid: str,
        name: str,
        html: str,
        *,
        at: int = 100,
        project: Path | None = None,
        versions: tuple[str, ...] = (),
        kind: str | None = None,
        starred: bool = False,
        archived: bool = False,
        mtime: int = FILE_TIME,
    ) -> None:
        registry = self.env.registry
        meta, _ = registry.ensure(sid, str(project or self.project), "claude")
        folder = registry.folder_of(meta)
        (folder / name).write_text(html)
        os.utime(folder / name, (mtime, mtime))
        registry._update(sid, pages=[*meta["pages"], name], active_page=name)
        if kind:
            registry.set_kind(sid, name, kind, "owner")
        if starred:
            registry.set_star(sid, name, True)
        if archived:
            registry.archive(sid, name, "owner")
        path = folder / "session.json"
        document = json.loads(path.read_text())
        entry = document.setdefault("page_meta", {}).setdefault(
            name, _new_entry(DEFAULT_KIND, "default")
        )
        entry["counted_from"] = stamp(at)
        if archived:
            entry["archived"] = stamp(at + 1)
        path.write_text(json.dumps(document))
        history = PageHistory(folder)
        for content in (*versions, html):
            history.save(name, content.encode())

    def comment(self, sid: str, page: str, text: str, send: bool = False) -> None:
        fields = {"kind": "text", "text": text, "anchor": {}, "page_version": 1}
        comments.create(self.folder(sid), page, fields)
        if send:
            comments.take_unsent(self.folder(sid), page, "now", "evt_1", stamp(900))

    def answer(self, sid: str, page: str, value: str) -> None:
        item = self.env.answers.item_of(sid, page, "q1")
        self.env.answers.record(
            sid,
            page,
            item,
            state="answered",
            value=value,
            event="evt_9",
            time=stamp(950),
        )

    def build(self) -> None:
        for sid, at, mtime in (
            ("sess-a", 100, 9_000),
            ("sess-b", 300, 5_000),
            ("sess-c", 200, 5_000),
        ):
            who = sid[-1]
            self.page(
                sid,
                "plan.html",
                f"<html>plan by {who} {ASK}</html>",
                at=at,
                mtime=mtime,
                versions=(f"<html>old plan {who}</html>",),
            )
            self.comment(sid, "plan.html", f"comment of {who}", send=True)
        self.answer("sess-b", "plan.html", "keep")
        self.page("sess-a", "ok.html", '<html><script src="chart.js"></script></html>')
        self.comment("sess-a", "ok.html", "first", send=True)
        self.comment("sess-a", "ok.html", "second")
        (self.folder("sess-a") / "chart.js").write_text("var chart = 1;\n")
        (self.folder("sess-a") / ".comments" / "ok.html.1.png").write_bytes(
            b"\x89PNG-1"
        )
        self.page("sess-a", "clash.html", '<html>reads "data.json"</html>')
        self.page("sess-a", "aaa-notes.html", "<html>see data.json for it</html>")
        self.page(
            "sess-a", "keep.html", "<html>keep</html>", kind="long-term", starred=True
        )
        self.page("sess-a", "tie.html", "<html>tie a</html>", at=500)
        self.page("sess-a", "arch.html", "<html>arch a</html>", at=100)
        self.page("sess-a", "notes.md", "# notes two\n", versions=("# notes one\n",))
        self.page("sess-a", "other-data.html", "<html>mentions data.js only</html>")
        (self.folder("sess-a") / "data.json").write_text('{"from": "a"}\n')
        (self.folder("sess-a") / "mydata.js").write_text("not named\n")
        self.page("sess-b", "dashboard.html", '<html>fetch("data.json")</html>', at=300)
        (self.folder("sess-b") / "data.json").write_text('{"from": "b"}\n')
        self.page(
            "sess-b",
            "Report.HTML",
            "<html>report two</html>",
            versions=("<html>report one</html>",),
        )
        self.page(
            "sess-b", "old.html", "<html>old</html>", archived=True, kind="long-term"
        )
        self.page(
            "sess-c", "dashboard.html", '<html>fetch("data.json") c</html>', at=200
        )
        (self.folder("sess-c") / "data.json").write_text('{"from": "c"}\n')
        self.page("sess-c", "other.html", "<html>other</html>")
        self.page("sess-c", "tie.html", "<html>tie c</html>", at=500)
        self.page("sess-c", "arch.html", "<html>arch c</html>", at=200, archived=True)
        (self.folder("sess-c") / "tie.draft.html").write_text("<html>draft</html>")
        other = self.root / "home" / "other"
        (other / ".git").mkdir(parents=True)
        self.page("sess-x", "foreign.html", "<html>other project</html>", project=other)
        sub = self.project / "sub"
        sub.mkdir()
        self.page("sess-s", "sub.html", "<html>from a sub-folder</html>", project=sub)
        (sub / ".agent-canvas" / "lost-s").mkdir()
        (sub / ".agent-canvas" / "lost-s" / "lost.html").write_text("<html>lost</html>")
        lost = self.canvas / "unknown-sess"
        lost.mkdir()
        (lost / "lost.html").write_text("<html>from another machine</html>")
        (self.canvas / "pool-ffffffff").mkdir()
        (self.canvas / "pool-ffffffff" / "page.html").write_text("<html>theirs</html>")
        legacy = self.canvas / "project"
        (legacy / ".comments").mkdir(parents=True)
        (legacy / "shared.html").write_text("<html>shared page</html>")
        fields = {"kind": "text", "text": "shared", "anchor": {}, "page_version": 1}
        comments.create(legacy, "shared.html", fields)

    def known(self) -> dict[str, dict[str, Any]]:
        registry = self.env.registry
        return {
            m["id"]: {
                "folder": registry.folder_of(m),
                "project": m["project"],
                "title": m.get("title"),
                "agent": m["agent"],
            }
            for m in registry.list(True, None)
        }

    def plan(self) -> dict[str, Any]:
        return plan_migration(
            self.known(), self.pool, str(self.project), recorded=set(self.records)
        )

    def write_record(self, name: str, record: dict[str, Any]) -> None:
        self.records[name] = record

    def run(self) -> dict[str, Any]:
        return apply_migration(self.plan(), self.pool, self.write_record)

    def log(self) -> dict[str, Any]:
        return json.loads((self.pool / LOG_NAME).read_text())

    def old_hash(self) -> str:
        return tree_hash(self.root, skip=self.pool)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def tree_hash(root: Path, skip: Path | None = None) -> str:
    """Hash every name and content below ``root``, folders included."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if skip and (path == skip or skip in path.parents):
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        if path.is_file() and not path.is_symlink():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def sources(world: World) -> dict[tuple[str, str], Path]:
    folders = {
        sid: world.folder(sid) for sid in ("sess-a", "sess-b", "sess-c", "sess-s")
    }
    folders["project"] = world.canvas / "project"
    return {key: folders[key[0]] for key in MOVED}


def comment_count(folder: Path, page: str) -> int:
    return len(comments.load(folder, page)["comments"])


def answer_count(folder: Path, page: str) -> int:
    path = folder / ".answers" / f"{page}.json"
    return len(json.loads(path.read_text())["items"]) if path.exists() else 0


def moved_pairs(plan: dict[str, Any]) -> set[tuple[str, str]]:
    return {(m["session"], m["page"]) for m in plan["moves"]}


def test_pool_09_known_sessions_pages_move_with_comments_answers_and_versions(
    world: World,
) -> None:
    world.run()
    pairs = sources(world)
    counts = {
        "comments": lambda f, p: (
            comment_count(f, p) if (f / ".comments" / f"{p}.json").exists() else 0
        ),
        "answers": answer_count,
        "versions": lambda f, p: len(PageHistory(f).versions(p)),
    }
    for label, count in counts.items():
        expected = sum(count(folder, page) for (_, page), folder in pairs.items())
        found = sum(count(world.pool, page) for _, page in pairs)
        assert expected > 0, label
        assert found == expected, label
    assert moved_pairs(world.plan()) == set()
    assert set(world.records) == {page for _, page in MOVED}
    assert (world.pool / ".comments" / "ok.html.1.png").read_bytes() == b"\x89PNG-1"


def test_pool_09_the_hub_reads_the_migrated_data_back(world: World) -> None:
    world.run()
    document = comments.load(world.pool, "ok.html")
    rows = comments.with_status(document)
    assert [r["text"] for r in rows] == ["first", "second"]
    assert [r["status"] for r in rows] == ["sent", "draft"]
    assert {r["card"] for r in rows} == {"sess-a"}
    assert comments.unsent(world.pool, "sess-a")["comments"] == 1
    latest = PageHistory(world.pool).latest("plan.html")
    assert latest is not None
    assert latest[1] == (world.folder("sess-b") / "plan.html").read_bytes()
    store = AnswerStore(
        lambda sid: world.pool, lambda sid: ["plan.html"], lambda *a: None
    )
    assert store.entries("pool", "plan.html")["q1"]["value"] == "keep"
    assert comments.load(world.pool, "plan.html")["comments"][0]["card"] == "sess-b"


def test_pool_09_the_newest_same_name_copy_takes_the_name_and_older_ones_are_logged_in_place(  # noqa: E501
    world: World,
) -> None:
    world.run()
    # sess-a's plan.html has the newest file time but the oldest recorded time.
    assert (world.pool / "plan.html").read_bytes() == (
        world.folder("sess-b") / "plan.html"
    ).read_bytes()
    assert world.records["plan.html"]["created_by"]["session"] == "sess-b"
    assert [c["text"] for c in comments.load(world.pool, "plan.html")["comments"]] == [
        "comment of b"
    ]
    older = {(o["page"], o["session"], o["kept_in"]) for o in world.log()["older"]}
    assert (
        "plan.html",
        "sess-a",
        str(world.folder("sess-a").relative_to(world.project)),
    ) in older
    assert (
        "plan.html",
        "sess-c",
        str(world.folder("sess-c").relative_to(world.project)),
    ) in older
    assert (world.folder("sess-a") / "plan.html").exists()


def test_pool_09_a_tie_in_time_goes_to_the_higher_session_id(world: World) -> None:
    world.run()
    assert (world.pool / "tie.html").read_text() == "<html>tie c</html>"
    assert world.records["tie.html"]["created_by"]["session"] == "sess-c"
    assert [
        (o["page"], o["session"])
        for o in world.log()["older"]
        if o["page"] == "tie.html"
    ] == [("tie.html", "sess-a")]


def test_pool_09_an_archived_newest_copy_never_takes_the_name_from_a_live_one(
    world: World,
) -> None:
    world.run()
    assert (world.pool / "arch.html").read_text() == "<html>arch a</html>"
    assert world.records["arch.html"]["archived"] is None
    assert world.records["arch.html"]["created_by"]["session"] == "sess-a"


def test_pool_09_page_settings_travel_with_the_page(world: World) -> None:
    world.run()
    keep = world.records["keep.html"]
    assert (keep["kind"], keep["set_by"], keep["starred"]) == (
        "long-term",
        "owner",
        True,
    )
    assert world.records["old.html"]["archived"] == stamp(101)
    assert world.records["old.html"]["kind"] == "long-term"
    # The registry lays each record over a fresh entry (test_pool_wiring.py).
    for record in world.records.values():
        assert {"created_by", "updated_by", "digest", "sessions"} <= set(record)
    assert world.records["plan.html"]["counted_from"] == stamp(300)


def test_pool_09_markdown_and_upper_case_pages_move_with_their_versions(
    world: World,
) -> None:
    world.run()
    for page, expected in (("notes.md", 2), ("Report.HTML", 2)):
        history = PageHistory(world.pool)
        assert len(history.versions(page)) == expected
        latest = history.latest(page)
        assert latest is not None
        assert (
            latest[1]
            == (
                world.folder("sess-a" if page == "notes.md" else "sess-b") / page
            ).read_bytes()
        )
    assert (world.pool / "history" / "pages" / "Report.0001.html").exists()


def test_pool_09_a_page_naming_a_clashing_file_stays_and_is_logged(
    world: World,
) -> None:
    world.run()
    stayed = {(c["page"], c["session"], c["file"]) for c in world.log()["clashes"]}
    assert stayed == {
        ("clash.html", "sess-a", "data.json"),
        ("aaa-notes.html", "sess-a", "data.json"),
    }
    assert not (world.pool / "clash.html").exists()
    assert not (world.pool / ".comments" / "clash.html.json").exists()
    assert (world.pool / "ok.html").exists()
    assert (world.pool / "chart.js").read_text() == "var chart = 1;\n"


def test_pool_09_the_newest_page_wins_its_data_file(world: World) -> None:
    world.run()
    assert (
        world.pool / "dashboard.html"
    ).read_text() == '<html>fetch("data.json")</html>'
    assert (world.pool / "data.json").read_text() == '{"from": "b"}\n'
    assert ("dashboard.html", "sess-c") in {
        (o["page"], o["session"]) for o in world.log()["older"]
    }


def test_pool_09_a_file_name_matches_only_at_a_word_boundary(world: World) -> None:
    world.run()
    assert not (world.pool / "mydata.js").exists()
    assert (world.pool / "other-data.html").exists()


def test_pool_09_a_page_naming_a_file_the_pool_holds_differently_stays(
    world: World,
) -> None:
    (world.pool / "chart.js").write_text("the pool's chart\n")
    world.run()
    assert not (world.pool / "ok.html").exists()
    assert (world.pool / "chart.js").read_text() == "the pool's chart\n"
    assert ("ok.html", "chart.js") in {
        (c["page"], c["file"]) for c in world.log()["clashes"]
    }
    assert (world.pool / "keep.html").exists()


def test_pool_09_folders_of_unknown_sessions_are_left_alone_and_listed(
    world: World,
) -> None:
    world.run()
    assert world.log()["unknown"] == [
        ".agent-canvas/unknown-sess",
        "sub/.agent-canvas/lost-s",
    ]
    assert not (world.pool / "lost.html").exists()
    assert (world.pool / "ok.html").exists()


def test_pool_09_only_sessions_of_this_project_are_taken_in(world: World) -> None:
    world.run()
    assert not (world.pool / "foreign.html").exists()
    assert "foreign.html" not in world.records
    assert moved_pairs(world.plan()) == set()
    assert "sess-x" not in json.dumps(world.log())


def test_pool_09_a_session_started_in_a_sub_folder_is_taken_in_from_its_own_folder(
    world: World,
) -> None:
    assert world.folder("sess-s").parent.parent == world.project / "sub"
    world.run()
    assert (world.pool / "sub.html").read_text() == "<html>from a sub-folder</html>"
    assert world.records["sub.html"]["created_by"]["session"] == "sess-s"


def test_pool_09_other_hubs_pools_are_not_sessions_and_the_old_project_folder_is(
    world: World,
) -> None:
    world.run()
    assert not (world.pool / "page.html").exists()
    assert "pool-ffffffff" not in json.dumps(world.log())
    assert (world.pool / "shared.html").exists()
    assert world.records["shared.html"]["created_by"]["session"] == "project"
    rows = comments.load(world.pool, "shared.html")["comments"]
    assert [c["card"] for c in rows] == ["project"]


def test_pool_09_old_folders_keep_their_tree_hash(world: World) -> None:
    before = world.old_hash()
    pool_before = tree_hash(world.pool)
    world.run()
    assert tree_hash(world.pool) != pool_before
    assert world.old_hash() == before


def test_pool_09_a_second_run_changes_nothing(world: World) -> None:
    empty = tree_hash(world.pool)
    world.run()
    first = tree_hash(world.pool)
    assert first != empty
    assert world.records
    world.records.clear()
    assert moved_pairs(world.plan()) == set()
    world.run()
    assert tree_hash(world.pool) == first
    assert world.records == {}


def whole_run(world: World) -> tuple[str, dict[str, dict[str, Any]]]:
    """Run once, keep the pool's hash and records, and empty the pool again."""
    world.run()
    kept = tree_hash(world.pool), dict(world.records)
    shutil.rmtree(world.pool)
    world.pool.mkdir()
    world.records.clear()
    return kept


def test_pool_09_a_rerun_after_a_stop_half_way_gives_the_same_pool(
    world: World,
) -> None:
    whole, whole_records = whole_run(world)
    calls = []

    def stop_at_second(name: str, record: dict[str, Any]) -> None:
        calls.append(name)
        if len(calls) == 2:
            raise KeyboardInterrupt
        world.write_record(name, record)

    with pytest.raises(KeyboardInterrupt):
        apply_migration(world.plan(), world.pool, stop_at_second)
    assert len(world.log()["moved"]) == 1
    assert tree_hash(world.pool) != whole
    world.run()
    assert tree_hash(world.pool) == whole
    assert world.records == whole_records


def test_pool_09_a_rerun_after_a_stop_in_the_middle_of_a_pages_files_is_the_same(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    whole, whole_records = whole_run(world)
    real = migrate.write_safely
    count = []

    def stop_at_fifth(path: Path, content: Any, *args: Any, **kwargs: Any) -> None:
        count.append(path)
        if len(count) == 5:
            raise KeyboardInterrupt
        real(path, content, *args, **kwargs)

    monkeypatch.setattr(migrate, "write_safely", stop_at_fifth)
    with pytest.raises(KeyboardInterrupt):
        world.run()
    monkeypatch.setattr(migrate, "write_safely", real)
    assert tree_hash(world.pool) != whole
    assert world.records != whole_records
    world.run()
    assert tree_hash(world.pool) == whole
    assert world.records == whole_records


def test_pool_09_the_dry_run_writes_nothing_and_lists_the_pages(world: World) -> None:
    before = tree_hash(world.root)
    plan = world.plan()
    assert moved_pairs(plan) == MOVED
    assert {c["page"] for c in plan["clashes"]} == {"clash.html", "aaa-notes.html"}
    assert len(plan["unknown"]) == 2
    assert tree_hash(world.root) == before
    assert not (world.pool / LOG_NAME).exists()


def test_pool_09_a_pool_file_changed_between_plan_and_apply_is_never_overwritten(
    world: World,
) -> None:
    plan = world.plan()
    (world.pool / "chart.js").write_text("an agent wrote this\n")
    (world.pool / "keep.html").write_text("an agent's page\n")
    result = apply_migration(plan, world.pool, world.write_record)
    assert (world.pool / "chart.js").read_text() == "an agent wrote this\n"
    assert (world.pool / "keep.html").read_text() == "an agent's page\n"
    assert not (world.pool / "ok.html").exists()
    assert {"ok.html", "keep.html"} <= {c["page"] for c in result["clashes"]}
    assert "ok.html" not in world.records
    assert (world.pool / "plan.html").exists()


def test_pool_09_a_rerun_after_an_agent_changed_a_pool_page_never_overwrites_it(
    world: World,
) -> None:
    world.run()
    (world.pool / "plan.html").write_text("an agent's newer plan\n")
    world.run()
    (world.pool / LOG_NAME).unlink()
    world.run()
    assert (world.pool / "plan.html").read_text() == "an agent's newer plan\n"


def test_pool_09_a_damaged_log_is_set_aside_and_the_run_stops_cleanly(
    world: World,
) -> None:
    world.run()
    calls = len(world.records)
    (world.pool / LOG_NAME).write_text("{ damaged")
    assert world.plan()["stopped"]
    result = apply_migration(world.plan(), world.pool, world.write_record)
    assert result["stopped"]
    assert (world.pool / (LOG_NAME + ".bad")).read_text() == "{ damaged"
    assert not (world.pool / LOG_NAME).exists()
    again = world.run()
    assert not again.get("stopped")
    assert len(world.records) == calls
    assert (world.pool / "plan.html").read_bytes() == (
        world.folder("sess-b") / "plan.html"
    ).read_bytes()


def test_pool_09_a_lost_log_does_not_record_a_pool_page_again(world: World) -> None:
    world.run()
    (world.pool / LOG_NAME).unlink()
    seen = []
    plan = world.plan()
    apply_migration(plan, world.pool, lambda name, record: seen.append(name))
    assert seen == []


def test_pool_09_a_malformed_comments_file_skips_that_page_only(world: World) -> None:
    (world.folder("sess-a") / ".comments" / "ok.html.json").write_text("{not json")
    world.run()
    assert not (world.pool / "ok.html").exists()
    skipped = {(s["session"], s["file"]) for s in world.log()["skipped"]}
    assert ("sess-a", "ok.html") in skipped
    assert (world.pool / "keep.html").exists()
    assert (world.pool / "plan.html").exists()


def test_pool_09_a_page_skipped_in_planning_is_listed_as_left_behind(
    world: World,
) -> None:
    (world.folder("sess-a") / ".comments" / "ok.html.json").write_text("{not json")
    world.run()
    rows = migrate.left_behind(world.pool, str(world.project))
    mine = [r for r in rows if r["why"] == "skipped" and r["page"] == "ok.html"]
    assert mine == [
        {
            "page": "ok.html",
            "session": "sess-a",
            "why": "skipped",
            "folder": str(world.folder("sess-a")),
        }
    ]
    assert (world.pool / "keep.html").exists()  # positive control: a healthy page moved
    assert "keep.html" not in {r["page"] for r in rows}


def test_pool_09_drafts_are_logged_as_left_behind(world: World) -> None:
    world.run()
    left = {(s["session"], s["file"]) for s in world.log()["skipped"]}
    assert ("sess-c", "tie.draft.html") in left
    assert not (world.pool / "tie.draft.html").exists()


def test_pool_09_links_are_not_followed_and_a_linked_pool_is_refused(
    world: World,
) -> None:
    secret = world.root / "secret.txt"
    secret.write_text("private\n")
    folder = world.folder("sess-b")
    (folder / "secret.txt").symlink_to(secret)
    (folder / "dashboard.html").write_text('<html>fetch("data.json") secret.txt</html>')
    world.run()
    assert not (world.pool / "secret.txt").exists()
    assert (world.pool / "dashboard.html").exists()
    moved = world.root / "moved-pool"
    world.pool.rename(moved)
    world.pool.symlink_to(moved)
    assert world.plan()["stopped"]


def test_pool_09_files_get_the_dates_of_their_sources(world: World) -> None:
    world.run()
    page = world.folder("sess-b") / "plan.html"
    assert (world.pool / "plan.html").stat().st_mtime_ns == page.stat().st_mtime_ns
    version = PageHistory(world.folder("sess-b")).path("plan.html", 1)
    target = world.pool / version.relative_to(world.folder("sess-b"))
    assert target.stat().st_mtime_ns == version.stat().st_mtime_ns


def test_pool_09_the_records_digest_is_that_of_the_copied_bytes(world: World) -> None:
    plan = world.plan()
    page = world.folder("sess-b") / "plan.html"
    page.write_text("<html>changed after the plan</html>")
    apply_migration(plan, world.pool, world.write_record)
    digest = hashlib.sha256((world.pool / "plan.html").read_bytes()).hexdigest()
    assert world.records["plan.html"]["digest"] == digest
    assert world.records["plan.html"]["sessions"]["sess-b"]["digest"] == digest


def test_pool_09_only_the_top_level_history_folder_is_skipped(world: World) -> None:
    folder = world.folder("sess-b")
    (folder / "data").mkdir()
    (folder / "data" / "history").mkdir()
    (folder / "data" / "history" / "log.csv").write_text("1,2\n")
    (folder / "dashboard.html").write_text(
        '<html>fetch("data.json") data/history/log.csv</html>'
    )
    world.run()
    assert (world.pool / "data" / "history" / "log.csv").read_text() == "1,2\n"


def test_pool_09_a_pool_file_made_while_the_page_is_copied_is_never_replaced(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = migrate.write_safely

    def racing(path: Path, content: bytes, **kwargs: Any) -> None:
        if path == world.pool / "keep.html":
            path.write_text("an agent's page\n")  # after every check, before the write
        real(path, content, **kwargs)

    monkeypatch.setattr(migrate, "write_safely", racing)
    world.run()
    assert (world.pool / "keep.html").read_text() == "an agent's page\n"
    assert "keep.html" in {c["page"] for c in world.log()["clashes"]}
    assert "keep.html" not in world.records


def test_pool_09_a_linked_folder_in_the_pool_never_leads_a_copy_outside(
    world: World,
) -> None:
    outside = world.root / "elsewhere"
    outside.mkdir()
    (world.pool / ".comments").symlink_to(outside)
    world.run()
    assert list(outside.rglob("*")) == []
    skipped = {(s["session"], s["file"]) for s in world.log()["skipped"]}
    assert {("sess-b", "plan.html"), ("sess-a", "ok.html")} <= skipped
    assert (world.pool / "keep.html").exists()  # positive control: it has no comments


def test_pool_09_a_file_the_pool_holds_already_keeps_its_dates(world: World) -> None:
    held = world.pool / "chart.js"
    held.write_text("var chart = 1;\n")
    os.utime(held, (1234, 1234))
    world.run()
    assert (world.pool / "ok.html").exists()
    assert held.stat().st_mtime == 1234


def test_pool_09_an_unreadable_folder_beside_the_sessions_is_logged_not_fatal(
    world: World,
) -> None:
    canvas = world.project / "sub" / ".agent-canvas"
    canvas.chmod(0o300)  # entered, not listed
    try:
        world.run()
    finally:
        canvas.chmod(0o700)
    assert world.log()["unknown"] == [".agent-canvas/unknown-sess"]
    assert "sub/.agent-canvas" in {s["file"] for s in world.log()["skipped"]}
    assert (world.pool / "sub.html").exists()


def test_pool_09_two_pages_with_one_name_without_extension_never_both_enter(
    world: World,
) -> None:
    world.page("sess-a", "x.html", "<html>x first</html>", at=100)
    world.page("sess-c", "x.md", "# x later\n", at=400)
    (world.pool / "z.html").write_text("<html>the pool's z</html>")
    world.page("sess-b", "z.md", "# z\n", at=400)
    world.run()
    assert (world.pool / "x.html").exists()
    assert not (world.pool / "x.md").exists()
    assert not (world.pool / "z.md").exists()
    clashes = {(c["page"], c["session"], c["file"]) for c in world.log()["clashes"]}
    assert {("x.md", "sess-c", "x.html"), ("z.md", "sess-b", "z.html")} <= clashes
