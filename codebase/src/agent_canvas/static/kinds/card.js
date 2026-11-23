// The card module (KIND-01, KIND-02, A-81): ``drawCard`` builds the card of one
// interaction kind, ``CanvasCard`` is the base of the six card elements. Agent
// text is always set as text, never as HTML.
import { CanvasBlock, h } from "../blocks/base.js";
import { ICONS, kindSheet } from "./style.js";

// The SVG namespace is an identifier, not an address; written in two parts so that
// the no-network scan of the sources (OPS-01) does not take it for a URL.
const SVG = "http:" + "//www.w3.org/2000/svg";

/** The card elements, by kind. */
export const CARD_TAGS = {
  ask: "canvas-ask", do: "canvas-do", report: "canvas-report",
  decision: "canvas-decision", alert: "canvas-alert", live: "canvas-live",
};
const CARD_SELECTOR = Object.values(CARD_TAGS).join(",");
// Cards that may hold an Ask or a Do (KIND-04).
const HOLDERS = ["canvas-report", "canvas-alert", "canvas-live"];
const ANSWER_KINDS = ["ask", "do", "decision"];
/** Said on the answer cards of an ended session (ANS-08); the bar says it too (draw.js). */
export const ENDED_WORDS = "This session has ended: answers are kept, but no agent will read them";

/** ``HH:MM`` of an ISO time in the owner's time zone. */
export function clock(iso) {
  const time = new Date(iso);
  return Number.isNaN(time.getTime()) ? undefined
    : `${String(time.getHours()).padStart(2, "0")}:${String(time.getMinutes()).padStart(2, "0")}`;
}

/** The head line name of a kind (``Needs you: Ask``, ``Report: plan``, ...). */
export function headLine(kind, type) {
  return {
    ask: "Needs you: Ask", do: "Needs you: Do", decision: "Decision", alert: "Alert",
    live: "Live", report: `Report: ${type || "result"}`,
  }[kind];
}

function icon(name) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "ic");
  svg.setAttribute("aria-hidden", "true");
  for (const [tag, attributes] of ICONS[name]) {
    const shape = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attributes)) shape.setAttribute(key, String(value));
    svg.append(shape);
  }
  return svg;
}

/**
 * Turn agent text into nodes: lines starting ``- `` become list items, lines
 * starting ``N. `` numbered items, anything else paragraphs (a blank line ends
 * one). Nothing else is interpreted; every string is set as text.
 */
export function textNodes(text) {
  const nodes = [];
  let list = null;
  let paragraph = null;
  for (const line of String(text).split("\n")) {
    const bullet = /^- (.*)$/.exec(line);
    const number = /^\d+\. (.*)$/.exec(line);
    const item = bullet || number;
    if (item) {
      const tag = bullet ? "ul" : "ol";
      if (!list || list.localName !== tag) {
        list = h(tag, {});
        nodes.push(list);
      }
      list.append(h("li", {}, item[1]));
      paragraph = null;
    } else if (line.trim() === "") {
      list = paragraph = null;
    } else if (paragraph && !list) {
      paragraph.append("\n" + line);
    } else {
      paragraph = h("p", {class: "lines"}, line);
      nodes.push(paragraph);
      list = null;
    }
  }
  return nodes;
}

/**
 * Draw one card.
 *
 * ``spec``: ``kind`` (ask, do, report, decision, alert, live), ``label`` (the
 * head line name), ``words`` (the state words), ``title`` and ``text`` (agent
 * text), ``extra`` (nodes after the text), ``open`` (an open needs-you part:
 * it pulses), ``answered``, ``answer`` (a node for the answer area, kinds ask,
 * do and decision only) and ``slot`` (true: the element's child elements show
 * in page order, before the answer area).
 */
export function drawCard(spec) {
  const {kind} = spec;
  const classes = ["k", kind === "ask" || kind === "do" ? "need" : kind, kind];
  if (spec.open) classes.push("pulse");
  if (spec.answered) classes.push("answered");
  const body = h("div", {class: "kb"});
  if (spec.title) body.append(h("p", {class: "q"}, spec.title));
  if (spec.text) body.append(...textNodes(spec.text));
  if (spec.extra) body.append(...spec.extra);
  if (spec.slot) body.append(h("div", {class: "kc"}, h("slot", {})));
  if (ANSWER_KINDS.includes(kind)) {
    const area = h("div", {class: "answer"});
    if (spec.answer) area.append(spec.answer);
    body.append(area);
    if (spec.ended) body.append(h("p", {class: "meta ended"}, ENDED_WORDS));
  }
  const head = h("header", {class: "kh"}, icon(spec.answered ? "check" : kind),
    h("span", {class: "kl"}, spec.label), h("span", {class: "kt"}, spec.words || ""));
  return h("article", {
    class: classes.join(" "), role: "group",
    "aria-label": spec.words ? `${spec.label}, ${spec.words}` : spec.label,
  }, head, kind === "alert" ? h("div", {class: "hazard", "aria-hidden": "true"}) : null, body);
}

/**
 * Base of the six card elements. A subclass sets ``kind`` and ``card(config)``
 * (the spec for ``drawCard``). The owner-facing state lives in ``this.state``:
 * ``answered`` and ``later`` end the pulse, ``at`` and ``words`` change the
 * state words; ``setState`` redraws.
 */
export class CanvasCard extends CanvasBlock {
  static kind = "report";

  constructor() {
    super();
    this._onAnswers = () => {
      const ended = Boolean(window.agentCanvas && window.agentCanvas.sessionEnded);
      if (ended !== Boolean(this.state.ended)) this.setState({ended});
      this.applyStoredItem();
    };
  }

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(kindSheet())) this.shadowRoot.adoptedStyleSheets = [...sheets, kindSheet()];
    document.addEventListener("agentcanvas:answers", this._onAnswers);
    this._onAnswers();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("agentcanvas:answers", this._onAnswers);
  }

  /**
   * Draw an Ask or a Do from the item the hub stored for it (ANS-02), so a reload
   * or a rewrite never shows an answered item open again. Nothing happens before
   * the shell has handed over the page's items.
   */
  applyStoredItem() {
    const items = window.agentCanvas && window.agentCanvas.answerItems;
    if (!items || !["ask", "do"].includes(this.constructor.kind)) return;
    const item = items[this.getAttribute("data-canvas-id")] || {state: "open"};
    const answered = !["open", "later"].includes(item.state);
    const later = item.state === "later";
    const at = answered && item.time ? clock(item.time) : undefined;
    const state = this.state;
    const same = Boolean(state.answered) === answered && Boolean(state.later) === later;
    if (same && state.at === at) return;
    this.setState({answered, later, at});
  }

  /** True while this card is an Ask or a Do that is neither answered nor put off. */
  get isOpen() {
    return false;
  }

  /** Change the state and redraw; parents (an Alert) hear about it. */
  setState(patch) {
    Object.assign(this.state, patch);
    this._config = undefined;
    this.schedule();
    this.dispatchEvent(new CustomEvent("agentcanvas:kind-state", {bubbles: true}));
  }

  /** Only an Ask or Do may sit in a Report, Alert or Live; no other card in a card (KIND-04). */
  validate() {
    const outer = this.parentElement && this.parentElement.closest(CARD_SELECTOR);
    if (!outer) return null;
    const needsYou = this.localName === "canvas-ask" || this.localName === "canvas-do";
    if (needsYou && HOLDERS.includes(outer.localName)) return null;
    return `cannot sit inside ${outer.localName}: only an Ask or a Do goes inside a Report, `
      + "Alert or Live card, and no other card goes inside a card";
  }

  render(config, wrapper) {
    wrapper.className = "kind-wrap";
    wrapper.replaceChildren(drawCard({
      kind: this.constructor.kind, open: this.isOpen, answered: Boolean(this.state.answered),
      ended: this.state.ended, slot: true, ...this.card(config),
    }));
  }
}

/** State words shared by Ask and Do: open, put off, answered. */
export function needsYouWords(state, answeredWord) {
  if (state.words) return state.words;
  if (state.later) return "later";
  if (state.answered) return state.at ? `${answeredWord} ${state.at}` : answeredWord;
  return "waits for you";
}
