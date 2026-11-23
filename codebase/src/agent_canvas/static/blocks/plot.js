// canvas-plot: a Plotly figure from `data`/`layout`/`config` or a JSON `src`
// file. Plotly loads only when a plot is on the page (BLK-07). Clicks and
// selections become `plot-click` and `plot-select` actions (BLK-01); the block
// converts page pixels to data coordinates (kept for ANC-05, R-10) and draws itself
// to an image for screenshots (BLK-06). Figures get the canvas theme (PLT-01 to
// PLT-03) and an axis bar under cartesian plots (PLT-04 to PLT-06).
import { CanvasBlock, h, loadScript } from "./base.js";

const PLOTLY_JS = "/static/vendor/plotly.js-dist-min/plotly.min.js";
const MAX_SELECTED_POINTS = 100;
const MAX_AXIS_GROUPS = 6;
const DARK_QUERY = "(prefers-color-scheme: dark)";
const FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", '
  + "Arial, sans-serif";

// Okabe-Ito, a colour sequence that stays apart for the common colour blindnesses;
// the dark variant swaps the colours that vanish on a dark surface.
const THEMES = {
  light: {
    fg: "#1f2328", muted: "#59636e", surface: "#ffffff", grid: "#e6eaef",
    line: "#c3cbd4", accent: "#2457c5",
    colorway: ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00",
      "#B5A300", "#6b7280"],
  },
  dark: {
    fg: "#e6edf3", muted: "#9aa6b2", surface: "#1c2128", grid: "#2f363f",
    line: "#4a525c", accent: "#6e9bff",
    colorway: ["#56B4E9", "#E69F00", "#2FC79A", "#E08FC0", "#8DA7FF", "#F0793A",
      "#F0E442", "#c9d1d9"],
  },
};

/** The canvas theme as a Plotly template for the light or the dark scheme. */
function canvasTemplate(dark) {
  const c = dark ? THEMES.dark : THEMES.light;
  const clear = "rgba(0,0,0,0)";
  const axis = {
    gridcolor: c.grid, zerolinecolor: c.line, linecolor: c.line, tickcolor: c.line,
    showline: true, ticks: "outside", ticklen: 4, automargin: true,
    title: {standoff: 8},
  };
  const polarAxis = {gridcolor: c.grid, linecolor: c.line, tickcolor: c.line};
  const sceneAxis = {gridcolor: c.grid, zerolinecolor: c.line, linecolor: c.line};
  return {
    layout: {
      font: {family: FONT_FAMILY, size: 12, color: c.fg},
      colorway: c.colorway,
      paper_bgcolor: c.surface,
      plot_bgcolor: c.surface,
      margin: {l: 8, r: 12, t: 12, b: 8},
      title: {x: 0.01, xanchor: "left", automargin: true, font: {size: 14}},
      legend: {bgcolor: clear, font: {size: 12}},
      hoverlabel: {bgcolor: c.surface, bordercolor: c.line, font: {color: c.fg}},
      modebar: {bgcolor: clear, color: c.muted, activecolor: c.accent},
      xaxis: axis, yaxis: axis,
      polar: {bgcolor: clear, radialaxis: polarAxis, angularaxis: polarAxis},
      scene: {xaxis: sceneAxis, yaxis: sceneAxis, zaxis: sceneAxis},
      coloraxis: {colorbar: {outlinewidth: 0, tickcolor: c.line}},
    },
  };
}

// plotly.py writes its default template into every figure it saves; that one
// (and only that one) is replaced by the canvas theme.
function isPlotlyPyDefault(template) {
  const layout = template && template.layout;
  return !!layout && Array.isArray(layout.colorway) && layout.colorway[0] === "#636efa"
    && layout.plot_bgcolor === "#E5ECF6";
}

/** ``layout`` with the canvas template, unless the figure keeps its own (PLT-03). */
function themedLayout(layout, theme, dark) {
  if (theme === "figure") return layout;
  const own = layout.template;
  if (own !== undefined && own !== null && !isPlotlyPyDefault(own)) return layout;
  return {...layout, template: canvasTemplate(dark)};
}

// Axis layout names of the cartesian subplots: ``x``, ``x2`` -> ``xaxis``, ``xaxis2``.
function axisNames(fullLayout) {
  const subplots = fullLayout._subplots || {};
  if (!(subplots.cartesian || []).length) return [];
  const ids = [...(subplots.xaxis || []), ...(subplots.yaxis || [])];
  return ids.map((id) => `${id[0]}axis${id.slice(1)}`);
}

const axisLabel = (name) => name.replace("axis", "");

function formatValue(value) {
  return typeof value === "number" ? String(Number(value.toPrecision(4))) : String(value);
}

// How many values of the traces on axis ``name`` a log axis cannot show.
function hiddenByLog(gd, name) {
  const id = axisLabel(name);
  const key = id[0];
  let count = 0;
  for (const trace of gd._fullData || []) {
    if ((trace[`${key}axis`] || key) !== id) continue;
    const values = trace[key];
    if (!values || typeof values === "string" || typeof values.length !== "number") continue;
    for (const value of values) {
      if (typeof value === "number" && value <= 0) count += 1;
    }
  }
  return count;
}

// The coordinates of a Plotly point event; x and y are null for traces without.
function describePoint(point) {
  const value = (v) => (v === undefined ? null : v);
  return {
    trace: point.curveNumber, index: point.pointNumber, x: value(point.x), y: value(point.y),
  };
}

const POINT_COLOUR = "#e8590c";

// The owner's point of a point Ask (ASK-05): an arrow with a label at the clicked data point.
function pointNote(point, trace) {
  const axes = trace || {};
  return {
    name: "ac-point", x: point.x, y: point.y, xref: axes.xaxis || "x", yref: axes.yaxis || "y",
    text: "your point", showarrow: true, arrowhead: 2, arrowsize: 1.4, arrowwidth: 2.5,
    arrowcolor: POINT_COLOUR, ax: 0, ay: -42, font: {color: "#1c1c1c", size: 12},
    bgcolor: "rgba(255, 255, 255, 0.92)", bordercolor: POINT_COLOUR, borderpad: 3,
  };
}

function loadImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("plot image could not be decoded"));
    image.src = source;
  });
}

export class CanvasPlot extends CanvasBlock {
  static inPlace = true;
  static schema = {
    data: "array", layout: "object", config: "object", src: "string",
    theme: "canvas|figure", axes: "boolean",
  };

  connectedCallback() {
    super.connectedCallback();
    this.schemeQuery = window.matchMedia(DARK_QUERY);
    this.onScheme = () => this.redraw();
    this.schemeQuery.addEventListener("change", this.onScheme);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.schemeQuery.removeEventListener("change", this.onScheme);
  }

  // The same figure again, for a changed colour scheme.
  redraw() {
    if (!this._config || !this._wrapper || this._wrapper.isError) return;
    this.render(this._config, this._wrapper).catch((error) => this.showError(error.message));
  }

  validate(config) {
    return config.data === undefined && config.src === undefined
      ? 'needs "data" or "src"' : null;
  }

  async render(config, wrapper) {
    const spec = await this.specOf(config);
    if (!Array.isArray(spec.data)) throw new Error('the figure needs a "data" list');
    await loadScript(PLOTLY_JS);
    if (!this.gd) this.gd = h("div", {class: "plot"});
    if (this.gd.parentNode !== wrapper) wrapper.replaceChildren(this.gd);
    this.attach(wrapper);
    const theme = config.theme !== undefined ? config.theme : spec.theme;
    this.axesOn = (config.axes !== undefined ? config.axes : spec.axes) !== false;
    const dark = this.schemeQuery ? this.schemeQuery.matches : false;
    const own = {...spec.layout};
    this.keepOwnerAxes(own.uirevision);
    let layout = this.withOwnerAxes(themedLayout(this.ownTicks(own), theme, dark));
    const point = this.state.point;
    if (point) {
      const note = pointNote(point, spec.data[point.trace]);
      layout = {...layout, annotations: [...(own.annotations || []), note]};
    }
    // Plotly sizes a later redraw from the div; without a height of its own the div
    // would collapse to nothing (Plotly's default figure height is 450 px).
    this.gd.style.height = `${typeof own.height === "number" ? own.height : 450}px`;
    // A figure without its own width follows the block's width.
    const options = {
      responsive: layout.width === undefined, displaylogo: false, ...spec.config,
    };
    // Plotly returns a pending promise for a figure it cannot draw; its own
    // message is the best description of the problem.
    await window.Plotly.react(this.gd, spec.data, layout, options);
    this.bindEvents();
    this.copyPlotlyStyles();
    this.syncBar(wrapper);
  }

  async specOf(config) {
    if (config.src === undefined) return config;
    const response = await fetch(config.src, {cache: "no-store"});
    if (!response.ok) throw new Error(`could not read ${config.src} (${response.status})`);
    let spec;
    try {
      spec = await response.json();
    } catch (error) {
      throw new Error(`${config.src} is not valid JSON (${error.message})`);
    }
    if (spec === null || typeof spec !== "object") {
      throw new Error(`${config.src} must hold a JSON object`);
    }
    return spec;
  }

  // Plotly adds its stylesheets to the document head, which a shadow root does
  // not see: copy their rules so that the mode bar, cursors and hover labels work.
  copyPlotlyStyles() {
    const rules = [];
    for (const style of document.head.querySelectorAll('style[id^="plotly.js-style"]')) {
      if (style.sheet) rules.push(...Array.from(style.sheet.cssRules, (r) => r.cssText));
    }
    if (!this.styleNode) this.styleNode = h("style");
    this.styleNode.textContent = rules.join("\n");
    if (this.styleNode.parentNode !== this.gd.parentNode) {
      this.gd.parentNode.appendChild(this.styleNode);
    }
  }

  /** Mark the owner's point of a point Ask (ASK-05) with an arrow; ``null`` removes it. */
  async showPoint(point) {
    this.state.point = point;
    if (!this.gd || !this.gd.data) return;
    const own = (this.gd.layout.annotations || []).filter((note) => note.name !== "ac-point");
    const note = point ? [pointNote(point, this.gd._fullData[point.trace])] : [];
    await window.Plotly.relayout(this.gd, {annotations: [...own, ...note]});
  }

  hidePoint() {
    if (this.state.point) return this.showPoint(null);
    return undefined;
  }

  bindEvents() {
    if (this.bound) return;
    this.bound = true;
    this.gd.on("plotly_click", (data) => {
      if (!data.points || !data.points.length) return;
      this.action("plot-click", describePoint(data.points[0]), data.event);
    });
    this.gd.on("plotly_relayout", (event) => this.recordOwnerAxes(event));
    this.gd.on("plotly_selected", (data) => {
      if (!data || !data.points) return;
      const points = data.points.slice(0, MAX_SELECTED_POINTS).map(describePoint);
      this.action("plot-select", {points, total: data.points.length});
    });
  }

  // Plotly 4 syncs the ticks of an overlaying axis with the axis below it, which
  // crowds a linear secondary axis against the gridlines of a log one. Unless the
  // agent chose a tick mode, a secondary axis keeps its own ticks.
  ownTicks(layout) {
    const result = {...layout};
    for (const [name, axis] of Object.entries(layout)) {
      if (!/^[xy]axis\d+$/.test(name) || !axis || axis.tickmode !== undefined) continue;
      result[name] = {...axis, tickmode: "auto"};
    }
    return result;
  }

  // ---- PLT-05: the owner's axes ----------------------------------------------------

  // Forget the owner's axis changes when the agent starts a new revision.
  keepOwnerAxes(revision) {
    if (!this.state.axisView || (this.state.seen && this.state.revision !== revision)) {
      this.state.axisView = {};
    }
    this.state.seen = true;
    this.state.revision = revision;
  }

  // The layout with the axes as the owner left them (bar or zoom).
  withOwnerAxes(layout) {
    if (!this.axesOn) return layout;
    const result = {...layout};
    for (const [name, view] of Object.entries(this.state.axisView)) {
      const axis = {...result[name], ...view};
      if (view.autorange) delete axis.range;
      result[name] = axis;
    }
    return result;
  }

  // Note which axes the owner changed through the bar, the mouse or the mode bar.
  recordOwnerAxes(event) {
    if (!this.axesOn) return;
    const changed = {};
    for (const key of Object.keys(event)) {
      const match = /^([xy]axis\d*)\.(range|autorange|type)/.exec(key);
      if (match) (changed[match[1]] = changed[match[1]] || new Set()).add(match[2]);
    }
    for (const [name, fields] of Object.entries(changed)) {
      const axis = this.gd._fullLayout[name];
      if (!axis) continue;
      const before = this.state.axisView[name] || {};
      const view = axis.autorange
        ? {autorange: axis.autorange}
        : {autorange: false, range: axis.range.slice()};
      if (fields.has("type")) view.type = axis.type;
      else if (before.type) view.type = before.type;
      this.state.axisView[name] = view;
    }
    this.syncBar(this._wrapper);
  }

  // ---- PLT-04, PLT-06: the axis bar -----------------------------------------------

  syncBar(wrapper) {
    const names = this.axesOn ? this.barAxes() : [];
    if (!names.length) {
      if (this.bar) this.bar.remove();
      this.barKey = null;
      return;
    }
    const key = names.map((name) => `${name}:${this.gd._fullLayout[name].type}`).join();
    if (!this.bar) this.bar = h("div", {class: "axis-bar"});
    if (key !== this.barKey) {
      this.barKey = key;
      this.bar.replaceChildren(...names.map((name) => this.axisGroup(name)),
        h("span", {class: "axis-note", role: "status", hidden: true}));
    }
    if (this.bar.parentNode !== wrapper) wrapper.appendChild(this.bar);
    this.updateBar(names);
  }

  // The axes that get controls: shown, not slaved to another axis, at most six.
  barAxes() {
    const layout = this.gd._fullLayout;
    return axisNames(layout).filter((name) => {
      const axis = layout[name];
      return axis && axis.visible !== false && !axis.matches;
    }).slice(0, MAX_AXIS_GROUPS);
  }

  axisGroup(name) {
    const axis = this.gd._fullLayout[name];
    const label = axisLabel(name);
    const relayout = (update) => window.Plotly.relayout(this.gd, update);
    const scale = (type) => h("button", {
      type: "button", class: `axis-${type === "linear" ? "lin" : "log"}`,
      onclick: () => this.setAxisType(name, type),
    }, type === "linear" ? "lin" : "log");
    const field = (side) => h("input", {
      class: `axis-${side}`, type: "text", inputmode: "decimal", spellcheck: "false",
      "aria-label": `${label} ${side}imum`, title: `${label} ${side}imum`,
      onchange: () => this.applyRange(name),
    });
    const auto = h("button", {
      type: "button", class: "axis-auto", title: `Autoscale ${label}`,
      onclick: () => relayout({[`${name}.autorange`]: true}),
    }, "auto");
    const numeric = axis.type === "linear" || axis.type === "log";
    return h("div", {class: "axis-group", "data-axis": label},
      h("span", {class: "axis-name"}, label),
      numeric ? h("span", {class: "axis-scale"}, scale("linear"), scale("log")) : null,
      numeric ? field("min") : null,
      numeric ? h("span", {class: "axis-dash", "aria-hidden": "true"}, "\u2013") : null,
      numeric ? field("max") : null,
      auto);
  }

  updateBar(names) {
    const layout = this.gd._fullLayout;
    const focused = this.shadowRoot.activeElement;
    const notes = [];
    for (const name of names) {
      const axis = layout[name];
      const group = this.bar.querySelector(`[data-axis="${axisLabel(name)}"]`);
      const press = (selector, on) => {
        const button = group.querySelector(selector);
        if (button) button.setAttribute("aria-pressed", String(on));
      };
      press(".axis-lin", axis.type === "linear");
      press(".axis-log", axis.type === "log");
      const [low, high] = (axis.range || []).map((v) => (axis.type === "log" ? 10 ** v : v));
      for (const [selector, value] of [[".axis-min", low], [".axis-max", high]]) {
        const input = group.querySelector(selector);
        if (!input || input === focused || value === undefined) continue;
        input.value = formatValue(value);
        input.removeAttribute("aria-invalid");
      }
      const hidden = axis.type === "log" ? hiddenByLog(this.gd, name) : 0;
      if (hidden) {
        notes.push(`${axisLabel(name)}: ${hidden} value${hidden === 1 ? "" : "s"} at or below 0 `
          + "cannot be shown on a log axis");
      }
    }
    const note = this.bar.querySelector(".axis-note");
    note.textContent = notes.join("; ");
    note.hidden = !notes.length;
  }

  // Lin/log: the range of the other scale means nothing here, so start from autoscale.
  setAxisType(name, type) {
    if (this.gd._fullLayout[name].type === type) return;
    window.Plotly.relayout(this.gd, {[`${name}.type`]: type, [`${name}.autorange`]: true});
  }

  // Apply the two inputs of an axis; a value that does not fit is marked.
  applyRange(name) {
    const axis = this.gd._fullLayout[name];
    const group = this.bar.querySelector(`[data-axis="${axisLabel(name)}"]`);
    const inputs = [group.querySelector(".axis-min"), group.querySelector(".axis-max")];
    const log = axis.type === "log";
    const toAxis = (v) => (log ? Math.log10(v) : v);
    const range = inputs.map((input, i) => {
      const text = input.value.trim().replace(",", ".");
      if (text === "") return axis.range[i];
      const value = Number(text);
      return Number.isFinite(value) && (!log || value > 0) ? toAxis(value) : NaN;
    });
    const fits = range.every(Number.isFinite) && range[0] !== range[1];
    inputs.forEach((input) => (fits ? input.removeAttribute("aria-invalid")
      : input.setAttribute("aria-invalid", "true")));
    if (fits) window.Plotly.relayout(this.gd, {[`${name}.range`]: range});
  }

  // ---- BLK-09 ----------------------------------------------------------------------

  // Redraw from the changed file; Plotly keeps the zoom if the figure sets a
  // `uirevision`, and the block element and its nodes stay.
  reloadSource() {
    if (this._wrapper && !this._wrapper.isError) {
      this.render(this._config, this._wrapper).catch((error) => this.showError(error.message));
    } else {
      super.reloadSource();
    }
  }

  // ---- pixels to data (R-10) ---------------------------------------------------------------------

  /**
   * Convert a box in frame-viewport pixels, ``[x, y, width, height]``, to data
   * ranges of the first x and y axes; null if it misses the plot area or the
   * axes are not numeric.
   */
  dataBbox(box) {
    const layout = this.gd && this.gd._fullLayout;
    const xa = layout && layout.xaxis;
    const ya = layout && layout.yaxis;
    if (!xa || !ya || !xa.p2d || !ya.p2d) return null;
    const rect = this.gd.getBoundingClientRect();
    const clamp = (v, length) => Math.min(Math.max(v, 0), length);
    const x0 = clamp(box[0] - rect.left - xa._offset, xa._length);
    const x1 = clamp(box[0] + box[2] - rect.left - xa._offset, xa._length);
    const y0 = clamp(box[1] - rect.top - ya._offset, ya._length);
    const y1 = clamp(box[1] + box[3] - rect.top - ya._offset, ya._length);
    if (x0 === x1 || y0 === y1) return null;
    const x = [xa.p2d(x0), xa.p2d(x1)].sort((a, b) => a - b);
    const y = [ya.p2d(y0), ya.p2d(y1)].sort((a, b) => a - b);
    if (![...x, ...y].every((v) => typeof v === "number" && Number.isFinite(v))) return null;
    const round = (v) => Number(v.toPrecision(6));
    return {x: x.map(round), y: y.map(round)};
  }

  /**
   * Convert a point in frame-viewport pixels to data coordinates of the first
   * x and y axes (log axes give data values); null outside the plot area or
   * on axes that are not numeric.
   */
  dataPoint(x, y) {
    const layout = this.gd && this.gd._fullLayout;
    const xa = layout && layout.xaxis;
    const ya = layout && layout.yaxis;
    if (!xa || !ya || !xa.p2d || !ya.p2d) return null;
    const rect = this.gd.getBoundingClientRect();
    const px = x - rect.left - xa._offset;
    const py = y - rect.top - ya._offset;
    if (px < 0 || px > xa._length || py < 0 || py > ya._length) return null;
    const values = [xa.p2d(px), ya.p2d(py)];
    if (!values.every((v) => typeof v === "number" && Number.isFinite(v))) return null;
    return {x: Number(values[0].toPrecision(6)), y: Number(values[1].toPrecision(6))};
  }

  // ---- BLK-06 ----------------------------------------------------------------------

  /** The plot as an image, for screenshots (Plotly also draws WebGL traces). */
  async snapshot() {
    // The figure may be narrower than the block (fixed layout width).
    const {width, height} = this.gd._fullLayout;
    const {left, top} = this.gd.getBoundingClientRect();
    const url = await window.Plotly.toImage(this.gd, {format: "png", width, height, scale: 1});
    return {image: await loadImage(url), rect: {left, top, width, height}};
  }
}
