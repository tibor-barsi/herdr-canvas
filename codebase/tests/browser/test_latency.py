"""NFR-01: file write to new content in the frame DOM."""

from __future__ import annotations

import logging
import statistics
import time

import pytest

pytestmark = pytest.mark.browser

log = logging.getLogger(__name__)

FILLER = "".join(
    f'<p class="row" data-i="{i}">Row {i}: the quick brown fox jumps over the lazy dog.'
    " Pack my box with five dozen liquor jugs.</p>\n"
    for i in range(800)
)


def build_page(tag: str) -> str:
    return f"<!doctype html><html><body><h1 id='m'>{tag}</h1>\n{FILLER}</body></html>"


@pytest.mark.timing
def test_nfr_01_write_to_dom_latency_p95_and_max(owner) -> None:
    assert len(build_page("v00").encode()) >= 100_000
    session = owner.hub.add_session("lat", {"page.html": build_page("v00")})
    owner.show("lat", "page.html")
    owner.wait_report("loaded")
    frame = owner.frame
    frame.evaluate(
        """() => {
          window.__seen = {};
          const note = () => {
            const text = document.getElementById('m').textContent;
            if (!(text in window.__seen)) window.__seen[text] = Date.now();
          };
          new MutationObserver(note).observe(document, {
            subtree: true, childList: true, characterData: true});
        }"""
    )
    page_file = session.folder / "page.html"
    samples: list[float] = []
    for index in range(1, 21):
        tag = f"v{index:02d}"
        page_file.write_text(build_page(tag))
        written = time.time()
        frame.wait_for_function(f"window.__seen['{tag}']", polling=5, timeout=5000)
        seen = frame.evaluate(f"window.__seen['{tag}']") / 1000
        samples.append(seen - written)
        time.sleep(1.0)
    ordered = sorted(samples)
    p95 = ordered[int(0.95 * len(ordered)) - 1]
    summary = (
        f"NFR-01 samples (s): {[round(s, 3) for s in samples]} "
        f"median={statistics.median(samples):.3f} p95={p95:.3f} max={max(samples):.3f}"
    )
    log.warning(summary)
    print(summary)
    assert p95 < 0.5
    assert max(samples) < 1.0
