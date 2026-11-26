"""Window launch, ``open`` and the ``show`` render report (HUB-06, CLI-03).

Also the hub side of the tab and history features: titles, rename, hide and
the version listing (SES-06, SES-08, HIST-02, HIST-05, PAGE-06).
"""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import httpx
import pytest
from test_page_watching import FakeShell, new_session, post_show

pytestmark = pytest.mark.integration

LAUNCHING = pytest.mark.hub_config(open_window=True)


def prepared(hub, home: Path, html: str = "<p>x</p>") -> tuple[str, Path]:  # noqa: ANN001
    sid, folder = new_session(hub, home)
    (folder / "page.html").write_text(html)
    return sid, folder


def api(hub, method: str, path: str, **kwargs):  # noqa: ANN001, ANN201
    return httpx.request(
        method, f"{hub.base_url}{path}", headers=hub.key_headers, timeout=15, **kwargs
    )


# ---- HUB-06 ----------------------------------------------------------------


@LAUNCHING
def test_hub_06_no_launch_while_a_shell_is_connected(hub, home) -> None:
    sid, _ = prepared(hub, home)
    shell = FakeShell(hub)
    try:
        shell.auto_report = {"type": "page-report", "name": "loaded", "data": {}}
        answer = post_show(hub, sid, home / "proj")
        assert answer["window"] == "connected"
        assert hub.launches == []
    finally:
        shell.close()


@LAUNCHING
def test_hub_06_two_shows_one_second_apart_launch_once_then_again_after_10_s(
    hub, home
) -> None:
    sid, _ = prepared(hub, home)
    assert post_show(hub, sid, home / "proj")["window"] == "launched"
    hub.clock.advance(1)
    assert post_show(hub, sid, home / "proj")["window"] == "launched"
    assert len(hub.launches) == 1
    hub.clock.advance(10)
    post_show(hub, sid, home / "proj")
    assert len(hub.launches) == 2


@LAUNCHING
def test_hub_06_url_is_one_argument_with_a_single_use_login_token(
    hub, home, tmp_path: Path
) -> None:
    script = tmp_path / "argv.sh"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$#" "$@" > "{tmp_path}/argv.txt"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    # The command comes from the config, so rebuild the launcher's command.
    hub.app.state.launcher._config = type(hub.app.state.launcher._config)(
        port=hub.port,
        window_command=f"{script} --app={{url}} 'two words; touch x'",
        window_wrapper="none",
    )
    sid, _ = prepared(hub, home)
    post_show(hub, sid, home / "proj")
    count, app_arg, second = (tmp_path / "argv.txt").read_text().splitlines()
    assert (count, second) == ("2", "two words; touch x")
    assert app_arg.startswith(f"--app=http://127.0.0.1:{hub.port}/login?t=")
    login = httpx.get(app_arg.removeprefix("--app="), follow_redirects=False)
    assert login.status_code == 302
    assert httpx.get(app_arg.removeprefix("--app=")).status_code == 401  # single use
    assert not (tmp_path / "x").exists()


@pytest.mark.hub_config(open_window=True, window_command="false {url}")
def test_hub_06_failing_command_gives_launch_failed_and_show_still_succeeds(
    hub, home
) -> None:
    sid, _ = prepared(hub, home)
    answer = post_show(hub, sid, home / "proj")
    assert (answer["window"], answer["rendered"]) == ("launch-failed", False)


@pytest.mark.hub_config(open_window=True, window_command="/nonexistent/browser {url}")
def test_hub_06_missing_program_gives_launch_failed(hub, home) -> None:
    sid, _ = prepared(hub, home)
    assert post_show(hub, sid, home / "proj")["window"] == "launch-failed"


def test_hub_06_open_window_false_gives_disabled_and_no_launch(hub, home) -> None:
    sid, _ = prepared(hub, home)
    answer = post_show(hub, sid, home / "proj")
    assert (answer["window"], answer["rendered"]) == ("disabled", False)
    assert hub.launches == []


# ---- CLI-03 -------------------------------------------------------------------


@LAUNCHING
def test_cli_03_recorder_window_gives_pending_after_the_wait(hub, home) -> None:
    sid, _ = prepared(hub, home)
    started = time.monotonic()
    answer = post_show(hub, sid, home / "proj")
    assert answer["rendered"] == "pending"
    assert 1.8 < time.monotonic() - started < 4


def test_cli_03_disabled_window_gives_false_at_once(hub, home) -> None:
    sid, _ = prepared(hub, home)
    started = time.monotonic()
    assert post_show(hub, sid, home / "proj")["rendered"] is False
    assert time.monotonic() - started < 1.5


# ---- open --print-url (CLI-18) ---------------------------------------------------


def test_cli_18_print_url_returns_a_fresh_login_url_and_launches_nothing(hub) -> None:
    answer = api(hub, "POST", "/api/open", json={"print_url": True}).json()
    assert list(answer) == ["url"]
    assert answer["url"].startswith(f"http://127.0.0.1:{hub.port}/login?t=")
    assert hub.launches == []


@LAUNCHING
def test_cli_18_print_url_does_not_launch_even_when_windows_are_enabled(hub) -> None:
    api(hub, "POST", "/api/open", json={"print_url": True})
    assert hub.launches == []


def test_cli_18_the_printed_url_logs_in_once(hub) -> None:
    url = api(hub, "POST", "/api/open", json={"print_url": True}).json()["url"]
    first = httpx.get(url, follow_redirects=False)
    assert first.status_code == 302 and "set-cookie" in first.headers
    assert httpx.get(url, follow_redirects=False).status_code == 401


def test_cli_18_each_call_gives_a_different_token(hub) -> None:
    urls = {
        api(hub, "POST", "/api/open", json={"print_url": True}).json()["url"]
        for _ in range(2)
    }
    assert len(urls) == 2


def test_cli_18_print_url_needs_the_key(hub) -> None:
    response = httpx.post(f"{hub.base_url}/api/open", json={"print_url": True})
    assert response.status_code in (401, 403)


def test_cli_18_command_prints_just_the_url(cli, hub) -> None:
    done = cli("open", "--print-url")
    assert done.code == 0, done.err
    assert done.out.count("\n") == 1
    assert done.out.strip().startswith(f"http://127.0.0.1:{hub.port}/login?t=")
    assert hub.launches == []


# ---- open -----------------------------------------------------------------------


@LAUNCHING
def test_hub_06_open_states_launched_connected(hub) -> None:
    assert api(hub, "POST", "/api/open", json={}).json() == {"window": "launched"}
    assert len(hub.launches) == 1
    shell = FakeShell(hub)
    try:
        assert api(hub, "POST", "/api/open", json={}).json() == {"window": "connected"}
    finally:
        shell.close()
    assert len(hub.launches) == 1


@pytest.mark.hub_config(open_window=True, window_command="false {url}")
def test_hub_06_open_state_launch_failed(hub) -> None:
    assert api(hub, "POST", "/api/open", json={}).json() == {"window": "launch-failed"}


def test_hub_06_open_state_disabled(hub) -> None:
    assert api(hub, "POST", "/api/open", json={}).json() == {"window": "disabled"}


def test_hub_06_open_command_prints_the_state(cli) -> None:
    assert cli("open").json == {"window": "disabled"}


# ---- SES-06 / SES-08 on the hub ---------------------------------------------------


def read_meta(folder: Path) -> dict:
    return json.loads((folder / "session.json").read_text())


def own_meta(folder: Path, sid: str) -> dict:
    """The session's own record, beside the pool folder it shows pages from."""
    return read_meta(folder.parent / sid)


def cards(tabs: list[dict]) -> list[dict]:
    """The session tabs, without the pool's own tab (POOL Q4)."""
    return [t for t in tabs if t["agent"] != "project"]


def test_ses_06_title_falls_back_to_page_title_then_session_prefix(hub, home) -> None:
    sid, folder = prepared(
        hub, home, "<html><head><title>  My &amp; page </title></head><body>x</body>"
    )
    post_show(hub, sid, home / "proj")
    assert [t["title"] for t in cards(hub.state.tabs_provider())] == ["My & page"]
    other, other_folder = new_session(hub, home)
    (other_folder / "page.html").write_text("<p>no title</p>")
    post_show(hub, other, home / "proj")
    titles = {t["id"]: t["title"] for t in hub.state.tabs_provider()}
    assert titles[other] == other[:8]


def test_ses_06_rename_keeps_both_titles_and_wins_over_agent(hub, home) -> None:
    sid, folder = prepared(hub, home)
    post_show(hub, sid, home / "proj")
    assert api(
        hub, "POST", f"/api/sessions/{sid}/rename", json={"title": "Mine"}
    ).is_success
    api(hub, "POST", f"/api/sessions/{sid}/title", json={"title": "Agent"})
    meta = own_meta(folder, sid)
    assert (meta["owner_title"], meta["title"]) == ("Mine", "Agent")
    assert cards(hub.state.tabs_provider())[0]["title"] == "Mine"
    api(hub, "POST", f"/api/sessions/{sid}/rename", json={"title": " "})
    assert cards(hub.state.tabs_provider())[0]["title"] == "Agent"


def test_ses_08_hide_sets_hidden_and_show_unhides(hub, home) -> None:
    sid, folder = prepared(hub, home)
    post_show(hub, sid, home / "proj")
    api(hub, "POST", f"/api/sessions/{sid}/end", json={})
    assert cards(hub.state.tabs_provider())[0]["state"] == "ended"
    api(hub, "POST", f"/api/sessions/{sid}/hide", json={})
    assert own_meta(folder, sid)["hidden"] is True
    assert cards(hub.state.tabs_provider()) == []
    assert (folder / "page.html").exists()
    post_show(hub, sid, home / "proj")
    assert own_meta(folder, sid)["hidden"] is False
    assert [t["id"] for t in cards(hub.state.tabs_provider())] == [sid]


# ---- SES-12 / SES-07 on the hub ---------------------------------------------------


def test_ses_12_tabs_message_lists_closed_sessions_and_unhide_reopens_one(
    hub, home
) -> None:
    older, older_folder = prepared(hub, home)
    post_show(hub, older, home / "proj")
    newer, _ = prepared(hub, home)
    post_show(hub, newer, home / "proj")
    for sid in (older, newer):
        api(hub, "POST", f"/api/sessions/{sid}/hide", json={})
    message = hub.state.tabs_message()
    assert cards(message["sessions"]) == []
    assert [t["id"] for t in message["closed"]] == [newer, older]
    assert message["closed"][0]["pages"] == ["page.html"]
    answer = api(hub, "POST", f"/api/sessions/{older}/unhide", json={})
    assert answer.json() == {"session": older, "hidden": False}
    assert own_meta(older_folder, older)["hidden"] is False
    message = hub.state.tabs_message()
    assert [t["id"] for t in cards(message["sessions"])] == [older]
    assert [t["id"] for t in message["closed"]] == [newer]


def test_ses_12_unhide_of_an_unknown_session_is_404(hub) -> None:
    unknown = "00000000-0000-4000-8000-000000000000"
    assert (
        api(hub, "POST", f"/api/sessions/{unknown}/unhide", json={}).status_code == 404
    )


@LAUNCHING
def test_ses_07_a_window_launched_by_show_opens_on_that_page_once(hub, home) -> None:
    sid, _ = prepared(hub, home)
    assert post_show(hub, sid, home / "proj")["window"] == "launched"
    first = hub.state.tabs_message(initial=True)
    assert first["show"] == {"session": sid, "page": "page.html"}
    assert hub.state.tabs_message(initial=True)["show"] is None


def test_ses_07_without_a_launch_a_new_window_names_no_page(hub, home) -> None:
    sid, _ = prepared(hub, home)
    assert post_show(hub, sid, home / "proj")["window"] == "disabled"
    assert hub.state.tabs_message(initial=True)["show"] is None


# ---- PAGE-06 / HIST-02 / HIST-05 on the hub ----------------------------------------


def test_page_06_edit_of_the_inactive_page_adds_a_version_only(hub, home) -> None:
    sid, folder = prepared(hub, home, "<p>a</p>")
    (folder / "b.html").write_text("<p>b</p>")
    post_show(hub, sid, home / "proj")
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/show",
        headers=hub.key_headers,
        json={"project": str(home / "proj"), "name": "b.html"},
    ).json()
    assert answer["page"] == "b.html"
    shell = FakeShell(hub)
    try:
        (folder / "page.html").write_text("<p>a2</p>")
        updates = shell.updates(1.5)
        assert [u["url"].rsplit("/", 1)[1] for u in updates] == ["page.html"]
    finally:
        shell.close()
    meta = read_meta(folder)
    assert (meta["active_page"], meta["pages"]) == ("b.html", ["page.html", "b.html"])
    versions = api(hub, "GET", f"/api/sessions/{sid}/versions?page=page.html").json()
    assert [v["version"] for v in versions["versions"]] == [1, 2]


def test_hist_02_version_listing_and_read_only_version_url(hub, home) -> None:
    sid, folder = prepared(hub, home, "<p>one</p>")
    post_show(hub, sid, home / "proj")
    (folder / "page.html").write_text("<p>two</p>")
    path = f"/api/sessions/{sid}/versions?page=page.html"
    hub.wait_for(lambda: len(api(hub, "GET", path).json()["versions"]) == 2, timeout=15)
    listing = api(hub, "GET", path).json()
    assert [v["version"] for v in listing["versions"]] == [1, 2]
    assert listing["versions"][0]["time"].endswith("Z")
    token = hub.state.session_of(hub.pool_of(sid)).page_token
    url = f"{hub.frame_origin}/s/{token}/page.html"
    old = httpx.get(f"{url}?v=1")
    assert "one" in old.text and "/static/helper.js" in old.text
    assert httpx.get(f"{url}?v=9").status_code == 404
    history_url = f"{hub.frame_origin}/s/{token}/history/pages/page.0001.html"
    assert httpx.get(history_url).status_code == 404
    assert (
        api(hub, "GET", f"/api/sessions/{sid}/versions?page=../x.html").status_code
        == 404
    )


def test_hist_05_assets_are_not_copied_into_history(hub, home) -> None:
    sid, folder = prepared(hub, home, "<img src='pic.png'><p>x</p>")
    (folder / "pic.png").write_bytes(b"\x89PNG fake")
    post_show(hub, sid, home / "proj")
    names = sorted(p.name for p in (folder / "history").rglob("*") if p.is_file())
    assert names == ["page.0001.html"]


@pytest.mark.hub_config(open_window=True, window_wrapper="auto")
def test_hub_06_a_failing_wrapper_falls_back_to_the_plain_command(
    hub, home, tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    failing = tmp_path / "failing-wrapper"
    failing.write_text("#!/bin/sh\nexit 1\n")
    failing.chmod(failing.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(
        "agent_canvas.hub.window._which",
        lambda name: str(failing) if name == "systemd-run" else None,
    )
    sid, _ = prepared(hub, home)
    assert post_show(hub, sid, home / "proj")["window"] == "launched"
    hub.wait_for(lambda: len(hub.launches) == 1)
