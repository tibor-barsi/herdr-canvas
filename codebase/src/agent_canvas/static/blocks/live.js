// canvas-live: a card whose content updates in place (KIND-01, KIND-08). It reads its age
// ("updated 2 min ago"), redrawn each minute without a push, and turns stale after
// `stale_after` seconds. Its icon blinks (A-104); its children are plain content.
import { CanvasCard, clock, headLine } from "../kinds/card.js";

const REFRESH_MS = 60000;
const DEFAULT_STALE_AFTER = 600;
const CSS = `
.k.live.stale { background: var(--ac-subtle); border-color: var(--ac-border); }
.k.live.stale > .kh { background: var(--ac-muted); }
.k.live.stale > .kh .ic { animation: none; opacity: .6; }
.k.live.stale > .kh .kt { font-weight: 700; }
`;
let sheetObject = null;

function liveSheet() {
  if (!sheetObject) {
    sheetObject = new CSSStyleSheet();
    sheetObject.replaceSync(CSS);
  }
  return sheetObject;
}

/** The age of ``seconds`` in the largest whole unit. */
function ageText(seconds) {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

export class CanvasLive extends CanvasCard {
  static kind = "live";
  static schema = {title: "string!", text: "string", updated: "string", stale_after: "number"};

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(liveSheet())) this.shadowRoot.adoptedStyleSheets = [...sheets, liveSheet()];
    this._timer = setInterval(() => {
      if (!this._config || !this._config.updated) return;
      this._config = undefined;
      this.schedule();
    }, REFRESH_MS);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._timer);
  }

  validate(config) {
    if (config.updated !== undefined && Number.isNaN(new Date(config.updated).getTime())) {
      return '"updated" must be an ISO time';
    }
    if (config.stale_after !== undefined && config.stale_after <= 0) {
      return '"stale_after" must be above 0';
    }
    return super.validate(config);
  }

  /** ``{words, stale}``: the state words for the age of ``updated``. */
  freshness(config) {
    if (!config.updated) return {words: "updating", stale: false};
    const updated = new Date(config.updated).getTime();
    const limit = (config.stale_after || DEFAULT_STALE_AFTER) * 1000;
    const age = Date.now() - updated;
    if (age > limit) {
      return {words: `stale since ${clock(new Date(updated + limit).toISOString())}`, stale: true};
    }
    return {words: `updated ${ageText(age / 1000)}`, stale: false};
  }

  render(config, wrapper) {
    super.render(config, wrapper);
    wrapper.firstChild.classList.toggle("stale", this.freshness(config).stale);
  }

  card(config) {
    return {
      label: headLine("live"), words: this.freshness(config).words,
      title: config.title, text: config.text,
    };
  }
}
