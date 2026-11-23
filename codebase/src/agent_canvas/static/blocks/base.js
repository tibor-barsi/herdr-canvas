// Block runtime (BLK-02, BLK-03, BLK-08): a custom element renders into a shadow
// root from the JSON config in a child script and re-renders only when the
// parsed config changes by deep equality. Interactive state lives on the
// element, so it survives page updates that morph the light DOM.
import { sheet } from "./style.js";

const TYPE_CHECKS = {
  string: (v) => typeof v === "string",
  number: (v) => typeof v === "number" && Number.isFinite(v),
  boolean: (v) => typeof v === "boolean",
  array: Array.isArray,
  object: (v) => v !== null && typeof v === "object" && !Array.isArray(v),
};

/** Deep equality of parsed JSON values. */
export function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || !a || !b) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((k) => k in b && deepEqual(a[k], b[k]));
}

/**
 * Create an element: ``h("div", {class: "x", onclick: fn}, "text", child)``.
 * Text is always set as text, never as HTML.
 */
export function h(tag, props, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (name.startsWith("on")) element.addEventListener(name.slice(2), value);
    else if (name === "class") element.className = value;
    else element.setAttribute(name, value === true ? "" : String(value));
  }
  element.append(...children.filter((c) => c !== undefined && c !== null));
  return element;
}

const loading = new Map();

/** Load a classic script from /static/ once (lazy libraries, BLK-07). */
export function loadScript(url) {
  if (!loading.has(url)) {
    loading.set(url, new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = url;
      tag.setAttribute("data-agent-canvas-helper", "");
      tag.onload = resolve;
      tag.onerror = () => reject(new Error("could not load " + url));
      document.head.appendChild(tag);
    }));
  }
  return loading.get(url);
}

/** Add a stylesheet link to the document head once (fonts need document scope). */
export function loadStyle(url) {
  if (document.head.querySelector(`link[href="${url}"]`)) return;
  const link = h("link", {rel: "stylesheet", href: url, "data-agent-canvas-helper": true});
  document.head.appendChild(link);
}

/**
 * Check ``config`` against a schema ``{key: "type[!]"}``; ``type`` is string,
 * number, boolean, array, object or ``a|b`` for a fixed set of strings, and
 * ``!`` marks a required key. Returns a problem text or null.
 */
export function checkSchema(config, schema) {
  for (const [key, raw] of Object.entries(schema)) {
    const required = raw.endsWith("!");
    const spec = required ? raw.slice(0, -1) : raw;
    const value = config[key];
    if (value === undefined) {
      if (required) return `config key "${key}" is required`;
      continue;
    }
    const ok = spec in TYPE_CHECKS ? TYPE_CHECKS[spec](value) : spec.split("|").includes(value);
    if (!ok) {
      const wanted = spec in TYPE_CHECKS ? `a ${spec}` : `one of ${spec.split("|").join(", ")}`;
      return `config key "${key}" must be ${wanted}`;
    }
  }
  return null;
}

const WHEEL_LATCH_MS = 500;
let lastPageWheel = -Infinity;
let pageHasWheel = false;

/**
 * Let the page keep the wheel while it scrolls (#71): a view that slides under the
 * pointer ignores wheel events for 500 ms after the last one the page kept; a gesture
 * that starts over the view, or follows a pause, goes to the view. Call it on the
 * element that takes the wheel, before adding the wheel listener or the orbit controls.
 *
 * @param {HTMLElement} element the view whose wheel events the block uses
 */
export function latchWheel(element) {
  element.wheelView = true;
  pageHasWheel = false;
  if (!document.wheelLatchOn) {
    document.wheelLatchOn = true;
    document.addEventListener("wheel", (event) => {
      if (event.composedPath().some((node) => node.wheelView)) return;
      lastPageWheel = event.timeStamp;
      pageHasWheel = true;
    }, {capture: true, passive: true});
  }
  element.addEventListener("wheel", (event) => {
    const latched = pageHasWheel && event.timeStamp - lastPageWheel < WHEEL_LATCH_MS;
    pageHasWheel = latched;
    lastPageWheel = event.timeStamp;
    if (latched) event.stopImmediatePropagation();
  }, {capture: true});
}

export class CanvasBlock extends HTMLElement {
  /** Schema for ``checkSchema``; blocks override it. */
  static schema = {};
  /** True when a rewrite updates the existing nodes instead of rebuilding. */
  static inPlace = false;
  /** True when a ``text/markdown`` child supplies the ``text`` key. */
  static markdownChild = false;

  constructor() {
    super();
    this.state = {};
    this.renderCount = 0;
    this._config = undefined;
    this._wrapper = null;
    this._reported = null;
    this._scheduled = false;
    this._busy = 0;
    this._idleWaiters = [];
    this._generation = 0;
    this._onFileChanged = (event) => this.fileChanged(event.detail.path);
  }

  connectedCallback() {
    if (!this.shadowRoot) {
      this.attachShadow({mode: "open"}).adoptedStyleSheets = [sheet];
      new MutationObserver(() => this.schedule()).observe(this, {
        childList: true, characterData: true, subtree: true,
        attributes: true, attributeFilter: ["data-canvas-id"],
      });
    }
    document.addEventListener("agentcanvas:file-changed", this._onFileChanged);
    this.schedule();
  }

  disconnectedCallback() {
    document.removeEventListener("agentcanvas:file-changed", this._onFileChanged);
  }

  // One refresh per burst of changes, after the page code that builds the
  // element has finished (a block created by script gets its child first).
  schedule() {
    if (this._scheduled) return;
    this._scheduled = true;
    queueMicrotask(() => {
      this._scheduled = false;
      this.refresh();
    });
  }

  /** True when no refresh is scheduled or running (the block shows its config). */
  get renderIdle() {
    return !this._scheduled && this._busy === 0;
  }

  /**
   * A promise that resolves once the block is idle: used by ``look`` to wait
   * until plots, models and markdown are drawn before it takes the picture.
   */
  whenRendered() {
    if (this.renderIdle) return Promise.resolve();
    return new Promise((resolve) => this._idleWaiters.push(resolve));
  }

  _notifyIdle() {
    if (!this.renderIdle) return;
    for (const resolve of this._idleWaiters.splice(0)) resolve();
  }

  get tagLabel() {
    const id = this.getAttribute("data-canvas-id");
    return id ? `${this.localName} "${id}"` : this.localName;
  }

  readConfig() {
    if (!this.getAttribute("data-canvas-id")) {
      throw new Error("missing data-canvas-id");
    }
    let config = {};
    const json = this.querySelector(':scope > script[type="application/json"]');
    if (json) {
      try {
        config = JSON.parse(json.textContent);
      } catch (error) {
        throw new Error(`config is not valid JSON (${error.message})`);
      }
      if (!TYPE_CHECKS.object(config)) throw new Error("config must be a JSON object");
    }
    const markdown = this.querySelector(':scope > script[type="text/markdown"]');
    if (markdown && this.constructor.markdownChild) {
      config = {...config, text: markdown.textContent};
    }
    return config;
  }

  async refresh() {
    this._busy += 1;
    try {
      await this._refresh();
    } finally {
      this._busy -= 1;
      this._notifyIdle();
    }
  }

  async _refresh() {
    let config;
    try {
      config = this.readConfig();
      const problem = checkSchema(config, this.constructor.schema) || this.validate(config);
      if (problem) throw new Error(problem);
    } catch (error) {
      this.showError(error.message);
      return;
    }
    if (this._wrapper && deepEqual(config, this._config)) return;
    const generation = ++this._generation;
    const inPlace = this.constructor.inPlace && this._wrapper && !this._wrapper.isError;
    const wrapper = inPlace ? this._wrapper : h("div", {class: "block"});
    try {
      this.renderCount += 1;
      const before = this._config;
      this._config = config;
      await this.render(config, wrapper, before);
    } catch (error) {
      if (generation === this._generation) this.showError(error.message);
      return;
    }
    if (generation !== this._generation) return;
    this._reported = null;
    this._wrapper = wrapper;
    if (!inPlace) this.shadowRoot.replaceChildren(wrapper);
  }

  showError(problem) {
    this._generation += 1;
    this._config = undefined;
    const text = `${this.localName}: ${problem}`;
    if (this._reported === text && this._wrapper && this._wrapper.isError) return;
    const box = h("div", {class: "block block-error", role: "alert"}, text);
    box.isError = true;
    this._wrapper = box;
    this.shadowRoot.replaceChildren(box);
    if (this._reported === text) return;
    this._reported = text;
    const id = this.getAttribute("data-canvas-id");
    window.agentCanvas.report("error", {
      source: "block", message: text, line: null, canvas_id: id || null,
    });
  }

  // ---- ``src`` files (BLK-09) ----------------------------------------------------

  /** Called when the hub reports a changed file; reloads if it is our ``src``. */
  fileChanged(path) {
    const src = this._config && this._config.src;
    if (typeof src !== "string" || typeof path !== "string") return;
    const resolved = decodeURIComponent(new URL(src, document.baseURI).pathname);
    if (resolved.endsWith("/" + path)) this.reloadSource();
  }

  /**
   * Load the ``src`` data again. The default re-renders from scratch; blocks
   * that hold view state (plot, image, model) override it to keep that state.
   */
  reloadSource() {
    this._config = undefined;
    this.schedule();
  }

  /** Put ``wrapper`` in the shadow root now (libraries need a laid-out element). */
  attach(wrapper) {
    if (wrapper.parentNode !== this.shadowRoot) this.shadowRoot.replaceChildren(wrapper);
  }

  /** Extra checks beyond the schema; return a problem text or null. */
  validate() {
    return null;
  }

  /** Build or update ``wrapper`` for ``config``; blocks override it. */
  render() {
    throw new Error("block has no render method");
  }

  // ---- events and actions for the owner's feedback ------------------------------

  /** Record an owner action of ``kind`` (select, input, ...) for the next send. */
  action(kind, value, pointerEvent) {
    const ask = this.parentElement;
    if (ask && ask.takePoint && ask.takePoint(this, kind, value)) return; // ASK-05
    const at = pointerEvent && Number.isFinite(pointerEvent.clientX)
      ? [Math.round(pointerEvent.clientX), Math.round(pointerEvent.clientY)] : null;
    window.agentCanvas.blockAction(kind, this, value, at);
  }

  /** True while the point Ask around this block takes its clicks as the answer (ASK-05). */
  get pointing() {
    const ask = this.parentElement;
    return Boolean(ask && ask.pointsAt && ask.pointsAt(this));
  }

  /** Send a ``button``, ``choice`` or ``text`` event. */
  event(kind, value) {
    window.agentCanvas.blockEvent(kind, this, value);
  }
}
