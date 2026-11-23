"""`agent-canvas new` and the served kit (KIT-01 to KIT-03)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_canvas.templates import TEMPLATES

pytestmark = pytest.mark.integration


def test_kit_01_the_stylesheet_is_served_from_static_kit(hub) -> None:  # noqa: ANN001
    answer = httpx.get(f"{hub.base_url}/static/kit/kit.css")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/css")
    assert ".columns" in answer.text


def test_kit_03_new_writes_the_page_and_prints_the_path(cli, hub) -> None:  # noqa: ANN001
    session = cli("session", "start").json["session"]
    result = cli(
        "new", "options", "--template", "compare", "--no-draft", "--session", session
    )
    assert result.code == 0 and result.err == ""
    data = result.json
    path = Path(data["path"])
    assert path.name == "options.html" and path.parent.name == session
    assert data["template"] == "compare" and data["page"] == "options.html"
    assert data["draft"] is False
    assert 'href="/static/kit/kit.css"' in path.read_text()
    assert cli("show", "options.html", "--session", session).code == 0


def test_kit_03_new_refuses_an_existing_file_unless_forced(cli, hub) -> None:  # noqa: ANN001
    session = cli("session", "start").json["session"]
    args = ("new", "p", "--template", "run", "--no-draft", "--session", session)
    path = Path(cli(*args).json["path"])
    path.write_text("edited")
    refused = cli(*args)
    assert refused.code == 1 and refused.json["error"] == "failed"
    assert "already exists" in refused.json["message"] and path.read_text() == "edited"
    assert cli(*args, "--force").code == 0
    assert "canvas-progress" in path.read_text()


def test_kit_03_new_validates_name_and_template(cli, hub) -> None:  # noqa: ANN001
    session = cli("session", "start").json["session"]
    bad_name = cli("new", "../x", "--template", "run", "--session", session)
    assert bad_name.code == 2 and bad_name.json["error"] == "usage"
    bad_template = cli("new", "x", "--template", "poster", "--session", session)
    assert bad_template.code == 2
    no_template = cli("new", "x", "--session", session)
    assert no_template.code == 2


def test_kit_03_new_list_needs_no_hub_or_session(cli) -> None:  # noqa: ANN001
    result = cli("new", "--list")
    assert result.code == 0
    names = [t["name"] for t in result.json["templates"]]
    assert names == list(TEMPLATES)
    assert all(t["description"] for t in result.json["templates"])


def test_draft_04_new_writes_a_private_draft_by_default(cli, hub) -> None:  # noqa: ANN001
    session = cli("session", "start").json["session"]
    result = cli("new", "options", "--template", "compare", "--session", session)
    assert result.code == 0, result.err
    data = result.json
    path = Path(data["path"])
    assert path.name == "options.draft.html" and path.parent.name == session
    assert data["page"] == "options.draft.html" and data["draft"] is True
    assert not (path.parent / "options.html").exists()
    assert cli("show", "options.html", "--session", session).code == 1
    explicit = cli("new", "x", "--template", "run", "--draft", "--session", session)
    assert explicit.json["page"] == "x.draft.html"


def test_draft_04_the_draft_and_the_page_are_refused_and_forced_separately(
    cli,
    hub,  # noqa: ANN001
) -> None:
    session = cli("session", "start").json["session"]
    base = ("new", "p", "--template", "run", "--session", session)
    assert cli(*base).code == 0
    assert cli(*base).code == 1  # the draft exists
    assert cli(*base, "--no-draft").code == 0  # the page does not
    assert cli(*base, "--no-draft").code == 1
    assert cli(*base, "--force").code == 0
