// Comment layer, loaded by helper.js into the page's frame (COM-01, COM-05,
// COM-12, ANC-03, COM-13; 4.2). It holds what touches the page's document:
// the rectangle gesture, the markers, the anchor and the picture. It reports
// only geometry, anchors and pictures to the shell (SEC-09) and never receives
// a comment text (COM-15): the box and the text live in the shell.
//
// Revision 12, HTML pages: the four selection kinds (P22.2), their markers and
// finding anchors again after a change (P22.3, anchor.js holds the finders).
// Viewers with a space of their own (a picture's image-px, a PDF's pdf-pt, 4.2)
// convert through window.acViewer.
(function () {
  "use strict";
  const agent = window.agentCanvas;
  if (!agent || agent.commentLayer || !agent.layerSupport) return;
  const support = agent.layerSupport;
  const anchors = agent.anchor;
  if (!anchors) return;

  const HOST_ATTRIBUTE = "data-ac-comment-host";
  const MIN_DRAG = 4;            // px, both directions (COM-02)
  const PAD = 16;                // px around the shape in its picture (COM-12)
  const POINT_BOX = [320, 200];  // px of a point's picture (COM-12)
  const MARK_COLOUR = "#c2410c"; // the pin and the lasso path on a picture
  const MAX_SIDE = 1200;         // px, longer side of a picture
  const INSIDE_LIMIT = 500;      // characters of text_inside (ANC-03)
  const QUOTE_LIMIT = 1000;      // characters of a text anchor's quote (ANC-01)
  const CONTEXT_LIMIT = 120;     // letters and digits of before and after (ANC-01)
  const LASSO_MIN_POINTS = 3;    // COM-02
  const LASSO_MIN_AREA = 64;     // px squared, COM-02
  const LASSO_MAX_POINTS = 200;  // ANC-04
  const LASSO_TOLERANCE = 2;     // px, ANC-04
  const MAX_RAW_POINTS = 5000;   // samples of one lasso drag
  const LOST_DELAY_MS = 300;     // wait before a lost report, ANC-06
  const KINDS = ["text", "point", "rect", "lasso"];
  const STATUSES = ["draft", "sent", "seen", "answered", "done"];
  const SKIPPED_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"]);

  const STYLE = `
    :host { all: initial; }
    .box { position: absolute; box-sizing: border-box; border: 2px solid var(--mark);
           background: rgba(194, 65, 12, .07); border-radius: 3px; pointer-events: none; }
    .box.draft { border-style: dashed; }
    .box.answered { border-color: #1b7f4b; background: rgba(27, 127, 75, .07); }
    .box.done { border-color: #6b7480; background: none; }
    .box.hot { outline: 2px solid #2457c5; outline-offset: 1px; }
    .box.hl { border: 0; border-radius: 2px; background: rgba(250, 204, 21, .38); }
    .draft .hl { border: 1px dashed var(--mark); background: rgba(250, 204, 21, .22); }
    .answered .hl { background: rgba(27, 127, 75, .22); }
    .done .hl { background: rgba(107, 116, 128, .18); }
    .hot .hl { outline: 2px solid #2457c5; }
    .mk.done, .box.done { opacity: .55; }
    .pin { position: absolute; width: 12px; height: 12px; margin: -6px 0 0 -6px;
           box-sizing: border-box; border: 2px solid #fff; border-radius: 50%;
           background: var(--mark); box-shadow: 0 0 0 1px var(--mark); pointer-events: none; }
    .answered .pin { background: #1b7f4b; box-shadow: 0 0 0 1px #1b7f4b; }
    .done .pin { background: #6b7480; box-shadow: 0 0 0 1px #6b7480; }
    .draft .pin { background: #fff; border-color: var(--mark); box-shadow: none; }
    svg.outline { position: absolute; left: 0; top: 0; width: 1px; height: 1px;
                  overflow: visible; pointer-events: none; }
    svg.outline polygon { fill: rgba(194, 65, 12, .07); stroke: var(--mark); stroke-width: 2;
                          stroke-linejoin: round; }
    .draft svg.outline polygon { stroke-dasharray: 5 3; }
    .answered svg.outline polygon { stroke: #1b7f4b; fill: rgba(27, 127, 75, .07); }
    .done svg.outline polygon { stroke: #6b7480; fill: none; }
    .hot svg.outline polygon { stroke: #2457c5; }
    .box.temp { border: 2px dashed #2457c5; background: rgba(36, 87, 197, .08); }
    .dot { position: absolute; width: 14px; height: 14px; margin: -7px 0 0 -7px;
           box-sizing: border-box; border: 2px solid #2457c5; border-radius: 50%;
           background: rgba(36, 87, 197, .25); pointer-events: none; }
    svg.lasso { position: absolute; left: 0; top: 0; width: 1px; height: 1px;
                overflow: visible; pointer-events: none; }
    svg.lasso polygon { fill: rgba(36, 87, 197, .08); stroke: #2457c5; stroke-width: 2;
                        stroke-dasharray: 5 3; stroke-linejoin: round; }
    .badge { position: absolute; left: -11px; top: -11px; width: 20px; height: 20px;
             border-radius: 50%; background: var(--mark); color: #fff; text-align: center;
             font: 700 11px/20px system-ui, sans-serif; box-shadow: 0 0 0 2px #fff;
             cursor: pointer; pointer-events: auto; user-select: none; }
    .draft .badge { background: #fff; color: var(--mark);
                    box-shadow: 0 0 0 2px var(--mark) inset, 0 0 0 2px #fff; }
    .answered .badge { background: #1b7f4b; }
    .done .badge { background: #6b7480; }
    .hot .badge { background: #2457c5; color: #fff; transform: scale(1.25); }
    .sign-box { position: absolute; box-sizing: border-box; border: 2px solid #1d4ed8;
                border-radius: 3px; pointer-events: none; }
    .sign-box.new { border-color: #15803d; }
    .sign-tag { position: absolute; left: -2px; top: -18px; padding: 0 6px; border-radius: 3px 3px 0 0;
                background: #1d4ed8; color: #fff; font: 600 11px/18px system-ui, sans-serif;
                white-space: nowrap; }
    .sign-box.new .sign-tag { background: #15803d; }
    :host, .layer { --mark: #c2410c; }
  `;

  let host = null;
  let root = null;
  let layer = null;
  let drag = null;               // {pointer, x0, y0, page0, points} while the button is held
  let selection = null;          // {kind, anchor, region, selector, parts} the box is open for
  let markers = [];              // the last comment-markers list
  let placements = new Map();    // token -> {rects} | {points}; null when lost (ANC-06)
  const reported = new Map();    // token -> the lost state the hub has or was told
  let reportTimer = null;
  const stats = {reanchorMs: 0, textMs: 0};  // what the last pass took, for the tests
  let selectedToken = null;
  let hoverToken = null;         // the marker the pointer is on in the panel
  let frameRequested = false;
  let signs = [];                // [{id, sign}] what's new marks (NEW-03)
  const SIGN_NAMES = ["new", "changed"];
  const MAX_SIGNS = 200;

  const post = support.post;

  // ---- the one overlay host (COM-05) --------------------------------------------

  // A child of <html> after <body>: the morph only touches <body>, so the host
  // survives it (early check 14). Created again if a page removed it.
  function ensureHost() {
    const html = document.documentElement;
    for (const extra of html.querySelectorAll(":scope > [" + HOST_ATTRIBUTE + "]")) {
      if (extra !== host) extra.remove();
    }
    if (!host) {
      host = document.createElement("div");
      host.setAttribute(HOST_ATTRIBUTE, "");
      host.style.cssText = "position:absolute;left:0;top:0;width:0;height:0;" +
        "overflow:visible;pointer-events:none;z-index:2147483647;";
      root = host.attachShadow({mode: "open"});  // open: the browser tests look inside
      const style = document.createElement("style");
      style.textContent = STYLE;
      layer = document.createElement("div");
      layer.className = "layer";
      root.append(style, layer);
    }
    const afterBody = !document.body ||
      Boolean(host.compareDocumentPosition(document.body) & Node.DOCUMENT_POSITION_PRECEDING);
    if (host.parentNode !== html || !afterBody) html.appendChild(host);
  }

  // ---- geometry ------------------------------------------------------------------

  function pagePoint(event) {
    const x = Math.min(Math.max(event.clientX, 0), window.innerWidth);
    const y = Math.min(Math.max(event.clientY, 0), window.innerHeight);
    return {cx: x, cy: y, x: x + window.scrollX, y: y + window.scrollY};
  }

  function pageBox(element) {
    const box = element.getBoundingClientRect();
    return {
      x: box.left + window.scrollX, y: box.top + window.scrollY,
      w: box.width, h: box.height,
    };
  }

  function contains(outer, inner) {
    return outer.x <= inner.x + 0.5 && outer.y <= inner.y + 0.5 &&
      outer.x + outer.w >= inner.x + inner.w - 0.5 && outer.y + outer.h >= inner.y + inner.h - 0.5;
  }

  // The innermost element whose border box holds the whole rectangle; else the
  // element under its centre (ANC-03). The host does not take pointer input,
  // so ``elementsFromPoint`` never returns it.
  function targetOf(rect) {
    const centre = [rect.x + rect.w / 2 - window.scrollX, rect.y + rect.h / 2 - window.scrollY];
    const under = document.elementsFromPoint(centre[0], centre[1])
      .find((e) => !e.hasAttribute(HOST_ATTRIBUTE)) || document.body || document.documentElement;
    for (let e = under; e; e = e.parentElement) {
      if (contains(pageBox(e), rect)) return e;
    }
    return under;
  }

  function fraction(value) {
    return Math.round(value * 10000) / 10000;
  }

  // ---- text of the page (ANC-01, ANC-03) -------------------------------------------

  function visibleText(node) {
    const parent = node.parentElement;
    if (!parent) return node.parentNode instanceof ShadowRoot;
    if (SKIPPED_TAGS.has(parent.tagName) || parent.closest("[" + HOST_ATTRIBUTE + "]")) {
      return false;
    }
    const style = getComputedStyle(parent);
    return style.visibility !== "hidden" && style.display !== "none";
  }

  function textWalker(root) {
    const top = root === document ? document.body : root;
    return document.createTreeWalker(top, NodeFilter.SHOW_TEXT);
  }

  // The nearest ancestor that is not inline: text of two blocks never runs together.
  function blockOf(node, cache) {
    const first = node.parentElement;
    let element = first;
    while (element && !cache.has(element)) {
      const display = getComputedStyle(element).display;
      if (!display.startsWith("inline") && display !== "contents") break;
      element = element.parentElement;
    }
    if (!element) return null;
    const block = cache.get(element) || element;
    cache.set(first, block);
    return block;
  }

  // True when a line break lies between two text nodes of one block.
  function breaksBetween(first, second) {
    const gap = document.createRange();
    gap.setStartAfter(first);
    gap.setEndBefore(second);
    return Boolean(gap.cloneContents().querySelector("br"));
  }

  // The text of the document (or of one block's shadow root) with white space
  // collapsed, and for every text node where it stands in it: ``start`` and ``end``
  // are the text's length before and after the node. ``endsOf(part)[k]`` is the
  // length after the node's k-th character, worked out only for a node that is
  // asked for. ``root`` is the document or a shadow root.
  function textIndex(root) {
    const cache = new Map();
    const parts = [];
    let text = "";
    let lastBlock = null;
    let previous = null;
    const walker = textWalker(root);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!visibleText(node)) continue;
      const block = blockOf(node, cache);
      if (text && !text.endsWith(" ") &&
          (block !== lastBlock || breaksBetween(previous, node))) text += " ";
      lastBlock = block;
      previous = node;
      const start = text.length;
      const joined = !text || text.endsWith(" ");
      const collapsed = node.data.replace(/\s+/g, " ");
      text += joined && collapsed.startsWith(" ") ? collapsed.slice(1) : collapsed;
      parts.push({node, start, end: text.length, joined, ends: null});
    }
    return {text, parts};
  }

  function endsOf(part) {
    if (!part.ends) {
      const data = part.node.data;
      const ends = new Int32Array(data.length);
      let length = part.start;
      let space = part.joined;
      for (let i = 0; i < data.length; i++) {
        if (/\s/.test(data[i])) {
          if (!space) length += 1;
          space = true;
        } else {
          length += 1;
          space = false;
        }
        ends[i] = length;
      }
      part.ends = ends;
    }
    return part.ends;
  }

  function offsetIn(part, index) {
    const ends = endsOf(part);
    return index <= 0 ? part.start : ends[Math.min(index, ends.length) - 1];
  }

  function round1(value) {
    return Math.round(value * 10) / 10;
  }

  // The client rectangles of the selected characters, one per line box, in page pixels.
  function lineRects(pieces) {
    const lines = [];
    const probe = document.createRange();
    for (const {node, from, to} of pieces) {
      probe.setStart(node, from);
      probe.setEnd(node, to);
      for (const box of probe.getClientRects()) {
        if (box.width <= 0 || box.height <= 0) continue;
        const mid = (box.top + box.bottom) / 2;
        const line = lines.find((l) => Math.abs((l.top + l.bottom) / 2 - mid) < box.height / 2);
        if (line) {
          line.left = Math.min(line.left, box.left);
          line.right = Math.max(line.right, box.right);
          line.top = Math.min(line.top, box.top);
          line.bottom = Math.max(line.bottom, box.bottom);
        } else {
          lines.push({left: box.left, right: box.right, top: box.top, bottom: box.bottom});
        }
      }
    }
    return lines.sort((a, b) => a.top - b.top || a.left - b.left).map((l) => ({
      x: round1(l.left + window.scrollX), y: round1(l.top + window.scrollY),
      w: round1(l.right - l.left), h: round1(l.bottom - l.top),
    }));
  }

  function boundsOf(rects) {
    const x0 = Math.min(...rects.map((r) => r.x));
    const y0 = Math.min(...rects.map((r) => r.y));
    const x1 = Math.max(...rects.map((r) => r.x + r.w));
    const y1 = Math.max(...rects.map((r) => r.y + r.h));
    return {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
  }

  // Words of one text node with their client rectangles, in line groups.
  function lineGroups(node) {
    const text = node.data;
    const lines = [];
    const range = document.createRange();
    for (const match of text.matchAll(/\S+/g)) {
      range.setStart(node, match.index);
      range.setEnd(node, match.index + match[0].length);
      const rects = range.getClientRects();
      if (!rects.length) continue;
      const box = rects[0];
      const last = lines[lines.length - 1];
      if (last && Math.abs(last.top - box.top) < 2 && Math.abs(last.bottom - box.bottom) < 2) {
        last.words.push(match[0]);
        last.left = Math.min(last.left, box.left);
        last.right = Math.max(last.right, rects[rects.length - 1].right);
      } else {
        lines.push({
          words: [match[0]], top: box.top, bottom: box.bottom,
          left: box.left, right: rects[rects.length - 1].right,
        });
      }
    }
    return lines;
  }

  // Even-odd rule; the polygon and the point are in the same pixels.
  function inPolygon(x, y, points) {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [xi, yi] = points[i];
      const [xj, yj] = points[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  // The visible text of the line boxes whose centre lies in the rectangle (and,
  // for a lasso, inside its polygon, even-odd), in document order, joined by
  // spaces, cut at 500 characters; null when empty. A text node whose bounding
  // box misses the rectangle is not split into lines (early check 13: 4-16 ms
  // instead of 110 ms for 200 points over 2000 lines).
  function textInside(rect, polygon) {
    const view = {
      left: rect.x - window.scrollX, top: rect.y - window.scrollY,
      right: rect.x + rect.w - window.scrollX, bottom: rect.y + rect.h - window.scrollY,
    };
    const parts = [];
    const walker = textWalker(document);
    const probe = document.createRange();
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.data.trim() || !visibleText(node)) continue;
      probe.selectNodeContents(node);
      const box = probe.getBoundingClientRect();
      if (box.right < view.left || box.left > view.right ||
          box.bottom < view.top || box.top > view.bottom) continue;
      for (const line of lineGroups(node)) {
        const x = (line.left + line.right) / 2;
        const y = (line.top + line.bottom) / 2;
        if (x < view.left || x > view.right || y < view.top || y > view.bottom) continue;
        if (polygon && !inPolygon(x + window.scrollX, y + window.scrollY, polygon)) continue;
        parts.push(line.words.join(" "));
      }
    }
    const joined = parts.join(" ");
    return joined ? joined.slice(0, INSIDE_LIMIT) : null;
  }

  // ---- the shape being dragged and the selection ------------------------------------

  function shapeElement(klass, rect) {
    const element = document.createElement("div");
    element.className = "box " + klass;
    element.style.left = rect.x + "px";
    element.style.top = rect.y + "px";
    element.style.width = rect.w + "px";
    element.style.height = rect.h + "px";
    return element;
  }

  function dotElement(point) {
    const element = document.createElement("div");
    element.className = "dot";
    element.style.left = point.x + "px";
    element.style.top = point.y + "px";
    return element;
  }

  // Parsed as HTML, so that the browser gives the svg element its namespace.
  function lassoElement(points, klass = "lasso") {
    const holder = document.createElement("template");
    const list = points.map((p) => `${Number(p[0])},${Number(p[1])}`).join(" ");
    holder.innerHTML = `<svg class="${klass}"><polygon points="${list}"/></svg>`;
    return holder.content.firstElementChild;
  }

  function dragRect(end) {
    return {
      x: Math.min(drag.page0.x, end.x), y: Math.min(drag.page0.y, end.y),
      w: Math.abs(end.x - drag.page0.x), h: Math.abs(end.y - drag.page0.y),
    };
  }

  function onMove(event) {
    if (!drag || event.pointerId !== drag.pointer) return;
    drag.last = pagePoint(event);
    if (support.mode.kind === "lasso") {
      // Fast strokes arrive as one event per frame: take the samples it holds.
      const samples = event.getCoalescedEvents ? event.getCoalescedEvents() : [];
      for (const sample of samples.length ? samples : [event]) {
        if (drag.points.length >= MAX_RAW_POINTS) break;
        const at = pagePoint(sample);
        drag.points.push([at.x, at.y]);
      }
    } else {
      drag.rect = dragRect(drag.last);
    }
    render();
  }

  function endDrag() {
    window.removeEventListener("pointermove", onMove, true);
    window.removeEventListener("pointercancel", cancelDrag, true);
    drag = null;
  }

  function cancelDrag() {
    endDrag();
    render();
  }

  function startDrag(event) {
    if (!event.isPrimary || event.button !== 0 || !support.mode.on) return;
    if (support.mode.kind === "text") return;
    ensureHost();
    const point = pagePoint(event);
    drag = {
      pointer: event.pointerId, x0: point.cx, y0: point.cy, page0: point, rect: null,
      last: point, points: [[point.x, point.y]],
    };
    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("pointercancel", cancelDrag, true);
    if (support.mode.kind === "point") return;
    try {
      document.documentElement.setPointerCapture(event.pointerId);
    } catch (error) { /* the gesture still works inside the frame */ }
  }

  function finishDrag(event) {
    if (!drag || event.pointerId !== drag.pointer) return;
    const end = pagePoint(event);
    const kind = support.mode.kind;
    const moved = [Math.abs(end.cx - drag.x0), Math.abs(end.cy - drag.y0)];
    const rect = dragRect(end);
    const points = drag.points;
    const start = drag.page0;
    endDrag();
    if (kind === "point" && Math.max(...moved) < MIN_DRAG) {
      selectPoint({x: Math.round(start.x), y: Math.round(start.y)});
    } else if (kind === "rect" && Math.min(...moved) >= MIN_DRAG) {
      selectRect({x: Math.round(rect.x), y: Math.round(rect.y),
        w: Math.round(rect.w), h: Math.round(rect.h)});
    } else if (kind === "lasso") {
      const last = points[points.length - 1];
      if (last[0] !== end.x || last[1] !== end.y) points.push([end.x, end.y]);
      selectLasso(points);
    } else {
      render();
    }
  }

  // ---- anchors (ANC-01 to ANC-05) ---------------------------------------------------

  // The fractions of ``rect`` (page pixels) in the target's border box.
  function fractionsIn(target, rect) {
    const box = pageBox(target);
    return {
      fx: fraction((rect.x - box.x) / (box.w || 1)), fy: fraction((rect.y - box.y) / (box.h || 1)),
      fw: fraction(rect.w / (box.w || 1)), fh: fraction(rect.h / (box.h || 1)),
    };
  }

  function targetReport(target) {
    const described = support.describeTarget(target);
    return {canvas_id: described.canvas_id, selector: described.selector, text: described.text};
  }

  // The element the report's selector names: the target itself, or the ancestor
  // with an id that owns it. Fractions are taken in its box, so that finding it
  // again (ANC-06) gives the same place.
  function namedBy(described, target) {
    try {
      return document.querySelector(described.selector) || target;
    } catch (error) {
      return target;
    }
  }

  // The plot a shape lies over: the one holding the point, or overlapping the
  // box most (ANC-05).
  function plotOver(box) {
    let best = null;
    let bestArea = 0;
    for (const plot of document.querySelectorAll("canvas-plot")) {
      if (typeof plot.dataBbox !== "function") continue;
      const p = pageBox(plot);
      const w = Math.min(p.x + p.w, box.x + box.w) - Math.max(p.x, box.x);
      const h = Math.min(p.y + p.h, box.y + box.h) - Math.max(p.y, box.y);
      const overlap = box.w || box.h ? Math.max(0, w) * Math.max(0, h) : (w >= 0 && h >= 0 ? 1 : 0);
      if (overlap > bestArea) {
        best = plot;
        bestArea = overlap;
      }
    }
    return best;
  }

  // Data coordinates of a point or a box (ANC-05); null when no plot is under it.
  function plotData(box, isPoint) {
    const plot = plotOver(box);
    if (!plot) return null;
    const left = box.x - window.scrollX;
    const top = box.y - window.scrollY;
    const converted = isPoint ? plot.dataPoint(left, top) : plot.dataBbox([left, top, box.w, box.h]);
    return converted ? {canvas_id: plot.getAttribute("data-canvas-id"), ...converted} : null;
  }

  // Keep the selection and report it, which opens the shell's comment box.
  function report(kind, anchor, region, target, extra) {
    selection = {kind, anchor, region, selector: target.selector, pieces: extra.pieces || null};
    render();
    const message = {
      type: "comment-selection", kind, anchor, target,
      rect: {x: region.x - window.scrollX, y: region.y - window.scrollY, w: region.w, h: region.h},
      text_inside: extra.text_inside === undefined ? null : extra.text_inside,
    };
    if (extra.data) message.data = extra.data;
    post(message);
  }

  // ---- a picture's pixels (ANC-02 to ANC-04 in image-px) ----------------------------

  // The viewer whose anchors are in a space of its own (4.2), or null on a page.
  function picture() {
    const viewer = window.acViewer;
    return viewer && viewer.space === "image-px" ? viewer : null;
  }

  function pdf() {
    const viewer = window.acViewer;
    return viewer && viewer.space === "pdf-pt" ? viewer : null;
  }

  function spaced() {
    return picture() || pdf();
  }

  // A picture anchor in the frame's pixels now; null when the picture has another
  // natural size than the anchor was made on (ANC-08).
  function placePicture(kind, anchor) {
    const viewer = picture();
    if (!viewer || !anchor || anchor.space !== "image-px") return null;
    const size = viewer.size();
    if (!size.w || anchor.nw !== size.w || anchor.nh !== size.h) return null;
    return placeIn(kind, anchor, (x, y) => {
      const spot = viewer.fromSpace(x, y);
      return [spot.x, spot.y];
    });
  }

  // A PDF shape anchor in the frame's pixels now; null when its page no longer
  // exists (ANC-08).
  function placePdf(kind, anchor) {
    const viewer = pdf();
    if (!viewer || !anchor || anchor.space !== "pdf-pt") return null;
    if (!Number.isInteger(anchor.p) || anchor.p < 1 || anchor.p > viewer.pageCount) return null;
    return placeIn(kind, anchor, (x, y) => {
      const spot = viewer.fromSpace(anchor.p, x, y);
      return [spot.x, spot.y];
    });
  }

  function placeViewer(kind, anchor) {
    return anchor && anchor.space === "pdf-pt" ? placePdf(kind, anchor) : placePicture(kind, anchor);
  }

  // The shape of ``anchor`` with ``at`` turning its coordinates into frame pixels.
  function placeIn(kind, anchor, at) {
    if (kind === "lasso") {
      return Array.isArray(anchor.points) && anchor.points.length
        ? {points: anchor.points.map(([x, y]) => at(x, y))} : null;
    }
    const [x, y] = at(anchor.x, anchor.y);
    if (kind === "point") return {rect: {x, y, w: 0, h: 0}};
    const [x1, y1] = at(anchor.x + anchor.w, anchor.y + anchor.h);
    return {rect: {x, y, w: x1 - x, h: y1 - y}};
  }

  // The gesture's shape (frame pixels; a viewer does not scroll the page) as an
  // image-px or pdf-pt anchor, cut to the picture or to the page it begins on (a
  // rectangle at its top-left corner, a lasso at its first point). Nothing is
  // selected outside it.
  function selectInViewer(kind, shape) {
    const viewer = spaced();
    const first = kind === "lasso" ? shape[0] : [shape.x, shape.y];
    const page = viewer === pdf() ? viewer.toSpace(first[0], first[1]).p : undefined;
    const {w, h} = viewer.size(page);
    const clamp = (value, high) => round1(Math.min(Math.max(value, 0), high));
    const toPixel = ([x, y]) => {
      const spot = viewer.toSpace(x, y, page);
      return [clamp(spot.x, w), clamp(spot.y, h)];
    };
    const base = page ? {space: "pdf-pt", p: page} : {space: "image-px", nw: w, nh: h};
    let anchor;
    if (kind === "point") {
      const spot = viewer.toSpace(shape.x, shape.y, page);
      if (spot.x < 0 || spot.y < 0 || spot.x > w || spot.y > h) return render();
      anchor = {...base, x: round1(spot.x), y: round1(spot.y)};
    } else if (kind === "rect") {
      const [x0, y0] = toPixel([shape.x, shape.y]);
      const [x1, y1] = toPixel([shape.x + shape.w, shape.y + shape.h]);
      if (x1 - x0 < 1 || y1 - y0 < 1) return render();
      anchor = {...base, x: x0, y: y0, w: round1(x1 - x0), h: round1(y1 - y0)};
    } else {
      const points = lassoPoints(shape).map(toPixel);
      const bbox = boundsOf(points.map(([x, y]) => ({x, y, w: 0, h: 0})));
      anchor = {...base, points, bbox};
    }
    const placed = placeViewer(kind, anchor);
    const region = placed.points
      ? boundsOf(placed.points.map(([x, y]) => ({x, y, w: 0, h: 0}))) : placed.rect;
    const element = page ? document.querySelector(`[data-pdf-page="${page}"]`)
      : document.querySelector("[data-stage] img");
    const box = kind === "lasso" ? anchor.bbox : kind === "rect" ? anchor : null;
    report(kind, anchor, region, targetReport(element),
      {text_inside: page && kind !== "point" ? pdfInside(viewer, page, box, anchor.points) : null});
  }

  // The text of the page's items whose centre lies in ``box`` (and in ``polygon``, even-odd),
  // in document order, joined by spaces, cut at 500 characters; null when empty (ANC-03).
  function pdfInside(viewer, page, box, polygon) {
    const index = viewer.index;
    if (!index) return null;
    const parts = [];
    for (const item of index.pages[page - 1]) {
      const x = item.x + item.w / 2;
      const y = item.y + item.h / 2;
      if (item.end === item.start || x < box.x || x > box.x + box.w ||
          y < box.y || y > box.y + box.h) continue;
      if (polygon && !inPolygon(x, y, polygon)) continue;
      parts.push(index.text.slice(item.start, item.end));
    }
    const joined = parts.join(" ");
    return joined ? joined.slice(0, INSIDE_LIMIT) : null;
  }

  function selectRect(rect) {
    if (spaced()) return selectInViewer("rect", rect);
    const target = targetOf(rect);
    const described = targetReport(target);
    const anchor = {space: "page-px", ...rect, ...fractionsIn(namedBy(described, target), rect)};
    report("rect", anchor, rect, described,
      {text_inside: textInside(rect), data: plotData(rect, false)});
  }

  function selectPoint(point) {
    if (spaced()) return selectInViewer("point", point);
    const spot = {x: point.x, y: point.y, w: 0, h: 0};
    const target = targetOf(spot);
    const described = targetReport(target);
    const box = pageBox(namedBy(described, target));
    const anchor = {
      space: "page-px", x: point.x, y: point.y,
      fx: fraction((point.x - box.x) / (box.w || 1)), fy: fraction((point.y - box.y) / (box.h || 1)),
    };
    report("point", anchor, spot, described, {data: plotData(spot, true)});
  }

  function areaOf(points) {
    let sum = 0;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      sum += points[j][0] * points[i][1] - points[i][0] * points[j][1];
    }
    return Math.abs(sum) / 2;
  }

  // Douglas-Peucker on the open path; both ends stay.
  function simplify(points, tolerance) {
    const keep = new Uint8Array(points.length);
    keep[0] = keep[points.length - 1] = 1;
    const stack = [[0, points.length - 1]];
    while (stack.length) {
      const [a, b] = stack.pop();
      let far = -1;
      let farDistance = tolerance;
      const [ax, ay] = points[a];
      const dx = points[b][0] - ax;
      const dy = points[b][1] - ay;
      const length = Math.hypot(dx, dy);
      for (let i = a + 1; i < b; i++) {
        const [px, py] = points[i];
        const distance = length
          ? Math.abs(dx * (ay - py) - (ax - px) * dy) / length
          : Math.hypot(px - ax, py - ay);
        if (distance > farDistance) {
          far = i;
          farDistance = distance;
        }
      }
      if (far >= 0) {
        keep[far] = 1;
        stack.push([a, far], [far, b]);
      }
    }
    return points.filter((_, i) => keep[i]);
  }

  // The path simplified with a 2 px tolerance; a longer result is simplified
  // again with a wider one until it has at most 200 points (ANC-04).
  function lassoPoints(raw) {
    let tolerance = LASSO_TOLERANCE;
    let points = simplify(raw, tolerance);
    while (points.length > LASSO_MAX_POINTS) {
      tolerance *= 1.5;
      points = simplify(points, tolerance);
    }
    return points.map(([x, y]) => [round1(x), round1(y)]);
  }

  function selectLasso(raw) {
    if (raw.length < LASSO_MIN_POINTS || areaOf(raw) < LASSO_MIN_AREA) {
      render();
      return;
    }
    if (spaced()) return selectInViewer("lasso", raw);
    const points = lassoPoints(raw);
    const bbox = boundsOf(points.map(([x, y]) => ({x, y, w: 0, h: 0})));
    const target = targetOf(bbox);
    const described = targetReport(target);
    const base = namedBy(described, target);
    const box = pageBox(base);
    const anchor = {
      space: "page-px", points, bbox, ...fractionsIn(base, bbox),
      fpoints: points.map(([x, y]) => [fraction((x - box.x) / (box.w || 1)),
        fraction((y - box.y) / (box.h || 1))]),
    };
    report("lasso", anchor, bbox, described,
      {text_inside: textInside(bbox, points), data: plotData(bbox, false)});
  }

  // ---- text selection (ANC-01, COM-17) -------------------------------------------------

  function shadowRoots(scope, found) {
    for (const element of scope.querySelectorAll("*")) {
      if (!element.shadowRoot) continue;
      found.push(element.shadowRoot);
      shadowRoots(element.shadowRoot, found);
    }
    return found;
  }

  // The selection the owner made with the browser's own tools, read when the
  // pointer is released. Text inside one block's shadow root comes through the
  // composed ranges (early check 16); a selection whose ends lie in different
  // trees gives no single range: the shell shows a notice.
  function readText() {
    if (pdf()) return readPdfText(pdf());
    const picked = window.getSelection();
    if (!picked || !picked.rangeCount || !picked.toString().trim()) return;
    const found = picked.getComposedRanges
      ? picked.getComposedRanges({shadowRoots: shadowRoots(document, [])})[0]
      : picked.getRangeAt(0);
    const root = found.startContainer.getRootNode();
    if (root !== found.endContainer.getRootNode()) {
      post({type: "comment-selection", kind: "text", notice: "block-boundary"});
      return;
    }
    const range = document.createRange();
    range.setStart(found.startContainer, found.startOffset);
    range.setEnd(found.endContainer, found.endOffset);
    const index = textIndex(root);
    const pieces = [];
    let from = Infinity;
    let to = -Infinity;
    for (const part of index.parts) {
      if (!range.intersectsNode(part.node)) continue;
      const a = part.node === range.startContainer ? range.startOffset : 0;
      const b = part.node === range.endContainer ? range.endOffset : part.node.data.length;
      if (b <= a) continue;
      pieces.push({node: part.node, from: a, to: b});
      from = Math.min(from, offsetIn(part, a));
      to = Math.max(to, offsetIn(part, b));
    }
    const raw = index.text.slice(from, to);
    const quote = raw.trim();
    if (!quote) return;
    const start = from + raw.length - raw.trimStart().length;
    const end = start + quote.length;
    const alnum = (text) => text.match(/[\p{L}\p{N}]/gu) || [];
    const rects = lineRects(pieces);
    if (!rects.length) return;
    const anchor = {
      space: "page-px", quote: quote.slice(0, QUOTE_LIMIT), cut: quote.length > QUOTE_LIMIT,
      before: alnum(index.text.slice(0, start)).slice(-CONTEXT_LIMIT).join(""),
      after: alnum(index.text.slice(end)).slice(0, CONTEXT_LIMIT).join(""),
      start, end, rects,
    };
    const common = range.commonAncestorContainer;
    const element = common.nodeType === Node.ELEMENT_NODE ? common : common.parentElement;
    report("text", anchor, boundsOf(rects), targetReport(element || document.body), {pieces});
  }

  // Where character ``k`` of a text item's string stands in the document's text.
  function itemOffset(item, k) {
    const collapsed = item.str.slice(0, k).replace(/\s+/g, " ").length - item.lead;
    return Math.min(item.end, Math.max(item.start, item.start + collapsed));
  }

  // The line boxes (points on their page) of the characters ``start`` to ``end`` of a
  // PDF's text: each item's share of its box, items on one line joined.
  function pdfRects(index, start, end) {
    const {items} = index;
    let low = 0;
    let high = items.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (items[mid].end > start) high = mid;
      else low = mid + 1;
    }
    const lines = [];
    for (let i = low; i < items.length && items[i].start < end; i++) {
      const item = items[i];
      const length = item.end - item.start;
      const a = Math.max(start, item.start) - item.start;
      const b = Math.min(end, item.end) - item.start;
      if (!length || b <= a) continue;
      const x = item.x + item.w * a / length;
      const right = item.x + item.w * b / length;
      const mid = item.y + item.h / 2;
      const line = lines.find((l) => l.p === item.p && Math.abs((l.top + l.bottom) / 2 - mid) < item.h / 2);
      if (line) {
        line.left = Math.min(line.left, x);
        line.right = Math.max(line.right, right);
        line.top = Math.min(line.top, item.y);
        line.bottom = Math.max(line.bottom, item.y + item.h);
      } else {
        lines.push({p: item.p, left: x, right, top: item.y, bottom: item.y + item.h});
      }
    }
    return lines.sort((a, b) => a.p - b.p || a.top - b.top || a.left - b.left).map((l) => ({
      p: l.p, x: round1(l.left), y: round1(l.top), w: round1(l.right - l.left), h: round1(l.bottom - l.top),
    }));
  }

  // Point rectangles on their pages as frame pixels now.
  function frameRects(viewer, rects) {
    return rects.map((r) => {
      const a = viewer.fromSpace(r.p, r.x, r.y);
      const b = viewer.fromSpace(r.p, r.x + r.w, r.y + r.h);
      return {x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y};
    });
  }

  // The selection in a PDF's text layers (ANC-01): the quote and its place come from
  // the document's text items, so that they do not depend on which pages are drawn.
  function readPdfText(viewer) {
    const picked = window.getSelection();
    const index = viewer.index;
    if (!picked || !picked.rangeCount || !picked.toString().trim() || !index) return;
    const range = picked.getRangeAt(0);
    let from = Infinity;
    let to = -Infinity;
    for (const span of document.querySelectorAll(".textLayer span")) {
      const node = span.firstChild;
      const item = node && range.intersectsNode(node) ? viewer.itemOf(span) : null;
      if (!item) continue;
      const a = node === range.startContainer ? range.startOffset : 0;
      const b = node === range.endContainer ? range.endOffset : node.data.length;
      if (b <= a) continue;
      from = Math.min(from, itemOffset(item, a));
      to = Math.max(to, itemOffset(item, b));
    }
    const raw = index.text.slice(from, to);
    const quote = raw.trim();
    if (!quote) return;
    const start = from + raw.length - raw.trimStart().length;
    const end = start + quote.length;
    const alnum = (text) => text.match(/[\p{L}\p{N}]/gu) || [];
    const rects = pdfRects(index, start, end);
    if (!rects.length) return;
    const anchor = {
      space: "pdf-pt", quote: quote.slice(0, QUOTE_LIMIT), cut: quote.length > QUOTE_LIMIT,
      before: alnum(index.text.slice(0, start)).slice(-CONTEXT_LIMIT).join(""),
      after: alnum(index.text.slice(end)).slice(0, CONTEXT_LIMIT).join(""),
      start, end, rects,
    };
    const page = document.querySelector(`[data-pdf-page="${rects[0].p}"]`);
    report("text", anchor, boundsOf(frameRects(viewer, rects)), targetReport(page), {pieces: null});
  }

  // The open selection's shape again from its anchor, after a resize or a
  // reflow (COM-13): from the target's fractions when it is found, else page pixels.
  function shapeOf(kind, anchor, selector) {
    const found = placeViewer(kind, anchor) || anchors.placeShape(kind, anchor, {selector});
    if (found) return found;
    if (kind === "lasso") return {points: anchor.points};
    return {rect: {x: anchor.x, y: anchor.y, w: anchor.w || 0, h: anchor.h || 0}};
  }

  // ---- the picture (COM-12)------------------------------------------------------------

  function pageSize() {
    const html = document.documentElement;
    return {
      w: Math.max(html.scrollWidth, document.body ? document.body.scrollWidth : 0),
      h: Math.max(html.scrollHeight, document.body ? document.body.scrollHeight : 0),
    };
  }

  // The shape's box padded by 16 px (a point: 320 x 200 around it), clamped to the
  // page, whole pixels.
  function pictureRegion(rect, isPoint) {
    const size = pageSize();
    const padX = isPoint ? POINT_BOX[0] / 2 : PAD;
    const padY = isPoint ? POINT_BOX[1] / 2 : PAD;
    const x0 = Math.max(0, rect.x - padX);
    const y0 = Math.max(0, rect.y - padY);
    const x1 = Math.min(size.w, rect.x + rect.w + padX);
    const y1 = Math.min(size.h, rect.y + rect.h + padY);
    return {x: x0, y: y0, w: Math.max(1, x1 - x0), h: Math.max(1, y1 - y0)};
  }

  // The pin of a point and the path of a lasso, drawn on a crop. ``anchor`` holds
  // the selection's own coordinates, ``origin`` the crop's top-left in them and
  // ``unit`` the size of one CSS px in them.
  function drawMarks(canvas, kind, anchor, origin, unit) {
    if (kind !== "point" && kind !== "lasso") return;
    const context = canvas.getContext("2d");
    context.lineWidth = 2 * unit;
    context.strokeStyle = MARK_COLOUR;
    context.fillStyle = MARK_COLOUR;
    context.beginPath();
    if (kind === "point") {
      context.arc(anchor.x - origin.x, anchor.y - origin.y, 6 * unit, 0, 2 * Math.PI);
      context.fill();
      context.strokeStyle = "#fff";
    } else {
      anchor.points.forEach(([x, y], i) => context[i ? "lineTo" : "moveTo"](x - origin.x, y - origin.y));
      context.closePath();
    }
    context.stroke();
  }

  // The selection cut from the picture's own pixels (COM-12), at least one picture
  // pixel for each CSS px, with the pin or the lasso path on it.
  function cropPicture() {
    const {kind, anchor} = selection;
    const scale = window.acImageView().scale;
    const unit = Math.max(1, 1 / scale);
    const {canvas, x, y} = picture().crop(cropBox(scale));
    drawMarks(canvas, kind, anchor, {x, y}, unit);
    return canvas;
  }

  // The selection's box in the viewer's own units padded by 16 CSS px (a point:
  // 320 x 200 CSS px around it); ``scale`` is CSS px per unit. A text on several
  // pages is cut on its first.
  function cropBox(scale) {
    const {kind, anchor} = selection;
    if (kind === "point") {
      return {x: anchor.x - POINT_BOX[0] / scale / 2, y: anchor.y - POINT_BOX[1] / scale / 2,
        w: POINT_BOX[0] / scale, h: POINT_BOX[1] / scale};
    }
    const first = kind === "text" ? anchor.rects.filter((r) => r.p === anchor.rects[0].p) : null;
    const {x, y, w, h} = kind === "text" ? boundsOf(first) : kind === "lasso" ? anchor.bbox : anchor;
    return {x: x - PAD / scale, y: y - PAD / scale, w: w + 2 * PAD / scale, h: h + 2 * PAD / scale};
  }

  // The selection cut from its page's canvas, which has at least one canvas pixel for
  // each CSS px and is not enlarged (COM-12), with the pin or the lasso path on it.
  async function cropPdf() {
    const viewer = pdf();
    const {kind, anchor} = selection;
    const page = kind === "text" ? anchor.rects[0].p : anchor.p;
    const {canvas, x, y, k} = await viewer.crop(page, cropBox(viewer.scale));
    const inPixels = {
      x: anchor.x * k, y: anchor.y * k,
      points: anchor.points && anchor.points.map(([a, b]) => [a * k, b * k]),
    };
    drawMarks(canvas, kind, inPixels, {x, y}, k / viewer.scale);
    return canvas;
  }

  async function cropPage() {
    const {kind, anchor, region} = selection;
    const crop = pictureRegion(region, kind === "point");
    const {canvas} = await support.renderRegion(crop);
    drawMarks(canvas, kind, anchor, crop, 1);
    return canvas;
  }

  async function makePicture(token) {
    const answer = {type: "comment-picture", token, ok: false};
    try {
      let canvas = picture() ? cropPicture() : pdf() ? await cropPdf() : await cropPage();
      const longer = Math.max(canvas.width, canvas.height);
      if (longer > MAX_SIDE) {
        const scale = MAX_SIDE / longer;
        const small = document.createElement("canvas");
        small.width = Math.max(1, Math.round(canvas.width * scale));
        small.height = Math.max(1, Math.round(canvas.height * scale));
        small.getContext("2d").drawImage(canvas, 0, 0, small.width, small.height);
        canvas = small;
      }
      answer.png = canvas.toDataURL("image/png");
      answer.ok = true;
    } catch (error) {
      answer.error = "picture failed: " + (error && error.message ? error.message : error);
    }
    post(answer);
  }

  // ---- finding anchors again (ANC-06) -----------------------------------------------------

  // First index of ``ends`` (sorted) whose value is at least ``value``.
  function firstAtLeast(ends, value) {
    let low = 0;
    let high = ends.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (ends[mid] >= value) high = mid;
      else low = mid + 1;
    }
    return low;
  }

  // The characters of the text nodes that stand in ``index.text`` between
  // ``start`` and ``end``, as ranges of their nodes.
  function piecesBetween(index, start, end) {
    const {parts} = index;
    let low = 0;
    let high = parts.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (parts[mid].end > start) high = mid;
      else low = mid + 1;
    }
    const pieces = [];
    for (let i = low; i < parts.length && parts[i].start < end; i++) {
      const {node} = parts[i];
      const ends = endsOf(parts[i]);
      const from = firstAtLeast(ends, start + 1);
      const to = Math.min(ends.length, firstAtLeast(ends, end) + 1);
      if (to > from) pieces.push({node, from, to});
    }
    return pieces;
  }

  // The quote's line boxes: the occurrence whose surroundings agree most among
  // the document's text and every shadow root's text (ANC-06); offsets inside a
  // block are offsets in that block's text. A dead heat between texts is lost.
  function placeText(marker, texts) {
    if (!texts.document) {
      const built = performance.now();
      texts.document = textIndex(document);
      texts.shadows = shadowRoots(document, []).map((r) => textIndex(r));
      stats.textMs = performance.now() - built;
    }
    let best = null;
    let tied = false;
    for (const index of [texts.document, ...texts.shadows]) {
      const hit = anchors.search(index.text, marker.anchor);
      if (!hit) continue;
      if (!best || hit.score > best.hit.score) {
        best = {index, hit};
        tied = false;
      } else if (hit.score === best.hit.score) {
        tied = true;
      }
    }
    if (!best || tied) return null;
    const rects = lineRects(piecesBetween(best.index, best.hit.start, best.hit.end));
    return rects.length ? {rects} : null;
  }

  // A PDF text anchor searched in the text of the document's items (ANC-08).
  function placePdfText(marker) {
    const viewer = pdf();
    const index = viewer && viewer.index;
    const hit = index && anchors.search(index.text, marker.anchor);
    const rects = hit ? pdfRects(index, hit.start, hit.end) : [];
    return rects.length ? {rects: frameRects(viewer, rects)} : null;
  }

  function place(marker, texts) {
    if (marker.anchor.space === "pdf-pt" && marker.kind === "text") return placePdfText(marker);
    if (marker.kind === "text") return placeText(marker, texts);
    const shape = marker.anchor.space === "image-px" || marker.anchor.space === "pdf-pt"
      ? placeViewer(marker.kind, marker.anchor)
      : anchors.placeShape(marker.kind, marker.anchor, marker.target);
    return shape && (shape.points ? shape : {rects: [shape.rect]});
  }

  // Find every marker's anchor again; a marker that is not found has no place.
  function reanchor() {
    const started = performance.now();
    const texts = {};
    const found = new Map();
    for (const marker of markers) found.set(marker.token, place(marker, texts));
    placements = found;
    stats.reanchorMs = performance.now() - started;
    if (!reportTimer) reportTimer = setTimeout(sendLost, LOST_DELAY_MS);
  }

  // Report each marker whose lost state differs from the hub's (ANC-06). Page
  // blocks may still be drawing while the page loads: wait for the load, and
  // report what stands then, not every step on the way.
  function sendLost() {
    reportTimer = null;
    // An earlier version (?v=N) is read-only: its anchors are not the hub's newest.
    if (new URLSearchParams(location.search).has("v")) return;
    // A viewer shows its file after the load event, a PDF's text is read after that;
    // anchors are not lost before.
    const viewer = window.acViewer;
    if (document.readyState !== "complete" || (viewer && (!viewer.mounted || viewer.index === null))) {
      reportTimer = setTimeout(sendLost, LOST_DELAY_MS);
      return;
    }
    const items = [];
    for (const marker of markers) {
      const lost = !placements.get(marker.token);
      if (reported.get(marker.token) === lost) continue;
      reported.set(marker.token, lost);
      items.push({token: marker.token, lost});
    }
    if (items.length) post({type: "comment-lost", items});
  }

  // ---- markers (COM-05) ---------------------------------------------------------------

  function badgeElement(marker, x, y) {
    const badge = document.createElement("div");
    badge.className = "badge";
    badge.textContent = String(marker.n);
    badge.dataset.token = marker.token;
    if (x !== undefined) {
      badge.style.left = x - 11 + "px";
      badge.style.top = y - 11 + "px";
    }
    badge.addEventListener("click", () => {
      post({type: "comment-marker", token: marker.token, action: "click"});
    });
    badge.addEventListener("pointerenter", () => {
      post({type: "comment-marker", token: marker.token, action: "hover"});
    });
    badge.addEventListener("pointerleave", () => {
      post({type: "comment-marker", token: marker.token, action: "leave"});
    });
    return badge;
  }

  function markerElement(marker, spot) {
    const hot = marker.token === selectedToken || marker.token === hoverToken;
    const klass = `${marker.status}${hot ? " hot" : ""}`;
    if (marker.kind === "rect") {
      const element = shapeElement(klass, spot.rects[0]);
      element.dataset.mk = marker.token;
      element.dataset.n = String(marker.n);
      element.append(badgeElement(marker));  // at the outline's corner, by the style sheet
      return element;
    }
    const element = document.createElement("div");
    element.className = "mk " + klass;
    element.dataset.mk = marker.token;
    element.dataset.n = String(marker.n);
    let at;
    if (marker.kind === "text") {
      element.append(...spot.rects.map((rect) => shapeElement("hl", rect)));
      at = [Math.max(12, spot.rects[0].x - 16), spot.rects[0].y + spot.rects[0].h / 2];
    } else if (marker.kind === "point") {
      const {x, y} = spot.rects[0];
      const pin = dotElement({x, y});
      pin.className = "pin";
      element.append(pin);
      at = [x, y - 20];
    } else {
      element.append(lassoElement(spot.points, "outline"));
      at = spot.points.reduce((a, p) => (p[0] + p[1] < a[0] + a[1] ? p : a));
    }
    element.append(badgeElement(marker, at[0], at[1]));
    return element;
  }

  // Toggled in place: a re-render would replace the badge under the pointer.
  function setHover(token) {
    hoverToken = typeof token === "string" ? token : null;
    if (!layer) return;
    for (const element of layer.querySelectorAll("[data-mk]")) {
      const hot = element.dataset.mk === selectedToken || element.dataset.mk === hoverToken;
      element.classList.toggle("hot", hot);
    }
  }

  function scrollToMarker(token) {
    const spot = placements.get(token);
    if (!spot) return;
    const boxes = spot.points
      ? spot.points.map(([x, y]) => ({x, y, w: 0, h: 0})) : spot.rects;
    const left = Math.min(...boxes.map((b) => b.x));
    const top = Math.min(...boxes.map((b) => b.y));
    const right = Math.max(...boxes.map((b) => b.x + b.w));
    const bottom = Math.max(...boxes.map((b) => b.y + b.h));
    const viewer = spaced();
    if (viewer) {
      const from = viewer.toSpace(left, top);
      const to = viewer.toSpace(right, bottom, from.p);
      viewer.reveal({p: from.p, x: from.x, y: from.y, w: to.x - from.x, h: to.y - from.y});
      return;
    }
    const fit = (low, high, view, now) => {
      if (low >= now && high <= now + view) return now;
      return high - low >= view || low < now ? low - 20 : high + 20 - view;
    };
    window.scrollTo(fit(left, right, window.innerWidth, window.scrollX),
      fit(top, bottom, window.innerHeight, window.scrollY));
  }

  function render() {
    ensureHost();
    const items = [];
    for (const marker of markers) {
      const spot = placements.get(marker.token);
      if (spot) items.push(markerElement(marker, spot));
    }
    items.push(...shapeItems(), ...cursorItems(), ...signItems());
    layer.replaceChildren(...items);
  }

  // The marks of what's new: found by id again at every render, so that a morph that
  // replaces an element moves its mark along. They live in the host, never in the page.
  function signItems() {
    const items = [];
    for (const {id, sign} of signs) {
      const element = document.querySelector("[data-canvas-id=\"" + CSS.escape(id) + "\"]") ||
        document.getElementById(id);
      if (!element || element.hasAttribute(HOST_ATTRIBUTE)) continue;
      const box = pageBox(element);
      if (!box.w || !box.h) continue;
      const mark = document.createElement("div");
      mark.className = "sign-box " + sign;
      mark.style.cssText = `left:${box.x}px;top:${box.y}px;width:${box.w}px;height:${box.h}px;`;
      const tag = document.createElement("span");
      tag.className = "sign-tag";
      tag.textContent = sign;
      mark.append(tag);
      items.push(mark);
    }
    return items;
  }

  function setSigns(message) {
    signs = (Array.isArray(message.signs) ? message.signs : [])
      .filter((s) => s && typeof s.id === "string" && s.id.length <= 200 && SIGN_NAMES.includes(s.sign))
      .slice(0, MAX_SIGNS)
      .map((s) => ({id: s.id, sign: s.sign}));
    render();
  }

  // The shape being dragged, or the selection the box is open for.
  function shapeItems() {
    if (drag) {
      if (support.mode.kind === "lasso") return drag.points.length > 1 ? [lassoElement(drag.points)] : [];
      return drag.rect ? [shapeElement("temp", drag.rect)] : [];
    }
    if (!selection) return [];
    if (selection.kind === "text") {
      const rects = pdf() ? frameRects(pdf(), selection.anchor.rects) : lineRects(selection.pieces);
      return rects.map((rect) => shapeElement("temp", rect));
    }
    const shape = shapeOf(selection.kind, selection.anchor, selection.selector);
    if (shape.points) return [lassoElement(shape.points)];
    return [shape.rect.w || shape.rect.h || selection.kind === "rect"
      ? shapeElement("temp", shape.rect) : dotElement(shape.rect)];
  }

  function clearSelection() {
    if (selection && selection.kind === "text") window.getSelection().removeAllRanges();
    selection = null;
  }

  function setMarkers(message) {
    markers = (Array.isArray(message.markers) ? message.markers : [])
      .filter((m) => m && KINDS.includes(m.kind) && typeof m.token === "string" && Number.isInteger(m.n))
      .map((m) => ({
        n: m.n, kind: m.kind, token: m.token, anchor: m.anchor || {}, lost: m.lost === true,
        status: STATUSES.includes(m.status) ? m.status : "sent",
        target: {selector: m.selector, canvas_id: m.canvas_id},
      }));
    const tokens = new Set(markers.map((m) => m.token));
    for (const token of reported.keys()) if (!tokens.has(token)) reported.delete(token);
    for (const marker of markers) if (!reported.has(marker.token)) reported.set(marker.token, marker.lost);
    selectedToken = typeof message.selected === "string" ? message.selected : null;
    reanchor();
    render();
  }

  // The crosshair over the whole page while comment mode is on. The style
  // exists only then, so that a page's styles are as the agent wrote them.
  let cursorStyle = null;
  function showCursor(on) {
    if (!on) {
      if (cursorStyle) cursorStyle.remove();
      cursorStyle = null;
    } else if (!cursorStyle) {
      cursorStyle = document.createElement("style");
      cursorStyle.setAttribute("data-agent-canvas-helper", "");
      cursorStyle.setAttribute("data-ac-comment-style", "");
      cursorStyle.textContent = "html[data-ac-commenting], html[data-ac-commenting] * " +
        "{ cursor: crosshair !important; }" +
        "html[data-ac-commenting=text], html[data-ac-commenting=text] * " +
        "{ cursor: text !important; }";
      document.head.appendChild(cursorStyle);
    }
  }

  // ---- the keyboard cursor: the keyboard's way to draw and to select text ----------------

  // ``kc`` is the cursor in client pixels; ``corner`` and ``points`` are page pixels. A point
  // is set by one Enter, a rectangle by two (corner, opposite corner), a lasso by one Enter per
  // vertex and "finish"; a text selection starts at the text under the cursor and the arrows
  // extend it.
  let kc = null;
  const STEP = 10;
  const BIG_STEP = 50;

  const cursorAt = () => ({x: kc.cx + window.scrollX, y: kc.cy + window.scrollY});

  function cursorItems() {
    if (!kc || kc.text) return [];
    const at = cursorAt();
    const kind = support.mode.kind;
    if (kind === "rect" && kc.corner) {
      const x = Math.min(kc.corner.x, at.x);
      const y = Math.min(kc.corner.y, at.y);
      const rect = {x, y, w: Math.abs(at.x - kc.corner.x), h: Math.abs(at.y - kc.corner.y)};
      return [shapeElement("temp", rect), dotElement(at)];
    }
    if (kind === "lasso" && kc.points.length) return [lassoElement([...kc.points, [at.x, at.y]]), dotElement(at)];
    return [dotElement(at)];
  }

  function moveCursor(side, big) {
    const step = big ? BIG_STEP : STEP;
    const dx = {left: -step, right: step}[side] || 0;
    const dy = {up: -step, down: step}[side] || 0;
    if (kc.text) {
      const sel = window.getSelection();
      if (sel.modify) sel.modify("extend", dx + dy < 0 ? "backward" : "forward", dx ? "character" : "line");
      return;
    }
    const nx = Math.min(Math.max(kc.cx + dx, 0), window.innerWidth - 1);
    const ny = Math.min(Math.max(kc.cy + dy, 0), window.innerHeight - 1);
    window.scrollBy(kc.cx + dx - nx, kc.cy + dy - ny);
    kc.cx = nx;
    kc.cy = ny;
  }

  function startTextSelection() {
    const range = document.caretRangeFromPoint ? document.caretRangeFromPoint(kc.cx, kc.cy) : null;
    if (!range) return;
    window.getSelection().setBaseAndExtent(range.startContainer, range.startOffset, range.startContainer, range.startOffset);
    kc.text = true;
  }

  function cursorEnter() {
    const kind = support.mode.kind;
    const at = cursorAt();
    const done = () => { kc = null; };
    if (kind === "text") {
      if (!kc.text) return startTextSelection();
      done();
      return readText();
    }
    if (kind === "point") {
      done();
      return selectPoint({x: Math.round(at.x), y: Math.round(at.y)});
    }
    if (kind === "rect") {
      if (!kc.corner) {
        kc.corner = at;
        return;
      }
      const rect = {
        x: Math.min(kc.corner.x, at.x), y: Math.min(kc.corner.y, at.y),
        w: Math.abs(at.x - kc.corner.x), h: Math.abs(at.y - kc.corner.y),
      };
      if (Math.min(rect.w, rect.h) < MIN_DRAG) return;
      done();
      return selectRect({x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.w), h: Math.round(rect.h)});
    }
    kc.points.push([at.x, at.y]);
  }

  function cursorMessage(message) {
    if (message.op === "cancel" || !support.mode.on) {
      if (kc && kc.text) window.getSelection().removeAllRanges();
      kc = null;
    } else if (message.op === "enter") {
      ensureHost();
      if (!kc) kc = {cx: Math.round(window.innerWidth / 2), cy: Math.round(window.innerHeight / 2), corner: null, points: [], text: false};
      else cursorEnter();
    } else if (kc && message.op === "finish") {
      const points = kc.points;
      kc = null;
      selectLasso(points);
    } else if (kc) {
      moveCursor(message.op, message.big === true);
    }
    render();
  }

  // ---- events the helper hands over and messages from the shell -------------------------

  function handle(event) {
    if (event.type === "pointerdown") startDrag(event);
    else if (event.type === "pointerup") {
      if (support.mode.kind === "text" && event.isPrimary && event.button === 0) setTimeout(readText, 0);
      else finishDrag(event);
    }
    else if (event.type === "click") {
      const origin = event.composedPath()[0];
      if (origin && origin.classList && origin.classList.contains("badge")) {
        post({type: "comment-marker", token: String(origin.dataset.token || ""), action: "click"});
      }
    }
  }

  function onMessage(message) {
    if (message.type === "comment-cursor") {
      cursorMessage(message);
    } else if (message.type === "comment-mode") {
      kc = null;
      if (!message.on) {
        endDrag();
        clearSelection();
      }
      showCursor(Boolean(message.on));
      render();
    } else if (message.type === "change-signs") {
      setSigns(message);
    } else if (message.type === "comment-markers") {
      setMarkers(message);
    } else if (message.type === "comment-hover") {
      setHover(message.token);
    } else if (message.type === "comment-scroll") {
      if (typeof message.token === "string") scrollToMarker(message.token);
    } else if (message.type === "comment-clear") {
      clearSelection();
      render();
    } else if (message.type === "comment-crop") {
      if (selection && typeof message.token === "string") makePicture(message.token);
    }
  }

  // A morph changes the text and the elements: find the anchors again at once.
  // A resize or a load only moves them: once per frame is enough.
  const refresh = () => {
    if (frameRequested) return;
    frameRequested = true;
    requestAnimationFrame(() => {
      frameRequested = false;
      if (!host && !markers.length) return;
      reanchor();
      render();
    });
  };
  window.addEventListener("resize", refresh);
  window.addEventListener("load", refresh);
  document.addEventListener("agentcanvas:view", refresh);
  document.addEventListener("agentcanvas:updated", () => {
    reanchor();
    render();
  });
  new ResizeObserver(refresh).observe(document.documentElement);
  // Marks follow their element when it moves without the window scrolling or the
  // document changing size: an inner container scrolls, a section above opens, a
  // style or class changes, an animation ends (NEW-04).
  document.addEventListener("scroll", (event) => {
    if (event.target !== document) refresh();
  }, true);
  for (const name of ["transitionend", "animationend"]) document.addEventListener(name, refresh, true);
  new MutationObserver(refresh).observe(document, {
    subtree: true, childList: true, attributes: true, characterData: true,
  });

  agent.commentLayer = {handle, onMessage, textInside, stats, cursorActive: () => kc !== null};
})();
