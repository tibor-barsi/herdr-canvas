"""Drafts against a real hub: invisible to the window, publish (DRAFT-02, 03)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub.watcher import PageHistory
from helpers import own_draft
from shellfake import FakeShell

pytestmark = pytest.mark.integration


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    fake = FakeShell(hub)
    yield fake
    fake.close()


@pytest.fixture
def shown(cli, hub, shell) -> dict:  # noqa: ANN001
    """A session showing ``page.html`` with the window quiet again."""
    started = cli("session", "start").json
    folder = Path(started["folder"])
    (folder / "page.html").write_text("<p>published</p>")
    result = cli("show", "page.html", "--session", started["session"])
    assert result.code == 0, result.err
    time.sleep(0.6)  # the first scan of the watcher and its pushes
    shell.messages.clear()
    return {"id": started["session"], "folder": folder}


def test_draft_02_a_draft_changes_nothing_in_the_window(cli, hub, shell, shown) -> None:  # noqa: ANN001
    draft = shown["folder"] / own_draft(shown["id"])
    draft.write_text("<p>first idea</p>")
    time.sleep(0.7)
    draft.write_text("<p>second idea</p>")
    time.sleep(0.7)
    draft.unlink()
    time.sleep(0.7)
    assert shell.types() == []
    pages = PageHistory(shown["folder"])
    assert [n for n, _ in pages.versions("page.html")] == [1]
    assert pages.versions(own_draft(shown["id"])) == []
    assert hub.state.tab_provider(shown["id"])["pages"] == ["page.html"]
    assert hub.on_loop(lambda: hub.state.events.all(shown["id"])) == []


def test_draft_02_other_data_files_still_reach_the_window(hub, shell, shown) -> None:  # noqa: ANN001
    (shown["folder"] / "data.csv").write_text("a,b\n1,2\n")
    hub.wait_for(lambda: "file-changed" in shell.types(), timeout=5)


def test_draft_02_a_draft_cannot_be_shown(cli, shown) -> None:  # noqa: ANN001
    (shown["folder"] / own_draft(shown["id"])).write_text("<p>x</p>")
    result = cli("show", own_draft(shown["id"]), "--session", shown["id"])
    assert result.code == 1
    assert "--publish" in result.json["message"] and "look" in result.json["message"]


def test_draft_01_a_draft_is_served_like_a_session_file(hub, shown) -> None:  # noqa: ANN001
    (shown["folder"] / own_draft(shown["id"])).write_text("<p>draft text</p>")
    token = hub.state.session_of(hub.pool_of(shown["id"])).page_token
    draft_name = own_draft(shown["id"])
    url = f"{hub.frame_origin}/s/{token}/{draft_name}"
    answer = httpx.get(url)
    assert answer.status_code == 200 and "draft text" in answer.text
    assert "helper.js" in answer.text  # the helper runs, so the look can report
    assert httpx.get(url + "?v=1").status_code == 404  # no versions of drafts


def test_draft_03_publish_copies_the_draft_and_shows_it(cli, hub, shell, shown) -> None:  # noqa: ANN001
    folder = shown["folder"]
    (folder / own_draft(shown["id"])).write_text("<p>better</p>")
    result = cli("show", "page.html", "--publish", "--session", shown["id"])
    assert result.code == 0, result.err
    assert (folder / "page.html").read_text() == "<p>better</p>"
    assert (folder / own_draft(shown["id"])).read_text() == "<p>better</p>"
    assert result.json["page"] == "page.html" and result.json["version"] == 2
    leftovers = {p.name for p in folder.iterdir()} - {
        "page.html", own_draft(shown["id"]), "session.json", "events.jsonl", "history",
    }  # fmt: skip
    assert leftovers == set()  # no temporary file stays behind
    assert "show" in shell.types()
    assert PageHistory(folder).read("page.html", 2) == b"<p>better</p>"


def test_draft_03_publish_without_a_name_uses_the_default_page(cli, shown) -> None:  # noqa: ANN001
    (shown["folder"] / own_draft(shown["id"])).write_text("<p>via default</p>")
    result = cli("show", "--publish", "--session", shown["id"])
    assert result.code == 0, result.err
    assert (shown["folder"] / "page.html").read_text() == "<p>via default</p>"


def test_draft_03_publishing_a_new_page_creates_it(cli, shown) -> None:  # noqa: ANN001
    (shown["folder"] / own_draft(shown["id"], "fresh")).write_text("<p>fresh</p>")
    result = cli("show", "fresh", "--publish", "--session", shown["id"])
    assert result.code == 0, result.err
    assert result.json["page"] == "fresh.html"
    assert (shown["folder"] / "fresh.html").read_text() == "<p>fresh</p>"


def test_draft_03_publish_without_a_draft_fails_and_keeps_the_page(cli, shown) -> None:  # noqa: ANN001
    result = cli("show", "page.html", "--publish", "--session", shown["id"])
    assert result.code == 1 and own_draft(shown["id"]) in result.json["message"]
    assert (shown["folder"] / "page.html").read_text() == "<p>published</p>"


def test_draft_03_a_second_publish_makes_a_second_version(cli, shown) -> None:  # noqa: ANN001
    draft = shown["folder"] / own_draft(shown["id"])
    for text in ("<p>v2</p>", "<p>v3</p>", "<p>v3</p>"):
        draft.write_text(text)
        assert cli("show", "--publish", "--session", shown["id"]).code == 0
    assert [n for n, _ in PageHistory(shown["folder"]).versions("page.html")] == [
        1,
        2,
        3,
    ]
