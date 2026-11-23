// canvas-choices: pick one or several options; select -> `select` action,
// submit -> `choice` event with the option ids. With a submit button the block then shows
// the answered line and read receipt from the hub's store, like an Ask card (ANS-01, #19).
import { CanvasBlock, deepEqual, h } from "./base.js";
import { ENDED_WORDS, clock } from "../kinds/card.js";
import { answerSheet } from "../kinds/answer-area.js";

export class CanvasChoices extends CanvasBlock {
  static schema = {mode: "single|multi", options: "array!", submit: "string"};

  validate(config) {
    const ids = new Set();
    for (const option of config.options) {
      if (!option || typeof option.id !== "string" || typeof option.title !== "string") {
        return "every option needs a string id and title";
      }
      if (ids.has(option.id)) return `duplicate option id "${option.id}"`;
      ids.add(option.id);
    }
    return null;
  }

  constructor() {
    super();
    this._onAnswers = () => this.applyStoredItem();
  }

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(answerSheet())) this.shadowRoot.adoptedStyleSheets = [...sheets, answerSheet()];
    document.addEventListener("agentcanvas:answers", this._onAnswers);
    this.applyStoredItem();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("agentcanvas:answers", this._onAnswers);
  }

  /** Take the stored answer of this block (ANS-01) and redraw when it changed. */
  applyStoredItem() {
    const items = window.agentCanvas && window.agentCanvas.answerItems;
    if (!items) return;
    const stored = items[this.getAttribute("data-canvas-id")];
    const item = stored && stored.state === "answered" ? stored : undefined;
    const previous = this.state.item;
    const ended = window.agentCanvas.sessionEnded === true; // ANS-08
    if (deepEqual(item, previous) && ended === this.state.ended) return;
    this.state.item = item;
    this.state.ended = ended;
    if (!previous || !item || previous.time !== item.time) this.state.editing = false;
    this._config = undefined;
    this.schedule();
  }

  answeredLine(config, wrapper) {
    const {item} = this.state;
    const titles = new Map(config.options.map((o) => [o.id, o.title]));
    const said = (Array.isArray(item.value) ? item.value : []).map((id) => titles.get(id) || id).join(", ");
    const receipt = item.read
      ? `read by the agent ${clock(item.read) || ""}`.trim() : "not read by the agent yet";
    const at = clock(item.time);
    wrapper.replaceChildren(h("div", {class: "line"},
      h("span", {class: "said"}, `Sent${at ? " " + at : ""}${said ? ": " + said : ""}`),
      h("span", {class: "receipt"}, receipt),
      h("button", {type: "button", class: "link", onclick: () => this.change(item)}, "Change")),
    ...this.endedLine());
  }

  /** On an ended session, an Options box that sends says no agent will read it (ANS-08). */
  endedLine() {
    return this.state.ended ? [h("div", {class: "receipt ended"}, ENDED_WORDS)] : [];
  }

  change(item) {
    this.state.selected = Array.isArray(item.value) ? item.value : [];
    this.state.editing = true;
    this._config = undefined;
    this.schedule();
  }

  render(config, wrapper) {
    if (typeof config.submit === "string" && this.state.item && !this.state.editing) {
      this.answeredLine(config, wrapper);
      return;
    }
    const multi = config.mode === "multi";
    const known = new Set(config.options.map((o) => o.id));
    // Keep the selection that still exists after the options changed (BLK-03).
    let selected = (this.state.selected || []).filter((id) => known.has(id));
    if (!multi) selected = selected.slice(0, 1);
    this.state.selected = selected;

    const buttons = config.options.map((option) => h("button", {
      type: "button", class: "option", role: multi ? "checkbox" : "radio",
      "aria-checked": selected.includes(option.id), "data-id": option.id,
      onclick: (event) => this.pick(option.id, multi, event),
    },
    option.image ? h("img", {src: option.image, alt: option.title}) : null,
    h("span", {class: "title"}, option.title),
    option.description ? h("span", {class: "muted"}, option.description) : null));
    this.optionButtons = buttons;
    this.submitButton = typeof config.submit === "string"
      ? h("button", {type: "button", class: "submit", onclick: () => this.submit()}, config.submit)
      : null;
    this.sync();
    wrapper.replaceChildren(
      h("div", {class: "options", role: multi ? "group" : "radiogroup"}, ...buttons),
      ...(this.submitButton ? [h("div", {class: "actions"}, this.submitButton), ...this.endedLine()] : []),
    );
  }

  pick(id, multi, event) {
    const current = this.state.selected;
    if (!multi) this.state.selected = [id];
    else this.state.selected = current.includes(id)
      ? current.filter((x) => x !== id) : [...current, id];
    this.sync();
    this.action("select", this.orderedSelection(), event);
  }

  orderedSelection() {
    return this.optionButtons.map((b) => b.dataset.id).filter((id) => this.state.selected.includes(id));
  }

  sync() {
    for (const button of this.optionButtons) {
      button.setAttribute("aria-checked", String(this.state.selected.includes(button.dataset.id)));
    }
    if (this.submitButton) this.submitButton.disabled = this.state.selected.length === 0;
  }

  submit() {
    if (this.state.selected.length) this.event("choice", this.orderedSelection());
  }
}
