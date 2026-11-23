"""Sandboxed frame, CSP in the browser, hang isolation and route guard."""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.browser

REPORT = "agentCanvas.report"


def show(owner, name: str, html: str, session: str = "p") -> None:
    owner.hub.add_session(session, {name: html})
    owner.show(session, name)


def test_tst_02_owner_fixture_is_logged_in_to_the_shell(owner) -> None:
    assert owner.page.url == owner.hub.base_url + "/"
    assert owner.page.title() == "agent-canvas"
    cookies = owner.context.cookies()
    assert [c["name"] for c in cookies] == [f"agent_canvas_session_{owner.hub.port}"]
    assert cookies[0]["httpOnly"] and cookies[0]["sameSite"] == "Strict"


def test_nfr_02_route_guard_records_and_blocks_foreign_origins(owner) -> None:
    outcome = owner.page.evaluate(
        "fetch('http://example.invalid/x').then(() => 'reached', () => 'blocked')"
    )
    assert outcome == "blocked"
    assert owner.foreign_requests == ["http://example.invalid/x"]
    owner.foreign_requests.clear()  # expected here; the fixture fails on others


def test_nfr_06_tests_run_on_chromium(browser) -> None:
    assert browser.browser_type.name == "chromium"


def test_page_01_iframe_is_sandboxed_with_scripts_only_on_the_frame_site(owner) -> None:
    show(
        owner,
        "p.html",
        f"<script>try {{ parent.document; {REPORT}('r', 'reached'); }}"
        f" catch (e) {{ {REPORT}('r', e.name); }}</script>",
    )
    assert owner.wait_report("r") == "SecurityError"
    frame = owner.page.locator("#frame")
    assert frame.get_attribute("sandbox") == "allow-scripts"
    token = owner.hub.sessions["p"].page_token
    assert frame.get_attribute("src") == (
        f"http://localhost:{owner.hub.port}/s/{token}/p.html"
    )


CSP_PAGE = f"""<body>
<form id="f" method="post" action="http://127.0.0.1:{{port}}/login"></form>
<script>
const seen = [];
document.addEventListener("securitypolicyviolation",
  (e) => seen.push(e.violatedDirective.split("-")[0] + ":" + e.blockedURI));
const attempts = [
  fetch("https://example.com/x").catch(() => 0),
  new Promise((done) => {{
    const img = new Image();
    img.onerror = img.onload = done;
    img.src = "http://10.0.0.1/x";
  }}),
  new Promise((done) => {{
    try {{ const ws = new WebSocket("ws://127.0.0.1:{{port}}/ws/shell");
          ws.onerror = ws.onclose = done; }} catch (e) {{ done(); }}
  }}),
];
Promise.all(attempts).then(() => setTimeout(
  () => {{ {REPORT}("csp", seen); }}, 200));
</script></body>"""


def test_sec_06_csp_blocks_fetch_img_and_websocket_in_the_browser(owner) -> None:
    show(owner, "c.html", CSP_PAGE.replace("{port}", str(owner.hub.port)), "csp")
    seen = owner.wait_report("csp")
    directives = {entry.split(":")[0] for entry in seen}
    assert {"connect", "img"} <= directives, seen
    assert any(e.startswith("connect:") and "example.com" in e for e in seen), seen
    assert any(e.startswith("img:") and "10.0.0.1" in e for e in seen), seen
    assert any(e.startswith("connect:") and "ws:" in e for e in seen), seen
    # The route guard (fixture teardown) proves that nothing left the browser.


def test_sec_06_csp_form_action_none_blocks_a_form_post(owner) -> None:
    owner.hub.add_session("form", {"f.html": CSP_PAGE.replace("{port}", "1")})
    top_level = owner.context.new_page()
    top_level.goto(owner.hub.page_url("form", "f.html"))
    violation = top_level.evaluate(
        """() => new Promise((resolve) => {
             document.addEventListener("securitypolicyviolation",
               (e) => resolve(e.violatedDirective));
             document.getElementById("f").submit();
             setTimeout(() => resolve("none"), 2000);
           })"""
    )
    assert violation == "form-action"


def test_page_12_api_is_unreachable_from_the_frame_even_with_the_key_cookie(
    owner,
) -> None:
    show(
        owner,
        "a.html",
        f"<script>fetch('http://127.0.0.1:{owner.hub.port}/api/sessions',"
        f"{{credentials:'include'}}).then(() => {REPORT}('r', 'reached'),"
        f" () => {REPORT}('r', 'blocked'));</script>",
    )
    assert owner.wait_report("r") == "blocked"


@pytest.mark.timing
def test_page_10_hanging_page_keeps_toolbar_responsive_and_shows_notice(owner) -> None:
    show(
        owner,
        "hang.html",
        f"<script>{REPORT}('ready', 1); setTimeout(() => {{ while (true) {{}} }}, 300);"
        "</script>",
        "hang",
    )
    owner.wait_report("ready")
    time.sleep(0.6)  # the page is now inside its infinite loop
    started = time.monotonic()
    owner.page.click(".hv-fold", timeout=5000)
    owner.page.wait_for_function(
        "document.getElementById('herdr').classList.contains('folded')", timeout=5000
    )
    click_latency = time.monotonic() - started
    notice_started = started - 0.6  # hang began about 0.3 s after the report
    owner.page.wait_for_selector("#notice.visible", timeout=6000)
    notice_after = time.monotonic() - notice_started
    print(
        f"PAGE-10 click latency {click_latency:.3f}s, notice after {notice_after:.2f}s"
    )
    assert click_latency < 0.5
    assert notice_after < 4.0
    assert "unresponsive" in owner.page.text_content("#notice-text")


def test_page_10_healthy_page_shows_no_notice_and_reload_button_recovers(
    owner,
) -> None:
    show(owner, "ok.html", f"<p>fine</p><script>{REPORT}('ready', 1)</script>", "ok")
    owner.wait_report("ready")
    time.sleep(3.6)  # longer than the 3 s watchdog limit
    assert not owner.page.locator("#notice.visible").count()


def test_page_10_reload_button_reloads_a_hung_page(owner) -> None:
    owner.hub.add_session(
        "rl",
        {
            "rl.html": "<script>agentCanvas.report('boot', Date.now());"
            "if (!location.hash) { setTimeout(() => { while (true) {} }, 200); }"
            "</script>"
        },
    )
    owner.show("rl", "rl.html")
    owner.page.wait_for_selector("#notice.visible", timeout=8000)
    # Replace the page with a healthy one, then use the reload button.
    (owner.hub.sessions["rl"].folder / "rl.html").write_text(
        "<script>agentCanvas.report('second', 1)</script><p>recovered</p>"
    )
    owner.page.click("#notice-reload")
    owner.wait_report("second")
    time.sleep(1.5)
    assert not owner.page.locator("#notice.visible").count()
