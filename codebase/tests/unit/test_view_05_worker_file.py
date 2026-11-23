"""The vendored PDF.js worker keeps the shape the viewer relies on (VIEW-05)."""

from __future__ import annotations

import re
from pathlib import Path

import agent_canvas

WORKER = (
    Path(agent_canvas.__file__).parent / "static/vendor/pdfjs-dist/pdf.worker.min.mjs"
)
CLOSING_EXPORT = re.compile(r"export\{[^}]*\};?\s*$")


def test_view_05_the_worker_file_ends_with_one_export_statement() -> None:
    text = WORKER.read_text()
    assert len(CLOSING_EXPORT.findall(text)) == 1
    rest = CLOSING_EXPORT.sub("", text)
    assert re.search(r"(?<![\w.$])export\s*(\{|\*|default\b)", rest) is None


def test_view_05_the_worker_file_holds_no_import_meta() -> None:
    assert "import.meta" not in WORKER.read_text()
