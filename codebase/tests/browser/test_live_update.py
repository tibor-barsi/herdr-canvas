"""Live update in the browser: morph, script reload, reports, message guard."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

pytestmark = pytest.mark.browser

PROBE_PAGE = """<!doctype html><html><head><title>t</title></head><body>
<h1>Probe</h1>
<input id="q" type="text">
<div style="height:1500px">spacer</div>
<section id="a">A</section>
<section id="b">{b}</section>
<div style="height:1500px">end</div>
</body></html>"""


def open_page(owner, name: str, html: str, session: str = "p"):  # noqa: ANN201
    session_obj = owner.hub.add_session(session, {name: html})
    owner.show(session, name)
    owner.wait_report("loaded")
    return session_obj.folder / name


def test_page_04_morph_keeps_value_focus_caret_scroll_and_identity(owner) -> None:
    page_file = open_page(owner, "page.html", PROBE_PAGE.format(b="old"))
    frame = owner.frame
    frame.focus("#q")
    owner.page.keyboard.type("hello")
    frame.evaluate(
        """() => {
          document.getElementById('q').setSelectionRange(2, 2);
          window.scrollTo(0, 600);
          document.getElementById('a').__probe = 1;
        }"""
    )
    seen = owner.count_reports("updated")
    page_file.write_text(PROBE_PAGE.format(b="new"))
    owner.wait_report_after("updated", seen)
    state = frame.evaluate(
        """() => ({
          value: document.getElementById('q').value,
          focused: document.activeElement.id,
          caret: document.getElementById('q').selectionStart,
          scroll: window.scrollY,
          probe: document.getElementById('a').__probe,
          b: document.getElementById('b').textContent,
        })"""
    )
    assert state == {
        "value": "hello",
        "focused": "q",
        "caret": 2,
        "scroll": 600,
        "probe": 1,
        "b": "new",
    }


def test_page_04_head_style_and_title_are_merged_and_helper_stays_once(owner) -> None:
    page_file = open_page(
        owner,
        "page.html",
        "<html><head><title>one</title><style>p{color:red}</style></head>"
        "<body><p id='p'>x</p></body></html>",
    )
    seen = owner.count_reports("updated")
    page_file.write_text(
        "<html><head><title>two</title><style>p{color:blue}</style></head>"
        "<body><p id='p'>y</p></body></html>"
    )
    owner.wait_report_after("updated", seen)
    state = owner.frame.evaluate(
        """() => ({
          title: document.title,
          styles: [...document.querySelectorAll('style')].map((s) => s.textContent),
          helpers: document.querySelectorAll('script[src="/static/helper.js"]').length,
          first: document.head.firstElementChild.getAttribute('src'),
          color: getComputedStyle(document.getElementById('p')).color,
        })"""
    )
    assert state["title"] == "two"
    assert state["styles"] == ["p{color:blue}"]
    assert state["helpers"] == 1
    assert state["first"] == "/static/helper.js"
    assert state["color"] == "rgb(0, 0, 255)"


def test_page_04_update_before_dom_content_loaded_morphs(owner) -> None:
    # A module script delays DOMContentLoaded past parsing (#4); holding it puts
    # the update in that window.
    held = []
    owner.page.route("**/slow.js", lambda route: held.append(route))
    template = "<p id='p'>{text}</p><script type='module' src='slow.js'></script>"
    session = owner.hub.add_session(
        "p", {"page.html": template.format(text="one"), "slow.js": ""}
    )
    owner.show("p", "page.html")
    for _ in range(500):
        if held:
            break
        owner.page.wait_for_timeout(20)
    owner.frame.wait_for_function("document.readyState === 'interactive'")
    owner.frame.evaluate("window.__probe = 'alive'")
    (session.folder / "page.html").write_text(template.format(text="two"))
    owner.frame.wait_for_function("document.getElementById('p').textContent === 'two'")
    assert owner.frame.evaluate("window.__probe") == "alive"
    for route in held:
        route.continue_()


def test_page_04_blocks_render_after_a_morph_before_the_block_loader_ran(
    owner,  # noqa: ANN001
) -> None:
    held = []
    owner.page.route("**/blocks/loader.js", lambda route: held.append(route))
    template = (
        '<canvas-textbox data-canvas-id="note">'
        '<script type="application/json">{{"label": "{label}"}}</script>'
        "</canvas-textbox>"
        '<canvas-ask data-canvas-id="q1"><script type="application/json">'
        '{{"question": "Keep?", "options": ["keep", "change"]}}</script></canvas-ask>'
    )
    session = owner.hub.add_session("p", {"page.html": template.format(label="one")})
    owner.show("p", "page.html")
    for _ in range(500):
        if held:
            break
        owner.page.wait_for_timeout(20)
    owner.frame.wait_for_function("document.readyState === 'interactive'")
    seen = owner.count_reports("updated")
    (session.folder / "page.html").write_text(template.format(label="two"))
    owner.wait_report_after("updated", seen)
    for route in held:
        route.continue_()
    owner.frame.wait_for_function(
        """() => { const e = document.querySelector('canvas-textbox');
          const a = document.querySelector('canvas-ask');
          return e.renderIdle && e.shadowRoot && e.shadowRoot.querySelector('input')
            && e.shadowRoot.querySelector('label').textContent === 'two'
            && a.renderIdle && a.shadowRoot && a.shadowRoot.querySelector('.k'); }""",
        timeout=10000,
    )


def test_page_05_added_script_reloads_runs_it_and_restores_scroll(owner) -> None:
    body = "<div style='height:3000px'>tall</div><p id='p'>x</p>"
    page_file = open_page(owner, "page.html", body)
    frame = owner.frame
    frame.evaluate("window.scrollTo(0, 500)")
    loaded = owner.count_reports("loaded")
    page_file.write_text(body + "<script>window.v = 2;</script>")
    owner.wait_report_after("loaded", loaded)
    owner.frame.wait_for_function("window.v === 2", timeout=5000)
    owner.frame.wait_for_function("Math.abs(window.scrollY - 500) <= 5", timeout=5000)


def test_page_05_json_only_config_change_keeps_page_state(owner) -> None:
    template = (
        "<div id='out'>x</div><script type='application/json' id='cfg'>{cfg}</script>"
    )
    page_file = open_page(owner, "page.html", template.format(cfg='{"a": 1}'))
    owner.frame.evaluate("window.__probe = 'alive'")
    loaded = owner.count_reports("loaded")
    seen = owner.count_reports("updated")
    page_file.write_text(template.format(cfg='{"a": 2}'))
    owner.wait_report_after("updated", seen)
    state = owner.frame.evaluate(
        "() => ({probe: window.__probe,"
        " cfg: document.getElementById('cfg').textContent})"
    )
    assert state == {"probe": "alive", "cfg": '{"a": 2}'}
    assert owner.count_reports("loaded") == loaded


def test_page_05_changed_script_source_and_removed_script_reload(owner) -> None:
    page_file = open_page(owner, "page.html", "<p>x</p><script>window.n = 1</script>")
    loaded = owner.count_reports("loaded")
    page_file.write_text("<p>x</p>")  # script removed
    owner.wait_report_after("loaded", loaded)
    assert owner.frame.evaluate("window.n") is None


def new_api_session(owner, tmp_path):  # noqa: ANN001, ANN201
    hub = owner.hub
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    answer = httpx.post(
        f"{hub.base_url}/api/sessions",
        headers=hub.key_headers,
        json={"project": str(project)},
    ).json()
    return answer["session"], project, answer["folder"]


def api_show(owner, sid: str, project) -> dict:  # noqa: ANN001
    """Call ``show`` over the API while keeping Playwright's event loop running."""
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            httpx.post,
            f"{owner.hub.base_url}/api/sessions/{sid}/show",
            headers=owner.hub.key_headers,
            json={"project": str(project)},
            timeout=15,
        )
        while not future.done():
            owner.page.wait_for_timeout(20)
        return future.result().json()


def test_page_08_throw_shows_badge_report_and_show_error(owner, tmp_path) -> None:
    from pathlib import Path

    sid, project, folder = new_api_session(owner, tmp_path)
    (Path(folder) / "page.html").write_text(
        "<p>x</p><script>throw new Error('boom')</script>"
    )
    owner.visit(sid)  # the tab is on screen before the page arrives
    answer = api_show(owner, sid, project)
    assert answer["rendered"] is True
    assert [e["source"] for e in answer["errors"]] == ["script"]
    assert "boom" in answer["errors"][0]["message"]
    assert answer["errors"][0]["canvas_id"] is None
    owner.page.wait_for_selector("#tab-badge", state="visible", timeout=5000)
    reports = owner.reports_of("error")
    assert reports and "boom" in reports[0]["message"]


def test_page_08_badge_is_hidden_for_a_healthy_page_and_clears_on_fix(owner) -> None:
    page_file = open_page(owner, "page.html", "<script>throw new Error('bad')</script>")
    owner.page.wait_for_selector("#tab-badge", state="visible", timeout=5000)
    loaded = owner.count_reports("loaded")
    page_file.write_text("<p>fine</p>")
    owner.wait_report_after("loaded", loaded)  # script set changed: reload
    owner.page.wait_for_selector("#tab-badge", state="hidden", timeout=5000)


def test_page_09_document_that_leaves_the_page_triggers_warning_and_reload(
    owner,
) -> None:
    requests: list[str] = []
    owner.context.on("request", lambda r: requests.append(r.url))
    owner.hub.add_session(
        "nav", {"page.html": "<p>x</p><script>location.href='about:blank'</script>"}
    )
    owner.show("nav", "page.html")
    owner.page.wait_for_selector("#warning.visible", timeout=8000)
    assert "did not report ready" in owner.page.text_content("#warning")
    deadline = time.monotonic() + 3
    url = owner.hub.page_url("nav", "page.html")
    while time.monotonic() < deadline and requests.count(url) < 2:
        time.sleep(0.1)
    assert requests.count(url) >= 2


def test_page_09_healthy_page_gets_no_ready_warning(owner) -> None:
    open_page(owner, "page.html", "<p>fine</p>")
    time.sleep(3)
    assert not owner.page.locator("#warning.visible").count()


FORGE_PAGE = """<p>forger</p><script>
const big = "x".repeat(50 * 1024 * 1024);
parent.postMessage({type: "send", message: "forged"}, "*");
parent.postMessage({type: "bogus"}, "*");
parent.postMessage({type: "report", name: "big", data: big}, "*");
window.addEventListener("load", () => setTimeout(() => {
  for (let i = 0; i < 1000; i++)
    parent.postMessage({type: "report", name: "flood", data: i}, "*");
  agentCanvas.report("flooded", true);
}, 300));
</script>"""


def test_sec_09_forged_unknown_oversized_and_flooded_messages(owner) -> None:
    open_page(owner, "page.html", FORGE_PAGE)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and owner.count_reports("flood") < 1:
        time.sleep(0.1)
    time.sleep(1.5)
    guard = owner.page.evaluate("window.__guard")
    assert guard["accepted"].get("send", 0) == 0
    assert guard["accepted"].get("bogus", 0) == 0
    assert guard["dropped"]["type"] >= 2  # send and bogus are not on the list
    assert guard["dropped"]["size"] >= 1
    assert owner.count_reports("big") == 0
    assert owner.count_reports("flood") <= 105
    assert guard["dropped"]["rate"] >= 800
    started = time.monotonic()
    owner.page.click(".hv-fold", timeout=5000)
    owner.page.wait_for_function(
        "document.getElementById('herdr').classList.contains('folded')", timeout=2000
    )
    assert time.monotonic() - started < 0.5


def test_sec_09_shell_ignores_messages_not_from_the_frame(owner) -> None:
    open_page(owner, "page.html", "<p>x</p>")
    owner.page.evaluate(
        "window.postMessage({type: 'report', name: 'self', data: 1}, '*')"
    )
    time.sleep(0.3)
    assert owner.count_reports("self") == 0
    assert owner.page.evaluate("window.__guard.dropped.source") >= 1


def test_sec_09_helper_ignores_update_messages_not_from_its_parent(owner) -> None:
    html = """<p id="t">original</p><script>
    window.addEventListener("load", () => {
      const child = document.createElement("iframe");
      child.srcdoc = "<script>parent.postMessage({type:'update', " +
        "html:'<body><p id=t>evil</p></body>'}, '*')<\\/script>";
      child.sandbox = "allow-scripts";
      document.body.appendChild(child);
    });
    </script>"""
    open_page(owner, "page.html", html)
    time.sleep(1.0)
    assert (
        owner.frame.evaluate("document.getElementById('t').textContent") == "original"
    )


def test_page_05_show_of_the_page_already_shown_keeps_the_frame_state(owner) -> None:
    """Agents run ``show`` after every rewrite; that must not reload the page."""
    page_file = open_page(owner, "page.html", PROBE_PAGE.format(b="old"))
    owner.frame.evaluate("window.__probe = 'alive'; window.scrollTo(0, 600)")
    seen = owner.count_reports("updated")
    page_file.write_text(PROBE_PAGE.format(b="new"))
    owner.hub.show("p", "page.html")  # the second ``show`` of the same page
    owner.wait_report_after("updated", seen)
    owner.page.wait_for_timeout(1500)  # a reload would have happened by now
    state = owner.frame.evaluate(
        "() => ({probe: window.__probe, scroll: window.scrollY,"
        " b: document.getElementById('b').textContent})"
    )
    assert state == {"probe": "alive", "scroll": 600, "b": "new"}
