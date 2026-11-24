"""Deletion of the data of pages archived 30 days ago (LIFE-08, HIST-04).

Every test works in the folders of the ``hub`` fixture under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import clock
from agent_canvas.hub import purge as purge_module
from agent_canvas.hub.lifetime import DAY_SECONDS

pytestmark = pytest.mark.integration

PAGES = ("one.html", "two.html", "three.html")


@pytest.fixture(autouse=True)
def versions_out_of_reach(monkeypatch) -> None:  # noqa: ANN001
    """Test LIFE-08 alone; old saved versions (HIST-86) have their own tests."""
    monkeypatch.setattr(purge_module, "VERSION_DAYS", 10_000)


def shifted(monkeypatch, days: float) -> None:  # noqa: ANN001
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(days * DAY_SECONDS))


def put(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def hashes(root: Path, skip: tuple[str, ...] = ("session.json",)) -> dict[str, str]:
    """Hash every file below ``root`` (links are not followed) except ``skip``."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink() and p.name not in skip
    }


def act(hub, action: str, name: str) -> httpx.Response:  # noqa: ANN001
    return httpx.post(
        f"{hub.base_url}/api/sessions/a/pages",
        json={"action": action, "name": name},
        headers=hub.key_headers,
    )


def run_purge(hub) -> list[str]:  # noqa: ANN001
    services = hub.app.state.services
    return hub.on_loop(lambda: purge_module.purge(services.registry))


def at(hub, path: str) -> str:  # noqa: ANN001
    """A path as purge names it: under the id of session ``a``'s pool."""
    return f"{hub.app.state.registry.pool_of('a')}/{path}"


def meta(folder: Path) -> dict:
    return json.loads((folder / "session.json").read_text())


def data_of(folder: Path, name: str) -> list[Path]:
    """The hub's data files of page ``name`` (not its page file)."""
    stem = Path(name).stem
    return [
        folder / f"history/pages/{stem}.0001.html",
        folder / f"history/pages/{stem}.0002.html",
        folder / f".comments/{name}.json",
        folder / f".comments/{name}.1.png",
        folder / f".answers/{name}.json",
        folder / f"{stem}.draft.html",
    ]


@pytest.fixture
def folder(hub) -> Path:  # noqa: ANN001
    """Session ``a`` with three shown pages, data for each, events and a send."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    place = Path(answer.json()["folder"])
    for name in PAGES:
        put(place / name, f"<title>{name}</title><p>{name}</p>")
        httpx.post(
            f"{hub.base_url}/api/sessions/a/show",
            json={"name": name, "audit": False},
            headers=hub.key_headers,
            timeout=30,
        )
        for path in data_of(place, name):
            # Versions equal to the page: a late watcher ingest then saves nothing.
            same = path.parent.name == "pages"
            put(path, (place / name).read_text() if same else f"{path.name} of {name}")
    put(place / "events.jsonl", '{"record": "event", "id": "evt_1"}\n')
    put(place / "history/sends/0001.json", '{"event": "evt_1"}')
    put(place / "history/sends/0001.png", "png")
    put(place / "history/sends/0001.c1.png", "picture")
    put(place / "data.csv", "1,2")
    return place


@pytest.fixture
def around(folder: Path) -> Path:
    """A sibling folder of the session and a file one level up, never to change."""
    put(folder.parent / "other-session/history/pages/one.0001.html", "not ours")
    put(folder.parent / "other-session/one.html", "not ours")
    put(folder.parent / "marker.txt", "not ours")
    return folder.parent


def test_life_08_a_page_archived_30_days_ago_loses_its_data_and_nothing_else(
    hub,  # noqa: ANN001
    folder: Path,
    around: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    before = hashes(around)
    gone = [folder / "one.html", *data_of(folder, "one.html")]
    assert all(p.is_file() for p in gone)
    shifted(monkeypatch, 30)
    assert run_purge(hub) == [at(hub, "one.html")]
    assert not any(p.exists() for p in gone)
    after = hashes(around)
    assert set(before) - set(after) == {str(p.relative_to(around)) for p in gone}
    assert {k: v for k, v in before.items() if k in after} == after
    assert meta(folder)["pages"] == ["two.html", "three.html"]
    assert "one.html" not in meta(folder)["page_meta"]


def test_life_08_a_page_archived_29_days_ago_survives(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    before, registry = hashes(folder), meta(folder)
    shifted(monkeypatch, 29.9)
    assert run_purge(hub) == []
    assert hashes(folder) == before and len(before) > 20
    assert meta(folder) == registry


def test_life_08_a_restored_page_is_never_deleted(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    assert act(hub, "restore", "one.html").json()["archived"] is None
    before = hashes(folder)
    shifted(monkeypatch, 400)
    assert run_purge(hub) == []
    assert hashes(folder) == before
    assert "one.html" in meta(folder)["pages"]


def test_hist_04_a_year_ahead_only_pages_archived_30_days_are_gone(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    act(hub, "archive", "three.html")
    act(hub, "restore", "three.html")
    gone = {str(p.relative_to(folder)) for p in data_of(folder, "one.html")}
    gone.add("one.html")
    kept = {k: v for k, v in hashes(folder).items() if k not in gone}
    assert len(kept) > 15 and len(gone) == 7
    shifted(monkeypatch, 365)
    assert run_purge(hub) == [at(hub, "one.html")]
    assert hashes(folder) == kept
    assert meta(folder)["pages"] == ["two.html", "three.html"]


def test_life_08_events_and_send_records_stay_byte_identical(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    for name in PAGES:
        act(hub, "archive", name)
    protected = {
        k: v
        for k, v in hashes(folder).items()
        if k == "events.jsonl" or k.startswith("history/sends/")
    }
    assert len(protected) == 4
    shifted(monkeypatch, 31)
    assert len(run_purge(hub)) == 3
    now = hashes(folder)
    assert {k: now[k] for k in protected} == protected
    assert (folder / "data.csv").read_text() == "1,2"


def test_life_08_nothing_leaves_the_session_folder_through_links_or_names(
    hub,  # noqa: ANN001
    folder: Path,
    around: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    outside = around / "outside"
    put(outside / "one.html.json", "outside comment")
    put(outside / "target.html", "outside page")
    for name in PAGES:
        act(hub, "archive", name)
    (folder / ".comments").rename(folder / ".comments-real")
    (folder / ".comments").symlink_to(outside)
    for page in ("one", "three"):
        text = (folder / f"{page}.html").read_text()
        put(outside / f"linked-history/pages/{page}.0001.html", text)
    (folder / "history").rename(folder / "history-real")
    (folder / "history").symlink_to(outside / "linked-history")
    (folder / "two.html").unlink()
    (folder / "two.html").symlink_to(outside / "target.html")
    registry = meta(folder)
    stamp = registry["page_meta"]["three.html"]["archived"]
    registry["pages"] += ["events.jsonl", "../marker.txt", "session.json"]
    for bad in ("events.jsonl", "../marker.txt", "session.json"):
        registry["page_meta"][bad] = {**registry["page_meta"]["three.html"]}
        registry["page_meta"][bad]["archived"] = stamp
    (folder / "session.json").write_text(json.dumps(registry))
    untouched = {
        k: v
        for k, v in hashes(around, skip=()).items()
        if k.startswith(("outside/", "other-session/", "marker.txt"))
    }
    assert len(untouched) == 7
    shifted(monkeypatch, 31)
    assert sorted(run_purge(hub)) == [
        at(hub, n) for n in ("one.html", "three.html", "two.html")
    ]
    assert {k: hashes(around, skip=()).get(k) for k in untouched} == untouched
    assert (outside / "target.html").read_text() == "outside page"
    assert (outside / "one.html.json").read_text() == "outside comment"
    assert (around / "marker.txt").read_text() == "not ours"
    assert (folder / "events.jsonl").is_file() and (folder / "session.json").is_file()
    assert not (folder / "two.html").is_symlink()


@pytest.mark.parametrize(
    ("reference", "page", "target"),
    [
        ('<img src="one.html">', "ref.html", "one.html"),
        ('<a href="./one.html#top">go</a>', "ref.html", "one.html"),
        ('<object data="one.html?v=2"></object>', "ref.html", "one.html"),
        ("see [it](one.html)", "ref.md", "one.html"),
        ("![it](sub/../one.html)", "ref.md", "one.html"),
        ("[it]: one.html", "ref.md", "one.html"),
        ('<img srcset="one.html 2x">', "ref.html", "one.html"),
        ('<img srcset="small.png 1x, one.html 2x">', "ref.html", "one.html"),
        ('<video poster="one.html"></video>', "ref.html", "one.html"),
        ('<div style="background: url(one.html)">x</div>', "ref.html", "one.html"),
        ("<div style=\"background:url('one.html')\">x</div>", "ref.html", "one.html"),
        ('<style>.a { background: url("one.html") }</style>', "ref.html", "one.html"),
    ],
)
def test_life_08_a_file_another_current_page_refers_to_is_kept_and_logged(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    capsys,  # noqa: ANN001
    reference: str,
    page: str,
    target: str,
) -> None:
    put(folder / page, reference)
    httpx.post(
        f"{hub.base_url}/api/sessions/a/show",
        json={"name": page, "audit": False},
        headers=hub.key_headers,
        timeout=30,
    )
    act(hub, "archive", target)
    shifted(monkeypatch, 31)
    capsys.readouterr()
    assert run_purge(hub) == [at(hub, "one.html")]
    assert (folder / "one.html").read_text() == "<title>one.html</title><p>one.html</p>"
    assert not any(p.exists() for p in data_of(folder, "one.html"))
    assert "one.html" not in meta(folder)["pages"]
    log = capsys.readouterr().err
    assert f"kept {at(hub, 'one.html')} (referenced by {page})" in log


def test_life_08_a_file_only_an_unrelated_reference_names_is_deleted(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    put(
        folder / "ref.html",
        '<a href="https://example.org/one.html">x</a><img src="/one.html">'
        '<a href="../one.html">y</a><a href="two.html.old">z</a>',
    )
    httpx.post(
        f"{hub.base_url}/api/sessions/a/show",
        json={"name": "ref.html", "audit": False},
        headers=hub.key_headers,
        timeout=30,
    )
    act(hub, "archive", "one.html")
    shifted(monkeypatch, 31)
    run_purge(hub)
    assert not (folder / "one.html").exists()


def test_life_08_pages_that_refer_only_to_each_other_are_both_deleted(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    for name, other in (("one.html", "two.html"), ("two.html", "one.html")):
        put(folder / name, f'<a href="{other}">x</a>')
        httpx.post(
            f"{hub.base_url}/api/sessions/a/show",
            json={"name": name, "audit": False},
            headers=hub.key_headers,
            timeout=30,
        )
    act(hub, "archive", "one.html")
    act(hub, "archive", "two.html")
    shifted(monkeypatch, 31)
    assert sorted(run_purge(hub)) == [at(hub, "one.html"), at(hub, "two.html")]
    assert not (folder / "one.html").exists() and not (folder / "two.html").exists()


def test_life_08_each_deletion_is_one_hub_log_line(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    capsys,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    shifted(monkeypatch, 31)
    capsys.readouterr()
    run_purge(hub)
    lines = [
        line
        for line in capsys.readouterr().err.splitlines()
        if "agent-canvas: purge:" in line
    ]
    assert len(lines) == 7
    assert f"agent-canvas: purge: deleted {at(hub, 'one.html')}" in lines
    assert f"agent-canvas: purge: deleted {at(hub, '.answers/one.html.json')}" in lines


def test_life_08_f1_a_page_rewritten_while_the_hub_was_down_is_restored_not_deleted(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    capsys,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    hub.stop()
    (folder / "one.html").write_text("<p>new work</p>")
    shifted(monkeypatch, 31)
    capsys.readouterr()
    hub.restart()
    deadline = time.monotonic() + 10
    while meta(folder)["page_meta"]["one.html"]["archived"] is not None:
        assert time.monotonic() < deadline, "page not restored"
        time.sleep(0.05)
    time.sleep(0.5)
    assert (folder / "one.html").read_text() == "<p>new work</p>"
    assert "one.html" in meta(folder)["pages"]
    assert f"deleted {at(hub, 'one.html')}" not in capsys.readouterr().err


def test_life_08_f1_purge_keeps_and_restores_a_page_changed_since_it_was_archived(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
    capsys,  # noqa: ANN001
) -> None:
    hub.on_loop(lambda: hub.app.state.services.registry.set_hidden("a", True))
    act(hub, "archive", "one.html")
    (folder / "one.html").write_text("<p>written while hidden</p>")
    shifted(monkeypatch, 31)
    capsys.readouterr()
    assert run_purge(hub) == []
    assert (folder / "one.html").read_text() == "<p>written while hidden</p>"
    assert meta(folder)["page_meta"]["one.html"]["archived"] is None
    assert all(p.is_file() for p in data_of(folder, "one.html"))
    log = capsys.readouterr().err
    assert f"purge: kept {at(hub, 'one.html')} (changed since it was archived)" in log


def test_life_08_f1_a_page_with_no_version_is_kept_and_restored(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    for path in (folder / "history/pages").glob("one.*.html"):
        path.unlink()
    shifted(monkeypatch, 31)
    assert run_purge(hub) == []
    assert (folder / "one.html").is_file()
    assert meta(folder)["page_meta"]["one.html"]["archived"] is None


def test_life_08_f1_the_first_purge_comes_after_the_watchers_start_scan(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    from agent_canvas.hub import app as app_module

    seen: list[bool] = []
    real = app_module.purge

    def recording(registry, thumbs=None):  # noqa: ANN001, ANN202
        seen.append((folder / "history/pages/one.0003.html").is_file())
        return real(registry, thumbs)

    act(hub, "archive", "one.html")
    hub.stop()
    (folder / "one.html").write_text("<p>new work</p>")
    monkeypatch.setattr(app_module, "purge", recording)
    hub.restart()
    deadline = time.monotonic() + 10
    while not seen:
        assert time.monotonic() < deadline, "no purge at hub start"
        time.sleep(0.05)
    assert seen[0] is True


def test_life_08_f3_a_purge_run_that_removed_pages_publishes_tabs(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    from agent_canvas.hub import app as app_module

    act(hub, "archive", "one.html")
    shifted(monkeypatch, 31)
    published: list[str] = []
    channel = hub.app.state.services.state.channel
    real = channel.publish
    monkeypatch.setattr(
        channel,
        "publish",
        lambda view, *a, **k: (published.append(view), real(view, *a, **k))[1],
    )
    monkeypatch.setattr(app_module, "PURGE_INTERVAL_SECONDS", 0.2)
    services = hub.app.state.services
    task = hub.on_loop(
        lambda: services.state.loop.create_task(app_module._purge_archived(services))
    )
    try:
        deadline = time.monotonic() + 10
        while "tabs" not in published:
            assert time.monotonic() < deadline, f"no tabs push, got {published}"
            time.sleep(0.05)
    finally:
        hub.on_loop(task.cancel)


def test_life_08_the_hub_purges_at_start(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    act(hub, "archive", "one.html")
    shifted(monkeypatch, 31)
    hub.restart()
    deadline = time.monotonic() + 10
    while (folder / "one.html").exists():
        assert time.monotonic() < deadline, "no purge at hub start"
        time.sleep(0.05)
    assert (folder / "two.html").is_file()


def test_life_08_the_hub_purges_again_every_24_hours(
    hub,  # noqa: ANN001
    folder: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    from agent_canvas.hub import app as app_module

    assert purge_module.PURGE_INTERVAL_SECONDS == 24 * 3600
    monkeypatch.setattr(app_module, "PURGE_INTERVAL_SECONDS", 0.2)
    hub.restart()
    act_after_restart = httpx.post(
        f"{hub.base_url}/api/sessions/a/pages",
        json={"action": "archive", "name": "one.html"},
        headers=hub.key_headers,
    )
    assert act_after_restart.status_code == 200
    shifted(monkeypatch, 31)
    deadline = time.monotonic() + 10
    while (folder / "one.html").exists():
        assert time.monotonic() < deadline, "no second purge"
        time.sleep(0.05)
