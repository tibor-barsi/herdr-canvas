// Automatic page checks (CHK-01 to CHK-11): the page audit behind ``look`` and
// ``show``. Loaded by the helper only when a render frame asks for the audit
// (never into the owner's visible frame); it defines
// ``agentCanvas.auditPage(options)``, which resolves with ``{findings,
// truncated}``. A finding is ``{rule, severity, message, where, bbox}``;
// ``bbox`` is ``{x, y, w, h}`` in page pixels. The hub adds the page errors,
// sorts, counts and cuts the crops (hub/audit.py).
//
// Thresholds are named constants below.
"use strict";

(function () {
  if (!window.agentCanvas || window.agentCanvas.auditPage) return;

  const LIMITS = {
    clipTolerance: 2,          // px a box may overflow before it counts as clipped
    minClipBox: 4,             // boxes under this size are visually hidden helpers
    stickOut: 4,               // px a child may leave a card before it is reported
    overlapShare: 0.2,         // share of the smaller text that overlaps (warn)
    overlapSevere: 0.5,        // ... and the share that makes it an error
    bodyFont: 12,              // px: body text below this is small
    labelFont: 11,             // px: labels and captions below this are small
    illegibleFont: 8,          // px: below this the finding is an error
    lineChars: 100,            // characters per line above which lines are long
    contrastText: 4.5,         // WCAG AA, normal text
    contrastLarge: 3.0,        // WCAG AA, large text
    contrastError: 2.0,        // ratio below which the text is practically invisible
    largeFont: 24,             // px: large text
    largeBoldFont: 18.66,      // px: large when bold (700 and up)
    pageHeights: 3,            // page heights (viewports) above which to suggest splitting
    maxTraces: 8,
    maxTableRows: 50,
    numericShare: 0.8,         // share of numeric cells that makes a column numeric
    perRule: 8,                // findings kept per rule
  };

  const SKIP_TAGS = new Set([
    "script", "style", "link", "meta", "noscript", "template", "title", "head",
    "option", "optgroup", "datalist", "textarea", "select",
  ]);
  const CODE_TAGS = new Set(["code", "pre", "kbd", "samp"]);
  const LABEL_TAGS = new Set(["label", "legend", "caption", "figcaption", "th", "small"]);
  const GENERIC_FONTS = new Set([
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
    "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded", "emoji", "math",
    "fangsong", "-apple-system", "blinkmacsystemfont",
  ]);
  const EMPTY_TAGS = new Set([
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "blockquote",
    "figcaption", "dt", "dd", "summary", "label",
  ]);
  const MEDIA_SELECTOR = "img,svg,canvas,video,audio,iframe,object,embed,input,"
    + "select,textarea,picture,hr,meter,progress";
  const CARD_WORDS = new Set(["card", "tile", "callout", "panel", "cards", "tiles"]);

  const PLACEHOLDERS = [
    {re: /\(replace[^)]*\)|\[replace[^\]]*\]/i, severity: "error"},
    {re: /lorem ipsum/i, severity: "error"},
    {re: /\[object Object\]/, severity: "error"},
    {re: /(^|[^\w.])NaN(?!\w)/, severity: "error"},
    {re: /(^|[^\w.])-?Infinity(?!\w)/, severity: "error"},
    {re: /(^|[^\w.])undefined(?!\w)(?!\s+[a-z])/, severity: "error"},
    {re: /(^|[^\w.])null(?!\w)(?!\s+[a-z])/, severity: "error"},
    {re: /\b(?:TODO|TBD|FIXME)\b/, severity: "warn"},
  ];

  // ---- small helpers -------------------------------------------------------

  const styles = new Map();
  function style(el) {
    let value = styles.get(el);
    if (!value) {
      value = getComputedStyle(el);
      styles.set(el, value);
    }
    return value;
  }

  function parentOf(node) {
    if (node.parentElement) return node.parentElement;
    const root = node.getRootNode ? node.getRootNode() : null;
    return root instanceof ShadowRoot ? root.host : null;
  }

  function within(ancestor, node) {
    for (let current = node; current; current = parentOf(current)) {
      if (current === ancestor) return true;
    }
    return false;
  }

  function allElements() {
    const found = [];
    (function visit(root) {
      for (const el of root.querySelectorAll("*")) {
        if (el.hasAttribute("data-ac-comment-host")) continue;  // markers are not the page (COM-05)
        found.push(el);
        if (el.shadowRoot) visit(el.shadowRoot);
      }
    })(document);
    return found;
  }

  function pageBox(rect) {
    return {x: rect.left + window.scrollX, y: rect.top + window.scrollY,
      w: rect.width, h: rect.height};
  }

  function round(box) {
    return {x: Math.round(box.x), y: Math.round(box.y),
      w: Math.round(box.w), h: Math.round(box.h)};
  }

  function boxOf(el) {
    return pageBox(el.getBoundingClientRect());
  }

  function isHelper(el) {
    return el.hasAttribute("data-agent-canvas-helper");
  }

  function opacityOf(el) {
    let opacity = 1;
    for (let node = el; node; node = parentOf(node)) {
      opacity *= parseFloat(style(node).opacity);
      if (opacity < 0.02) return 0;
    }
    return opacity;
  }

  // Content of a closed <details> has boxes but is not shown (except the summary).
  function inClosedDetails(el) {
    for (let node = el; node; node = parentOf(node)) {
      const parent = parentOf(node);
      if (parent && parent.localName === "details" && !parent.open
          && !(node.localName === "summary" && node.parentNode === parent)) return true;
    }
    return false;
  }

  function isRendered(el) {
    const st = style(el);
    if (st.display === "none" || st.visibility !== "visible") return false;
    return el.getClientRects().length > 0 && opacityOf(el) > 0 && !inClosedDetails(el);
  }

  function segment(el) {
    let text = el.localName;
    const first = (el.getAttribute("class") || "").trim().split(/\s+/)[0];
    if (first) text += "." + CSS.escape(first);
    const parent = el.parentNode;
    if (parent) {
      const same = Array.from(parent.children).filter((c) => c.localName === el.localName);
      if (same.length > 1) text += `:nth-of-type(${same.indexOf(el) + 1})`;
    }
    return text;
  }

  function localSelector(el) {
    if (el.id) return "#" + CSS.escape(el.id);
    const canvasId = el.getAttribute("data-canvas-id");
    if (canvasId) return `${el.localName}[data-canvas-id="${canvasId}"]`;
    const parts = [];
    let node = el;
    for (let depth = 0; node && depth < 3; depth++) {
      if (node === document.body || node === document.documentElement) break;
      if (node.id) {
        parts.unshift("#" + CSS.escape(node.id));
        break;
      }
      parts.unshift(segment(node));
      node = node.parentElement;
    }
    return parts.join(" > ") || el.localName;
  }

  function selectorOf(el) {
    const root = el.getRootNode ? el.getRootNode() : null;
    if (root instanceof ShadowRoot) return `${selectorOf(root.host)} » ${localSelector(el)}`;
    return localSelector(el);
  }

  function snippet(text) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length > 40 ? clean.slice(0, 37) + "..." : clean;
  }

  function whereOf(el, text) {
    const label = snippet(text);
    return label ? `${selectorOf(el)} "${label}"` : selectorOf(el);
  }

  // ---- colour --------------------------------------------------------------

  const colourCache = new Map();
  let probeContext = null;
  const RGB = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+)(%?))?\s*\)$/;

  // [r, g, b, a] with a in 0..1; any CSS colour the browser understands.
  function parseColour(value) {
    if (colourCache.has(value)) return colourCache.get(value);
    let result = null;
    const match = RGB.exec(value);
    if (match) {
      let alpha = match[4] === undefined ? 1 : parseFloat(match[4]);
      if (match[5] === "%") alpha /= 100;
      result = [parseFloat(match[1]), parseFloat(match[2]), parseFloat(match[3]), alpha];
    } else {
      if (!probeContext) {
        probeContext = document.createElement("canvas").getContext(
          "2d", {willReadFrequently: true});
      }
      probeContext.clearRect(0, 0, 1, 1);
      probeContext.fillStyle = value;
      probeContext.fillRect(0, 0, 1, 1);
      const data = probeContext.getImageData(0, 0, 1, 1).data;
      result = [data[0], data[1], data[2], data[3] / 255];
    }
    colourCache.set(value, result);
    return result;
  }

  function over(top, below) {
    const alpha = top[3] + below[3] * (1 - top[3]);
    if (alpha <= 0) return [0, 0, 0, 0];
    const mix = (i) => (top[i] * top[3] + below[i] * below[3] * (1 - top[3])) / alpha;
    return [mix(0), mix(1), mix(2), alpha];
  }

  function luminance(colour) {
    const channel = (value) => {
      const unit = value / 255;
      return unit <= 0.03928 ? unit / 12.92 : Math.pow((unit + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(colour[0]) + 0.7152 * channel(colour[1])
      + 0.0722 * channel(colour[2]);
  }

  function contrastRatio(a, b) {
    const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (high + 0.05) / (low + 0.05);
  }

  function canvasColour() {
    const scheme = style(document.documentElement).colorScheme || "";
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const supportsDark = scheme.includes("dark");
    const supportsLight = scheme.includes("light") || scheme === "normal" || scheme === "";
    return supportsDark && (!supportsLight || dark) ? [18, 18, 18, 1] : [255, 255, 255, 1];
  }

  // The colour behind ``el``: layers of ancestors' backgrounds, or null when an
  // image or gradient lies behind and the contrast cannot be judged.
  function backgroundOf(el) {
    const layers = [];
    let opaque = false;
    for (let node = el; node; node = parentOf(node)) {
      const st = style(node);
      const colour = parseColour(st.backgroundColor);
      if (st.backgroundImage !== "none") return null;
      if (colour[3] > 0) layers.push(colour);
      if (colour[3] >= 0.999) {
        opaque = true;
        break;
      }
    }
    let result = opaque ? layers.pop() : canvasColour();
    for (let i = layers.length - 1; i >= 0; i--) result = over(layers[i], result);
    return result;
  }

  // ---- collecting ----------------------------------------------------------

  function lineRects(nodes) {
    const rects = [];
    const range = document.createRange();
    for (const node of nodes) {
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.width > 0 && rect.height > 0) rects.push(pageBox(rect));
      }
    }
    return rects;
  }

  function union(rects) {
    const left = Math.min(...rects.map((r) => r.x));
    const top = Math.min(...rects.map((r) => r.y));
    const right = Math.max(...rects.map((r) => r.x + r.w));
    const bottom = Math.max(...rects.map((r) => r.y + r.h));
    return {x: left, y: top, w: right - left, h: bottom - top};
  }

  function textItems(elements) {
    const items = [];
    for (const el of elements) {
      if (SKIP_TAGS.has(el.localName) || isHelper(el)) continue;
      const nodes = Array.from(el.childNodes).filter(
        (n) => n.nodeType === Node.TEXT_NODE && n.nodeValue.trim() !== "");
      if (!nodes.length || !isRendered(el)) continue;
      const rects = lineRects(nodes);
      if (!rects.length) continue;
      const text = nodes.map((n) => n.nodeValue).join(" ").replace(/\s+/g, " ").trim();
      items.push({
        el, nodes, rects, text, box: union(rects), svg: el instanceof SVGElement,
      });
    }
    return items;
  }

  // ---- findings ------------------------------------------------------------

  function createReport() {
    const findings = [];
    const counts = {};
    const truncated = {};
    function add(rule, severity, message, where, box) {
      counts[rule] = (counts[rule] || 0) + 1;
      if (counts[rule] > LIMITS.perRule) {
        truncated[rule] = counts[rule] - LIMITS.perRule;
        return;
      }
      findings.push({rule, severity, message, where, bbox: box ? round(box) : null});
    }
    return {add, findings, truncated};
  }

  // ---- rules ---------------------------------------------------------------

  function checkClipped(elements, report) {
    for (const el of elements) {
      if (!(el instanceof HTMLElement) || el === document.body || isHelper(el)) continue;
      const st = style(el);
      const clipsX = st.overflowX === "hidden" || st.overflowX === "clip";
      const clipsY = st.overflowY === "hidden" || st.overflowY === "clip";
      if (!clipsX && !clipsY) continue;
      if (el.clientWidth < LIMITS.minClipBox || el.clientHeight < LIMITS.minClipBox) continue;
      if (!isRendered(el)) continue;
      const lineClamp = st.getPropertyValue("-webkit-line-clamp");
      if (lineClamp && lineClamp !== "none") continue;
      const tooWide = clipsX && el.scrollWidth > el.clientWidth + LIMITS.clipTolerance;
      const tooTall = clipsY && el.scrollHeight > el.clientHeight + LIMITS.clipTolerance;
      if (!tooWide && !tooTall) continue;
      let message;
      if (tooWide && st.textOverflow === "ellipsis") {
        message = "Text is cut off with an ellipsis because its box is too narrow; "
          + "widen the box or let the text wrap.";
      } else if (tooWide) {
        message = `Content is ${el.scrollWidth} px wide but its box shows only `
          + `${el.clientWidth} px, so the rest is cut off; widen the box or let it scroll.`;
      } else {
        message = `Content is ${el.scrollHeight} px high but its box shows only `
          + `${el.clientHeight} px, so the rest is cut off; make the box taller or let it scroll.`;
      }
      report.add("overflow", "warn", message, whereOf(el, el.textContent), boxOf(el));
    }
  }

  function inScrollContainer(el) {
    for (let node = parentOf(el); node; node = parentOf(node)) {
      if (node === document.body || node === document.documentElement) return false;
      const st = style(node);
      if (st.overflowX !== "visible" || st.overflowY !== "visible") return true;
    }
    return false;
  }

  function checkPageWidth(elements, report) {
    const root = document.documentElement;
    const viewport = root.clientWidth;
    if (root.scrollWidth <= viewport + 1) return;
    let widest = null;
    let widestRight = viewport + 1;
    for (const el of elements) {
      if (!(el instanceof HTMLElement) || isHelper(el) || !isRendered(el)) continue;
      if (style(el).position === "fixed" || inScrollContainer(el)) continue;
      const right = el.getBoundingClientRect().right + window.scrollX;
      if (right > widestRight) {
        widest = el;
        widestRight = right;
      }
    }
    const message = `The page is ${root.scrollWidth} px wide in a ${viewport} px window, `
      + "so the owner gets a horizontal scrollbar; make the widest element narrower or "
      + "let it wrap or scroll.";
    const box = widest ? boxOf(widest)
      : {x: 0, y: 0, w: root.scrollWidth, h: window.innerHeight};
    report.add("overflow", "warn", message, widest ? whereOf(widest, widest.textContent) : "page", box);
  }

  function isBoxy(st) {
    const background = parseColour(st.backgroundColor);
    if (background[3] > 0.05 || st.backgroundImage !== "none" || st.boxShadow !== "none") return true;
    return ["Top", "Right", "Bottom", "Left"].some(
      (side) => st["border" + side + "Style"] !== "none" && parseFloat(st["border" + side + "Width"]) > 0);
  }

  function checkStickingOut(elements, report) {
    const reported = new Set();
    for (const el of elements) {
      if (!(el instanceof HTMLElement) || isHelper(el) || SKIP_TAGS.has(el.localName)) continue;
      const st = style(el);
      if (["absolute", "fixed", "sticky"].includes(st.position) || st.transform !== "none") continue;
      if (["br", "wbr"].includes(el.localName)) continue;
      const parent = parentOf(el);
      if (!(parent instanceof HTMLElement) || parent === document.body || reported.has(parent)) continue;
      const parentStyle = style(parent);
      if (!isBoxy(parentStyle) || parentStyle.display === "contents" || parentStyle.display === "inline") continue;
      if (parentStyle.overflowX !== "visible" || parentStyle.overflowY !== "visible") continue;
      if (!isRendered(el)) continue;
      const inner = el.getBoundingClientRect();
      const outer = parent.getBoundingClientRect();
      if (inner.width === 0 || inner.height === 0) continue;
      const out = Math.max(outer.left - inner.left, inner.right - outer.right, inner.bottom - outer.bottom);
      if (out <= LIMITS.stickOut) continue;
      reported.add(parent);
      report.add("overflow", "warn",
        `This element sticks out of its card by ${Math.round(out)} px; make it fit `
        + "inside or let the card grow.",
        whereOf(el, el.textContent), boxOf(el));
    }
  }

  function isOverlay(el) {
    for (let node = el; node; node = parentOf(node)) {
      const st = style(node);
      if (st.position === "fixed" || st.position === "sticky") return true;
      if (st.position === "absolute" && st.zIndex !== "auto" && parseInt(st.zIndex, 10) > 0) return true;
      if (node.localName === "dialog" || node.hasAttribute("popover")) return true;
      const role = node.getAttribute && node.getAttribute("role");
      if (role === "tooltip" || role === "dialog") return true;
    }
    return false;
  }

  function overlapShare(a, b) {
    let best = null;
    for (const r1 of a.rects.slice(0, 20)) {
      for (const r2 of b.rects.slice(0, 20)) {
        const width = Math.min(r1.x + r1.w, r2.x + r2.w) - Math.max(r1.x, r2.x);
        const height = Math.min(r1.y + r1.h, r2.y + r2.h) - Math.max(r1.y, r2.y);
        if (width <= 2 || height <= 3) continue;
        const share = (width * height) / Math.min(r1.w * r1.h, r2.w * r2.h);
        if (!best || share > best.share) {
          best = {share, box: {x: Math.max(r1.x, r2.x), y: Math.max(r1.y, r2.y), w: width, h: height}};
        }
      }
    }
    return best;
  }

  // True when a scrolling or clipping ancestor of ``el`` hides all of ``box`` (page coordinates).
  function clippedAway(el, box) {
    for (let node = parentOf(el); node && node !== document.body; node = parentOf(node)) {
      const st = style(node);
      if (!/(auto|scroll|hidden|clip)/.test(st.overflowX + st.overflowY)) continue;
      const area = boxOf(node);
      if (box.y >= area.y + area.h || box.y + box.h <= area.y
          || box.x >= area.x + area.w || box.x + box.w <= area.x) return true;
    }
    return false;
  }

  function checkOverlap(items, report) {
    const list = items.filter((item) => !item.svg).sort((a, b) => a.box.y - b.box.y);
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        if (list[j].box.y >= list[i].box.y + list[i].box.h) break;
        const [a, b] = [list[i], list[j]];
        if (within(a.el, b.el) || within(b.el, a.el)) continue;
        if (a.box.x >= b.box.x + b.box.w || b.box.x >= a.box.x + a.box.w) continue;
        if (isOverlay(a.el) || isOverlay(b.el)) continue;
        const found = overlapShare(a, b);
        if (!found || found.share < LIMITS.overlapShare) continue;
        if (clippedAway(a.el, found.box) || clippedAway(b.el, found.box)) continue;
        const severity = found.share >= LIMITS.overlapSevere ? "error" : "warn";
        report.add("overlap", severity,
          `The text "${snippet(b.text)}" overlaps "${snippet(a.text)}"; move one of them `
          + "or give the layout more room.",
          whereOf(b.el, b.text), found.box);
      }
    }
  }

  function checkSmallText(items, report) {
    const groups = new Map();
    for (const item of items) {
      if (item.svg || ["sup", "sub"].includes(item.el.localName)) continue;
      const size = parseFloat(style(item.el).fontSize);
      const label = LABEL_TAGS.has(item.el.localName);
      const limit = label ? LIMITS.labelFont : LIMITS.bodyFont;
      if (!(size > 0) || size >= limit) continue;
      const key = `${label}:${size.toFixed(1)}`;
      const group = groups.get(key) || {item, size, label, count: 0, limit};
      group.count += 1;
      groups.set(key, group);
    }
    for (const group of groups.values()) {
      const kind = group.label ? "Label" : "Text";
      const severity = group.size < LIMITS.illegibleFont ? "error" : "warn";
      const many = group.count > 1 ? ` (${group.count} elements)` : "";
      report.add("small-text", severity,
        `${kind} is set at ${+group.size.toFixed(1)} px${many}, which is hard to read; `
        + `use at least ${group.limit} px.`,
        whereOf(group.item.el, group.item.text), group.item.box);
    }
  }

  function checkLongLines(items, report) {
    for (const item of items) {
      if (item.svg || item.text.length < LIMITS.lineChars) continue;
      if (item.el.closest && item.el.closest("pre,code,textarea")) continue;
      const tops = new Set(item.rects.map((r) => Math.round(r.y / 4)));
      const average = item.text.length / tops.size;
      if (average <= LIMITS.lineChars) continue;
      report.add("long-lines", "info",
        `Lines hold about ${Math.round(average)} characters, which is tiring to read; `
        + `limit the text width to about ${LIMITS.lineChars} characters (max-width: 70ch).`,
        whereOf(item.el, item.text), item.box);
    }
  }

  function checkContrast(items, report) {
    const seen = new Map();
    let unknown = null;
    let unknownCount = 0;
    for (const item of items) {
      if (item.svg) continue;
      const st = style(item.el);
      if (item.el.matches && item.el.matches(":disabled")) continue;
      const fill = st.webkitTextFillColor ? parseColour(st.webkitTextFillColor) : null;
      const ink = fill && fill[3] < 1 ? fill : parseColour(st.color);
      if (ink[3] < 0.05) continue;
      const background = backgroundOf(item.el);
      if (background === null) {
        unknown = unknown || item;
        unknownCount += 1;
        continue;
      }
      const effective = over([ink[0], ink[1], ink[2], ink[3] * opacityOf(item.el)], background);
      const size = parseFloat(st.fontSize);
      const large = size >= LIMITS.largeFont
        || (size >= LIMITS.largeBoldFont && parseInt(st.fontWeight, 10) >= 700);
      const ratio = contrastRatio(effective, background);
      const limit = large ? LIMITS.contrastLarge : LIMITS.contrastText;
      if (ratio >= limit) continue;
      const key = `${effective.map(Math.round)}/${background.map(Math.round)}/${large}`;
      const entry = seen.get(key) || {item, ratio, large, limit, count: 0};
      entry.count += 1;
      seen.set(key, entry);
    }
    for (const entry of seen.values()) {
      const severity = entry.ratio < LIMITS.contrastError ? "error" : "warn";
      const many = entry.count > 1 ? ` (${entry.count} elements)` : "";
      report.add("contrast", severity,
        `Text contrast is ${entry.ratio.toFixed(1)}:1${many}, below the ${entry.limit}:1 `
        + "needed to read it; use a darker text colour or a lighter background.",
        whereOf(entry.item.el, entry.item.text), entry.item.box);
    }
    if (unknown) {
      report.add("contrast", "info",
        `${unknownCount} text element(s) sit on an image or gradient, so their contrast `
        + "was not checked; look at the picture.",
        whereOf(unknown.el, unknown.text), unknown.box);
    }
  }

  function unquote(name) {
    return name.trim().replace(/^["']|["']$/g, "");
  }

  function familiesOf(value) {
    return value.split(",").map(unquote).filter((name) => name !== "");
  }

  let fontProbe = null;
  function fontAvailable(name) {
    const declared = Array.from(document.fonts).filter((face) => unquote(face.family) === name);
    if (declared.length) return declared.some((face) => face.status !== "error");
    if (!fontProbe) fontProbe = document.createElement("canvas").getContext("2d");
    const sample = "mmmmmmmmmmlliWQ@#0Oo";
    return ["monospace", "serif", "sans-serif"].some((base) => {
      fontProbe.font = `72px ${base}`;
      const plain = fontProbe.measureText(sample).width;
      fontProbe.font = `72px "${name.replace(/"/g, "")}", ${base}`;
      return fontProbe.measureText(sample).width !== plain;
    });
  }

  function checkFonts(items, report) {
    const checked = new Map();
    for (const item of items) {
      if (item.svg) continue;
      const stack = familiesOf(style(item.el).fontFamily);
      const first = stack[0];
      if (!first || GENERIC_FONTS.has(first.toLowerCase()) || checked.has(first)) continue;
      const available = fontAvailable(first);
      checked.set(first, available);
      if (available) continue;
      const next = stack.slice(1).find(
        (name) => GENERIC_FONTS.has(name.toLowerCase()) || fontAvailable(name));
      const fallback = next ? `"${next}"` : "the browser's default font";
      report.add("missing-font", "info",
        `The font "${first}" is not available here, so the text is shown in ${fallback}; `
        + "load it with @font-face from a file in the session folder or name an installed font.",
        whereOf(item.el, item.text), item.box);
    }
  }

  // ---- empty content ---------------------------------------------------------

  function hasContent(el) {
    if (el.shadowRoot) return true;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeType === Node.TEXT_NODE) {
        const tag = node.parentElement && node.parentElement.localName;
        if (tag !== "script" && tag !== "style" && node.nodeValue.trim() !== "") return true;
      } else if (node.shadowRoot || node.matches(MEDIA_SELECTOR) || node.localName.startsWith("canvas-")) {
        return true;
      }
    }
    return false;
  }

  function hasPseudoContent(el) {
    return ["::before", "::after"].some((pseudo) => {
      const content = getComputedStyle(el, pseudo).content;
      return content !== "none" && content !== "normal" && content !== '""';
    });
  }

  function isCardLike(el) {
    return Array.from(el.classList).some(
      (name) => CARD_WORDS.has(name) || /^(card|tile|panel)[-_]/.test(name));
  }

  function checkEmptyElements(elements, report) {
    for (const el of elements) {
      if (isHelper(el) || el.getAttribute("aria-hidden") === "true") continue;
      const named = EMPTY_TAGS.has(el.localName);
      if (!named && !isCardLike(el)) continue;
      if (style(el).display === "none" || el.getClientRects().length === 0) continue;
      if (hasContent(el) || hasPseudoContent(el)) continue;
      const cell = el.localName === "td" || el.localName === "th";
      const noun = named ? `<${el.localName}>` : "card";
      report.add("empty", cell ? "info" : "warn",
        `This ${noun} has no content; fill it in or remove it.`,
        selectorOf(el), boxOf(el));
    }
  }

  function checkImages(elements, blocked, report) {
    for (const el of elements) {
      if (!(el instanceof HTMLImageElement)) continue;
      const st = style(el);
      if (st.display === "none" || st.visibility !== "visible") continue;
      if (!el.getAttribute("src") && !el.getAttribute("srcset")) {
        report.add("empty", "error", "This image has no src, so the owner sees a broken image; "
          + "set a file from the session folder.", selectorOf(el), boxOf(el));
      } else if (el.complete && el.naturalWidth === 0 && !blocked.has(el.currentSrc || el.src)) {
        report.add("empty", "error",
          `The image "${snippet(el.getAttribute("src") || "")}" failed to load, so the owner `
          + "sees a broken image; check the file name and that the file exists.",
          selectorOf(el), boxOf(el));
      }
    }
  }

  const BLOCK_EMPTY = {
    "canvas-table": (config) => Array.isArray(config.rows) && config.rows.length === 0
      && "table block has no rows",
    "canvas-choices": (config) => Array.isArray(config.options) && config.options.length === 0
      && "choices block has no options",
    "canvas-buttons": (config) => Array.isArray(config.buttons) && config.buttons.length === 0
      && "buttons block has no buttons",
    "canvas-markdown": (config) => typeof config.text === "string" && config.text.trim() === ""
      && "markdown block has no text",
  };

  function checkBlocks(elements, report) {
    for (const el of elements) {
      const test = BLOCK_EMPTY[el.localName];
      if (!test || !el._config || (el._wrapper && el._wrapper.isError)) continue;
      const problem = test(el._config);
      if (problem) {
        report.add("empty", "warn", `The ${problem}; give it data or remove it.`,
          selectorOf(el), boxOf(el));
      }
    }
  }

  // ---- placeholders --------------------------------------------------------

  function checkPlaceholders(items, report) {
    for (const item of items) {
      if (item.el.closest && item.el.closest("code,pre,kbd,samp")) continue;
      for (const node of item.nodes) {
        const value = node.nodeValue.replace(/\s+/g, " ");
        const hit = PLACEHOLDERS.map((p) => ({p, m: p.re.exec(value)})).find((x) => x.m);
        if (!hit) continue;
        const word = hit.m[0].trim();
        report.add("placeholder", hit.p.severity,
          `Visible text contains the placeholder "${snippet(word)}"; replace it with the real content.`,
          whereOf(item.el, value.slice(Math.max(0, hit.m.index - 10))), item.box);
        break;
      }
    }
  }

  // ---- interaction mistakes (AGI-15 to AGI-19) -----------------------------

  const NATIVE_CONTROLS = "button,input:not([type=hidden]),textarea,select,form";
  const ANSWER_BLOCKS = "canvas-ask,canvas-choices,canvas-buttons,canvas-textbox,"
    + "canvas-decision,canvas-do";
  const PROSE_QUESTION_TAGS = new Set(["p", "li", "div", "span"]);
  const MIN_QUESTION_WORDS = 4;

  function inBlock(el) {
    for (let node = el; node; node = parentOf(node)) {
      if (node.localName.startsWith("canvas-")) return true;
    }
    return false;
  }

  function checkInteraction(elements, items, report) {
    const own = elements.filter((el) => !inBlock(el));
    const control = own.find((el) => el.matches(NATIVE_CONTROLS) && isRendered(el));
    if (control) {
      report.add("interaction", "warn",
        "Hand-made buttons or fields: if the owner answers you with them, use one canvas-ask "
        + "per question instead; controls that only change this page (a slider, a filter, "
        + "a mock-up) are fine, ignore this then.",
        selectorOf(control), boxOf(control));
    }
    for (const el of elements) {
      const config = el._config;
      if (el.localName === "canvas-choices" && config && config.submit) {
        report.add("interaction", "warn",
          "This canvas-choices has a submit button, but its answer is not an answer card "
          + "(`answers` does not list it). Use a canvas-ask (form one or several) for a decision.",
          selectorOf(el), boxOf(el));
      }
      if (el.localName === "canvas-ask" && config && typeof config.question === "string"
          && /\?\s+\S[^?]*\?/.test(config.question)) {
        report.add("interaction", "warn",
          "This canvas-ask holds more than one question. One Ask is one question: "
          + "split it into one canvas-ask per question.",
          selectorOf(el), boxOf(el));
      }
    }
    if (control || elements.some((el) => el.matches(ANSWER_BLOCKS))) return;
    const inScope = (item, other) => within(
      item.el.closest("section,article,aside,main") || document.body, other.el);
    const asked = items.find((item, index) => PROSE_QUESTION_TAGS.has(item.el.localName)
      && !inBlock(item.el) && !item.el.closest("code,pre,kbd,samp,blockquote,details,table")
      && /\?$/.test(item.text) && item.text.split(" ").length >= MIN_QUESTION_WORDS
      && !items.slice(index + 1).some((other) => inScope(item, other)));
    if (asked) {
      report.add("interaction", "warn",
        "A question is written as plain text and the page has nowhere to answer it. "
        + "Put it in a canvas-ask, so the owner answers on the page.",
        whereOf(asked.el, asked.text), asked.box);
    }
  }

  function checkTitle(report) {
    if (document.title.trim() !== "") return;
    report.add("interaction", "warn",
      "The page has no <title>; add one, the canvas and your next line name the page by it.",
      "page", null);
  }

  // ---- page height, plots, tables ---------------------------------------------

  function checkPageHeight(options, report) {
    const root = document.documentElement;
    const viewport = options.viewportHeight || window.innerHeight;
    const height = Math.max(root.scrollHeight, document.body ? document.body.scrollHeight : 0);
    if (height <= LIMITS.pageHeights * viewport) return;
    report.add("page-height", "info",
      `The page is ${height} px high, about ${(height / viewport).toFixed(1)} windows tall; `
      + "consider splitting it into pages or folding parts into <details>.",
      "page", {x: 0, y: 0, w: root.scrollWidth, h: height});
  }

  function axisTitle(axis) {
    const title = axis.title;
    const text = typeof title === "string" ? title : title && title.text;
    return String(text || "").replace(/<[^>]*>/g, "").trim();
  }

  // ``gd.layout`` is the figure as written; Plotly 3 and later ignore a plain
  // string as an axis title and keep only ``{"text": ...}``.
  function writtenAsString(gd, key) {
    const written = gd.layout && gd.layout[key];
    return Boolean(written) && typeof written.title === "string" && written.title.trim() !== "";
  }

  function axisProblems(gd) {
    const layout = gd._fullLayout;
    const subplots = layout._subplots || {};
    const used = new Set([...(subplots.xaxis || []), ...(subplots.yaxis || [])]);
    const problems = [];
    for (const id of used) {
      const key = id.replace(/^([xy])/, "$1axis");
      const axis = layout[key];
      if (!axis || axis.visible === false || axis.showticklabels === false) continue;
      const name = id.startsWith("x") ? "x axis" : "y axis";
      const title = axisTitle(axis);
      if (writtenAsString(gd, key)) {
        problems.push(`the ${name} title is a plain string, which Plotly ignores `
          + '(write {"text": "..."})');
      } else if (!title) {
        problems.push(`the ${name} has no title`);
      } else if (!["category", "date"].includes(axis.type) && !/[(\[][^)\]]+[)\]]/.test(title)) {
        problems.push(`the ${name} title "${snippet(title)}" has no unit in brackets`);
      }
    }
    return problems;
  }

  function checkPlots(elements, report) {
    for (const el of elements) {
      if (!el.classList || !el.classList.contains("js-plotly-plot")) continue;
      const data = Array.isArray(el.data) ? el.data : [];
      const where = selectorOf(el);
      if (!data.length) {
        report.add("empty", "warn", "This plot has no traces; give it data or remove it.", where, boxOf(el));
        continue;
      }
      if (data.length > LIMITS.maxTraces) {
        report.add("plot", "warn",
          `This plot draws ${data.length} traces, more than ${LIMITS.maxTraces} can be told apart; `
          + "split it into several plots or show fewer.", where, boxOf(el));
      }
      const problems = el._fullLayout ? axisProblems(el) : [];
      if (problems.length) {
        report.add("plot", "info",
          `In this plot ${problems.join(" and ")}; name each axis with a unit, like "force (N)".`,
          where, boxOf(el));
      }
    }
  }

  const NUMBER = /^[+\-−]?(?:\d{1,3}(?:[,' ]\d{3})+|\d+)?(?:[.,]\d+)?(?:[eE][+\-−]?\d+)?\s*(?:%|[A-Za-zµ°Ω²³/]{1,6})?$/;

  function decimalsOf(text) {
    const match = /^[+\-−]?\d[\d,' ]*([.,])(\d+)\s*[^\d]*$/.exec(text);
    if (!match || /[eE]/.test(text)) return 0;
    return match[1] === "," && match[2].length === 3 && !/\./.test(text) ? 0 : match[2].length;
  }

  // A row made only of <th> cells is a header row, with or without <thead>.
  function isHeaderRow(row) {
    return row.cells.length > 0 && Array.from(row.cells).every((c) => c.localName === "th");
  }

  function columnCells(table, index) {
    const cells = [];
    for (const row of table.rows) {
      if (row.parentElement.localName === "thead" || row.parentElement.localName === "tfoot") continue;
      if (isHeaderRow(row)) continue;
      if (row.cells.length <= index || Array.from(row.cells).some((c) => c.colSpan > 1)) continue;
      // A <th> in a data row is a row label, not data.
      if (row.cells[index].localName !== "th") cells.push(row.cells[index]);
    }
    return cells;
  }

  function headerOf(table, index) {
    const row = (table.tHead && table.tHead.rows[0]) || Array.from(table.rows).find(isHeaderRow);
    const cell = row && row.cells[index];
    return cell ? snippet(cell.textContent) : `${index + 1}`;
  }

  // True when every row has one number format across the numeric columns: a
  // comparison table whose rows are different quantities (mass, cost, time), where
  // different decimals down a column are intended.
  function rowsAreUniform(table, columns) {
    if (columns.length < 2) return false;
    return Array.from(table.rows).every((row) => {
      const formats = new Set();
      for (const column of columns) {
        const cell = row.cells[column.index];
        if (cell && column.numeric.includes(cell)) formats.add(decimalsOf(cell.textContent.trim()));
      }
      return formats.size <= 1;
    });
  }

  function checkNumericColumns(table, report) {
    const width = Math.max(0, ...Array.from(table.rows, (r) => r.cells.length));
    const columns = [];
    for (let index = 0; index < width; index++) {
      const cells = columnCells(table, index).filter((c) => c.textContent.trim() !== "");
      const numeric = cells.filter((c) => /\d/.test(c.textContent) && NUMBER.test(c.textContent.trim()));
      if (cells.length < 2 || numeric.length / cells.length < LIMITS.numericShare) continue;
      columns.push({index, numeric, name: headerOf(table, index)});
    }
    const transposed = rowsAreUniform(table, columns);
    for (const {numeric, name} of columns) {
      const aligned = numeric.filter((c) => ["right", "end"].includes(style(c).textAlign));
      if (aligned.length < numeric.length / 2) {
        report.add("table", "info",
          `The numbers in column "${name}" are not right-aligned, so digits do not line up; `
          + "use text-align: right.", selectorOf(table), boxOf(table));
      }
      const decimals = [...new Set(numeric.map((c) => decimalsOf(c.textContent.trim())))];
      if (decimals.length > 1 && !transposed) {
        report.add("table", "info",
          `The numbers in column "${name}" have different decimal places `
          + `(${decimals.sort((a, b) => a - b).join(", ")}); use the same number of decimals.`,
          selectorOf(table), boxOf(table));
      }
    }
  }

  function scrolls(el) {
    for (let node = el; node && node !== document.documentElement; node = parentOf(node)) {
      if (node === document.body) return false;
      const st = style(node);
      if (/(auto|scroll)/.test(st.overflowY) && node.scrollHeight > node.clientHeight) return true;
    }
    return false;
  }

  function checkTables(elements, report) {
    for (const el of elements) {
      if (el.localName !== "table" || !isRendered(el)) continue;
      checkNumericColumns(el, report);
      const rows = Array.from(el.rows).filter((r) => r.parentElement.localName !== "thead").length;
      if (rows > LIMITS.maxTableRows && !scrolls(el)) {
        report.add("table", "warn",
          `This table has ${rows} rows and no scroll container, which makes the page very long; `
          + "put it in a box with max-height and overflow: auto, or show fewer rows.",
          selectorOf(el), boxOf(el));
      }
    }
  }

  // ---- blocked requests (recorded by the helper) -----------------------------

  function checkBlocked(blocked, report) {
    for (const entry of blocked) {
      report.add("errors", "error",
        `The browser blocked a request to ${snippet(entry.uri)} (${entry.directive}); `
        + "pages may load only files from the session folder, so it is missing for the owner.",
        entry.uri, null);
    }
  }

  // ---- entry ---------------------------------------------------------------

  function guarded(report, name, work) {
    try {
      work();
    } catch (error) {
      report.add("audit", "info", `The ${name} check could not run: ${error && error.message}.`, "page", null);
    }
  }

  /**
   * Run all checks on the page as it is now.
   *
   * ``options.viewportHeight`` is the height of the window (the frame may have
   * grown for a full-page picture). Resolves with ``{findings, truncated}``.
   */
  async function auditPage(options) {
    options = options || {};
    const report = createReport();
    const elements = allElements().filter((el) => !isHelper(el));
    const items = textItems(elements);
    const blockedList = (window.agentCanvas.blocked || []).slice(0, 20);
    const blocked = new Set(blockedList.map((entry) => entry.uri));
    guarded(report, "overflow", () => {
      checkClipped(elements, report);
      checkPageWidth(elements, report);
      checkStickingOut(elements, report);
    });
    guarded(report, "overlap", () => checkOverlap(items, report));
    guarded(report, "small text", () => checkSmallText(items, report));
    guarded(report, "long lines", () => checkLongLines(items, report));
    guarded(report, "contrast", () => checkContrast(items, report));
    guarded(report, "font", () => checkFonts(items, report));
    guarded(report, "empty content", () => {
      checkEmptyElements(elements, report);
      checkImages(elements, blocked, report);
      checkBlocks(elements, report);
    });
    guarded(report, "placeholder", () => checkPlaceholders(items, report));
    guarded(report, "interaction", () => {
      checkInteraction(elements, items, report);
      checkTitle(report);
    });
    guarded(report, "page height", () => checkPageHeight(options, report));
    guarded(report, "plot", () => checkPlots(elements, report));
    guarded(report, "table", () => checkTables(elements, report));
    guarded(report, "blocked request", () => checkBlocked(blockedList, report));
    return {findings: report.findings, truncated: report.truncated};
  }

  window.agentCanvas.auditPage = auditPage;
})();
