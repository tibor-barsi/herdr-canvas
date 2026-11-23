"""The lost report route (ANC-06, COM-18, ARC-02): who sends it, what it stores."""

# ruff: noqa: F811  (the fixtures are imported from the comment route tests)
from __future__ import annotations

import time

import httpx
import pytest
from test_com_04_comment_routes import (  # noqa: F401
    owner,
    save,
    shell,
    shown,
    url,
)

from agent_canvas.hub import comments

pytestmark = pytest.mark.integration


def report(owner, shown, reports) -> httpx.Response:  # noqa: ANN001
    body = {"page": "page.html", "reports": reports}
    return owner.post(url(shown, "/lost"), json=body)


def test_anc_06_a_lost_report_is_stored_and_one_comments_message_follows(
    hub, owner, shell, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    save(owner, shown)
    hub.wait_for(lambda: shell.types() == ["comments", "comments"])
    shell.messages.clear()
    answer = report(owner, shown, [{"n": 2, "lost": True}])
    assert answer.status_code == 200 and answer.json()["stored"] is True
    hub.wait_for(lambda: shell.types() == ["comments"])
    flags = [(c["n"], c["lost"]) for c in shell.messages[0]["comments"]]
    assert flags == [(1, False), (2, True)]
    stored = comments.load(shown["folder"], "page.html")["comments"][1]
    assert stored["lost"] is True and stored["anchored_version"] == 1
    # The same report again changes nothing, so nothing is pushed.
    shell.messages.clear()
    assert report(owner, shown, [{"n": 2, "lost": True}]).json()["stored"] is False
    time.sleep(0.8)
    assert shell.types() == []


def test_anc_06_the_agent_sees_lost_in_the_list_of_sent_comments(
    cli, owner, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    report(owner, shown, [{"n": 1, "lost": True}])
    comments.take_unsent(shown["folder"], "page.html", "now", "evt_1")
    listed = cli("comment", "list", "--all", "--session", shown["id"]).json
    assert [c["lost"] for c in listed["comments"]] == [True]


def test_anc_06_only_the_owner_may_report_and_a_bad_body_is_refused(
    hub, owner, shown
) -> None:  # noqa: ANN001
    save(owner, shown)
    agent = httpx.post(
        hub.base_url + url(shown, "/lost"),
        json={"page": "page.html", "reports": [{"n": 1, "lost": True}]},
        headers=hub.key_headers,
    )
    assert agent.status_code == 403
    for bad in (
        {"page": "page.html", "reports": "x"},
        {"page": "page.html", "reports": [{"n": 1, "lost": "yes"}]},
        {"page": "page.html", "reports": [{"n": True, "lost": True}]},
        {"page": "../x.html", "reports": []},
        {"page": 3, "reports": []},
    ):
        assert owner.post(url(shown, "/lost"), json=bad).status_code == 400, bad
    assert comments.load(shown["folder"], "page.html")["comments"][0]["lost"] is False
