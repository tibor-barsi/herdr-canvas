// canvas-metrics: key numbers as tiles, each judged against its limits (CNT-05). The state
// (ok, near, out) is computed here from the value and the limits and is never read from the
// config; it is shown as a word with a mark, so colour is never the only cue (A-190).
import { CanvasBlock, h } from "./base.js";

const MAX_TILES = 12;
const DEFAULT_NEAR = 0.1; // fraction of the limit (A-98)
const EPSILON = 1e-9; // relative; keeps 1.65 against a limit of 1.5 "ok" at near 0.1
const STATES = {
  ok: {mark: "✓", word: "ok"},
  near: {mark: "!", word: "near limit"},
  out: {mark: "✗", word: "out of limit"},
};

const CSS = `
:host { --met-warn: #8a5a00; }
@media (prefers-color-scheme: dark) { :host { --met-warn: #e3b341; } }
.met-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.met-tile { border: 1px solid var(--ac-border); border-left-width: 4px; border-radius: 6px;
  padding: 8px 10px; background: var(--ac-subtle); min-width: 0; }
.met-tile[data-state="ok"] { border-left-color: var(--ac-ok); }
.met-tile[data-state="near"] { border-left-color: var(--met-warn); }
.met-tile[data-state="out"] { border-left-color: var(--ac-danger); }
.met-label { color: var(--ac-muted); font-size: 12.8px; overflow-wrap: anywhere; }
.met-value { font-size: 24px; font-weight: 600; line-height: 1.2; font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere; }
.met-unit { font-size: 13px; font-weight: 400; color: var(--ac-muted); margin-left: 4px; }
.met-limit, .met-change { color: var(--ac-muted); font-size: 12.8px; font-variant-numeric: tabular-nums; }
.met-state { display: flex; gap: 6px; align-items: center; font-weight: 600; font-size: 12.8px; margin-top: 2px; }
.met-mark { display: inline-grid; place-items: center; width: 1.4em; height: 1.4em;
  border: 1.5px solid currentColor; border-radius: 50%; font-size: .85em; }
.met-tile[data-state="ok"] .met-state { color: var(--ac-ok); }
.met-tile[data-state="near"] .met-state { color: var(--met-warn); }
.met-tile[data-state="out"] .met-state { color: var(--ac-danger); }
`;
const ownSheet = new CSSStyleSheet();
ownSheet.replaceSync(CSS);

/** ``ok``, ``near``, ``out`` or ``none`` (no limit) from a value, its limits and ``near``. */
export function stateOf({value, min, max}, near) {
  if (min === undefined && max === undefined) return "none";
  if ((min !== undefined && value < min) || (max !== undefined && value > max)) return "out";
  const close = (limit) => Math.abs(value - limit) <= (near + EPSILON) * Math.abs(limit);
  return (min !== undefined && close(min)) || (max !== undefined && close(max)) ? "near" : "ok";
}

function limitText({min, max, unit}) {
  const tail = unit ? ` ${unit}` : "";
  const parts = [];
  if (min !== undefined) parts.push(`needs ≥ ${min}${tail}`);
  if (max !== undefined) parts.push(`must be ≤ ${max}${tail}`);
  return parts.join(" · ");
}

function changeText({value, previous}) {
  if (previous === undefined || previous === 0) return null;
  const percent = Number((((value - previous) / Math.abs(previous)) * 100).toFixed(1));
  return `${percent > 0 ? "+" : ""}${percent} % vs previous`;
}

function tileProblem(tile) {
  if (!tile || typeof tile !== "object") return "must be an object";
  if (typeof tile.label !== "string") return '"label" must be a string';
  if (!Number.isFinite(tile.value)) return '"value" must be a number';
  for (const key of ["min", "max", "previous"]) {
    if (tile[key] !== undefined && !Number.isFinite(tile[key])) return `"${key}" must be a number`;
  }
  if (tile.unit !== undefined && typeof tile.unit !== "string") return '"unit" must be a string';
  if (tile.min !== undefined && tile.max !== undefined && tile.min > tile.max) return '"min" is above "max"';
  return null;
}

export class CanvasMetrics extends CanvasBlock {
  static schema = {tiles: "array!", near: "number"};

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(ownSheet)) this.shadowRoot.adoptedStyleSheets = [...sheets, ownSheet];
  }

  validate(config) {
    if (config.tiles.length < 1 || config.tiles.length > MAX_TILES) {
      return `"tiles" must hold 1 to ${MAX_TILES} tiles`;
    }
    if (config.near !== undefined && (config.near < 0 || config.near >= 1)) {
      return '"near" must be from 0 up to (not including) 1';
    }
    for (const [index, tile] of config.tiles.entries()) {
      const problem = tileProblem(tile);
      if (problem) return `tile ${index + 1}: ${problem}`;
    }
    return null;
  }

  render(config, wrapper) {
    const near = config.near === undefined ? DEFAULT_NEAR : config.near;
    wrapper.replaceChildren(h("div", {class: "met-grid"}, ...config.tiles.map((tile) => this.tile(tile, near))));
  }

  tile(tile, near) {
    const state = stateOf(tile, near);
    const limit = limitText(tile);
    const change = changeText(tile);
    return h("div", {class: "met-tile", "data-state": state},
      h("div", {class: "met-label"}, tile.label),
      h("div", {class: "met-value"}, String(tile.value),
        tile.unit ? h("span", {class: "met-unit"}, tile.unit) : null),
      limit ? h("div", {class: "met-limit"}, limit) : null,
      state === "none" ? null : h("div", {class: "met-state"},
        h("span", {class: "met-mark", "aria-hidden": "true"}, STATES[state].mark), ` ${STATES[state].word}`),
      change ? h("div", {class: "met-change"}, change) : null);
  }
}
