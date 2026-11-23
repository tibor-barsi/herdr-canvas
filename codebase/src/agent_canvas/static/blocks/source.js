// canvas-source: a claim with the line that says where it comes from (CNT-04). The source
// line is plain text with Copy (through the shell, DO-02); a link in it is shown, never
// made clickable, so it cannot navigate. The status is a word with a mark, `quote` is
// folded, and "Doubt this..." sends the owner's one-line reason as a `text` event.
import { CanvasBlock, h } from "./base.js";

const MAX_SOURCE = 500;
const MAX_REASON = 300;
const STATUSES = {
  verified: {mark: "✓", colour: "var(--ac-ok)"},
  "not checked": {mark: "?", colour: "var(--ac-muted)"},
  disputed: {mark: "✗", colour: "var(--ac-danger)"},
};

const CSS = `
.src-claim { font-weight: 600; overflow-wrap: anywhere; }
.src-status { display: inline-flex; gap: 6px; align-items: center; margin-top: 4px;
  font-weight: 600; font-size: 12.8px; }
.src-mark { display: inline-grid; place-items: center; width: 1.4em; height: 1.4em;
  border: 1.5px solid currentColor; border-radius: 50%; }
.src-line { display: flex; gap: 8px; align-items: flex-start; margin-top: 6px; }
.src-text { flex: 1 1 auto; min-width: 0; color: var(--ac-muted); font-size: 12.8px;
  overflow-wrap: anywhere; white-space: pre-wrap; }
.src-line button, .src-doubt button { padding: 2px 10px; }
.src-quote { margin-top: 6px; font-size: 12.8px; }
.src-quote blockquote { margin: 4px 0 0; padding-left: 10px; border-left: 3px solid var(--ac-border);
  white-space: pre-wrap; overflow-wrap: anywhere; }
.src-doubt { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; }
.src-doubt input { flex: 1 1 14em; width: auto; }
`;
const ownSheet = new CSSStyleSheet();
ownSheet.replaceSync(CSS);

export class CanvasSource extends CanvasBlock {
  static schema = {claim: "string!", source: "string!", status: "verified|not checked|disputed", quote: "string"};

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(ownSheet)) this.shadowRoot.adoptedStyleSheets = [...sheets, ownSheet];
  }

  validate(config) {
    if (config.source.length > MAX_SOURCE) return `"source" is longer than ${MAX_SOURCE} characters`;
    return null;
  }

  render(config, wrapper) {
    if (this.state.claim !== config.claim) this.state = {claim: config.claim, doubt: "closed", reason: ""};
    const status = STATUSES[config.status || "not checked"];
    const word = config.status || "not checked";
    const line = h("div", {class: "src-line"},
      h("span", {class: "src-text"}, config.source),
      h("button", {
        type: "button", "aria-label": "Copy source",
        onclick: () => window.agentCanvas.copyText("source", config.source),
      }, "Copy"));
    const mark = h("span", {class: "src-status"},
      h("span", {class: "src-mark", "aria-hidden": "true"}, status.mark), word);
    mark.style.color = status.colour;
    wrapper.replaceChildren(
      h("div", {class: "src-claim"}, config.claim), mark, line,
      config.quote ? h("details", {class: "src-quote"}, h("summary", {}, "Quote"),
        h("blockquote", {}, config.quote)) : null,
      this.doubtArea());
  }

  doubtArea() {
    const redraw = () => this.reloadSource();
    if (this.state.doubt === "sent") {
      return h("p", {class: "src-doubt", role: "status"}, `Doubt sent: ${this.state.reason}`);
    }
    if (this.state.doubt === "closed") {
      return h("div", {class: "src-doubt"}, h("button", {
        type: "button",
        onclick: () => { this.state.doubt = "open"; redraw(); this.whenRendered().then(() => this.focusField()); },
      }, "Doubt this…"));
    }
    const field = h("input", {
      type: "text", maxlength: MAX_REASON, placeholder: "Why do you doubt it?", "aria-label": "Why do you doubt it",
    });
    field.value = this.state.reason;
    const send = h("button", {type: "button", class: "primary"}, "Send");
    const sync = () => { send.disabled = field.value.trim() === ""; };
    const submit = () => {
      const reason = field.value.trim();
      if (!reason) return;
      this.event("text", reason);
      Object.assign(this.state, {doubt: "sent", reason});
      redraw();
    };
    field.addEventListener("input", () => { this.state.reason = field.value; sync(); });
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); submit(); }
    });
    send.addEventListener("click", submit);
    const cancel = h("button", {type: "button", onclick: () => { Object.assign(this.state, {doubt: "closed", reason: ""}); redraw(); }}, "Cancel");
    sync();
    return h("div", {class: "src-doubt"}, field, send, cancel);
  }

  focusField() {
    const field = this.shadowRoot.querySelector(".src-doubt input");
    if (field) field.focus();
  }
}
