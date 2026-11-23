// Finding anchors again (ANC-06, ANC-07), loaded by helper.js before the comment
// layer and in test host pages. Two functions, both without state of their own
// except the search indexes of the last texts.
//
// ``findQuote(text, anchor)``: where a text anchor's quote stands in the page's
// text now. The occurrence whose surroundings agree most wins (longest common
// end of ``before`` plus longest common start of ``after``, letters and digits
// only); ties go to the nearest ``start``; a tie that stays is unclear, and an
// unclear match is null, never a guess (A-43, A-53).
//
// ``placeShape(kind, anchor, target, doc)``: where a point, rectangle or lasso
// stands now, from its fractions of the one element its target names.
(function () {
  "use strict";
  const registry = window.agentCanvas || (window.agentCanvas = {});
  if (registry.anchor) return;

  const MAX_INDEXES = 8;
  const indexes = new Map();  // text -> {text, flat, map, cum, stream}

  function isAlnum(code) {
    if (code < 128) {
      return (code >= 48 && code <= 57) || (code >= 65 && code <= 90) || (code >= 97 && code <= 122);
    }
    return /[\p{L}\p{N}]/u.test(String.fromCodePoint(code));
  }

  // White space collapsed to single spaces; ``map[i]`` is where flat character
  // ``i`` stands in the original text (null when the text is already flat).
  function flatten(text) {
    if (!/\s\s|[^\S ]/.test(text)) return {flat: text, map: null};
    const map = [];
    let flat = "";
    for (let i = 0; i < text.length; i++) {
      const space = /\s/.test(text[i]);
      if (space && flat.endsWith(" ")) continue;
      flat += space ? " " : text[i];
      map.push(i);
    }
    return {flat, map};
  }

  // ``cum[j]`` is the number of letters and digits in the first ``j`` characters
  // of the flat text, ``stream`` those letters and digits as code points.
  function buildIndex(text) {
    const {flat, map} = flatten(text);
    const cum = new Int32Array(flat.length + 1);
    const stream = [];
    for (let i = 0; i < flat.length;) {
      const code = flat.codePointAt(i);
      const width = code > 0xffff ? 2 : 1;
      if (isAlnum(code)) stream.push(code);
      for (let k = 1; k <= width; k++) cum[i + k] = stream.length;
      i += width;
    }
    findQuote.builds += 1;
    return {text, flat, map, cum, stream};
  }

  function indexOf(text) {
    let index = indexes.get(text);
    if (!index) {
      index = buildIndex(text);
      if (indexes.size >= MAX_INDEXES) indexes.delete(indexes.keys().next().value);
      indexes.set(text, index);
    }
    return index;
  }

  function codes(text) {
    return Array.from(typeof text === "string" ? text : "", (c) => c.codePointAt(0));
  }

  // How many letters and digits agree with ``before`` (backwards from ``at``)
  // and ``after`` (forwards from ``end``).
  function agreement(index, at, end, before, after) {
    const {cum, stream} = index;
    let score = 0;
    for (let i = cum[at] - 1, j = before.length - 1; i >= 0 && j >= 0 && stream[i] === before[j]; i--, j--) {
      score++;
    }
    for (let i = cum[end], j = 0; i < stream.length && j < after.length && stream[i] === after[j]; i++, j++) {
      score++;
    }
    return score;
  }

  // ``findQuote`` with the winning occurrence's ``score`` (agreeing letters and
  // digits) and ``distance`` from the anchor's start, to compare texts.
  function search(text, anchor) {
    const quote = String(anchor && anchor.quote || "").replace(/\s+/g, " ").trim();
    if (!quote || typeof text !== "string") return null;
    const index = indexOf(text);
    const before = codes(anchor.before);
    const after = anchor.cut ? [] : codes(anchor.after);
    const wanted = Number.isFinite(anchor.start) ? anchor.start : 0;
    let best = null;
    let tied = false;
    for (let at = index.flat.indexOf(quote); at >= 0; at = index.flat.indexOf(quote, at + 1)) {
      const found = {
        at, score: agreement(index, at, at + quote.length, before, after),
        distance: Math.abs(at - wanted),
      };
      if (!best || found.score > best.score ||
          (found.score === best.score && found.distance < best.distance)) {
        best = found;
        tied = false;
      } else if (found.score === best.score && found.distance === best.distance) {
        tied = true;
      }
    }
    if (!best || tied) return null;
    const last = best.at + quote.length - 1;
    const {score, distance} = best;
    return index.map
      ? {start: index.map[best.at], end: index.map[last] + 1, score, distance}
      : {start: best.at, end: best.at + quote.length, score, distance};
  }

  /**
   * Find a text anchor's quote in the page's text.
   *
   * @param {string} text The text of the page.
   * @param {{quote: string, before?: string, after?: string, start?: number, cut?: boolean}} anchor
   * @returns {{start: number, end: number} | null} Offsets in ``text``, or null
   *   when the quote is gone or the best occurrence is not unique.
   */
  function findQuote(text, anchor) {
    const hit = search(text, anchor);
    return hit && {start: hit.start, end: hit.end};
  }
  findQuote.builds = 0;

  function onlyOne(doc, selector) {
    try {
      const found = doc.querySelectorAll(selector);
      return found.length === 1 ? found[0] : null;
    } catch (error) {
      return null;  // a selector that no longer parses
    }
  }

  // The one element the target names: by its selector, else by its canvas id.
  function targetElement(target, doc) {
    const named = target || {};
    const bySelector = typeof named.selector === "string" && named.selector
      ? onlyOne(doc, named.selector) : null;
    if (bySelector || typeof named.canvas_id !== "string" || !named.canvas_id) return bySelector;
    const id = named.canvas_id.replace(/["\\]/g, "\\$&");
    return onlyOne(doc, `[data-canvas-id="${id}"]`) || onlyOne(doc, "#" + CSS.escape(named.canvas_id));
  }

  function finite(values) {
    return values.every((v) => typeof v === "number" && Number.isFinite(v));
  }

  /**
   * Place a point, rectangle or lasso at its fractions of its target element.
   *
   * @param {"point"|"rect"|"lasso"} kind
   * @param {object} anchor An anchor in ``page-px`` with its fractions.
   * @param {{selector?: string, canvas_id?: string}} target
   * @param {Document} [doc]
   * @returns {{rect: {x: number, y: number, w: number, h: number}} |
   *   {points: number[][]} | null} Page pixels; null when the element is gone,
   *   named twice, has no box or the anchor has no fractions.
   */
  function placeShape(kind, anchor, target, doc = document) {
    if (!anchor || anchor.space !== "page-px") return null;
    const element = targetElement(target, doc);
    if (!element) return null;
    const box = element.getBoundingClientRect();
    if (!(box.width > 0 && box.height > 0)) return null;
    const view = doc.defaultView;
    const x = (f) => box.left + view.scrollX + f * box.width;
    const y = (f) => box.top + view.scrollY + f * box.height;
    if (kind === "point" && finite([anchor.fx, anchor.fy])) {
      return {rect: {x: x(anchor.fx), y: y(anchor.fy), w: 0, h: 0}};
    }
    if (kind === "rect" && finite([anchor.fx, anchor.fy, anchor.fw, anchor.fh])) {
      return {rect: {
        x: x(anchor.fx), y: y(anchor.fy), w: anchor.fw * box.width, h: anchor.fh * box.height,
      }};
    }
    const points = anchor.fpoints;
    if (kind === "lasso" && Array.isArray(points) && points.length && points.every((p) => Array.isArray(p) && finite(p))) {
      return {points: points.map(([a, b]) => [x(a), y(b)])};
    }
    return null;
  }

  registry.anchor = {findQuote, search, placeShape};
})();
