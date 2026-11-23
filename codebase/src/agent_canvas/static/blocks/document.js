// canvas-document: a Markdown or PDF file of the session folder in a window of its own
// inside the page (CNT-01). Markdown goes through the viewers' cleaned renderer
// (markdown-render.js, VIEW-03); a PDF through PDF.js, started as the viewer does
// (pdf-core.js, VIEW-05), with pages drawn when they come near the window (at most KEEP
// canvases), zoom buttons and a selectable text layer. No frame is nested: both are drawn
// into this block's shadow root. "Open" asks the shell to show the file as a page (A-100).
import { CanvasBlock, h } from "./base.js";
import { renderMarkdown } from "../markdown-render.js";

const KATEX_CSS = "/static/vendor/katex/katex.min.css";
const PDF_CORE = "/static/pdf-core.js";
const FILE = /^(?![/\\]|[a-z][a-z0-9+.-]*:)[^\0]*\.(md|markdown|pdf)$/i;
const DEFAULT_HEIGHT = 480;
const MIN_HEIGHT = 120;
const MAX_HEIGHT = 2000;
const CSS_PER_PT = 96 / 72; // zoom 100 % = the size on paper at 96 dpi
const STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
const KEEP = 10;
const GAP = 8;
const HOLD_MS = 150;

const CSS = `
.doc-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
.doc-name { flex: 1 1 8em; font-weight: 600; overflow-wrap: anywhere; }
.doc-head button { padding: 3px 10px; }
.doc-head output { min-width: 4em; text-align: right; color: var(--ac-muted);
  font-variant-numeric: tabular-nums; }
.doc-scroll { contain: paint; overflow: auto; scrollbar-gutter: stable; color-scheme: light dark; border: 1px solid var(--ac-border); border-radius: 6px;
  background: var(--ac-subtle); }
.doc-scroll.text { background: var(--ac-surface); padding: 10px 14px; }
.doc-pages { display: flex; flex-direction: column; align-items: center; min-width: 100%;
  width: max-content; padding: ${GAP}px 0 0; }
.doc-page { position: relative; flex: none; margin: 0 ${GAP}px ${GAP}px; background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, .35); }
.doc-page canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.textLayer { position: absolute; inset: 0; overflow: hidden; line-height: 1;
  text-size-adjust: none; forced-color-adjust: none; }
.textLayer :is(span, br) { position: absolute; white-space: pre; color: transparent;
  cursor: text; transform-origin: 0 0; }
.textLayer ::selection { background: rgba(0, 80, 255, .35); }
`;
const ownSheet = new CSSStyleSheet();
ownSheet.replaceSync(CSS);

export class CanvasDocument extends CanvasBlock {
  static schema = {src: "string!", height: "number", title: "string"};

  constructor() {
    super();
    this.session = null;
    this.entries = [];
    this.scale = CSS_PER_PT;
    this.fitting = true;
    this.observer = null;
    this.queued = false;
    this.holdTimer = 0;
    this.holding = false;
  }

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(ownSheet)) this.shadowRoot.adoptedStyleSheets = [...sheets, ownSheet];
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.dispose();
  }

  validate(config) {
    if (!FILE.test(config.src) || config.src.split("/").includes("..")) {
      return '"src" must be a Markdown or PDF file (.md, .markdown, .pdf) in the session folder';
    }
    if (config.height !== undefined && (config.height < MIN_HEIGHT || config.height > MAX_HEIGHT)) {
      return `"height" must be ${MIN_HEIGHT} to ${MAX_HEIGHT}`;
    }
    return null;
  }

  get isPdf() {
    return this._config.src.toLowerCase().endsWith(".pdf");
  }

  dispose() {
    if (this.observer) this.observer.disconnect();
    this.observer = null;
    if (this.session) this.core.closeSession(this.session);
    this.session = null;
    this.entries = [];
    this.snapshot = undefined;
  }

  async render(config, wrapper) {
    this.dispose();
    const scroll = h("div", {class: "doc-scroll", tabindex: "0"});
    scroll.style.height = `${config.height || DEFAULT_HEIGHT}px`;
    const head = h("div", {class: "doc-head"}, h("span", {class: "doc-name"}, config.title || config.src));
    this.head = head;
    this.scroll = scroll;
    wrapper.replaceChildren(head, scroll);
    this.attach(wrapper);
    // A plain name is a page the hub can show; a file in a subfolder is not.
    if (!config.src.includes("/")) {
      head.append(h("button", {type: "button", onclick: () => this.open()}, "Open"));
    }
    const url = new URL(config.src, document.baseURI).href;
    if (this.isPdf) await this.renderPdf(url, wrapper);
    else await this.renderMarkdown(url);
  }

  open() {
    window.agentCanvas.openFile(this._config.src);
  }

  // ---- Markdown ----------------------------------------------------------------------

  async renderMarkdown(url) {
    const response = await fetch(url, {cache: "no-store"});
    if (!response.ok) throw new Error(`could not read ${this._config.src} (${response.status})`);
    const body = h("div", {class: "markdown"});
    body.append(await renderMarkdown(await response.text()));
    this.scroll.classList.add("text");
    this.scroll.append(body);
    if (body.querySelector(".katex")) {
      this.shadowRoot.prepend(h("link", {rel: "stylesheet", href: KATEX_CSS}));
    }
  }

  // ---- PDF ----------------------------------------------------------------------------

  async renderPdf(url, wrapper) {
    this.core = await import(new URL(PDF_CORE, document.baseURI).href);
    const outButton = h("button", {type: "button", "aria-label": "Zoom out", onclick: () => this.step(-1)}, "−");
    const inButton = h("button", {type: "button", "aria-label": "Zoom in", onclick: () => this.step(1)}, "+");
    const fitButton = h("button", {type: "button", "aria-label": "Fit width", onclick: () => this.fit()}, "Fit width");
    this.percent = h("output", {"aria-live": "off"});
    this.where = h("output", {"aria-live": "off"});
    this.head.append(outButton, this.percent, inButton, fitButton, this.where);
    const mine = this._generation;
    const opened = await this.core.openDocument(url);
    if (mine !== this._generation) {
      this.core.closeSession(opened);
      return;
    }
    this.session = opened;
    this.lib = opened.lib;
    this.snapshot = () => this.pdfSnapshot();

    const pages = await Promise.all(Array.from({length: opened.doc.numPages}, (_, i) => opened.doc.getPage(i + 1)));
    this.pagesBox = h("div", {class: "doc-pages"});
    this.entries = pages.map((page, i) => {
      const view = page.getViewport({scale: 1});
      const el = h("div", {class: "doc-page", "data-page": i + 1});
      this.pagesBox.append(el);
      return {el, page, number: i + 1, w: view.width, h: view.height, canvas: null, text: null,
        task: null, layer: null, generation: 0, renderedScale: 0, drawn: null};
    });
    this.scroll.append(this.pagesBox);
    this.attach(wrapper);
    this.fitting = true;
    this.setScale(this.fitScale());
    this.scroll.addEventListener("scroll", () => this.scheduleRefresh());
    this.observer = new ResizeObserver(() => {
      if (this.fitting && this.scroll.clientWidth) this.setScale(this.fitScale());
      else this.scheduleRefresh();
    });
    this.observer.observe(this.scroll);
    const [first] = this.drawNear();
    if (first) await Promise.allSettled([first]);
  }

  /** The drawn pages as they are in the window, for the send screenshot and ``look`` (BLK-06). */
  async pdfSnapshot() {
    this.drawNear();
    await Promise.allSettled(this.entries.map((entry) => entry.drawn));
    const box = this.scroll.getBoundingClientRect();
    const rect = {
      left: box.left + this.scroll.clientLeft, top: box.top + this.scroll.clientTop,
      width: this.scroll.clientWidth, height: this.scroll.clientHeight,
    };
    const canvas = h("canvas", {width: rect.width, height: rect.height});
    const context = canvas.getContext("2d");
    context.fillStyle = getComputedStyle(this.scroll).backgroundColor;
    context.fillRect(0, 0, rect.width, rect.height);
    for (const entry of this.entries) {
      if (!entry.canvas) continue;
      const r = entry.el.getBoundingClientRect();
      context.drawImage(entry.canvas, r.left - rect.left, r.top - rect.top, r.width, r.height);
    }
    return {image: canvas, rect};
  }

  fitScale() {
    const widest = Math.max(1, ...this.entries.map((entry) => entry.w));
    return Math.max(1, this.scroll.clientWidth - 2 * GAP) / widest;
  }

  setScale(value) {
    this.scale = value;
    for (const entry of this.entries) {
      entry.el.style.width = `${entry.w * value}px`;
      entry.el.style.height = `${entry.h * value}px`;
      if (entry.text) this.layerScale(entry.text);
    }
    this.percent.textContent = `${Math.round((value / CSS_PER_PT) * 100)} %`;
    this.holding = true;
    clearTimeout(this.holdTimer);
    this.holdTimer = setTimeout(() => { this.holding = false; this.drawNear(); }, HOLD_MS);
    this.drawNear();
  }

  layerScale(layer) {
    layer.style.setProperty("--scale-factor", this.scale);
    layer.style.setProperty("--total-scale-factor", this.scale);
  }

  fit() {
    this.fitting = true;
    this.setScale(this.fitScale());
  }

  step(direction) {
    const zoom = this.scale / CSS_PER_PT;
    const next = direction > 0
      ? STEPS.find((s) => s > zoom * 1.001)
      : [...STEPS].reverse().find((s) => s < zoom / 1.001);
    if (next === undefined) return;
    this.fitting = false;
    this.setScale(next * CSS_PER_PT);
  }

  scheduleRefresh() {
    if (this.queued) return;
    this.queued = true;
    requestAnimationFrame(() => { this.queued = false; this.drawNear(); });
  }

  evict(entry) {
    entry.generation += 1;
    if (entry.task) entry.task.cancel();
    if (entry.layer) entry.layer.cancel();
    entry.task = entry.layer = null;
    if (entry.canvas) entry.canvas.remove();
    if (entry.text) entry.text.remove();
    entry.canvas = entry.text = null;
    entry.renderedScale = 0;
  }

  // Draw the pages near the window (the KEEP closest to its centre), drop the others.
  drawNear() {
    if (!this.entries.length || !this.session) return [];
    const box = this.scroll.getBoundingClientRect();
    const near = [];
    let shown = 1;
    let best = 0;
    this.entries.forEach((entry, i) => {
      const r = entry.el.getBoundingClientRect();
      const share = Math.min(r.bottom, box.bottom) - Math.max(r.top, box.top);
      if (share > best) { best = share; shown = i + 1; }
      if (r.bottom < box.top - box.height || r.top > box.bottom + box.height) return;
      near.push({entry, distance: Math.abs((r.top + r.bottom) / 2 - (box.top + box.bottom) / 2)});
    });
    near.sort((a, b) => a.distance - b.distance);
    const wanted = new Set(near.slice(0, KEEP).map((item) => item.entry));
    for (const entry of this.entries) if (entry.canvas && !wanted.has(entry)) this.evict(entry);
    const started = [];
    for (const entry of wanted) {
      if ((entry.canvas && entry.renderedScale === this.scale) || (entry.canvas && this.holding)) continue;
      entry.drawn = this.draw(entry).catch((error) => console.error("page render failed", error));
      started.push(entry.drawn);
    }
    this.where.textContent = `${shown} / ${this.entries.length}`;
    return started;
  }

  async draw(entry) {
    const generation = ++entry.generation;
    const at = this.scale;
    entry.renderedScale = at;
    const viewport = entry.page.getViewport({scale: at});
    if (entry.task) entry.task.cancel();
    if (!entry.canvas) {
      entry.canvas = h("canvas", {});
      entry.el.prepend(entry.canvas);
    }
    const canvas = entry.canvas;
    const ratio = Math.max(1, Math.min(window.devicePixelRatio || 1,
      Math.sqrt(24e6 / (viewport.width * viewport.height))));
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    entry.task = entry.page.render({
      canvasContext: canvas.getContext("2d"), viewport,
      transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
    });
    try {
      await entry.task.promise;
    } catch (error) {
      if (error && error.name === "RenderingCancelledException") {
        if (entry.generation === generation) entry.renderedScale = 0;
        return;
      }
      throw error;
    }
    if (entry.generation !== generation || entry.text) return;
    entry.text = h("div", {class: "textLayer"});
    this.layerScale(entry.text);
    entry.el.append(entry.text);
    entry.layer = new this.lib.TextLayer({
      textContentSource: entry.page.streamTextContent(), container: entry.text, viewport,
    });
    try {
      await entry.layer.render();
    } catch (error) {
      if (entry.generation !== generation) return;
      throw error;
    }
  }
}
