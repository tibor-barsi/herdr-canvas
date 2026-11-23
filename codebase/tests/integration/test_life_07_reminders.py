"""Reminders in ``pending`` through the CLI, MCP and the route (LIFE-07, CLI-09)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import clock
from agent_canvas.hub.lifetime import DAY_SECONDS

pytestmark = pytest.mark.integration

FIRST = 3 * DAY_SECONDS + 60  # the single-use page's lifetime plus a minute


def at(monkeypatch, seconds: float) -> None:  # noqa: ANN001
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(seconds))


def act(hub, action: str, name: str, **body):  # noqa: ANN001, ANN201
    return httpx.post(
        f"{hub.base_url}/api/sessions/a/pages",
        json={"action": action, "name": name, **body},
        headers=hub.key_headers,
    )


@pytest.fixture
def folder(hub) -> Path:  # noqa: ANN001
    """Session ``a``: single-use ``plot.html``, long-term ``keep.html``."""
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/a/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    place = Path(answer.json()["folder"])
    for name in ("plot.html", "keep.html"):
        (place / name).write_text(f"<p>{name}</p>")
        httpx.post(
            f"{hub.base_url}/api/sessions/a/show",
            json={"name": name, "audit": False},
            headers=hub.key_headers,
            timeout=30,
        )
    act(hub, "kind", "plot.html", kind="single-use")
    act(hub, "kind", "keep.html", kind="long-term")
    return place


def reminders(cli, *flags: str) -> list[dict]:  # noqa: ANN001
    result = cli("pending", "--session", "a", *flags)
    assert result.code == 0
    return result.json["reminders"]


def stamp(folder: Path, name: str = "plot.html") -> str | None:
    meta = json.loads((folder / "session.json").read_text())
    return meta["page_meta"][name]["reminded"]


def test_life_07_pending_names_an_expired_page_at_most_once_in_24_hours(
    cli,
    hub,
    folder,
    monkeypatch,  # noqa: ANN001
) -> None:
    assert reminders(cli) == []
    at(monkeypatch, FIRST)
    [named] = reminders(cli)
    assert (named["page"], named["kind"]) == ("plot.html", "single-use")
    expired = clock.seconds_of(named["expired"])
    assert expired == pytest.approx(clock.now() - 60, abs=5)
    assert stamp(folder) is not None
    at(monkeypatch, FIRST + 23 * 3600 + 59 * 60)
    assert reminders(cli) == []
    at(monkeypatch, FIRST + 24 * 3600)
    assert [r["page"] for r in reminders(cli)] == ["plot.html"]


def test_life_07_an_archived_page_is_not_named(cli, hub, folder, monkeypatch) -> None:  # noqa: ANN001
    at(monkeypatch, FIRST)
    act(hub, "archive", "plot.html")
    assert reminders(cli) == []
    assert stamp(folder) is None


def test_life_07_a_long_term_page_is_never_named_even_a_year_on(
    cli, hub, folder, monkeypatch
) -> None:  # noqa: ANN001
    at(monkeypatch, 900 * DAY_SECONDS)
    assert [r["page"] for r in reminders(cli)] == ["plot.html"]


def test_cli_09_peek_returns_reminders_and_stamps_nothing(
    cli,
    hub,
    folder,
    monkeypatch,  # noqa: ANN001
) -> None:
    at(monkeypatch, FIRST)
    assert [r["page"] for r in reminders(cli, "--peek")] == ["plot.html"]
    assert stamp(folder) is None
    assert [r["page"] for r in reminders(cli, "--peek")] == ["plot.html"]
    assert [r["page"] for r in reminders(cli)] == ["plot.html"]
    assert stamp(folder) is not None


def test_life_07_extending_the_page_ends_its_reminders(
    cli, hub, folder, monkeypatch
) -> None:  # noqa: ANN001
    at(monkeypatch, FIRST)
    act(hub, "extend", "plot.html")
    assert reminders(cli) == []
