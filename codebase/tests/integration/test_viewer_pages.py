"""Viewer pages in the hub: Markdown, PDF and pictures as pages (M20, P20.4)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub.serve import frame_csp, inject_helper, source_digest
from agent_canvas.hub.watcher import PageHistory
from shellfake import FakeShell

pytestmark = pytest.mark.integration

PDF1 = b"%PDF-1.4 one"
PDF2 = b"%PDF-1.4 two"
HELPER_SRC = 'src="/static/helper.js"'


@pytest.fixture
def folder(cli) -> Path:  # noqa: ANN001
    return Path(cli("session", "path", "--session", "a").json["folder"])


@pytest.fixture
def shell(hub):  # noqa: ANN001, ANN201
    fake = FakeShell(hub)
    yield fake
    fake.close()


def url(hub, name: str, query: str = "") -> str:  # noqa: ANN001
    token = hub.state.session_of(hub.pool_of("a")).page_token
    return f"{hub.frame_origin}/s/{token}/{name}{query}"


def show(cli, *args: str):  # noqa: ANN001, ANN201
    return cli("show", *args, "--session", "a")


def test_view_01_markdown_pdf_and_picture_can_be_shown(cli, hub, folder) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("# Notes\n")
    (folder / "r.pdf").write_bytes(PDF1)
    (folder / "p.webp").write_bytes(b"RIFFxxxxWEBP")
    for name in ("notes.md", "r.pdf", "p.webp"):
        result = show(cli, name)
        assert result.code == 0, result.err
        assert result.json["page"] == name
    assert hub.state.tab_provider("a")["pages"] == ["notes.md", "r.pdf", "p.webp"]


def test_view_01_another_type_exits_1_naming_the_allowed_ones(cli, folder) -> None:  # noqa: ANN001
    (folder / "data.csv").write_text("a,b\n")
    result = show(cli, "data.csv")
    assert result.code == 1
    message = result.json["message"]
    for extension in (".html", ".md", ".markdown", ".pdf", ".png", ".jpg", ".svg"):
        assert extension in message


def test_view_01_a_dotfile_is_no_page(cli, folder) -> None:  # noqa: ANN001
    (folder / ".hidden.md").write_text("x")
    assert show(cli, ".hidden.md").code == 1


def test_view_01_a_file_never_shown_stays_an_asset(cli, hub, folder, shell) -> None:  # noqa: ANN001
    (folder / "page.html").write_text("<img src=fig.png>")
    (folder / "fig.png").write_bytes(b"\x89PNG one")
    assert show(cli, "page.html").code == 0
    time.sleep(0.6)
    shell.messages.clear()
    (folder / "fig.png").write_bytes(b"\x89PNG two")
    hub.wait_for(lambda: "file-changed" in shell.types(), timeout=5)
    assert hub.state.tab_provider("a")["pages"] == ["page.html"]
    assert PageHistory(folder).versions("fig.png") == []
    # Not a page: no viewer document for it either.
    answer = httpx.get(url(hub, "fig.png", "?ac-view=1"))
    assert answer.content == b"\x89PNG two"


def test_view_02_viewer_document_and_file_both_carry_the_csp(cli, hub, folder) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("# Notes\n")
    assert show(cli, "notes.md").code == 0
    csp = frame_csp(hub.port, hub.state.session_of(hub.pool_of("a")).page_token)
    document = httpx.get(url(hub, "notes.md", "?ac-view=1"))
    plain = httpx.get(url(hub, "notes.md"))
    assert document.headers["content-type"].split(";")[0] == "text/html"
    assert plain.headers["content-type"].split(";")[0] == "text/markdown"
    assert document.headers["content-security-policy"] == csp
    assert plain.headers["content-security-policy"] == csp
    assert plain.content == b"# Notes\n"
    assert document.text.count(HELPER_SRC) == 1
    assert document.text.count("/static/viewer/markdown.js") == 1


@pytest.mark.parametrize(
    ("name", "script"),
    [("r.pdf", "pdf"), ("p.png", "image"), ("q.jpeg", "image"), ("s.svg", "image")],
)
def test_view_02_each_type_gets_its_own_script(cli, hub, folder, name, script) -> None:  # noqa: ANN001
    (folder / name).write_bytes(b"x")
    assert show(cli, name).code == 0
    text = httpx.get(url(hub, name, "?ac-view=1")).text
    assert f"/static/viewer/{script}.js" in text
    assert text.count("/static/viewer/") == 1


def test_view_02_versions_answer_their_own_bytes_and_unknown_is_404(  # noqa: ANN001
    cli, hub, folder
) -> None:
    (folder / "r.pdf").write_bytes(PDF1)
    assert show(cli, "r.pdf").code == 0
    (folder / "r.pdf").write_bytes(PDF2)
    assert show(cli, "r.pdf").code == 0
    first = httpx.get(url(hub, "r.pdf", "?v=1"))
    assert first.content == PDF1
    assert first.headers["content-type"].split(";")[0] == "application/pdf"
    assert httpx.get(url(hub, "r.pdf")).content == PDF2
    assert httpx.get(url(hub, "r.pdf", "?v=9")).status_code == 404
    assert httpx.get(url(hub, "r.pdf", "?ac-view=1&v=9")).status_code == 404
    assert httpx.get(url(hub, "r.pdf", "?ac-view=1&v=1")).text.count(HELPER_SRC) == 1


def test_view_02_a_version_is_read_only_from_history_pages(cli, hub, folder) -> None:  # noqa: ANN001
    (folder / "r.pdf").write_bytes(PDF1)
    assert show(cli, "r.pdf").code == 0
    # Files of the same stem outside history/pages must never be served as a version.
    (folder / "history" / "sends").mkdir(parents=True, exist_ok=True)
    (folder / "history" / "sends" / "r.0007.pdf").write_bytes(b"secret")
    (folder / "r.0007.pdf").write_bytes(b"loose")
    assert httpx.get(url(hub, "r.pdf", "?v=7")).status_code == 404


def test_page_03_html_serving_is_unchanged_by_the_viewer_query(
    cli, hub, folder
) -> None:  # noqa: ANN001
    body = b"<!doctype html><html><head><title>t</title></head><body>x</body></html>"
    (folder / "page.html").write_bytes(body)
    assert show(cli, "page.html").code == 0
    csp = frame_csp(hub.port, hub.state.session_of(hub.pool_of("a")).page_token)
    for query in ("", "?ac-view=1"):
        answer = httpx.get(url(hub, "page.html", query))
        assert answer.content == inject_helper(body, source_digest(body))
        assert answer.headers["content-security-policy"] == csp
        assert answer.headers["content-type"] == "text/html; charset=utf-8"


def test_view_02_comments_folder_is_not_served(cli, hub, folder) -> None:  # noqa: ANN001
    (folder / ".comments").mkdir()
    (folder / ".comments" / "notes.md.json").write_text("{}")
    assert httpx.get(url(hub, ".comments/notes.md.json")).status_code == 404


def test_view_11_two_versions_of_a_pdf_keep_their_extension(cli, folder) -> None:  # noqa: ANN001
    (folder / "r.pdf").write_bytes(PDF1)
    assert show(cli, "r.pdf").json["version"] == 1
    (folder / "r.pdf").write_bytes(PDF2)
    assert show(cli, "r.pdf").json["version"] == 2
    pages = sorted(p.name for p in (folder / "history" / "pages").iterdir())
    assert pages == ["r.0001.pdf", "r.0002.pdf"]
    assert (folder / "history" / "pages" / "r.0001.pdf").read_bytes() == PDF1


def test_view_11_stem_clash_exits_1_naming_the_other_page(cli, folder) -> None:  # noqa: ANN001
    (folder / "report.html").write_text("<p>x</p>")
    assert show(cli, "report.html").code == 0
    (folder / "report.md").write_text("# x")
    result = show(cli, "report.md")
    assert result.code == 1
    assert "report.html" in result.json["message"]
    (folder / "plot.png").write_bytes(b"1")
    (folder / "plot.jpg").write_bytes(b"2")
    assert show(cli, "plot.png").code == 0
    clash = show(cli, "plot.jpg")
    assert clash.code == 1 and "plot.png" in clash.json["message"]


def test_view_11_stem_clash_with_a_copy_changes_nothing(cli, folder, tmp_path) -> None:  # noqa: ANN001
    (folder / "report.html").write_text("<p>x</p>")
    assert show(cli, "report.html").code == 0
    source = tmp_path / "ext" / "report.md"
    source.parent.mkdir()
    source.write_text("# x")
    result = show(cli, "--copy", str(source))
    assert result.code == 1 and "report.html" in result.json["message"]
    assert not (folder / "report.md").exists()


def test_hub_05_a_listed_viewer_file_is_watched_and_versioned(cli, hub, folder) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("one")
    (folder / "other.md").write_text("one")
    assert show(cli, "notes.md").code == 0
    time.sleep(0.6)
    (folder / "notes.md").write_text("two")
    (folder / "other.md").write_text("two")
    history = PageHistory(folder)
    hub.wait_for(lambda: len(history.versions("notes.md")) == 2, timeout=5)
    time.sleep(0.5)
    assert history.read("notes.md", 2) == b"two"
    assert history.versions("other.md") == []  # never shown: an asset


def test_hub_05_viewer_change_is_no_file_changed_and_comments_are_ignored(  # noqa: ANN001
    cli, hub, folder, shell
) -> None:
    (folder / "notes.md").write_text("one")
    assert show(cli, "notes.md").code == 0
    time.sleep(0.6)
    (folder / ".comments").mkdir()
    shell.messages.clear()
    (folder / ".comments" / "notes.md.json").write_text("{}")
    (folder / ".comments" / "notes.md.1.png").write_bytes(b"x")
    (folder / "notes.md").write_text("two")
    history = PageHistory(folder)
    hub.wait_for(lambda: len(history.versions("notes.md")) == 2, timeout=5)
    time.sleep(0.5)
    assert "file-changed" not in shell.types()


def test_hist_01_viewer_pages_save_distinct_content_once(cli, folder) -> None:  # noqa: ANN001
    (folder / "notes.md").write_text("a")
    assert show(cli, "notes.md").json["version"] == 1
    (folder / "notes.md").write_text("b")
    assert show(cli, "notes.md").json["version"] == 2
    (folder / "notes.md").write_text("b")
    assert show(cli, "notes.md").json["version"] == 2
    names = sorted(p.name for p in (folder / "history" / "pages").iterdir())
    assert names == ["notes.0001.md", "notes.0002.md"]


def test_cli_02_viewer_name_missing_or_outside_exits_1(cli, folder, tmp_path) -> None:  # noqa: ANN001
    missing = show(cli, "none.pdf")
    assert missing.code == 1 and str(folder) in missing.json["message"]
    outside = tmp_path / "outside.md"
    outside.write_text("x")
    result = show(cli, str(outside))
    assert result.code == 1 and "--copy" in result.json["message"]
    (folder / "in.md").write_text("x")
    assert show(cli, str(folder / "in.md")).json["page"] == "in.md"


def test_cli_16_copy_of_a_pdf_is_a_file_and_a_changed_copy_is_version_2(  # noqa: ANN001
    cli, folder, tmp_path
) -> None:
    source = tmp_path / "ext" / "r.pdf"
    source.parent.mkdir()
    source.write_bytes(PDF1)
    link = tmp_path / "ext" / "link.pdf"
    link.symlink_to(source)
    first = show(cli, "--copy", str(source))
    assert first.code == 0 and first.json["version"] == 1
    copy = folder / "r.pdf"
    assert copy.lstat().st_mode & 0o170000 == 0o100000  # a regular file, no link
    source.write_bytes(PDF2)
    second = show(cli, "--copy", str(source))
    assert second.json["version"] == 2 and copy.read_bytes() == PDF2
    source.write_bytes(PDF1)  # the copy is independent of its source
    assert copy.read_bytes() == PDF2
    via_link = show(cli, "--copy", str(link))
    assert via_link.code == 0 and not copy.is_symlink()
    assert copy.lstat().st_mode & 0o170000 == 0o100000


def test_cli_16_copy_replaces_a_link_in_the_folder_without_writing_through(  # noqa: ANN001
    cli, folder, tmp_path
) -> None:
    precious = b"%PDF-1.4 precious"
    target = tmp_path / "precious.pdf"
    target.write_bytes(precious)
    # The session's own page first: a pool refuses a copy over a page it never touched.
    (folder / "r.pdf").write_bytes(precious)
    assert show(cli, "r.pdf").code == 0
    (folder / "r.pdf").unlink()
    (folder / "r.pdf").symlink_to(target)
    source = tmp_path / "ext" / "r.pdf"
    source.parent.mkdir()
    source.write_bytes(PDF1)
    copied = show(cli, "--copy", str(source))
    assert copied.code == 0, copied.err
    assert target.read_bytes() == precious
    assert not (folder / "r.pdf").is_symlink()
    assert (folder / "r.pdf").read_bytes() == PDF1


def test_cli_16_copy_of_another_type_exits_1(cli, folder, tmp_path) -> None:  # noqa: ANN001
    source = tmp_path / "data.csv"
    source.write_text("a")
    result = show(cli, "--copy", str(source))
    assert result.code == 1 and ".pdf" in result.json["message"]
    assert not (folder / "data.csv").exists()


def test_cli_16_copy_of_a_250_character_name_works(cli, folder, tmp_path) -> None:  # noqa: ANN001
    name = "a" * 246 + ".pdf"
    source = tmp_path / "ext" / name
    source.parent.mkdir()
    source.write_bytes(PDF1)
    result = show(cli, "--copy", str(source))
    assert result.code == 0, result.err
    assert (folder / name).read_bytes() == PDF1
    assert not list(folder.glob(".copy-*"))


def test_hub_05_control_file_changed_arrives_for_an_unlisted_data_file(  # noqa: ANN001
    cli, hub, folder, shell
) -> None:
    (folder / "notes.md").write_text("one")
    assert show(cli, "notes.md").code == 0
    time.sleep(0.6)
    shell.messages.clear()
    (folder / "data.csv").write_text("1,2")
    hub.wait_for(lambda: "file-changed" in shell.types(), timeout=5)
