"""The frame's private channel goes only to the page the shell loaded (SEC-09, ANS-02, A-577 to A-579)."""

# ruff: noqa: E501  (the scripts run in the frame are one-line strings)
from __future__ import annotations

import json
from urllib.parse import quote

import pytest

from .test_view_03_markdown_viewer import open_markdown

pytestmark = pytest.mark.browser

# A document from elsewhere: it logs every message it gets, answers a token with the best
# address it can know, uses any port it is given, and posts answers once it has loaded.
FOREIGN = (
    "<!doctype html><p>elsewhere</p><script>"
    "console.log('FOREIGN loaded');"
    "addEventListener('message', (e) => {"
    " const type = e.data && e.data.type;"
    " console.log('FOREIGN got ' + type + ' ports=' + e.ports.length);"
    " if (type === 'relay-open') parent.postMessage({type: 'relay-open', token: e.data.token, href: document.referrer}, '*');"
    " for (const port of e.ports) port.postMessage({type: 'open-file', path: 'notes.md'});"
    "});"
    "addEventListener('load', () => setInterval(() => parent.postMessage({type: 'answer', id: 'q', value: {v: 1}}, '*'), 50));"
    "</script>"
)
FOREIGN_URL = "data:text/html," + quote(FOREIGN)


def console_of(page) -> list[str]:  # noqa: ANN001
    lines: list[str] = []
    page.on("console", lambda message: lines.append(message.text))
    return lines


def requests_to(page, part: str) -> list[str]:  # noqa: ANN001
    seen: list[str] = []
    page.on("request", lambda r: seen.append(r.url) if part in r.url else None)
    return seen


def wait_for_line(page, lines: list[str], text: str) -> None:  # noqa: ANN001
    for _ in range(100):
        if text in lines:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"{text!r} not in {lines}")


def test_sec_09_a_document_the_page_navigates_to_gets_no_channel_and_the_page_comes_back(
    studio,
) -> None:  # noqa: ANN001
    lines = console_of(studio.page)
    answers = requests_to(studio.page, "/answers/answer")
    studio.make("<p id='own'>own page</p>")
    studio.page.wait_for_function("active && active.relayOpen")
    studio.frame.evaluate(
        f"setTimeout(() => {{ location.href = {json.dumps(FOREIGN_URL)}; }}, 0)"
    )
    wait_for_line(studio.page, lines, "FOREIGN loaded")
    studio.page.wait_for_timeout(1500)
    got = [line for line in lines if line.startswith("FOREIGN got")]
    assert not any("relay-open" in line or "ports=1" in line for line in got), got
    assert answers == []
    # The shell loaded the page again, and that load has its channel.
    studio.page.wait_for_function("active && active.relayOpen")
    assert studio.frame.evaluate("document.getElementById('own') !== null")


def test_sec_09_a_document_that_replaces_the_page_during_its_load_cannot_open_the_relay(
    owner,
) -> None:  # noqa: ANN001
    lines = console_of(owner.page)
    answers = requests_to(owner.page, "/answers/answer")
    owner.hub.add_session(
        "away",
        {
            "page.html": f"<p>x</p><script>location.href = {json.dumps(FOREIGN_URL)};</script>"
        },
    )
    owner.show("away", "page.html")
    wait_for_line(owner.page, lines, "FOREIGN loaded")
    owner.page.wait_for_timeout(2500)
    got = [line for line in lines if line.startswith("FOREIGN got")]
    assert not any("ports=1" in line for line in got), got
    assert answers == []
    assert owner.page.evaluate("active.relayOpen") is False
    assert owner.page.evaluate("active.port") is None


def test_view_03_markdown_meta_link_and_base_are_removed(make, owner) -> None:  # noqa: ANN001
    made = make("<p>first</p>")
    text = (
        "# Title\n\n"
        f'<meta http-equiv="refresh" content="1; url={FOREIGN_URL}">\n\n'
        '<link rel="stylesheet" href="probe.css">\n\n'
        '<base href="sub/">\n\n'
        "after\n"
    )
    open_markdown(owner, made, text=text)
    owner.frame.evaluate("window.__mark = 1")
    owner.page.wait_for_timeout(2000)
    left = owner.frame.evaluate(
        "document.querySelector('main.markdown').querySelectorAll('meta, link, base').length"
    )
    assert left == 0
    assert owner.frame.evaluate("window.__mark") == 1  # the frame stayed on the file


@pytest.mark.parametrize("attribute", ["href", "xlink:href"])
def test_sec_09_an_svg_link_click_does_not_navigate_the_frame(
    studio, attribute: str
) -> None:  # noqa: ANN001
    studio.make(
        f'<svg width="200" height="40"><a id="go" {attribute}="data:text/html,away">'
        '<text x="5" y="25">go</text></a></svg>'
    )
    studio.frame.evaluate("window.__mark = 1")
    studio.frame.locator("#go text").click()
    studio.page.wait_for_timeout(1000)
    assert studio.frame.evaluate("window.__mark") == 1
    assert studio.frame.evaluate("location.href").endswith("/page.html")
