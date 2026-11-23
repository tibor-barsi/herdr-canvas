// canvas-compare: a before and an after picture of the session folder, side by side or one
// over the other with a slider (``mode: "slider"``), each with its label (CNT-06). A verdict
// is asked by putting the block inside an Ask (A-97). Both pictures load before the block
// shows, so ``look`` and the send screenshot see them.
import { CanvasBlock, h } from "./base.js";

const MAX_HEIGHT = 480; // px, as for canvas-image
const START = 50; // slider position in percent

const CSS = `
.cmp-side { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.cmp-side figure { margin: 0; min-width: 0; }
.cmp-side img, .cmp-stage img { display: block; max-width: 100%; max-height: ${MAX_HEIGHT}px; margin: 0 auto; }
.cmp-label { margin-top: 4px; font-weight: 600; font-size: 12.8px; text-align: center; overflow-wrap: anywhere; }
.cmp-stage { position: relative; display: grid; width: fit-content; max-width: 100%; margin: 0 auto;
  line-height: 0; background: var(--ac-subtle); }
.cmp-stage img { grid-area: 1 / 1; }
.cmp-divider { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px;
  background: var(--ac-accent); pointer-events: none; }
.cmp-bar { display: flex; gap: 12px; align-items: center; margin-top: 6px; }
.cmp-bar .cmp-label { margin: 0; flex: 0 0 auto; max-width: 30%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cmp-slider { flex: 1 1 auto; min-width: 80px; padding: 0; accent-color: var(--ac-accent); }
`;
const ownSheet = new CSSStyleSheet();
ownSheet.replaceSync(CSS);

export class CanvasCompare extends CanvasBlock {
  static schema = {
    before: "string!", after: "string!", mode: "side|slider", before_label: "string", after_label: "string",
  };

  constructor() {
    super();
    this.revision = 0;
    this.state = {reveal: START};
  }

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(ownSheet)) this.shadowRoot.adoptedStyleSheets = [...sheets, ownSheet];
  }

  url(src) {
    const url = new URL(src, document.baseURI);
    if (this.revision) url.searchParams.set("r", String(this.revision));
    return url.href;
  }

  picture(src, label) {
    const img = h("img", {alt: label, draggable: "false"});
    img.ready = new Promise((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error(`could not load picture ${src}`));
    });
    img.src = this.url(src);
    return img;
  }

  async render(config, wrapper) {
    const beforeLabel = config.before_label || "Before";
    const afterLabel = config.after_label || "After";
    const before = this.picture(config.before, beforeLabel);
    const after = this.picture(config.after, afterLabel);
    this.pictures = {before, after};
    await Promise.all([before.ready, after.ready]);
    const label = (text) => h("div", {class: "cmp-label"}, text);
    if (config.mode === "slider") {
      wrapper.replaceChildren(...this.sliderView(before, after, label(beforeLabel), label(afterLabel)));
    } else {
      wrapper.replaceChildren(h("div", {class: "cmp-side"},
        h("figure", {}, before, label(beforeLabel)), h("figure", {}, after, label(afterLabel))));
    }
  }

  sliderView(before, after, beforeLabel, afterLabel) {
    const divider = h("div", {class: "cmp-divider"});
    const slider = h("input", {
      type: "range", class: "cmp-slider", min: "0", max: "100", step: "1", "aria-label": "Reveal the after picture",
    });
    const place = () => {
      const value = Number(slider.value);
      this.state.reveal = value;
      after.style.clipPath = `inset(0 ${100 - value}% 0 0)`;
      divider.style.left = `${value}%`;
    };
    slider.value = String(this.state.reveal);
    slider.addEventListener("input", place);
    place();
    return [
      h("div", {class: "cmp-stage"}, before, after, divider),
      h("div", {class: "cmp-bar"}, beforeLabel, slider, afterLabel),
    ];
  }

  // BLK-09: a changed picture file is loaded again into the same elements.
  fileChanged(path) {
    const config = this._config;
    if (!config || !this.pictures || typeof path !== "string") return;
    const names = {before: config.before, after: config.after};
    const touched = Object.entries(names).filter(([, src]) => (
      decodeURIComponent(new URL(src, document.baseURI).pathname).endsWith("/" + path)));
    if (!touched.length) return;
    this.revision += 1;
    for (const [key, src] of touched) this.pictures[key].src = this.url(src);
  }
}
