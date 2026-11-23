"""The Markdown viewer and its cleaning step (VIEW-03, A-61, early check 15).

The fixture holds one hostile element per probe vector. Every probe records itself
twice if it runs: in ``window.__probes`` of its frame and as a request for
``probe-<name>.png``; the tests read both.
"""

# ruff: noqa: E501  (the scripts run in the frame are one-line strings)
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import PACKAGE_DIR

from .support import block, call

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "comments"
FIXTURE = (FIXTURES / "view-03.md").read_text()
PROBES = [
    "script",
    "img-onerror",
    "js-link",
    "iframe",
    "object",
    "embed",
    "svg-link",
    "form-action",
    "button-formaction",
]
# What a probe's element is clicked or submitted with, where it needs a gesture.
GESTURES = {
    "js-link": "#js-link",
    "svg-link": "#svg-text",
    "form-action": "#form-submit",
    "button-formaction": "#formaction",
}


def open_markdown(
    owner, made, name: str = "notes.md", text: str = FIXTURE
) -> list[str]:  # noqa: ANN001
    """Show ``name`` in the session and return the list the request log fills."""
    requests: list[str] = []
    owner.context.on("request", lambda request: requests.append(request.url))
    (made.folder / name).write_text(text)
    (made.folder / "fixture-pic.png").write_bytes(
        (FIXTURES / "fixture-pic.png").read_bytes()
    )
    call(
        owner,
        "POST",
        f"/api/sessions/{made.sid}/show",
        json={"project": str(made.folder.parents[1]), "name": name},
    )
    owner.frame.wait_for_selector("main.markdown h1")
    return requests


def probes_run(frame, requests: list[str]) -> set[str]:  # noqa: ANN001
    """Click every gesture probe, wait for requests, and return the probes that ran."""
    for selector in GESTURES.values():
        frame.evaluate(
            f"document.querySelector({selector!r})?.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true}}))"
        )
    frame.page.wait_for_timeout(500)
    ran = set(frame.evaluate("window.__probes || []"))
    for url in requests:
        if "/probe-" in url:
            ran.add(url.rsplit("/probe-", 1)[1].removesuffix(".png"))
    return ran


@pytest.fixture
def viewer(make, owner):  # noqa: ANN001, ANN201
    """The fixture shown in the Markdown viewer: ``(frame, request log, made)``."""
    made = make("<p>first</p>")
    requests = open_markdown(owner, made)
    return owner.frame, requests, made


def test_view_03_fixture_renders_in_the_light_dom_without_page_errors(
    viewer, owner
) -> None:  # noqa: ANN001
    errors: list[str] = []
    owner.page.on("pageerror", lambda error: errors.append(str(error)))
    frame, _, _ = viewer
    frame.wait_for_selector("main.markdown .katex-display")
    frame.wait_for_function("document.querySelector('main.markdown img').complete")
    seen = frame.evaluate(
        """() => {
      const main = document.querySelector('main.markdown');
      const image = main.querySelector('img');
      const heading = main.querySelector('h1');
      const range = document.createRange();
      range.selectNodeContents(heading);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      return {
        shadowHosts: [main, ...main.querySelectorAll('*')].filter((e) => e.shadowRoot).length,
        rows: main.querySelectorAll('table tbody tr').length,
        code: main.querySelector('pre code').textContent,
        inline: main.querySelectorAll('p .katex:not(.katex-display .katex)').length,
        display: main.querySelectorAll('.katex-display').length,
        imageLoaded: image.complete && image.naturalWidth > 0,
        imageUrl: image.src,
        linkUrl: main.querySelector('a[href$="other.html"]').href,
        selected: getSelection().toString(),
        base: location.href,
      };
    }"""
    )
    assert seen["shadowHosts"] == 0
    assert seen["rows"] == 2
    assert "$not math$" in seen["code"]
    assert seen["inline"] == 1
    assert seen["display"] == 1
    assert seen["imageLoaded"]
    assert seen["selected"] == "Heading of the fixture"
    folder = seen["base"].split("notes.md")[0]
    assert seen["imageUrl"] == folder + "fixture-pic.png"
    assert seen["linkUrl"] == folder + "other.html"
    assert errors == []


@pytest.mark.parametrize("probe", PROBES)
def test_view_03_probe_does_not_run_and_leaves_nothing_behind(
    viewer, probe: str
) -> None:
    frame, requests, _ = viewer
    assert probe not in probes_run(frame, requests)


def test_view_03_cleaned_document_has_no_forbidden_element_attribute_or_url(
    viewer,
) -> None:  # noqa: ANN001
    frame, _, _ = viewer
    left = frame.evaluate(
        """() => {
      const main = document.querySelector('main.markdown');
      const all = [...main.querySelectorAll('*')];
      const urls = ['href', 'src', 'xlink:href', 'action', 'formaction'];
      return {
        elements: main.querySelectorAll('script, iframe, object, embed').length,
        handlers: all.filter((e) => [...e.attributes].some((a) => /^on/i.test(a.name))).length,
        urls: all.filter((e) => urls.some((n) => /^\\s*javascript:/i.test(e.getAttribute(n) || ''))).length,
        keptHtml: main.querySelectorAll('svg, form, button, img[src="x"]').length,
      };
    }"""
    )
    assert left["elements"] == left["handlers"] == left["urls"] == 0
    assert left["keptHtml"] == 5  # the rest of the raw HTML is shown as in a page


HIDDEN_SCRIPT_LINKS = [
    "jav&#9;ascript:window.hit=1",
    "jav&#10;ascript:window.hit=1",
    "jav&#13;ascript:window.hit=1",
    "JaVaScRiPt:window.hit=1",
    "&#32;&#32;javascript:window.hit=1",
    "&#1;javascript:window.hit=1",
    "vbscript:msgbox(1)",
    "data:text/html,<script>window.hit=1</script>",
]
KEPT_LINKS = [
    "https://example.org/a",
    "http://example.org/a",
    "mailto:someone@example.org",
    "other.html",
    "#section",
    "?q=1",
]


def test_view_03_link_is_judged_after_the_browsers_own_parsing(viewer) -> None:  # noqa: ANN001
    """F1 of the M24 review: hidden tabs, newlines, blanks and other schemes."""
    frame, _, _ = viewer
    result = frame.evaluate(
        """async ([bad, good]) => {
      const {cleanHtml} = await import('/static/markdown-render.js');
      const kept = (html) => {
        const box = document.createElement('div');
        box.append(cleanHtml(html));
        return box.innerHTML;
      };
      const out = {bad: {}, good: {}};
      for (const value of bad) {
        out.bad[value] = [
          kept(`<a href="${value}">x</a>`),
          kept(`<img src="${value}">`),
          kept(`<svg><a xlink:href="${value}"><text>x</text></a></svg>`),
          kept(`<form action="${value}"></form>`),
          kept(`<button formaction="${value}">b</button>`),
        ];
      }
      for (const value of good) out.good[value] = kept(`<a href="${value}">x</a>`);
      out.imageData = kept('<img src="data:image/png;base64,AAAA">');
      out.linkData = kept('<a href="data:image/png;base64,AAAA">x</a>');
      return out;
    }""",
        [HIDDEN_SCRIPT_LINKS, KEPT_LINKS],
    )
    for value, outputs in result["bad"].items():
        for html in outputs:
            assert "script:" not in html.lower().replace("&#", ""), (value, html)
            assert "href=" not in html and "src=" not in html, (value, html)
            assert "action=" not in html, (value, html)
    # Positive controls: the check is not vacuous, ordinary addresses stay.
    assert len(result["bad"]) == len(HIDDEN_SCRIPT_LINKS)
    for value, html in result["good"].items():
        assert "href=" in html, (value, html)
    assert "src=" in result["imageData"]
    assert "href=" not in result["linkData"]


def test_view_03_control_uncleaned_html_does_run_a_probe(viewer) -> None:  # noqa: ANN001
    """Positive control: the same text without the cleaning step runs ``onerror``."""
    frame, requests, _ = viewer
    frame.evaluate(
        """async (text) => {
      const {markdownToHtml} = await import('/static/markdown-render.js');
      const scratch = document.createElement('div');
      scratch.innerHTML = await markdownToHtml(text);
      document.body.append(scratch);
    }""",
        FIXTURE,
    )
    assert "img-onerror" in probes_run(frame, requests)


@pytest.mark.parametrize(
    ("scheme", "foreground", "background"),
    [
        ("light", "rgb(31, 35, 40)", "rgb(255, 255, 255)"),
        ("dark", "rgb(230, 237, 243)", "rgb(20, 24, 29)"),
    ],
)
def test_view_03_typography_is_the_kits_in_light_and_dark(
    viewer, owner, scheme, foreground, background
) -> None:  # noqa: ANN001
    owner.page.emulate_media(color_scheme=scheme)
    frame, _, _ = viewer
    style = frame.evaluate(
        """() => ({
      color: getComputedStyle(document.body).color,
      background: getComputedStyle(document.body).backgroundColor,
      font: getComputedStyle(document.querySelector('main.markdown p')).fontFamily,
      heading: getComputedStyle(document.querySelector('main.markdown h1')).fontSize,
    })"""
    )
    assert (style["color"], style["background"]) == (foreground, background)
    assert style["font"].startswith("system-ui")
    assert style["heading"] == "30.4px"


def test_view_03_block_uses_the_same_renderer_and_cleaning(make, owner) -> None:  # noqa: ANN001
    page = block("canvas-markdown", "doc", {"src": "hostile.md"})
    made = make(page, files={"hostile.md": FIXTURE, "fixture-pic.png": b""})
    requests: list[str] = []
    owner.context.on("request", lambda request: requests.append(request.url))
    owner.frame.wait_for_function(
        "document.querySelector('canvas-markdown')?.shadowRoot?.querySelector('.markdown h1')"
    )
    html = owner.frame.evaluate(
        "document.querySelector('canvas-markdown').shadowRoot.querySelector('.markdown').innerHTML"
    )
    assert "onerror" not in html
    assert "javascript:" not in html
    assert "<script" not in html
    assert "<iframe" not in html
    assert probes_run(owner.frame, requests) == set()
    assert made.sid


def test_view_03_one_cleaning_step_in_one_module() -> None:
    static = PACKAGE_DIR / "static"
    for path in (static / "viewer" / "markdown.js", static / "blocks" / "markdown.js"):
        text = path.read_text()
        assert "markdown-render.js" in text or "renderMarkdown" in text
        assert "innerHTML" not in text
        assert "DOMParser" not in text
