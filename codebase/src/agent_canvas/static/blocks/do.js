// canvas-do: instructions for the owner (DO-01 to DO-04). Numbered steps, each `run`
// in a box with Copy (the shell copies, text from the page file, DO-02), a tick per
// step (stored, no event), and Done, Problem... and Later.
import { deepEqual, h } from "./base.js";
import { CanvasCard, clock, headLine, needsYouWords } from "../kinds/card.js";

const MAX_STEPS = 20;
const MAX_NOTE = 4000;
const SECRET_HINT = "Type this in your terminal yourself; do not paste the output here.";
const SECRET_WARNING = "This looks like a secret (a key or token). The agent reads what you send here.";
const LOOKS_SECRET = /-----BEGIN |\bsk-|ghp_|AKIA|[A-Za-z0-9]{32,}/;

const DO_CSS = `
.steps { margin: 0; padding-left: 1.6rem; }
.steps li + li { margin-top: 8px; }
.tick { display: inline-flex; gap: 8px; align-items: flex-start; cursor: pointer; }
.tick input { width: auto; margin-top: 4px; flex: none; }
.cmd { display: flex; gap: 8px; align-items: flex-start; margin-top: 4px; padding: 6px 8px;
  background: #1f2328; color: #e6edf3; border-radius: 6px; }
.cmd code { flex: 1; min-width: 0; white-space: pre-wrap; word-break: break-all;
  font: .82rem/1.45 ui-monospace, Menlo, Consolas, monospace; }
.cmd button { flex: none; padding: 0 8px; font-size: .8rem; color: #e6edf3;
  background: transparent; border-color: #8b949e; }
.hint { margin-top: 4px; padding-left: 8px; font-size: 12.8px; font-weight: 600;
  border-left: 3px solid var(--ac-warn); }
.step-note { margin-top: 3px; color: var(--ac-muted); font-size: 12.8px; }
.risks { margin: 2px 0 6px; padding-left: 1.3rem; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.row.end { justify-content: flex-end; }
.problem textarea { min-height: 6em; }
.problem .warn { padding-left: 8px; font-weight: 600; border-left: 3px solid var(--ac-warn); }
.problem .bad { font-weight: 600; border-left: 3px solid var(--ac-danger); padding-left: 8px; }
.receipt { color: var(--ac-muted); font-size: 12.8px; }
`;

let doSheet = null;

function stepsOf(config) {
  if (config.steps) return config.steps;
  return config.run === undefined ? [] : [{text: "", run: config.run}];
}

export class CanvasDo extends CanvasCard {
  static kind = "do";
  static schema = {
    title: "string!", why: "string", where: "string", time: "string", risk: "array",
    steps: "array", run: "string",
  };

  connectedCallback() {
    super.connectedCallback();
    if (!doSheet) {
      doSheet = new CSSStyleSheet();
      doSheet.replaceSync(DO_CSS);
    }
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(doSheet)) this.shadowRoot.adoptedStyleSheets = [...sheets, doSheet];
  }

  get isOpen() {
    return !this.state.answered && !this.state.later;
  }

  /** The hub's stored item of this Do: ``state``, ``time``, ``read``, ``ticked``. */
  get item() {
    const items = window.agentCanvas && window.agentCanvas.answerItems;
    return (items && items[this.getAttribute("data-canvas-id")]) || {state: "open"};
  }

  applyStoredItem() {
    super.applyStoredItem();
    const item = this.item;
    const seen = JSON.stringify([item.state, item.time, item.read,
      this.state.ticks === undefined ? item.ticked : null]);
    if (seen === this._seen) return;
    this._seen = seen;
    this.setState({});
  }

  validate(config) {
    const outer = super.validate();
    if (outer) return outer;
    if (config.steps !== undefined) {
      if (config.steps.length < 1 || config.steps.length > MAX_STEPS) {
        return `steps must hold 1 to ${MAX_STEPS} steps`;
      }
      for (const step of config.steps) {
        if (!step || typeof step.text !== "string") return "every step needs a string `text`";
        for (const key of ["run", "expect", "if_not"]) {
          if (step[key] !== undefined && typeof step[key] !== "string") return `step ${key} must be a string`;
        }
        if (step.secret !== undefined && typeof step.secret !== "boolean") return "step secret must be true or false";
      }
    }
    if (config.risk && !config.risk.every((r) => typeof r === "string")) return "risk must list strings";
    if (stepsOf(config).some((s) => s.run !== undefined) && !config.where) {
      return "a `run` needs `where` (the machine and folder to run it in)";
    }
    return null;
  }

  render(config, wrapper) {
    const identity = [config.title, config.steps, config.run];
    if (this._identity && !deepEqual(this._identity, identity)) {
      Object.assign(this.state, {ticks: undefined, problemOpen: false, draft: "", warned: false});
    }
    this._identity = identity;
    super.render(config, wrapper);
  }

  card(config) {
    const item = this.item;
    return {
      label: headLine("do"), words: needsYouWords(this.state, item.state === "problem" ? "problem reported" : "done"),
      title: config.title, text: config.why, extra: [this.meta(config), this.stepList(config)].filter(Boolean),
      answer: this.answerArea(config, item),
    };
  }

  meta(config) {
    const line = [config.where && `Where: ${config.where}`, config.time && `Time: ${config.time}`]
      .filter(Boolean).join(" · ");
    const risks = config.risk && config.risk.length
      ? h("div", {class: "meta"}, "Risks", h("ul", {class: "risks"}, ...config.risk.map((r) => h("li", {}, r)))) : null;
    return h("div", {}, line ? h("p", {class: "meta"}, line) : null, risks);
  }

  get ticks() {
    return this.state.ticks || this.item.ticked || [];
  }

  stepList(config) {
    const steps = stepsOf(config);
    if (!steps.length) return null;
    return h("ol", {class: "steps"}, ...steps.map((step, index) => {
      const number = index + 1;
      const box = h("input", {type: "checkbox", "aria-label": `Step ${number} done`});
      box.checked = this.ticks.includes(number);
      box.addEventListener("change", () => this.toggle(number, box.checked));
      const label = h("label", {class: "tick"}, box, h("span", {}, step.text));
      return h("li", {},
        step.text ? label : h("span", {}, box),
        step.secret ? h("p", {class: "hint"}, SECRET_HINT) : null,
        step.run !== undefined ? this.runBox(step.run, number) : null,
        step.expect ? h("p", {class: "step-note"}, `Expect: ${step.expect}`) : null,
        step.if_not ? h("p", {class: "step-note"}, `If not: ${step.if_not}`) : null);
    }));
  }

  runBox(run, number) {
    const copy = h("button", {type: "button", "aria-label": `Copy step ${number}`}, "Copy");
    copy.addEventListener("click", () => window.agentCanvas.copy(this, number));
    return h("div", {class: "cmd"}, h("code", {}, run), copy);
  }

  toggle(number, on) {
    const ticks = new Set(this.ticks);
    if (on) ticks.add(number); else ticks.delete(number);
    this.state.ticks = [...ticks].sort((a, b) => a - b);
    window.agentCanvas.tick(this, this.state.ticks);
  }

  send(status, note) {
    const value = {status, ticked: this.ticks};
    if (note !== undefined) value.note = note;
    window.agentCanvas.answer(this, value);
    Object.assign(this.state, {problemOpen: false, draft: "", warned: false, reopened: false});
  }

  redraw(focus) {
    this.setState({});
    if (focus) this.whenRendered().then(() => this.shadowRoot.querySelector(focus)?.focus());
  }

  answerArea(config, item) {
    const closed = ["done", "problem"].includes(item.state) && !this.state.reopened;
    if (closed) return this.receipt(item);
    if (this.state.problemOpen) return this.problemForm();
    const problem = h("button", {type: "button"}, "Problem…");
    problem.addEventListener("click", () => {
      this.state.problemOpen = true;
      this.redraw("textarea");
    });
    const later = h("button", {type: "button"}, "Later");
    later.addEventListener("click", () => this.send("later"));
    const done = h("button", {type: "button", class: "primary"}, "Done");
    done.addEventListener("click", () => this.send("done"));
    return h("div", {class: "row end"}, problem, item.state === "later" ? null : later, done);
  }

  receipt(item) {
    const said = item.state === "done" ? "You pressed Done." : "You reported a problem.";
    const read = item.read ? `read by the agent ${clock(item.read)}` : "not read by the agent yet";
    const reopen = h("button", {type: "button"}, "Reopen");
    reopen.addEventListener("click", () => {
      this.state.reopened = true;
      this.redraw();
    });
    return h("div", {}, h("p", {}, said), h("p", {class: "receipt"}, read),
      item.state === "done" ? h("div", {class: "row end"}, reopen) : null);
  }

  problemForm() {
    const field = h("textarea", {"aria-label": "What went wrong", placeholder: "What went wrong?"});
    field.value = this.state.draft || "";
    const message = h("p", {role: "status"});
    const send = h("button", {type: "button", class: "primary"}, this.state.warned ? "Send anyway" : "Send");
    if (this.state.warned) message.append(h("span", {class: "warn"}, SECRET_WARNING));
    field.addEventListener("input", () => {
      this.state.draft = field.value;
      if (this.state.warned) {
        this.state.warned = false;
        send.textContent = "Send";
        message.replaceChildren();
      }
    });
    send.addEventListener("click", () => {
      const note = field.value.trim();
      this.state.draft = field.value;
      if (!note || note.length > MAX_NOTE) {
        message.replaceChildren(h("span", {class: "bad"},
          note ? `At most ${MAX_NOTE} characters.` : "Say what went wrong first."));
      } else if (LOOKS_SECRET.test(note) && !this.state.warned) {
        this.state.warned = true;
        this.redraw("textarea");
      } else {
        this.send("problem", note);
      }
    });
    const cancel = h("button", {type: "button"}, "Cancel");
    cancel.addEventListener("click", () => {
      this.state.problemOpen = false;
      this.state.warned = false;
      this.redraw();
    });
    return h("div", {class: "problem"}, field, message, h("div", {class: "row end"}, cancel, send));
  }
}
