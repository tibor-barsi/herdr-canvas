"""Page kinds, the first-seen clock start and the test clock (LIFE-01, 03, 14)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import clock
from agent_canvas.hub.lifetime import DAY_SECONDS, is_expired

pytestmark = pytest.mark.integration

TAG = '<head><meta name="agent-canvas-kind" content="single-use"></head><p>q</p>'


@pytest.fixture
def folder(hub) -> Path:  # noqa: ANN001
    """Create session ``a`` and return its folder."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    return Path(answer.json()["folder"])


def show(hub, name: str = "page.html", **body):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/a/show",
        json={"name": name, "audit": False, **body},
        headers=hub.key_headers,
        timeout=30,
    )


def page_meta(folder: Path) -> dict:
    return json.loads((folder / "session.json").read_text()).get("page_meta", {})


def set_kind(hub, name: str, kind: str):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/a/pages",
        json={"action": "kind", "name": name, "kind": kind},
        headers=hub.key_headers,
    )


def test_life_01_default_is_transitional(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    assert "kind" not in show(hub).json()
    entry = page_meta(folder)["page.html"]
    assert (entry["kind"], entry["set_by"]) == ("transitional", "default")
    assert (entry["extended"], entry["answered"], entry["archived"]) == (None,) * 3


def test_life_01_the_meta_tag_gives_the_kind(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text(TAG)
    show(hub)
    entry = page_meta(folder)["page.html"]
    assert (entry["kind"], entry["set_by"]) == ("single-use", "meta")


def test_life_01_a_meta_tag_with_content_first_or_an_unknown_kind(hub, folder) -> None:  # noqa: ANN001
    (folder / "a.html").write_text(
        '<head><meta content="long-term" name="agent-canvas-kind"></head>'
    )
    (folder / "b.html").write_text(
        '<head><meta name="agent-canvas-kind" content="forever"></head>'
    )
    show(hub, "a.html")
    show(hub, "b.html")
    meta = page_meta(folder)
    assert meta["a.html"]["kind"] == "long-term"
    assert (meta["b.html"]["kind"], meta["b.html"]["set_by"]) == (
        "transitional",
        "default",
    )


def test_life_01_show_kind_wins_over_the_tag_and_is_answered(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text(TAG)
    answer = show(hub, kind="long-term").json()
    assert (answer["kind"], answer["set_by"]) == ("long-term", "agent")
    entry = page_meta(folder)["page.html"]
    assert (entry["kind"], entry["set_by"]) == ("long-term", "agent")


def test_life_01_page_kind_sets_it(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    show(hub)
    answer = set_kind(hub, "page.html", "single-use")
    assert answer.json() == {
        "session": "a",
        "page": "page.html",
        "kind": "single-use",
        "set_by": "agent",
    }
    assert page_meta(folder)["page.html"]["kind"] == "single-use"


def test_life_01_the_owners_choice_wins_over_a_later_agent_call(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    show(hub)
    hub.on_loop(lambda: hub.app.state.services.registry.set_kind(
        "a", "page.html", "transitional", "owner"
    ))  # fmt: skip
    answer = set_kind(hub, "page.html", "single-use").json()
    assert (answer["kind"], answer["set_by"]) == ("transitional", "owner")
    answer = show(hub, kind="long-term").json()
    assert (answer["kind"], answer["set_by"]) == ("transitional", "owner")
    assert page_meta(folder)["page.html"]["kind"] == "transitional"


def test_life_01_an_unknown_kind_is_a_usage_error_and_changes_nothing(
    hub, folder
) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    refused = show(hub, kind="forever")
    assert refused.json()["error"] == "usage"
    assert "page.html" not in page_meta(folder)
    show(hub)
    assert set_kind(hub, "page.html", "forever").json()["error"] == "usage"
    assert page_meta(folder)["page.html"]["kind"] == "transitional"
    assert set_kind(hub, "nope.html", "long-term").json()["error"] == "failed"


def test_life_01_a_new_version_follows_a_changed_tag_until_a_kind_is_set(
    hub, folder
) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    show(hub)
    (folder / "page.html").write_text(TAG)
    hub.wait_for(lambda: page_meta(folder)["page.html"]["kind"] == "single-use")
    set_kind(hub, "page.html", "long-term")
    (folder / "page.html").write_text("<p>y</p>")
    hub.wait_for(lambda: "y</p>" in (folder / "page.html").read_text())
    assert page_meta(folder)["page.html"]["kind"] == "long-term"


def test_life_02_a_change_of_kind_never_restarts_the_clock(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    show(hub)
    before = page_meta(folder)["page.html"]
    set_kind(hub, "page.html", "single-use")
    show(hub, kind="long-term")
    set_kind(hub, "page.html", "transitional")
    after = page_meta(folder)["page.html"]
    assert after["counted_from"] == before["counted_from"]
    assert after["extended"] is None and after["kind"] == "transitional"


def test_life_02_an_event_on_a_page_stamps_answered(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    show(hub)
    event = hub.create_event("a", "button", page="page.html")
    assert page_meta(folder)["page.html"]["answered"] == event["time"]


def test_life_03_a_page_first_seen_gets_counted_from_now(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    before = clock.now()
    show(hub)
    start = clock.seconds_of(page_meta(folder)["page.html"]["counted_from"])
    assert before - 1 <= start <= clock.now() + 1


def test_life_03_pages_90_days_old_are_not_expired_at_the_first_start(
    hub, folder, monkeypatch
) -> None:  # noqa: ANN001
    (folder / "old.html").write_text("<p>x</p>")
    old = clock.now() - 90 * DAY_SECONDS
    os.utime(folder / "old.html", (old, old))
    session = json.loads((folder / "session.json").read_text())
    (folder / "session.json").write_text(
        json.dumps({**session, "pages": ["old.html"], "active_page": "old.html"})
    )
    registry = hub.app.state.services.registry
    pool = registry.pool_of("a")  # the folder is the pool's (POOL-01)
    hub.on_loop(lambda: registry.note_pages(pool))  # what the hub does at its start
    entry = page_meta(folder)["old.html"]
    changed = (folder / "old.html").stat().st_mtime
    assert not is_expired(entry, changed, clock.now())
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(30 * DAY_SECONDS))
    assert is_expired(entry, changed, clock.now())


def test_life_03_a_second_start_keeps_the_first_counted_from(hub, folder) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    show(hub)
    first = page_meta(folder)["page.html"]["counted_from"]
    registry = hub.app.state.services.registry
    hub.on_loop(lambda: registry.note_pages("a"))
    assert page_meta(folder)["page.html"]["counted_from"] == first


def test_life_14_with_test_mode_and_31_days_a_page_changed_now_is_expired(
    hub, folder, monkeypatch
) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<p>x</p>")
    show(hub)
    entry = page_meta(folder)["page.html"]
    changed = (folder / "page.html").stat().st_mtime
    assert not is_expired(entry, changed, clock.now())
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(31 * DAY_SECONDS))
    assert is_expired(entry, changed, clock.now())


def test_life_14_without_test_mode_the_hub_exits_naming_the_variable(lone) -> None:  # noqa: ANN001
    done = lone.run("hub", extra_env={clock.TEST_CLOCK_OFFSET: "2678400"})
    assert done.code != 0
    assert clock.TEST_CLOCK_OFFSET in done.err


def test_life_14_create_app_refuses_the_offset_without_test_mode(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    from agent_canvas.config import ConfigError, load_config
    from agent_canvas.hub.app import create_app

    monkeypatch.delenv(clock.TEST_MODE, raising=False)
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, "60")
    with pytest.raises(ConfigError, match=clock.TEST_CLOCK_OFFSET):
        create_app(load_config(), tmp_path)
    assert not list(tmp_path.iterdir())  # refused before anything was written


def test_life_01_the_cli_sets_a_kind_and_an_unknown_kind_exits_2(cli, hub) -> None:  # noqa: ANN001
    session = cli("session", "start").json["session"]
    folder = Path(cli("session", "path", "--session", session).json["folder"])
    (folder / "page.html").write_text("<p>x</p>")
    at = ("--session", session)
    shown = cli("show", "page.html", "--no-audit", "--kind", "single-use", *at)
    assert shown.code == 0 and shown.json["kind"] == "single-use"
    done = cli("page", "kind", "page.html", "long-term", *at)
    assert done.code == 0 and done.json["kind"] == "long-term"
    assert cli("page", "kind", "page.html", "forever", *at).code == 2
    assert cli("show", "page.html", "--kind", "forever", *at).code == 2
