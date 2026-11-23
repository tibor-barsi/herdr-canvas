// canvas-progress: a rewrite updates the existing nodes (BLK-04). For long jobs it also
// shows start and expected end, the last lines of a log file of the session folder
// (BLK-09) and a Stop button that asks first (CNT-07). All nodes exist from the first
// draw and are only hidden or filled, so a rewrite never adds or removes one.
import { clock } from "../kinds/card.js";
import { CanvasBlock, h } from "./base.js";

const LOG_LINES = 5;
const SENT_MS = 1000;

// Change the text in place: the text node itself stays (no flicker).
function setText(node, text) {
  if (node.firstChild) node.firstChild.data = text;
  else node.textContent = text;
}

function isTime(value) {
  return value === undefined || !Number.isNaN(new Date(value).getTime());
}

/** The URL of a file of the session folder, or null for anything outside it. */
function sessionFileUrl(path) {
  const url = new URL(path, document.baseURI);
  const folder = new URL(".", document.baseURI);
  return url.origin === folder.origin && url.pathname.startsWith(folder.pathname) ? url : null;
}

/** ``HH:MM``, with the date in front when it is not today. */
function when(iso) {
  const time = new Date(iso);
  const day = time.toDateString() === new Date().toDateString()
    ? "" : `${time.getMonth() + 1}-${String(time.getDate()).padStart(2, "0")} `;
  return day + clock(iso);
}

export class CanvasProgress extends CanvasBlock {
  static inPlace = true;
  static schema = {
    value: "number!", max: "number", label: "string",
    status: "running|done|failed", detail: "string",
    started: "string", eta: "string", log: "string", stop: "boolean",
  };

  validate(config) {
    if (config.max !== undefined && config.max <= 0) return '"max" must be above 0';
    if (!isTime(config.started) || !isTime(config.eta)) {
      return '"started" and "eta" must be ISO times';
    }
    if (config.log !== undefined && !sessionFileUrl(config.log)) {
      return '"log" must be a file in the session folder';
    }
    return null;
  }

  render(config, wrapper) {
    if (!wrapper.firstChild) this.build(wrapper);
    const max = config.max === undefined ? 1 : config.max;
    const percent = Math.round(Math.min(Math.max(config.value / max, 0), 1) * 100);
    const status = config.status || "running";
    wrapper.className = `block status-${status}`;
    setText(this.labelNode, config.label || "");
    setText(this.percentNode, `${percent}%`);
    this.track.setAttribute("aria-valuenow", String(config.value));
    this.track.setAttribute("aria-valuemax", String(max));
    this.track.setAttribute("aria-label", config.label || "Progress");
    this.fill.style.width = `${percent}%`;
    setText(this.detailNode, config.detail || "");
    this.detailNode.hidden = !config.detail;
    const times = [];
    if (config.started) times.push(`Started ${when(config.started)}`);
    if (config.eta) times.push(`expected end ${when(config.eta)}`);
    setText(this.timesNode, times.join(" · "));
    this.timesNode.hidden = times.length === 0;
    this.logNode.hidden = config.log === undefined;
    this.stopRow.hidden = !(config.stop && status === "running");
    if (this.stopRow.hidden) this.confirmNode.hidden = true;
    if (config.log !== undefined && config.log !== this.logPath) this.loadLog(config.log);
    this.logPath = config.log;
  }

  build(wrapper) {
    this.labelNode = h("span", {class: "label-text"});
    this.percentNode = h("span", {class: "percent"});
    this.fill = h("div", {class: "fill"});
    this.track = h("div", {class: "track", role: "progressbar", "aria-valuemin": "0"}, this.fill);
    this.detailNode = h("div", {class: "detail"});
    this.timesNode = h("div", {class: "detail"});
    this.logText = h("pre", {class: "log-text"});
    this.logNode = h("details", {class: "log"}, h("summary", {}, "Log"), this.logText);
    this.stopButton = h("button", {type: "button", class: "danger", onclick: () => {
      this.confirmNode.hidden = false;
    }}, "Stop");
    this.confirmNode = h("span", {class: "confirm", role: "alertdialog", "aria-label": "Stop the run?"},
      h("span", {}, "Stop the run?"),
      h("button", {type: "button", class: "danger", onclick: () => this.sendStop()}, "Yes, stop"),
      h("button", {type: "button", onclick: () => { this.confirmNode.hidden = true; }}, "Keep running"));
    this.confirmNode.hidden = true;
    this.stopRow = h("div", {class: "actions"}, this.stopButton, this.confirmNode);
    wrapper.append(h("div", {class: "head"}, this.labelNode, this.percentNode), this.track,
      this.detailNode, this.timesNode, this.logNode, this.stopRow);
  }

  sendStop() {
    this.confirmNode.hidden = true;
    this.event("button", "stop");
    this.stopButton.textContent = "Stop sent";
    clearTimeout(this.sentTimer);
    this.sentTimer = setTimeout(() => { this.stopButton.textContent = "Stop"; }, SENT_MS);
  }

  /** Show the last lines of the log; the file is read from the session folder only. */
  async loadLog(path) {
    const url = sessionFileUrl(path);
    const token = (this.logToken = (this.logToken || 0) + 1);
    let text;
    try {
      const response = await fetch(url, {cache: "no-store"});
      text = response.ok ? await response.text() : `could not read ${path} (${response.status})`;
    } catch (error) {
      text = `could not read ${path}`;
    }
    if (token !== this.logToken) return;
    setText(this.logText, text.trimEnd().split("\n").slice(-LOG_LINES).join("\n"));
  }

  fileChanged(path) {
    const log = this._config && this._config.log;
    if (typeof log !== "string" || typeof path !== "string") return;
    const url = sessionFileUrl(log);
    if (url && decodeURIComponent(url.pathname).endsWith("/" + path)) this.loadLog(log);
  }
}
