# ruff: noqa: E501
"""Early check 18 (P26.7): may the shell write the clipboard on a click in the page frame?

The frame is ``sandbox="allow-scripts"`` and cross-origin to the shell. A probe
listener in the shell writes the clipboard when the frame posts a message; the
result is read back through Playwright's clipboard permissions. Positive
control: a real click on a shell button writes and reads back. Negative
control: the same write made inside the sandboxed frame is refused.
"""

from __future__ import annotations

import time

import pytest

from .support import SCROLL_PAGE

pytestmark = pytest.mark.browser

PROBE = """
window.__probe = [];
window.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "probe") return;
  const t0 = performance.now();
  setTimeout(() => {
    const active = navigator.userActivation.isActive;
    navigator.clipboard.writeText(event.data.text).then(
      () => window.__probe.push({ok: true, active, ms: Math.round(performance.now() - t0)}),
      (e) => window.__probe.push({ok: false, active, error: String(e)}));
  }, event.data.wait || 0);
});
const shellButton = document.createElement("button");
shellButton.id = "shell-probe";
shellButton.style.cssText = "position:fixed;left:0;bottom:0;z-index:99";
shellButton.textContent = "shell";
shellButton.onclick = () => navigator.clipboard.writeText("from-shell").then(
  () => window.__probe.push({ok: true, source: "shell"}),
  (e) => window.__probe.push({ok: false, source: "shell", error: String(e)}));
document.body.append(shellButton);
"""

FRAME_PROBE = """
window.__own = [];
window.sendProbe = (text, wait) => window.parent.postMessage({type: 'probe', text, wait}, '*');
document.getElementById('b').onclick = () => window.sendProbe('from-frame', 0);
document.getElementById('t').onclick = () => navigator.clipboard.writeText('from-inside').then(
  () => window.__own.push({ok: true}), (e) => window.__own.push({ok: false, error: String(e)}));
"""


def probes(owner) -> list:  # noqa: ANN001
    return owner.page.evaluate("window.__probe")


def clipboard(owner) -> str:  # noqa: ANN001
    return owner.page.evaluate("navigator.clipboard.readText()")


def settle(owner, count: int) -> None:  # noqa: ANN001
    owner.page.wait_for_function(f"window.__probe.length >= {count}", timeout=15000)


@pytest.fixture
def probed(owner, make):  # noqa: ANN001, ANN201
    owner.context.grant_permissions(["clipboard-read", "clipboard-write"])
    made = make(SCROLL_PAGE)
    owner.page.evaluate(PROBE)
    owner.frame.evaluate(FRAME_PROBE)
    return made


def test_check18_positive_control_a_click_in_the_shell_writes_and_reads_back(
    owner, probed
) -> None:  # noqa: ANN001
    owner.page.click("#shell-probe")
    settle(owner, 1)
    assert probes(owner)[0]["ok"] is True, probes(owner)
    assert clipboard(owner) == "from-shell"


def test_check18_a_click_in_the_sandboxed_frame_lets_the_shell_write(
    owner, probed
) -> None:  # noqa: ANN001
    owner.page.click("#shell-probe")
    settle(owner, 1)
    assert clipboard(owner) == "from-shell"
    owner.frame.click("#b")
    settle(owner, 2)
    result = probes(owner)[1]
    print("frame click, shell writes:", result)
    assert result["ok"] is True and result["active"] is True
    assert clipboard(owner) == "from-frame"


def test_check18_negative_control_the_frame_cannot_write_the_clipboard_itself(
    owner, probed
) -> None:  # noqa: ANN001
    owner.page.click("#shell-probe")
    settle(owner, 1)
    owner.frame.click("#t")
    owner.frame.wait_for_function("window.__own.length > 0")
    own = owner.frame.evaluate("window.__own")
    print("frame writes itself after a click:", own)
    assert own[0]["ok"] is False
    assert clipboard(owner) == "from-shell"


@pytest.mark.parametrize("wait", [1500, 7000])
def test_check18_the_write_after_a_wait_for_the_hub(owner, probed, wait: int) -> None:  # noqa: ANN001
    owner.page.click("#shell-probe")
    settle(owner, 1)
    time.sleep(6)  # the activation of the shell click has run out
    owner.frame.evaluate(
        f"document.getElementById('b').onclick = () => window.sendProbe('late', {wait})"
    )
    owner.frame.click("#b")
    settle(owner, 2)
    result = probes(owner)[1]
    print(f"write {wait} ms after the click:", result)
    assert result["ok"] is True
    assert result["active"] is (wait < 5000)
    assert clipboard(owner) == "late"
