// canvas-decision: a decision the owner may change (KIND-01, KIND-07). "Change…" opens a
// one-line field; Enter sends the reason as a `change` event. The line that follows is
// drawn from the hub's store, so it survives a reload (ANS-01).
import { CanvasCard, clock, headLine } from "../kinds/card.js";
import { deepEqual, h } from "./base.js";

const MAX_REASON = 300;
const CSS = `
.change-line { font-weight: 600; overflow-wrap: anywhere; }
.receipt { color: var(--ac-muted); font-size: 12.8px; }
.change-field { display: flex; gap: 8px; }
.change-field input { flex: 1; min-width: 0; }
`;
let sheetObject = null;

function decisionSheet() {
  if (!sheetObject) {
    sheetObject = new CSSStyleSheet();
    sheetObject.replaceSync(CSS);
  }
  return sheetObject;
}

export class CanvasDecision extends CanvasCard {
  static kind = "decision";
  static schema = {text: "string!", why: "string", ref: "string", date: "string"};

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(decisionSheet())) this.shadowRoot.adoptedStyleSheets = [...sheets, decisionSheet()];
  }

  /** Take the stored change of this decision (ANS-01), if there is one. */
  applyStoredItem() {
    const items = window.agentCanvas && window.agentCanvas.answerItems;
    if (!items) return;
    const item = items[this.getAttribute("data-canvas-id")];
    const change = item && item.state === "changed"
      ? {reason: item.value.reason, time: item.time, read: item.read} : undefined;
    if (deepEqual(change, this.state.change)) return;
    const previous = this.state.change;
    const sent = !change || !previous || change.time !== previous.time;
    this.setState({change, editing: sent ? false : this.state.editing});
  }

  openField() {
    this.setState({editing: true});
    this.whenRendered().then(() => {
      const field = this.shadowRoot.querySelector("input");
      if (field) field.focus();
    });
  }

  send(field) {
    const reason = field.value.trim();
    if (!reason) return;
    window.agentCanvas.answer(this, {reason});
    this.setState({editing: false, draft: ""});
  }

  answerArea() {
    const {change, editing} = this.state;
    const nodes = [];
    if (change) {
      const read = change.read
        ? `read by the agent ${clock(change.read)}` : "not read by the agent yet";
      nodes.push(
        h("p", {class: "change-line"}, `Change asked ${clock(change.time)}: ${change.reason}`),
        h("p", {class: "receipt"}, read));
    }
    if (!editing) {
      nodes.push(h("div", {class: "actions"},
        h("button", {type: "button", onclick: () => this.openField()}, "Change…")));
      return h("div", {}, ...nodes);
    }
    const field = h("input", {
      type: "text", maxlength: MAX_REASON, "aria-label": "Why change it?",
      placeholder: "What should change, and why?", value: this.state.draft || "",
    });
    field.addEventListener("input", () => { this.state.draft = field.value; });
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.send(field);
      else if (event.key === "Escape") this.setState({editing: false});
    });
    nodes.push(h("div", {class: "change-field"}, field,
      h("button", {type: "button", class: "primary", onclick: () => this.send(field)}, "Send")));
    return h("div", {}, ...nodes);
  }

  card(config) {
    const extra = [];
    if (config.why) {
      extra.push(h("details", {
        class: "why", open: this.state.whyOpen,
        ontoggle: (event) => { this.state.whyOpen = event.target.open; },
      }, h("summary", {}, "Why"), h("p", {}, config.why)));
    }
    const meta = [config.ref, config.date].filter(Boolean).join(" · ");
    if (meta) extra.push(h("p", {class: "meta"}, meta));
    return {
      label: headLine("decision"), words: "you may change it", title: config.text, extra,
      answer: this.answerArea(),
    };
  }
}
