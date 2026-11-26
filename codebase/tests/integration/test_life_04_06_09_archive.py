"""Archive, restore, extend, list and the snapshot page fields (LIFE-04, 05, 06, 09)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import clock
from agent_canvas.hub.lifetime import DAY_SECONDS

pytestmark = pytest.mark.integration

ALL = ["one.html", "two.html", "three.html"]


def show(hub, name: str, **body):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/a/show",
        json={"name": name, "audit": False, **body},
        headers=hub.key_headers,
        timeout=30,
    )


@pytest.fixture
def folder(hub) -> Path:  # noqa: ANN001
    """Create session ``a`` with the pages one, two and three, shown in that order."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    place = Path(answer.json()["folder"])
    for name in ALL:
        (place / name).write_text(f"<title>{name}</title><p>{name}</p>")
        show(hub, name)
    return place


def act(hub, action: str, name: str | None = "one.html", **body):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/a/pages",
        json={"action": action, "name": name, **body},
        headers=hub.key_headers,
    )


def listing(hub, archived: bool = False) -> list[dict]:  # noqa: ANN001
    answer = httpx.get(
        f"{hub.base_url}/api/sessions/a/pages",
        params={"archived": "1"} if archived else {},
        headers=hub.key_headers,
    )
    return answer.json()["pages"]


def expiry_of(hub, name: str, **query) -> dict:  # noqa: ANN001, ANN003
    return next(p for p in listing(hub, **query) if p["name"] == name)


def meta(folder: Path) -> dict:
    return json.loads((folder / "session.json").read_text())


def tab(hub) -> dict:  # noqa: ANN001
    return hub.on_loop(lambda: hub.app.state.services.registry.tabs())[0]


def home_session(hub) -> dict:  # noqa: ANN001
    registry = hub.app.state.services.registry
    return {"pages": hub.on_loop(lambda: registry.page_list("a", False))}


def disk_hashes(folder: Path) -> dict[str, str]:
    """Hash every file of the session folder except ``session.json`` (the registry)."""
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "session.json"
    }


def shifted(monkeypatch, days: float) -> None:  # noqa: ANN001
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(days * DAY_SECONDS))


def test_life_04_archive_and_restore_leave_every_file_byte_identical(
    hub,
    folder,  # noqa: ANN001
) -> None:
    mtimes = {p: p.stat().st_mtime_ns for p in folder.glob("*.html")}
    before = disk_hashes(folder)
    assert len(before) >= 3  # the compare below is not vacuous
    pages = meta(folder)["pages"]
    assert act(hub, "archive", "three.html").status_code == 200
    assert act(hub, "archive", "one.html").status_code == 200
    assert disk_hashes(folder) == before
    assert act(hub, "restore", "one.html").status_code == 200
    assert act(hub, "restore", "three.html").status_code == 200
    assert disk_hashes(folder) == before
    assert {p: p.stat().st_mtime_ns for p in folder.glob("*.html")} == mtimes
    assert meta(folder)["pages"] == pages  # the registry keeps archived pages


def test_life_04_an_archived_page_leaves_the_tab_and_the_snapshot(hub, folder) -> None:  # noqa: ANN001
    answer = act(hub, "archive", "two.html").json()
    assert answer["page"] == "two.html" and answer["archived"]
    gap = clock.seconds_of(answer["deleted_after"]) - clock.seconds_of(
        answer["archived"]
    )
    assert gap == 30 * DAY_SECONDS
    assert tab(hub)["pages"] == ["one.html", "three.html"]
    assert [p["name"] for p in home_session(hub)["pages"]] == ["one.html", "three.html"]
    assert meta(folder)["page_meta"]["two.html"]["archived"] == answer["archived"]


def test_life_04_archiving_the_active_page_makes_the_newest_other_page_active(
    hub,
    folder,  # noqa: ANN001
) -> None:
    assert tab(hub)["active_page"] == "three.html"
    act(hub, "archive", "three.html")
    assert tab(hub)["active_page"] == "two.html"
    act(hub, "archive", "one.html")  # not active: the active page stays
    assert tab(hub)["active_page"] == "two.html"


def test_life_04_with_no_page_left_the_tab_has_none_active(hub, folder) -> None:  # noqa: ANN001
    for name in ("three.html", "two.html", "one.html"):
        act(hub, "archive", name)
    shown = tab(hub)
    assert shown["pages"] == [] and shown["active_page"] is None
    assert home_session(hub)["pages"] == []
    act(hub, "restore", "two.html")
    assert tab(hub)["active_page"] == "two.html"


def test_life_04_show_restores_an_archived_page_and_makes_it_active(
    hub, folder
) -> None:  # noqa: ANN001
    act(hub, "archive", "one.html")
    assert show(hub, "one.html").status_code == 200
    assert meta(folder)["page_meta"]["one.html"]["archived"] is None
    assert tab(hub)["pages"] == ALL
    assert tab(hub)["active_page"] == "one.html"


def test_life_04_a_new_version_restores_an_archived_page(hub, folder) -> None:  # noqa: ANN001
    act(hub, "archive", "one.html")
    (folder / "one.html").write_text("<p>new version</p>")
    hub.wait_for(lambda: meta(folder)["page_meta"]["one.html"]["archived"] is None)
    assert "one.html" in tab(hub)["pages"]
    assert tab(hub)["active_page"] == "three.html"  # restored quietly, not shown


def test_life_04_an_unchanged_archived_page_stays_archived(hub, folder) -> None:  # noqa: ANN001
    act(hub, "archive", "one.html")
    (folder / "two.html").write_text("<p>other page changed</p>")
    second = folder / "history" / "pages" / "two.0002.html"
    hub.wait_for(lambda: second.exists())
    assert meta(folder)["page_meta"]["one.html"]["archived"] is not None


def test_life_04_archiving_twice_keeps_the_first_time(hub, folder) -> None:  # noqa: ANN001
    first = act(hub, "archive", "one.html").json()["archived"]
    assert act(hub, "archive", "one.html").json()["archived"] == first
    assert act(hub, "restore", "one.html").json()["archived"] is None
    assert act(hub, "restore", "one.html").json()["archived"] is None


def test_life_04_unknown_page_action_and_missing_name_are_refused(hub, folder) -> None:  # noqa: ANN001
    assert act(hub, "archive", "nope.html").json()["error"] == "failed"
    assert act(hub, "archive", None).json()["error"] == "usage"
    assert act(hub, "delete").json()["error"] == "usage"


def test_life_04_only_an_agent_may_archive(hub, folder) -> None:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/pages",
        json={"action": "archive", "name": "one.html"},
    )
    assert answer.status_code in (401, 403)
    assert meta(folder)["page_meta"]["one.html"]["archived"] is None


def test_life_05_extend_restarts_the_lifetime(hub, folder, monkeypatch) -> None:  # noqa: ANN001
    old = clock.now() - 25 * DAY_SECONDS
    os.utime(folder / "one.html", (old, old))
    entry = meta(folder)["page_meta"]["one.html"]
    entry["counted_from"] = clock.iso(old)
    (folder / "session.json").write_text(
        json.dumps(
            {
                **meta(folder),
                "page_meta": {**meta(folder)["page_meta"], "one.html": entry},
            }
        )
    )
    soon = clock.seconds_of(expiry_of(hub, "one.html")["expires"])
    assert soon < clock.now() + 6 * DAY_SECONDS
    done = act(hub, "extend", "one.html").json()
    assert done["page"] == "one.html"
    assert clock.seconds_of(done["expires"]) > clock.now() + 29 * DAY_SECONDS
    assert meta(folder)["page_meta"]["one.html"]["extended"]
    shifted(monkeypatch, 10)
    assert not expiry_of(hub, "one.html")["expired"]


def test_life_05_extend_of_a_long_term_page_answers_null(hub, folder) -> None:  # noqa: ANN001
    act(hub, "kind", "one.html", kind="long-term")
    assert act(hub, "extend", "one.html").json()["expires"] is None


def test_life_05_list_shows_live_pages_and_with_archived_the_archived_too(
    hub,
    folder,  # noqa: ANN001
) -> None:
    act(hub, "kind", "one.html", kind="single-use")
    act(hub, "archive", "two.html")
    live = listing(hub)
    assert [p["name"] for p in live] == ["one.html", "three.html"]
    assert set(live[0]) == {
        "name",
        "kind",
        "set_by",
        "expires",
        "expired",
        "archived",
        "starred",
        "pinned",  # a pool's page can be pinned (POOL-04)
        "updated_by",  # and names the session that changed it last (POOL-06)
    }
    assert (live[0]["kind"], live[0]["set_by"]) == ("single-use", "agent")
    assert live[0]["archived"] is None and live[0]["expired"] is False
    every = listing(hub, archived=True)
    assert [p["name"] for p in every] == ALL
    assert every[1]["archived"] == meta(folder)["page_meta"]["two.html"]["archived"]


def test_life_06_an_expired_page_is_never_archived_or_removed(
    hub,
    folder,
    monkeypatch,  # noqa: ANN001
) -> None:
    before = disk_hashes(folder)
    shifted(monkeypatch, 400)
    registry = hub.app.state.services.registry
    hub.on_loop(lambda: registry.note_pages("a"))
    (folder / "two.html").write_text(
        "<p>changed</p>"
    )  # a watcher pass at the shifted clock
    hub.wait_for(lambda: (folder / "history" / "pages" / "two.0002.html").exists())
    every = listing(hub, archived=True)
    assert [p["name"] for p in every] == ALL
    assert all(p["expired"] for p in every)
    assert all(e["archived"] is None for e in meta(folder)["page_meta"].values())
    assert tab(hub)["pages"] == ALL
    assert set(before) - {"two.html"} <= set(disk_hashes(folder))


def test_life_09_the_snapshot_pages_carry_kind_expiry_and_expired(hub, folder) -> None:  # noqa: ANN001
    act(hub, "kind", "two.html", kind="long-term")
    pages = {p["name"]: p for p in home_session(hub)["pages"]}
    two, one = pages["two.html"], pages["one.html"]
    assert (two["kind"], two["set_by"]) == ("long-term", "agent")
    assert two["expires"] is None and two["expired"] is False
    assert (one["kind"], one["set_by"]) == ("transitional", "default")
    assert clock.seconds_of(one["expires"]) > clock.now() + 29 * DAY_SECONDS


def test_life_09_the_snapshot_marks_an_expired_page_and_never_writes_the_registry(
    hub,
    folder,
    monkeypatch,  # noqa: ANN001
) -> None:
    shifted(monkeypatch, 31)
    registry_bytes = (folder / "session.json").read_bytes()
    pages = home_session(hub)["pages"]
    assert len(pages) == 3 and all(p["expired"] for p in pages)
    assert (folder / "session.json").read_bytes() == registry_bytes


def test_life_04_05_the_cli_archives_restores_extends_and_lists(cli, hub) -> None:  # noqa: ANN001
    session = cli("session", "start").json["session"]
    place = Path(cli("session", "path", "--session", session).json["folder"])
    at = ("--session", session)
    for name in ("x.html", "y.html"):
        (place / name).write_text("<p>x</p>")
        cli("show", name, "--no-audit", *at)
    done = cli("page", "archive", "x.html", *at)
    assert done.code == 0 and done.json["archived"] and done.json["deleted_after"]
    assert [p["name"] for p in cli("page", "list", *at).json["pages"]] == ["y.html"]
    listed = cli("page", "list", "--archived", *at).json["pages"]
    assert [p["name"] for p in listed] == ["x.html", "y.html"]
    assert cli("page", "extend", "y.html", *at).json["expires"]
    assert cli("page", "restore", "x.html", *at).json["archived"] is None
    assert cli("page", "archive", "nope.html", *at).code != 0
