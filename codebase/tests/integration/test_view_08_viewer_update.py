"""The update message of a viewer page (VIEW-08) and its load error report (VIEW-14)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from shellfake import FakeShell

pytestmark = pytest.mark.integration


@pytest.fixture
def folder(cli) -> Path:  # noqa: ANN001
    return Path(cli("session", "path", "--session", "a").json["folder"])


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    fake = FakeShell(hub)
    yield fake
    fake.close()


def updates(hub, shell: FakeShell, count: int) -> list[dict]:  # noqa: ANN001
    hub.wait_for(
        lambda: [m for m in shell.messages if m["type"] == "update"], timeout=5
    )
    time.sleep(0.5)
    found = [m for m in shell.messages if m["type"] == "update"]
    assert len(found) == count, found
    return found


def test_view_08_a_new_markdown_version_is_pushed_as_text_for_the_viewer(
    cli, hub, folder, shell
) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("one")
    assert cli("show", "notes.md", "--session", "a").code == 0
    time.sleep(0.6)
    shell.messages.clear()
    (folder / "notes.md").write_text("# two\n")
    [update] = updates(hub, shell, 1)
    token = hub.state.session_of("a").page_token
    assert update["url"] == f"{hub.frame_origin}/s/{token}/notes.md?ac-view=1"
    assert update["html"] == "# two\n"
    assert update["viewer"] == "markdown"
    assert update["version"] == 2


def test_view_08_a_new_picture_version_is_pushed_without_its_bytes(
    cli, hub, folder, shell
) -> None:  # noqa: ANN001
    (folder / "fig.png").write_bytes(b"\x89PNG one")
    assert cli("show", "fig.png", "--session", "a").code == 0
    time.sleep(0.6)
    shell.messages.clear()
    (folder / "fig.png").write_bytes(b"\x89PNG two")
    [update] = updates(hub, shell, 1)
    assert update["viewer"] == "image" and update["version"] == 2
    assert "html" not in update
    assert update["url"].endswith("/fig.png?ac-view=1")


def test_view_08_a_new_pdf_version_is_pushed_without_its_bytes_and_html_keeps_its_shape(
    cli, hub, folder, shell
) -> None:  # noqa: ANN001
    (folder / "r.pdf").write_bytes(b"%PDF-1.4 one")
    (folder / "page.html").write_text("<p>one</p>")
    assert cli("show", "r.pdf", "--session", "a").code == 0
    assert cli("show", "page.html", "--session", "a").code == 0
    time.sleep(0.6)
    shell.messages.clear()
    (folder / "r.pdf").write_bytes(b"%PDF-1.4 \xff\xfe two")
    [update] = updates(hub, shell, 1)
    assert update["viewer"] == "pdf" and update["version"] == 2
    assert "html" not in update
    assert update["url"].endswith("/r.pdf?ac-view=1")
    shell.messages.clear()
    (folder / "page.html").write_text("<p>two</p>")
    [update] = updates(hub, shell, 1)
    assert update["html"] == "<p>two</p>" and "viewer" not in update


def report(hub, shell: FakeShell, data: dict | None) -> None:  # noqa: ANN001
    token = hub.state.session_of("a").page_token
    url = f"{hub.frame_origin}/s/{token}/fig.png?ac-view=1"
    shell.send(
        {"type": "page-report", "url": url, "name": "viewer-error", "data": data}
    )


def test_view_14_the_hub_keeps_the_newest_report_per_page_version(
    cli, hub, folder, shell
) -> None:  # noqa: ANN001
    first = {"page": "fig.png", "version": 1, "reason": "image-undecodable"}
    report(hub, shell, first)
    report(hub, shell, {**first, "reason": "image-too-large"})
    report(hub, shell, {**first, "version": 2})
    status = hub.state.page_status("a", "fig.png")
    hub.wait_for(lambda: len(status.viewer_errors) == 2, timeout=5)
    assert status.viewer_errors == {1: "image-too-large", 2: "image-undecodable"}


def test_view_14_an_unknown_reason_or_a_malformed_report_is_ignored(
    cli, hub, folder, shell
) -> None:  # noqa: ANN001
    bad = {"page": "fig.png", "version": 1, "reason": "boom"}
    report(hub, shell, bad)
    report(hub, shell, {**bad, "version": "x", "reason": "pdf-corrupt"})
    report(hub, shell, None)
    report(hub, shell, {**bad, "version": None, "reason": "pdf-corrupt"})
    status = hub.state.page_status("a", "fig.png")
    hub.wait_for(lambda: len(status.viewer_errors) == 1, timeout=5)
    assert status.viewer_errors == {None: "pdf-corrupt"}
