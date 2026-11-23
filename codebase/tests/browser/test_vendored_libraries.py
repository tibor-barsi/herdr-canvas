# ruff: noqa: E501
"""Smoke test: every vendored library loads in Chromium with no network."""

from __future__ import annotations

import functools
import http.server
import threading
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page

from helpers import PACKAGE_DIR

pytestmark = pytest.mark.browser

PAGE = """<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="/static/vendor/katex/katex.min.css">
<script type="importmap">{"imports": {"three": "/static/vendor/three/three.module.js"}}</script>
<script src="/static/vendor/plotly.js-dist-min/plotly.min.js"></script>
<script src="/static/vendor/katex/katex.min.js"></script>
<script src="/static/vendor/idiomorph/idiomorph.min.js"></script>
<script src="/static/vendor/occt-import-js/occt-import-js.js"></script>
<body><span id="k"></span>
<script type="module">
import * as THREE from "three";
import {STLLoader} from "/static/vendor/three/addons/STLLoader.js";
import {OrbitControls} from "/static/vendor/three/addons/OrbitControls.js";
import {marked} from "/static/vendor/marked/marked.esm.js";
import {snapdom} from "/static/vendor/snapdom/snapdom.mjs";
import {finder} from "/static/vendor/finder/finder.js";
const occt = await occtimportjs({
  locateFile: (name) => "/static/vendor/occt-import-js/" + name});
katex.render("x^2", document.getElementById("k"));
window.result = {
  three: typeof THREE.Scene, stl: typeof STLLoader, orbit: typeof OrbitControls,
  marked: marked.parse("# t").includes("<h1"),
  snapdom: typeof snapdom, finder: finder(document.getElementById("k")).length > 0,
  occt: typeof occt.ReadStepFile, plotly: typeof Plotly.newPlot,
  idiomorph: typeof Idiomorph.morph,
  katex: document.querySelector(".katex") !== null,
};
</script></body>"""


@pytest.fixture
def server() -> Iterator[str]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/":
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_GET()

        def log_message(self, *args: object) -> None:
            pass

    handler = functools.partial(Handler, directory=str(PACKAGE_DIR))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_ops_01_vendored_libraries_load_offline(page: Page, server: str) -> None:
    foreign: list[str] = []
    page.on(
        "request",
        lambda req: (
            foreign.append(req.url)
            if urlparse(req.url).netloc != urlparse(server).netloc
            and not req.url.startswith(("data:", "blob:"))
            else None
        ),
    )
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(server + "/")
    page.wait_for_function("window.result !== undefined", timeout=20000)
    result = page.evaluate("window.result")
    assert errors == []
    assert foreign == []
    assert all(value not in ("undefined", False) for value in result.values()), result


PDF_JS = r"""
async () => {
  const pdfjs = await import("/static/vendor/pdfjs-dist/pdf.min.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs-dist/pdf.worker.min.mjs";
  const text = "BT /F1 24 Tf 20 50 Td (Hello pdf) Tj ET";
  const objs = [
    "<</Type/Catalog/Pages 2 0 R>>",
    "<</Type/Pages/Kids[3 0 R]/Count 1>>",
    "<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
      + "/Resources<</Font<</F1 5 0 R>>>>>>",
    `<</Length ${text.length}>>\nstream\n${text}\nendstream`,
    "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [];
  objs.forEach((o, i) => { offsets.push(pdf.length); pdf += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = pdf.length;
  pdf += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  offsets.forEach((o) => { pdf += String(o).padStart(10, "0") + " 00000 n \n"; });
  pdf += `trailer<</Size ${objs.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF`;
  const doc = await pdfjs.getDocument({
    data: new TextEncoder().encode(pdf),
    standardFontDataUrl: "/static/vendor/pdfjs-dist/standard_fonts/",
    cMapUrl: "/static/vendor/pdfjs-dist/cmaps/", cMapPacked: true,
  }).promise;
  const page = await doc.getPage(1);
  const canvas = document.createElement("canvas");
  const viewport = page.getViewport({scale: 1});
  canvas.width = viewport.width; canvas.height = viewport.height;
  await page.render({canvasContext: canvas.getContext("2d"), viewport}).promise;
  const content = await page.getTextContent();
  const ctx = canvas.getContext("2d");
  const ink = ctx.getImageData(0, 0, canvas.width, canvas.height).data.some(
    (v, i) => i % 4 === 3 && v > 0);
  return {pages: doc.numPages, text: content.items.map((i) => i.str).join(""), ink};
}
"""


def test_pdf_01_pdfjs_loads_from_static_without_outside_request(owner) -> None:  # noqa: ANN001
    result = owner.page.evaluate(PDF_JS)
    assert result == {"pages": 1, "text": "Hello pdf", "ink": True}
    assert owner.foreign_requests == []
