"""NEW-01 and NEW-03: the seen version in ``page_meta`` and the changes route."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub.watcher import PageHistory
from shellfake import FakeHeadless, FakeShell

pytestmark = pytest.mark.integration

PAGE = (
    '<h1>Report</h1><canvas-plot data-canvas-id="plot">'
    '<script type="application/json">{"x": [1, 2]}</script></canvas-plot>'
)
SECOND = PAGE.replace("[1, 2]", "[1, 3]")
THIRD = SECOND + '<section id="extra"><p>New.</p></section>'


@pytest.fixture
def folder(hub) -> Path:  # noqa: ANN001
    """Create session ``a`` and return its folder."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    return Path(answer.json()["folder"])


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    opened = FakeShell(hub, {"width": 900, "height": 700, "scheme": "dark"})
    yield opened
    opened.close()


def show(hub, folder: Path, name: str, text: str) -> None:  # noqa: ANN001
    (folder / name).write_text(text)
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/show",
        json={"name": name, "audit": False},
        headers=hub.key_headers,
        timeout=30,
    )
    assert answer.status_code == 200, answer.text


def save(folder: Path, name: str, text: str) -> None:
    """Make ``text`` the page and its newest version, whoever saves it first.

    The page file is written first so a late watcher event finds the same text
    as the history and saves no extra version.
    """
    (folder / name).write_text(text)
    history = PageHistory(folder)
    history.save(name, text.encode())
    assert history.latest(name)[1] == text.encode()


def entry(folder: Path, name: str = "page.html") -> dict:
    meta = json.loads((folder / "session.json").read_text())["page_meta"]
    return meta[name]


def seen(shell, version: object, name: str = "page.html") -> None:  # noqa: ANN001
    shell.send({"type": "seen", "session": "a", "page": name, "version": version})


def seen_is(hub, folder: Path, version: int, name: str = "page.html") -> None:  # noqa: ANN001
    hub.wait_for(lambda: entry(folder, name)["seen_version"] == version)


def changes(hub, page: str = "page.html", **query: str) -> dict:  # noqa: ANN001
    answer = httpx.get(
        f"{hub.base_url}/api/sessions/a/changes",
        params={"page": page, **query},
        headers=hub.key_headers,
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_new_01_a_page_has_null_seen_fields_until_the_owner_sees_it(
    hub, folder
) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    assert (entry(folder)["seen_version"], entry(folder)["seen_at"]) == (None, None)


def test_new_01_version_3_reported_is_seen_3_with_a_time(hub, folder, shell) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    save(folder, "page.html", SECOND)
    save(folder, "page.html", THIRD)
    seen(shell, 3)
    seen_is(hub, folder, 3)
    assert entry(folder)["seen_at"].endswith("Z")


def test_new_01_an_older_or_impossible_report_changes_nothing(
    hub, folder, shell
) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    save(folder, "page.html", SECOND)
    seen(shell, 2)
    seen_is(hub, folder, 2)
    stamp = entry(folder)["seen_at"]
    for bad in (1, 3, 0, -1, "2", 2.0, True, None):
        seen(shell, bad)
    shell.send({"type": "seen", "session": "zz", "page": "page.html", "version": 2})
    shell.send({"type": "seen", "session": "a", "page": "../x.html", "version": 1})
    show(hub, folder, "other.html", PAGE)
    seen(shell, 1, "other.html")  # the hub reads in order: this one is the witness
    seen_is(hub, folder, 1, "other.html")
    assert (entry(folder)["seen_version"], entry(folder)["seen_at"]) == (2, stamp)


def test_new_01_a_look_and_a_headless_look_never_count_as_seen(
    hub, folder, cli, shell
) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    save(folder, "page.html", SECOND)
    assert cli("look", "--session", "a", "page.html").code == 0
    assert shell.requests  # the window rendered it in its hidden frame
    headless = FakeHeadless()
    hub.app.state.looks.headless = headless
    shell.close()
    assert cli("look", "--session", "a", "page.html").code == 0
    assert headless.jobs
    assert (entry(folder)["seen_version"], entry(folder)["seen_at"]) == (None, None)


def test_new_03_a_page_never_seen_has_no_changes(hub, folder) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    save(folder, "page.html", SECOND)
    answer = changes(hub)
    assert (answer["count"], answer["version"], answer["since"]) == (0, 2, None)


def test_new_03_version_1_seen_and_one_block_changed_gives_1_change(
    hub, folder, shell
) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    seen(shell, 1)
    seen_is(hub, folder, 1)
    save(folder, "page.html", SECOND)
    answer = changes(hub)
    assert (answer["count"], answer["changed"], answer["added"]) == (1, ["plot"], [])
    assert (answer["since"], answer["version"]) == (1, 2)
    assert answer["since_time"] == entry(folder)["seen_at"]
    assert entry(folder)["seen_version"] == 1  # reading the changes is not seeing


def test_new_03_after_seeing_the_new_version_there_is_nothing(
    hub, folder, shell
) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    seen(shell, 1)
    seen_is(hub, folder, 1)
    save(folder, "page.html", SECOND)
    seen(shell, 2)
    seen_is(hub, folder, 2)
    assert changes(hub)["count"] == 0


def test_new_03_since_compares_from_the_named_version(hub, folder, shell) -> None:  # noqa: ANN001
    show(hub, folder, "page.html", PAGE)
    seen(shell, 1)
    seen_is(hub, folder, 1)
    save(folder, "page.html", SECOND)
    seen(shell, 2)
    seen_is(hub, folder, 2)
    save(folder, "page.html", THIRD)
    assert changes(hub)["added"] == ["extra"]
    answer = changes(hub, since="1")
    assert (answer["changed"], answer["added"], answer["count"]) == (
        ["plot"],
        ["extra"],
        2,
    )
    assert answer["since_time"].endswith("Z")


def test_new_03_a_viewer_page_gets_a_count_and_no_ids(hub, folder, shell) -> None:  # noqa: ANN001
    show(hub, folder, "notes.md", "# a\n")
    seen(shell, 1, "notes.md")
    seen_is(hub, folder, 1, "notes.md")
    save(folder, "notes.md", "# b\n")
    answer = changes(hub, "notes.md")
    assert (answer["count"], answer["changed"], answer["outside"]) == (1, [], True)


def test_new_03_an_unknown_page_is_refused(hub, folder) -> None:  # noqa: ANN001
    answer = httpx.get(
        f"{hub.base_url}/api/sessions/a/changes",
        params={"page": "none.html"},
        headers=hub.key_headers,
    )
    assert answer.status_code != 200
