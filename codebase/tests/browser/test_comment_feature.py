"""The window's comment feature alone, without the shell (P33.1).

COM-01, COM-15, COM-18 and ANC-01 to ANC-05: ``comment-feature.js`` runs in a bare
host page with recording callbacks in place of ``shell.js``; its cleaning functions
run with the file alone, fed bad positions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_canvas.config import load_keys

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src/agent_canvas/static"

FEATURE_HOST = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{(STATIC / "comments.css").as_uri()}">
<script src="{(STATIC / "keymap.js").as_uri()}"></script>
<script>keyMap.configure({{defaults: {json.dumps(load_keys()["defaults"])}}});</script>
<script src="{(STATIC / "comments.js").as_uri()}"></script>
<script src="{(STATIC / "comment-feature.js").as_uri()}"></script>
</head><body>
<main style="position: relative; width: 800px; height: 600px"></main>
<aside id="comment-panel" hidden></aside>
</body></html>"""

REPORTS_HOST = f"""<!doctype html><html><head><meta charset="utf-8">
<script src="{(STATIC / "comment-feature.js").as_uri()}"></script>
</head><body></body></html>"""

SETUP = """() => {
  window.calls = [];
  window.toFrame = [];
  window.tab = {id: "s1", page: "page.html"};
  window.viewed = null;
  const record = (name) => (...args) => calls.push([name, ...args]);
  const outbox = {
    size: () => 0,
    views: () => [],
    async submit(path, body) {
      calls.push(["submit", path, body]);
      return {ok: true, data: {
        id: "cmt_2", n: 2, kind: body.kind, text: body.text, sent: null, replies: [],
        anchor: body.anchor, target: body.target,
      }};
    },
  };
  window.feature = createCommentFeature({
    main: document.querySelector("main"),
    activeTab: () => tab,
    viewing: () => viewed,
    isOffline: () => false,
    commentOutbox: outbox,
    postToFrame: (message) => toFrame.push(message),
    sendToHub: record("sendToHub"),
    api: async () => null,
    el(tag, className, text) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = text;
      return element;
    },
    showNotice: record("showNotice"),
    drop: record("drop"),
    updateBar: record("updateBar"),
    commentsArrived: record("commentsArrived"),
  });
}"""

RECT = {"x": 10, "y": 20, "w": 30, "h": 40}
FRACTIONS = {"fx": 0.1, "fy": 0.2, "fw": 0.5, "fh": 0.5}
SECRET = "SECRET-COMMENT-TEXT"
COMMENT = {
    "id": "cmt_1", "n": 1, "kind": "rect", "status": "draft", "sent": None,
    "text": SECRET, "anchor": {"space": "page-px", **RECT, **FRACTIONS},
    "target": {"selector": "#a", "canvas_id": None, "text": "Target"},
    "replies": [{"from": "agent", "text": "SECRET-REPLY", "at": "2026-11-16T10:00:00Z",
                 "sent": None}],
    "unread": False, "page_version": 1,
}  # fmt: skip
COMMENTS = {
    "type": "comments", "session": "s1", "page": "page.html", "comments": [COMMENT],
    "next": 2,
}  # fmt: skip
SELECTION = {
    "type": "comment-selection", "kind": "rect", "rect": RECT,
    "anchor": {**RECT, **FRACTIONS}, "target": {"selector": "#a", "text": "Target"},
}  # fmt: skip


@pytest.fixture
def host(page, tmp_path: Path):  # noqa: ANN001, ANN201
    """Load comments.js and comment-feature.js alone, with recording callbacks."""
    file = tmp_path / "host.html"
    file.write_text(FEATURE_HOST)
    page.goto(file.as_uri())
    page.evaluate(SETUP)
    return page


@pytest.fixture
def reports(page, tmp_path: Path):  # noqa: ANN001, ANN201
    """Load comment-feature.js alone: no shell, no comments.js, no DOM to work on."""
    file = tmp_path / "reports.html"
    file.write_text(REPORTS_HOST)
    page.goto(file.as_uri())
    return page


def calls_of(host, name: str) -> list:  # noqa: ANN001
    """Return the recorded calls of one callback, without its name."""
    return [c[1:] for c in host.evaluate("calls") if c[0] == name]


def last_to_frame(host, kind: str) -> dict:  # noqa: ANN001
    """Return the last message of one type posted to the frame."""
    return [m for m in host.evaluate("toFrame") if m["type"] == kind][-1]


# ---- the feature through its callbacks -------------------------------------------


def test_com_01_the_comment_file_alone_turns_comment_mode_on_and_off(host) -> None:  # noqa: ANN001
    host.evaluate("feature.commentsPageChanged()")
    assert calls_of(host, "sendToHub") == [
        [{"type": "comments-get", "session": "s1", "page": "page.html"}]
    ]
    assert host.evaluate("feature.commentKey('c')") is True
    assert last_to_frame(host, "comment-mode") == {
        "type": "comment-mode", "on": True, "kind": "rect",
    }  # fmt: skip
    assert host.evaluate("document.body.classList.contains('commenting')")
    host.evaluate("feature.commentKey('p')")
    assert last_to_frame(host, "comment-mode")["kind"] == "point"
    # An earlier version is read-only: comment mode ends (COM-14).
    host.evaluate(
        "viewed = {page: 'page.html', version: 1}; feature.commentsPageChanged()"
    )
    assert not host.evaluate("document.body.classList.contains('commenting')")
    assert host.evaluate("feature.commentKey('p')") is False


def test_com_15_the_comment_file_alone_sends_markers_without_comment_text(host) -> None:  # noqa: ANN001
    host.evaluate("(m) => feature.onCommentsMessage(m)", COMMENTS)
    arrived = calls_of(host, "commentsArrived")
    assert len(arrived) == 1 and arrived[0][0]["comments"][0]["n"] == 1
    markers = last_to_frame(host, "comment-markers")["markers"]
    assert [(m["n"], m["kind"], m["selector"]) for m in markers] == [(1, "rect", "#a")]
    assert len(markers[0]["token"]) == 24
    assert SECRET in host.inner_text("#comment-panel .ent[data-n='1']")
    sent = json.dumps(host.evaluate("toFrame"))
    assert "SECRET" not in sent
    assert host.evaluate("feature.unsentComments()") == {"comments": 1, "files": 1}
    assert host.evaluate("feature.commentsOf('s1', 'page.html').length") == 1
    assert host.evaluate("feature.commentsOf('s1', 'other.html')") is None


def test_com_15_a_save_goes_to_the_outbox_and_never_to_the_frame(host) -> None:  # noqa: ANN001
    host.evaluate("feature.commentKey('c')")
    host.evaluate("(m) => feature.onCommentSelection(m)", SELECTION)
    token = last_to_frame(host, "comment-crop")["token"]
    picture = {"token": token, "ok": True, "png": "data:image/png;base64,AAAA"}
    host.evaluate("(m) => feature.onCommentPicture(m)", picture)
    host.fill(".cbox textarea", SECRET)
    host.press(".cbox textarea", "Enter")
    host.wait_for_function("calls.some((c) => c[0] === 'submit')")
    host.wait_for_function("!document.querySelector('.cbox')")
    [(path, body)] = calls_of(host, "submit")
    assert path == "/api/sessions/s1/comments"
    assert (body["text"], body["kind"], body["picture"]) == (SECRET, "rect", "AAAA")
    assert body["anchor"] == {"space": "page-px", **RECT, **FRACTIONS}
    assert last_to_frame(host, "comment-clear") == {"type": "comment-clear"}
    assert [m["n"] for m in last_to_frame(host, "comment-markers")["markers"]] == [2]
    assert "SECRET" not in json.dumps(host.evaluate("toFrame"))


def test_com_18_the_comment_file_alone_takes_reports_only_with_its_tokens(host) -> None:  # noqa: ANN001
    host.evaluate("(m) => feature.onCommentsMessage(m)", COMMENTS)
    token = host.evaluate("feature.commentTokens.get('cmt_1')")
    host.evaluate("feature.onCommentMarker({token: 'forged', action: 'click'})")
    host.evaluate("feature.onCommentLost({items: [{token: 'forged', lost: true}]})")
    assert calls_of(host, "drop") == [["token"], ["token"]]
    host.evaluate("(t) => feature.onCommentMarker({token: t, action: 'click'})", token)
    assert calls_of(host, "drop") == [["token"], ["token"]]
    assert last_to_frame(host, "comment-markers")["selected"] == token
    # A selection gets a fresh token; a picture with another token is dropped.
    host.evaluate("feature.commentKey('c')")
    host.evaluate("(m) => feature.onCommentSelection(m)", SELECTION)
    first = last_to_frame(host, "comment-crop")["token"]
    host.evaluate("(m) => feature.onCommentSelection(m)", SELECTION)
    second = last_to_frame(host, "comment-crop")["token"]
    assert len({token, first, second}) == 3
    host.evaluate("feature.onCommentPicture({token: 'forged', ok: true, png: ''})")
    assert calls_of(host, "drop") == [["token"], ["token"], ["token"]]


def test_com_18_a_selection_with_a_bad_position_opens_no_box(host) -> None:  # noqa: ANN001
    host.evaluate("feature.commentKey('c')")
    before = len(host.evaluate("toFrame"))
    bad = [
        {**SELECTION, "rect": {**RECT, "x": "10"}},
        {**SELECTION, "rect": None},
        {**SELECTION, "anchor": {**RECT}},  # no fractions
        {**SELECTION, "kind": "point"},  # not the kind picked
    ]
    for message in bad:
        host.evaluate("(m) => feature.onCommentSelection(m)", message)
    host.evaluate(
        "(m) => feature.onCommentSelection({...m, rect: {...m.rect, w: NaN}})",
        SELECTION,
    )
    assert len(host.evaluate("toFrame")) == before
    assert host.locator(".cbox").count() == 0


def test_com_18_the_comment_state_is_gone_from_the_shell() -> None:
    names = (
        "let commentMode", "let commentSelection", "commentPages = new Map",
        "hubUnsent", "function cleanAnchor", "function cleanRect",
        "function saveComment",
        "COMMENT_KIND_KEY", "panelCollapsed", "knownVersions",
    )  # fmt: skip
    text = (STATIC / "shell.js").read_text()
    assert [n for n in names if n in text] == []
    assert "window.createCommentFeature(" in text


# ---- the cleaning functions, fed bad positions -----------------------------------


def mismatches(reports, cases: list[tuple[str, object]]) -> list:  # noqa: ANN001
    """Run each expression on ``commentReports``; return the cases that differ."""
    assert cases
    wrong = []
    for expression, expected in cases:
        got = reports.evaluate(f"() => commentReports.{expression}")
        if got != expected:
            wrong.append((expression, got, expected))
    return wrong


R = "x: 10, y: 20, w: 30, h: 40"
F = "fx: 0.1, fy: 0.2, fw: 0.5, fh: 0.5"


def test_com_18_clean_rect_keeps_four_finite_numbers_in_range(reports) -> None:  # noqa: ANN001
    cases = [
        (f"cleanRect({{{R}}})", RECT),
        (
            "cleanRect({x: -5, y: -1e6, w: 0, h: 1e6})",
            {"x": -5, "y": -1e6, "w": 0, "h": 1e6},
        ),
        (f"cleanRect({{{R}, p: 9, onclick: 'alert(1)'}})", RECT),
        ("cleanRect({x: '10', y: 20, w: 30, h: 40})", None),
        ("cleanRect({x: true, y: 20, w: 30, h: 40})", None),
        ("cleanRect({x: NaN, y: 20, w: 30, h: 40})", None),
        ("cleanRect({x: 10, y: Infinity, w: 30, h: 40})", None),
        ("cleanRect({x: 10, y: 20, w: -1, h: 40})", None),
        ("cleanRect({x: 1e6 + 1, y: 20, w: 30, h: 40})", None),
        ("cleanRect({x: 10, y: 20, w: 30})", None),
        ("cleanRect(null)", None),
        ("cleanRect('10,20,30,40')", None),
        ("cleanRect([10, 20, 30, 40])", None),
    ]
    assert mismatches(reports, cases) == []


def test_com_18_clean_pairs_keeps_only_pairs_of_finite_numbers(reports) -> None:  # noqa: ANN001
    cases = [
        ("cleanPairs([[1, 2], [-3, 4.5]], 200)", [[1, 2], [-3, 4.5]]),
        ("cleanPairs([[1, 2, 99]], 200)", [[1, 2]]),
        ("cleanPairs([[1, '2']], 200)", None),
        ("cleanPairs([[1]], 200)", None),
        ("cleanPairs([1, 2], 200)", None),
        ("cleanPairs([[NaN, 1]], 200)", None),
        ("cleanPairs([[2e6, 0]], 200)", None),
        ("cleanPairs(Array(201).fill([0, 0]), 200)", None),
        ("cleanPairs(Array(200).fill([0, 0]), 200).length", 200),
        ("cleanPairs({0: [1, 2], length: 1}, 200)", None),
        ("cleanPairs(undefined, 200)", None),
    ]
    assert mismatches(reports, cases) == []


def test_com_18_clean_pdf_rect_needs_a_whole_page_number(reports) -> None:  # noqa: ANN001
    cases = [
        (f"cleanPdfRect({{p: 2, {R}}})", {"p": 2, **RECT}),
        (f"cleanPdfRect({{p: 0, {R}}})", None),
        (f"cleanPdfRect({{p: 1.5, {R}}})", None),
        (f"cleanPdfRect({{p: '2', {R}}})", None),
        (f"cleanPdfRect({{p: 1e5 + 1, {R}}})", None),
        (f"cleanPdfRect({{{R}}})", None),
        ("cleanPdfRect({p: 2, x: 10, y: 20, w: 30})", None),
        ("cleanPdfRect(null)", None),
    ]
    assert mismatches(reports, cases) == []


def anchor(fields: str, kind: str) -> str:
    """Return the call of ``cleanAnchor`` on a JavaScript object literal and a kind."""
    return f"cleanAnchor({{{fields}}}, '{kind}')"


def test_anc_01_to_04_clean_anchor_keeps_only_the_fields_of_its_kind(reports) -> None:  # noqa: ANN001
    page_rect = {"space": "page-px", **RECT, **FRACTIONS}
    text = {"space": "page-px", "quote": "q" * 1000, "cut": False, "before": "b" * 120,
            "after": "", "rects": [RECT], "start": 0, "end": 1500}  # fmt: skip
    pdf_text = {"space": "pdf-pt", "quote": "q", "cut": False, "before": "",
                "after": "", "rects": [{"p": 3, **RECT}], "start": 0,
                "end": 1}  # fmt: skip
    long_text = "quote: 'q'.repeat(1500), before: 'b'.repeat(200), after: 5, cut: 'yes'"
    bad_rect = "{x: NaN, y: 0, w: 1, h: 1}"
    lasso = "points: [[0, 0], [10, 0], [0, 10]], bbox: {x: 0, y: 0, w: 10, h: 10}"
    image = "space: 'image-px', nw: 800, nh: 600"
    pdf = "space: 'pdf-pt', quote: 'q'"
    triangle = "points: [[0, 0], [1, 1], [0, 1]], bbox: {x: 0, y: 0, w: 1, h: 1}"
    cases = [
        (anchor(f"{R}, {F}, space: 'evil', target: 'x', quote: 'q'", "rect"),
         page_rect),
        (anchor(f"{R}, fx: 0.1, fy: 0.2, fw: 0.5", "rect"), None),
        (anchor("x: 1, y: 2, fx: 0.5, fy: 0.5, w: 9", "point"),
         {"space": "page-px", "x": 1, "y": 2, "fx": 0.5, "fy": 0.5}),
        (anchor("x: 1, y: 2, fx: 0.5, fy: NaN", "point"), None),
        (anchor("x: 1, fx: 0.5, fy: 0.5", "point"), None),
        (anchor(f"{lasso}, fpoints: [[0, 0], [1, 0], [0, 1]], {F}", "lasso"),
         {"space": "page-px", "points": [[0, 0], [10, 0], [0, 10]],
          "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
          "fpoints": [[0, 0], [1, 0], [0, 1]], **FRACTIONS}),
        (anchor(f"{lasso}, fpoints: [[0, 0], [1, 0]], {F}", "lasso"), None),
        (anchor(f"points: [[0, 0]], fpoints: [[0, 0]], {F}", "lasso"), None),
        (anchor(f"{long_text}, start: 0, end: 1500, rects: [{{{R}}}]", "text"), text),
        (anchor(f"quote: '', rects: [{{{R}}}], start: 0, end: 1", "text"), None),
        (anchor(f"quote: 'q', rects: [{{{R}}}, {bad_rect}], start: 0, end: 1", "text"),
         None),
        (anchor("quote: 'q', start: 0, end: 1", "text"), None),
        (anchor(f"quote: 'q', rects: [{{{R}}}], start: 0", "text"), None),
        (anchor(f"{pdf}, rects: [{{p: 3, {R}}}], start: 0, end: 1", "text"), pdf_text),
        (anchor(f"{pdf}, rects: [{{{R}}}], start: 0, end: 1", "text"), None),
        (anchor(f"{image}, {R}, {F}", "rect"),
         {"space": "image-px", "nw": 800, "nh": 600, **RECT}),
        (anchor(f"space: 'image-px', nh: 600, {R}", "rect"), None),
        (anchor(f"{image}, x: 1, y: 2", "text"), None),
        (anchor(f"{image}, {triangle}", "lasso"),
         {"space": "image-px", "nw": 800, "nh": 600, "points": [[0, 0], [1, 1], [0, 1]],
          "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}),
        (anchor("space: 'pdf-pt', p: 3, x: 1, y: 2, fx: 0.5", "point"),
         {"space": "pdf-pt", "p": 3, "x": 1, "y": 2}),
        (anchor("space: 'pdf-pt', p: 0, x: 1, y: 2", "point"), None),
        (anchor(f"{R}, {F}", "circle"), None),
        ("cleanAnchor(null, 'rect')", None),
        ("cleanAnchor('x', 'rect')", None),
    ]  # fmt: skip
    assert mismatches(reports, cases) == []


def test_anc_05_clean_data_keeps_a_number_or_a_pair_per_axis(reports) -> None:  # noqa: ANN001
    huge = {"canvas_id": None, "x": 1e300, "y": -1e300}
    cases = [
        ("cleanData({canvas_id: 'plot1', x: 1.5, y: [0, 2], z: 9})",
         {"canvas_id": "plot1", "x": 1.5, "y": [0, 2]}),
        ("cleanData({x: 1e300, y: -1e300})", huge),
        ("cleanData({canvas_id: 'p'.repeat(300), x: 1, y: 2}).canvas_id.length", 200),
        ("cleanData({canvas_id: 7, x: 1, y: 2})", {"canvas_id": None, "x": 1, "y": 2}),
        ("cleanData({x: [1], y: 2})", None),
        ("cleanData({x: [1, 2, 3], y: 2})", None),
        ("cleanData({x: [1, NaN], y: 2})", None),
        ("cleanData({x: '1', y: 2})", None),
        ("cleanData({x: NaN, y: 2})", None),
        ("cleanData({x: 1, y: Infinity})", None),
        ("cleanData({x: 1})", None),
        ("cleanData(null)", None),
        ("cleanData(5)", None),
    ]  # fmt: skip
    assert mismatches(reports, cases) == []
