"""Project pages through the CLI and the hub (PROJ-01 to PROJ-06, #87)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import comments
from shellfake import FakeHeadless

pytestmark = pytest.mark.integration

COMMENT = {
    "page": "plan.html", "page_version": 1, "kind": "point", "text": "units?",
    "anchor": {"space": "page-px", "x": 1, "y": 2, "fx": 0.1, "fy": 0.2},
    "target": {"canvas_id": None, "selector": "#fig", "text": None},
}  # fmt: skip
SEND = {
    "delivery": "now", "message": "", "page": "plan.html",
    "viewport": {"width": 10, "height": 10, "scroll_x": 0, "scroll_y": 0},
    "screenshot": None, "screenshot_error": "none",
}  # fmt: skip


@pytest.fixture
def repos(home: Path) -> tuple[Path, Path]:
    """Two git repositories below the fake home; the first has a subfolder."""
    first, second = home / "proj", home / "other"
    for repo in (first, second):
        repo.mkdir(exist_ok=True)
        (repo / ".git").mkdir()
    (first / "sub").mkdir()
    return first, second


def folder_of(cli, session: str, cwd: Path) -> dict:  # noqa: ANN001
    """Make ``session`` known; return the answer of ``session path --project-page``."""
    assert cli("session", "path", "--session", session, cwd=cwd).code == 0
    answer = cli("session", "path", "--session", session, "--project-page", cwd=cwd)
    assert answer.code == 0, answer.err
    return answer.json


def write_page(folder: str, name: str = "plan.html") -> None:
    (Path(folder) / name).write_text(f"<title>{name}</title><p>hello</p>")


def show(cli, session: str, cwd: Path, name: str = "plan.html"):  # noqa: ANN001, ANN201
    return cli(
        "show", name, "--session", session, "--project-page", "--no-audit", cwd=cwd
    )


def test_proj_02_session_path_creates_the_project_session_and_prints_its_folder(
    cli, repos
) -> None:  # noqa: ANN001
    first, _ = repos
    answer = folder_of(cli, "A", first)
    folder = Path(answer["folder"])
    assert answer["session"].startswith("project-") and len(answer["session"]) == 24
    assert folder == first / ".agent-canvas" / "project"
    assert json.loads((folder / "session.json").read_text())["agent"] == "project"


def test_proj_01_two_repos_get_different_ids_and_a_subfolder_shares_its_repos(
    cli, repos
) -> None:  # noqa: ANN001
    first, second = repos
    a = folder_of(cli, "A", first)
    b = folder_of(cli, "B", second)
    c = folder_of(cli, "C", first / "sub")
    assert a["session"] != b["session"]
    assert c["session"] == a["session"] and c["folder"] == a["folder"]
    assert Path(a["folder"]).name == Path(b["folder"]).name == "project"


def test_proj_03_04_two_sessions_show_and_see_the_same_page_and_the_last_is_updater(
    cli, repos
) -> None:  # noqa: ANN001
    first, _ = repos
    folder = folder_of(cli, "A", first)["folder"]
    folder_of(cli, "B", first)
    write_page(folder)
    assert show(cli, "A", first).code == 0
    listing = cli("page", "list", "--session", "B", "--project-page", cwd=first).json
    (row,) = listing["pages"]
    assert row["name"] == "plan.html" and row["updated_by"]["session"] == "A"
    assert row["updated_by"]["agent"] == "agent" and row["updated_by"]["time"]
    assert show(cli, "B", first).code == 0
    listing = cli("page", "list", "--session", "A", "--project-page", cwd=first).json
    assert [r["updated_by"]["session"] for r in listing["pages"]] == ["B"]
    assert listing["session"] == folder_of(cli, "A", first)["session"]


def test_proj_03_comments_answers_and_kind_act_on_the_project_session(
    cli, repos
) -> None:  # noqa: ANN001
    first, _ = repos
    answer = folder_of(cli, "A", first)
    folder_of(cli, "B", first)
    write_page(answer["folder"])
    show(cli, "A", first)
    done = cli("page", "kind", "plan.html", "single-use", *B, cwd=first)
    assert done.code == 0, done.err
    assert done.json["kind"] == "single-use"
    assert done.json["session"] == answer["session"]
    assert (
        cli("page", "kind", "plan.html", "long-term", "--session", "B", cwd=first).code
        == 1
    )


def project_scene(cli, hub, repos):  # noqa: ANN001, ANN201
    """B and A in one project; the project page has two sent comments and an ask."""
    first, _ = repos
    answer = folder_of(cli, "A", first)
    folder_of(cli, "B", first)
    page = Path(answer["folder"]) / "plan.html"
    page.write_text(
        '<title>plan</title><canvas-ask data-canvas-id="q1">'
        '<script type="application/json">{"question": "Keep?", '
        '"options": ["keep", "change"]}</script></canvas-ask>'
    )
    assert show(cli, "A", first).code == 0
    owner = httpx.Client(base_url=hub.base_url, headers={"Origin": hub.base_url})
    owner.get(hub.login_url(), follow_redirects=False)
    base = f"/api/sessions/{answer['session']}"
    for _ in range(2):
        assert owner.post(f"{base}/comments", json=COMMENT).status_code == 200
    sent = httpx.post(f"{hub.base_url}{base}/send", json=SEND, headers=hub.key_headers)
    assert sent.status_code == 200, sent.text
    given = owner.post(
        f"{base}/answers/answer",
        json={"page": "plan.html", "id": "q1", "value": {"answer": ["keep"]}},
    )
    assert given.status_code == 200, given.text
    return first, answer


B = ("--session", "B", "--project-page")


def test_proj_03_comment_list_and_answers_read_the_project_session_only(
    cli, hub, repos
) -> None:  # noqa: ANN001
    first, answer = project_scene(cli, hub, repos)
    listed = cli("comment", "list", *B, cwd=first).json
    assert listed["session"] == answer["session"]
    assert [c["n"] for c in listed["comments"]] == [1, 2]
    answers = cli("answers", *B, cwd=first).json
    assert answers["session"] == answer["session"]
    assert [i["id"] for i in answers["items"]] == ["q1"]
    own_list = cli("comment", "list", "--session", "B", cwd=first).json
    assert own_list["session"] == "B" and own_list["comments"] == []
    own_answers = cli("answers", "--session", "B", cwd=first).json
    assert own_answers["session"] == "B" and own_answers["items"] == []


def test_proj_03_comment_reply_and_done_change_the_project_pages_comments(
    cli, hub, repos
) -> None:  # noqa: ANN001
    first, answer = project_scene(cli, hub, repos)
    replied = cli("comment", "reply", "plan.html", "1", "yes", *B, cwd=first)
    assert replied.code == 0, replied.err
    finished = cli("comment", "done", "plan.html", "2", *B, cwd=first)
    assert finished.code == 0, finished.err
    stored = {
        c["n"]: c
        for c in comments.load(Path(answer["folder"]), "plan.html")["comments"]
    }
    assert [r["text"] for r in stored[1]["replies"]] == ["yes"]
    assert stored[2]["done"]["by"] == "agent" and stored[1]["done"] is None
    own = cli("comment", "reply", "plan.html", "1", "x", "--session", "B", cwd=first)
    assert own.code != 0  # B's own session has no such comment


def test_proj_03_page_list_and_look_act_on_the_project_session(cli, hub, repos) -> None:  # noqa: ANN001
    first, answer = project_scene(cli, hub, repos)
    listing = cli("page", "list", *B, cwd=first).json
    assert listing["session"] == answer["session"]
    assert [p["name"] for p in listing["pages"]] == ["plan.html"]
    own = cli("page", "list", "--session", "B", cwd=first).json
    assert own["session"] == "B" and own["pages"] == []
    hub.app.state.looks.headless = FakeHeadless()
    looked = cli("look", "plan.html", *B, cwd=first)
    assert looked.code == 0, looked.err
    assert looked.json["png"].startswith(
        str(Path(answer["folder"]).resolve() / "history/looks/")
    )
    assert cli("look", "plan.html", "--session", "B", cwd=first).code != 0


def test_proj_04_a_caller_from_another_project_is_refused_with_exit_1(
    cli, hub, repos
) -> None:  # noqa: ANN001
    first, second = repos
    project_id = folder_of(cli, "A", first)["session"]
    folder_of(cli, "B", second)
    write_page(folder_of(cli, "A", first)["folder"])
    refused = httpx.post(
        f"{hub.base_url}/api/sessions/{project_id}/show",
        json={"name": "plan.html", "by": "B", "audit": False},
        headers=hub.key_headers,
    )
    assert refused.status_code == 422 and refused.json()["error"] == "failed"
    missing = httpx.post(
        f"{hub.base_url}/api/sessions/{project_id}/show",
        json={"name": "plan.html", "audit": False},
        headers=hub.key_headers,
    )
    assert missing.status_code == 404
    listing = cli("page", "list", "--session", "A", "--project-page", cwd=first).json
    assert listing["pages"] == []


def test_proj_05_end_title_start_and_reserve_of_project_ids_exit_5_and_write_nothing(
    cli, hub, repos
) -> None:  # noqa: ANN001
    first, _ = repos
    project_id = folder_of(cli, "A", first)["session"]
    meta = Path(first / ".agent-canvas/project/session.json")
    before = meta.read_text()
    fake = "project-0123456789abcdef"
    attempts = [
        ("session", "end", "--session", project_id),
        ("session", "set", "--title", "Mine", "--session", project_id),
        ("session", "path", "--session", fake),
        ("show", "plan.html", "--session", fake),
    ]
    for attempt in attempts:
        refused = cli(*attempt, cwd=first)
        assert refused.code == 5, (attempt, refused.out, refused.err)
    reserved = httpx.post(
        f"{hub.base_url}/api/sessions/{fake}/reserve",
        json={"project": str(first), "agent": "x"},
        headers=hub.key_headers,
    )
    assert reserved.status_code == 404
    assert meta.read_text() == before
    assert not (first / ".agent-canvas" / fake).exists()
    assert fake not in (hub.state_dir / "sessions.json").read_text()


def test_proj_06_a_new_project_page_is_long_term_by_default(cli, repos) -> None:  # noqa: ANN001
    first, _ = repos
    write_page(folder_of(cli, "A", first)["folder"])
    assert show(cli, "A", first).code == 0
    listing = cli("page", "list", "--session", "A", "--project-page", cwd=first).json
    (row,) = listing["pages"]
    assert (row["kind"], row["set_by"]) == ("long-term", "default")


def test_proj_05_the_project_session_is_never_the_updater(cli, repos) -> None:  # noqa: ANN001
    first, _ = repos
    answer = folder_of(cli, "A", first)
    write_page(answer["folder"])
    project_id = answer["session"]
    refused = cli(
        "session", "path", "--session", project_id, "--project-page", cwd=first
    )
    assert refused.code == 5
    assert show(cli, project_id, first).code == 5
    assert '"updated_by"' not in (Path(answer["folder"]) / "session.json").read_text()


def test_proj_05_by_naming_the_project_session_is_refused(cli, hub, repos) -> None:  # noqa: ANN001
    first, _ = repos
    answer = folder_of(cli, "A", first)
    write_page(answer["folder"])
    refused = httpx.post(
        f"{hub.base_url}/api/sessions/{answer['session']}/show",
        json={"name": "plan.html", "by": answer["session"], "audit": False},
        headers=hub.key_headers,
    )
    assert refused.status_code == 404
    assert '"updated_by"' not in (Path(answer["folder"]) / "session.json").read_text()


def test_proj_01_a_symlinked_project_folder_is_refused(
    cli, repos, tmp_path: Path
) -> None:  # noqa: ANN001
    first, _ = repos
    assert cli("session", "path", "--session", "A", cwd=first).code == 0
    target = tmp_path / "elsewhere"
    target.mkdir()
    (first / ".agent-canvas" / "project").symlink_to(target)
    refused = cli("session", "path", "--session", "A", "--project-page", cwd=first)
    assert refused.code == 1
    assert list(target.iterdir()) == []


def test_proj_12_cleanup_of_the_project_session_is_refused(cli, hub, repos) -> None:  # noqa: ANN001
    first, _ = repos
    answer = folder_of(cli, "A", first)
    refused = httpx.post(
        f"{hub.base_url}/api/cleanup",
        json={"session": answer["session"], "yes": True, "force": True},
        headers=hub.key_headers,
    )
    assert refused.status_code >= 400
    assert (Path(answer["folder"]) / "session.json").is_file()


@pytest.mark.parametrize("name", ["PROJECT", "Project", "Project-0123456789abcdef"])
def test_proj_05_reserved_ids_are_refused_in_any_case(cli, repos, name) -> None:  # noqa: ANN001
    first, _ = repos
    assert cli("session", "path", "--session", name, cwd=first).code == 5
    assert not (first / ".agent-canvas" / name).exists()
