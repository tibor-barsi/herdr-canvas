// PDF viewer (VIEW-04, VIEW-05): the pages one under another, fitted to the width,
// zoom 50-400 % by buttons and Ctrl+wheel around the pointer, the page number in view,
// a selectable text layer, pages rendered when they come near the view (at most
// KEEP canvases exist). PDF.js runs under the frame's CSP: its worker is a classic
// `blob:` worker made from the vendored worker's text without the closing `export{...}`
// (a module worker does not start here, early check 12); if that fails, the page's thread.
//
// window.acViewer is the one interface of all viewers (4.2): kind, space,
// mount(root, url) -> the element that holds the pages and their text layers,
// update(message), mounted. For the "pdf-pt" space (points from the top-left of a page,
// pages from 1) there is toSpace(cx, cy) -> {p, x, y}, fromSpace(p, x, y) -> {x, y} and
// size(p) -> {w, h}, async crop(p, box) and reveal(box) (a box is {x, y, w, h} in points
// on page p), scale (CSS px per point) and the text of the document: index
// {text, pages, items} (null until read), with one item {p, i, str, start, end, x, y, w, h} per
// text-layer span, itemOf(node) -> the item of a text-layer node.
// "agentcanvas:view" fires on zoom, scroll, resize and a change of the page in view;
// "agentcanvas:updated" once the document is shown and again when its text is read.
(() => {
  const CSS_PER_PT = 96 / 72; // zoom 100 % = the size on paper at 96 dpi
  const STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
  const MIN_ZOOM = STEPS[0];
  const MAX_ZOOM = STEPS[STEPS.length - 1];
  const KEEP = 10; // page canvases kept at most
  const NEAR = 1; // pages within this many frame heights of the view are rendered
  const GAP = 8;
  const WHEEL_RATE = 0.0015;
  const MAX_PIXELS = 24e6; // canvas area; below it the canvas has the device's resolution
  const HOLD_MS = 150; // zoom rerenders wait until the zoom has been still this long
  const ASCENT = 0.8; // of the font size above the baseline; the box of a text item
  const DESCENT = 0.2; // and below it
  const PROBLEM = { // VIEW-14: the owner's sentence for each reason code
    "pdf-corrupt": "the PDF is damaged. Ask the agent to make it again.",
    "pdf-password": "the PDF is locked with a password. Ask the agent for a copy without the password.",
  };

  const style = document.createElement("style");
  style.textContent = `
    html, body { margin: 0; height: 100%; overflow: hidden; background: #e4e4e4; }
    [data-scroller] { position: fixed; inset: 0; overflow: auto; }
    [data-pages] { display: flex; flex-direction: column; align-items: center;
      box-sizing: border-box; min-width: 100%; width: max-content; padding: ${GAP}px 0 0; }
    [data-pdf-page] { position: relative; flex: none; margin: 0 ${GAP}px ${GAP}px;
      background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,.35); }
    [data-pdf-page] canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
    [data-bar] { position: fixed; top: 8px; right: 24px; display: flex; gap: 4px;
      align-items: center; font: 13px system-ui, sans-serif; background: rgba(255,255,255,.9);
      border: 1px solid #bbb; border-radius: 6px; padding: 3px; z-index: 2; }
    [data-bar] button { font: inherit; padding: 2px 8px; }
    [data-bar] output { min-width: 4em; text-align: right; color: #333; }
    [data-notice] { margin: 2em; font: 16px system-ui, sans-serif; color: #333; }
    .textLayer { position: absolute; inset: 0; overflow: hidden; line-height: 1;
      text-size-adjust: none; forced-color-adjust: none; }
    .textLayer :is(span, br) { position: absolute; white-space: pre; color: transparent;
      cursor: text; transform-origin: 0 0; }
    .textLayer ::selection { background: rgba(0, 80, 255, .35); }
    html[data-ac-commenting] .textLayer :is(span, br) { cursor: crosshair; }
  `;
  document.head.append(style);

  const here = new URL(location.href);
  const version = here.searchParams.get("v");
  const fileUrl = new URL(here);
  fileUrl.searchParams.delete("ac-view");
  const name = decodeURIComponent(here.pathname.split("/").pop());

  const scroller = document.createElement("div");
  scroller.dataset.scroller = "";
  const pagesBox = document.createElement("div");
  pagesBox.dataset.pages = "";
  scroller.append(pagesBox);

  const bar = document.createElement("div");
  bar.dataset.bar = "";
  const button = (label, title) => {
    const element = Object.assign(document.createElement("button"), {textContent: label, type: "button"});
    element.setAttribute("aria-label", title);
    return element;
  };
  const outButton = button("−", "Zoom out");
  const inButton = button("+", "Zoom in");
  const fitButton = button("Fit width", "Fit width");
  const percent = document.createElement("output");
  const pageOutput = document.createElement("output");
  bar.append(outButton, percent, inButton, fitButton, pageOutput);

  let core = null; // static/pdf-core.js, once the first document is being opened
  let pdfjs = null;
  let thread = null; // "worker" or "page" once a document is open
  let session = null; // {doc, worker}
  let entries = []; // one per page: {el, w, h, page, canvas, text, ...}
  let scale = CSS_PER_PT;
  let fitting = true;
  let mounted = false;
  let current = 0; // the page in view, 1-based; 0 before the first layout
  let holding = false;
  let holdTimer = 0;
  let queued = false;
  let index = null; // {text, pages} of the document shown; null while it is being read
  let reading = 0; // counts the documents read, so that a late reading is dropped
  const itemAt = new WeakMap(); // text-layer span -> {p, i}

  const clampZoom = (value) => Math.min(MAX_ZOOM * CSS_PER_PT, Math.max(Math.min(MIN_ZOOM * CSS_PER_PT, fitScale()), value));

  function viewChanged() {
    document.dispatchEvent(new Event("agentcanvas:view"));
  }

  // ---- PDF.js and its worker (static/pdf-core.js) ---------------------------------

  // A classic script of an opaque origin cannot import() a path, only a full URL.
  const loadingCore = import(new URL("/static/pdf-core.js", location.href).href);

  async function openDocument(url) {
    core = await loadingCore;
    const opened = await core.openDocument(url);
    pdfjs = opened.lib;
    thread = opened.thread;
    return opened;
  }

  function closeSession(old) {
    if (old) core.closeSession(old);
  }

  // ---- layout ---------------------------------------------------------------------

  function fitScale() {
    const widest = Math.max(1, ...entries.map((entry) => entry.w));
    return Math.max(1, scroller.clientWidth - 2 * GAP) / widest;
  }

  function setScale(value) {
    scale = value;
    for (const entry of entries) {
      entry.el.style.width = `${entry.w * scale}px`;
      entry.el.style.height = `${entry.h * scale}px`;
      if (entry.text) setLayerScale(entry.text);
    }
    percent.textContent = `${Math.round((scale / CSS_PER_PT) * 100)} %`;
    holding = true;
    clearTimeout(holdTimer);
    holdTimer = setTimeout(() => { holding = false; refresh(); }, HOLD_MS);
    viewChanged();
    refresh();
  }

  function setLayerScale(layer) {
    layer.style.setProperty("--scale-factor", scale);
    layer.style.setProperty("--total-scale-factor", scale);
  }

  // Frame point -> {i, u, v}: page index and the point in points on it (the nearest page
  // when the point lies between pages, or page index ``only`` when given).
  function pointAt(px, py, only) {
    let best = only === undefined ? 0 : only;
    let distance = Infinity;
    if (only === undefined) {
      entries.forEach((entry, i) => {
        const r = entry.el.getBoundingClientRect();
        const d = py < r.top ? r.top - py : py > r.bottom ? py - r.bottom : 0;
        if (d < distance) { distance = d; best = i; }
      });
    }
    const r = entries[best].el.getBoundingClientRect();
    return {i: best, u: (px - r.left) / scale, v: (py - r.top) / scale};
  }

  // Scroll so that the point ``spot`` of pointAt lies under frame point (px, py).
  function placeAt(spot, px, py) {
    const r = entries[spot.i].el.getBoundingClientRect();
    scroller.scrollLeft += r.left + spot.u * scale - px;
    scroller.scrollTop += r.top + spot.v * scale - py;
  }

  function zoomAround(value, px, py) {
    if (!entries.length) return;
    fitting = false;
    const spot = pointAt(px, py);
    setScale(clampZoom(value));
    placeAt(spot, px, py);
  }

  function fit() {
    if (!entries.length) return;
    fitting = true;
    const spot = pointAt(0, 0);
    setScale(fitScale());
    scroller.scrollLeft = 0;
    placeAt(spot, 0, 0);
  }

  function step(direction) {
    const zoom = scale / CSS_PER_PT;
    const next = direction > 0
      ? STEPS.find((s) => s > zoom * 1.001)
      : [...STEPS].reverse().find((s) => s < zoom / 1.001);
    if (next !== undefined) zoomAround(next * CSS_PER_PT, scroller.clientWidth / 2, scroller.clientHeight / 2);
  }

  // ---- lazy rendering ---------------------------------------------------------------

  function evict(entry) {
    entry.generation += 1;
    if (entry.task) entry.task.cancel();
    if (entry.layer) entry.layer.cancel();
    entry.task = entry.layer = null;
    if (entry.canvas) entry.canvas.remove();
    if (entry.text) entry.text.remove();
    entry.canvas = entry.text = null;
    entry.renderedScale = 0;
  }

  function draw(entry) {
    entry.drawn = renderPage(entry);
    return entry.drawn;
  }

  async function renderPage(entry) {
    const generation = ++entry.generation;
    const at = scale;
    entry.renderedScale = at; // asked for; a cancelled or evicted render resets it
    const viewport = entry.page.getViewport({scale: at});
    if (entry.task) entry.task.cancel();
    if (!entry.canvas) {
      entry.canvas = document.createElement("canvas");
      entry.el.prepend(entry.canvas);
    }
    const canvas = entry.canvas;
    const ratio = Math.max(1, Math.min(window.devicePixelRatio || 1,
      Math.sqrt(MAX_PIXELS / (viewport.width * viewport.height))));
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    const task = entry.page.render({
      canvasContext: canvas.getContext("2d"), viewport,
      transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
    });
    entry.task = task;
    try {
      await task.promise;
    } catch (error) {
      if (error && error.name === "RenderingCancelledException") {
        if (entry.generation === generation) entry.renderedScale = 0;
        return;
      }
      throw error;
    }
    if (entry.generation !== generation) return;
    if (!entry.text) {
      entry.text = document.createElement("div");
      entry.text.className = "textLayer";
      setLayerScale(entry.text);
      entry.el.append(entry.text);
      entry.layer = new pdfjs.TextLayer({
        textContentSource: entry.page.streamTextContent(), container: entry.text, viewport,
      });
      try {
        await entry.layer.render();
        entry.layer.textDivs.forEach((div, i) => itemAt.set(div, {p: entry.number, i}));
      } catch (error) {
        if (entry.generation !== generation) return;
        throw error;
      }
    }
  }

  // Which pages are rendered: those near the view, the KEEP closest to its centre.
  function refresh() {
    queued = false;
    if (!entries.length) return [];
    const height = scroller.clientHeight;
    const near = [];
    let bestShare = 0;
    let shown = current || 1;
    entries.forEach((entry, i) => {
      const r = entry.el.getBoundingClientRect();
      const share = Math.min(r.bottom, height) - Math.max(r.top, 0);
      if (share > bestShare) { bestShare = share; shown = i + 1; }
      if (r.bottom < -NEAR * height || r.top > height * (1 + NEAR)) return;
      near.push({entry, distance: Math.abs((r.top + r.bottom) / 2 - height / 2)});
    });
    near.sort((a, b) => a.distance - b.distance);
    const wanted = new Set(near.slice(0, KEEP).map((item) => item.entry));
    for (const entry of entries) if (entry.canvas && !entry.cropping && !wanted.has(entry)) evict(entry);
    const started = [];
    for (const entry of wanted) {
      const fresh = entry.canvas && entry.renderedScale === scale;
      if (fresh || (entry.canvas && holding)) continue;
      started.push(draw(entry).catch((error) => console.error("page render failed", error)));
    }
    if (shown !== current) {
      current = shown;
      pageOutput.textContent = `${current} / ${entries.length}`;
      viewChanged();
    }
    return started;
  }

  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(refresh);
  }

  // ---- loading, errors, update --------------------------------------------------------

  async function lay(opened) {
    const pages = await Promise.all(
      Array.from({length: opened.doc.numPages}, (_, i) => opened.doc.getPage(i + 1)));
    for (const entry of entries) evict(entry);
    pagesBox.replaceChildren();
    entries = pages.map((page, i) => {
      const view = page.getViewport({scale: 1});
      const el = document.createElement("div");
      el.dataset.pdfPage = String(i + 1);
      pagesBox.append(el);
      return {el, w: view.width, h: view.height, page, number: i + 1, generation: 0, renderedScale: 0,
        canvas: null, text: null, task: null, layer: null, drawn: null};
    });
    current = 0;
  }

  // The box of a text item in points from the page's top-left: the font's em box
  // along the baseline, as the bounding box of its corners (any rotation).
  function itemBox(item, view, p, i) {
    const [a, b, c, d, e, f] = pdfjs.Util.transform(view.transform, item.transform);
    const along = Math.hypot(a, b) || 1;
    const run = [item.width * a / along, item.width * b / along];
    const top = [e + ASCENT * c, f + ASCENT * d];
    const bottom = [e - DESCENT * c, f - DESCENT * d];
    const xs = [top[0], bottom[0], top[0] + run[0], bottom[0] + run[0]];
    const ys = [top[1], bottom[1], top[1] + run[1], bottom[1] + run[1]];
    const x = Math.min(...xs);
    const y = Math.min(...ys);
    return {p, i, str: item.str, x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y};
  }

  // The text of the document, one item per text-layer span (ANC-01, ANC-03): items are
  // joined by one space, white space collapsed; ``start`` and ``end`` are the item's
  // place in the text, ``lead`` its leading space that was dropped.
  async function readText(pages) {
    const mine = ++reading;
    index = null;
    let lists;
    try {
      lists = await Promise.all(pages.map(async (page, n) => {
        const view = page.getViewport({scale: 1});
        const {items} = await page.getTextContent();
        return items.filter((item) => typeof item.str === "string")
          .map((item, i) => itemBox(item, view, n + 1, i));
      }));
    } catch (error) {
      if (mine !== reading) return;
      // No text: text anchors are lost, shapes still work.
      console.error("text read failed", error);
      index = {text: "", pages: pages.map(() => []), items: []};
      document.dispatchEvent(new CustomEvent("agentcanvas:updated"));
      return;
    }
    if (mine !== reading) return;
    const items = lists.flat();
    let text = "";
    for (const item of items) {
      const collapsed = item.str.replace(/\s+/g, " ");
      const body = collapsed.trim();
      item.lead = collapsed.startsWith(" ") ? 1 : 0;
      if (text && body) text += " ";
      item.start = text.length;
      text += body;
      item.end = text.length;
    }
    index = {text, pages: lists, items};
    document.dispatchEvent(new CustomEvent("agentcanvas:updated"));
  }

  function fail(reason) {
    closeSession(session);
    session = null;
    scroller.remove();
    bar.remove();
    const notice = document.createElement("p");
    notice.dataset.notice = "";
    notice.textContent = `This file could not be shown${PROBLEM[reason] ? `: ${PROBLEM[reason]}` : "."}`;
    document.body.append(notice);
    const canvas = window.agentCanvas;
    if (canvas && canvas.report) {
      canvas.report("viewer-error", {page: name, version: version === null ? null : Number(version), reason});
    }
  }

  // Show the PDF at ``url``; ``keep`` ({fitting, scale, page, fraction}) is the reading
  // place of the document it replaces.
  async function load(url, keep) {
    const opened = await openDocument(url);
    try {
      await lay(opened);
    } catch (error) {
      closeSession(opened);
      throw error;
    }
    closeSession(session);
    session = opened;
    readText(entries.map((entry) => entry.page));
    fitting = !keep || keep.fitting;
    setScale(fitting ? fitScale() : clampZoom(keep.scale));
    if (keep) {
      const target = entries[Math.min(keep.page, entries.length) - 1];
      scroller.scrollTop += target.el.getBoundingClientRect().top + keep.fraction * target.h * scale;
    }
    const [first] = refresh();
    if (first) await Promise.allSettled([first]);
  }

  function mount(root, url) {
    root.append(scroller, bar);
    return load(url, null).then(() => {
      mounted = true;
      return pagesBox;
    }, (error) => {
      fail((error && error.pdfReason) || "pdf-corrupt");
      return null;
    });
  }

  // A new version: the document is loaded again and the reading place kept: the same
  // page at the same offset within it, and the zoom (VIEW-08).
  async function update(message) {
    await ready;
    if (!session) return;
    const top = pointAt(0, 0);
    const next = new URL(fileUrl);
    next.searchParams.set("t", String(message.version));
    try {
      await load(next.pathname + next.search, {
        fitting, scale, page: top.i + 1,
        fraction: Math.max(0, top.v / entries[top.i].h),
      });
    } catch (error) {
      fail((error && error.pdfReason) || "pdf-corrupt");
    }
  }

  window.acViewer = {
    kind: "pdf",
    space: "pdf-pt",
    mount,
    update,
    get mounted() { return mounted; },
    get ready() { return ready; },
    get thread() { return thread; },
    get options() { return {...core.OPTIONS}; },
    get page() { return current; },
    get pageCount() { return entries.length; },
    // The point in frame px (cx, cy) as {p, x, y}: page from 1, points from its top-left.
    toSpace(cx, cy, p) {
      const spot = pointAt(cx, cy, p === undefined ? undefined : p - 1);
      return {p: spot.i + 1, x: spot.u, y: spot.v};
    },
    fromSpace(p, x, y) {
      const r = entries[p - 1].el.getBoundingClientRect();
      return {x: r.left + x * scale, y: r.top + y * scale};
    },
    size: (p) => ({w: entries[p - 1].w, h: entries[p - 1].h}),
    get scale() { return scale; },
    get index() { return index; },
    // The text item of a text-layer node, once the document's text is read.
    itemOf(node) {
      const element = node && node.nodeType === Node.ELEMENT_NODE ? node : node && node.parentElement;
      const spot = itemAt.get(element);
      return spot && index ? index.pages[spot.p - 1][spot.i] : null;
    },
    // The page's own pixels inside ``box`` (points on page ``p``) cut from its canvas,
    // drawn at the current zoom first when it is not: {canvas, x, y, k} with the crop's
    // top-left in canvas pixels and ``k`` canvas pixels per point (at least one per CSS px).
    async crop(p, box) {
      const entry = entries[p - 1];
      entry.cropping = (entry.cropping || 0) + 1; // refresh does not evict it meanwhile
      try {
        if (!entry.canvas || entry.renderedScale !== scale || !entry.drawn) draw(entry);
        await entry.drawn;
      } finally {
        entry.cropping -= 1;
      }
      if (!entry.canvas || entry.renderedScale !== scale) throw new Error("page not drawn");
      const k = entry.canvas.width / entry.w;
      const x0 = Math.max(0, Math.round(box.x * k));
      const y0 = Math.max(0, Math.round(box.y * k));
      const x1 = Math.min(entry.canvas.width, Math.round((box.x + box.w) * k));
      const y1 = Math.min(entry.canvas.height, Math.round((box.y + box.h) * k));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, x1 - x0);
      canvas.height = Math.max(1, y1 - y0);
      canvas.getContext("2d").drawImage(
        entry.canvas, x0, y0, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height);
      return {canvas, x: x0, y: y0, k};
    },
    // Scroll so that ``box`` (points on page ``box.p``) is in view; centred when it was not.
    reveal(box) {
      const a = this.fromSpace(box.p, box.x, box.y);
      const b = this.fromSpace(box.p, box.x + box.w, box.y + box.h);
      if (a.x >= 0 && a.y >= 0 && b.x <= scroller.clientWidth && b.y <= scroller.clientHeight) return;
      placeAt({i: box.p - 1, u: box.x + box.w / 2, v: box.y + box.h / 2},
        scroller.clientWidth / 2, scroller.clientHeight / 2);
    },
  };

  inButton.addEventListener("click", () => step(1));
  outButton.addEventListener("click", () => step(-1));
  fitButton.addEventListener("click", fit);

  scroller.addEventListener("wheel", (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    const lines = event.deltaMode === 1 ? 16 : 1;
    zoomAround(scale * Math.exp(-event.deltaY * lines * WHEEL_RATE), event.clientX, event.clientY);
  }, {passive: false});

  scroller.addEventListener("scroll", () => { viewChanged(); schedule(); });
  window.addEventListener("resize", () => {
    if (fitting && entries.length) fit();
    else { viewChanged(); schedule(); }
  });

  const ready = mount(document.body, fileUrl.pathname + fileUrl.search).then(() => {
    if (mounted) document.dispatchEvent(new CustomEvent("agentcanvas:updated"));
  });
})();
