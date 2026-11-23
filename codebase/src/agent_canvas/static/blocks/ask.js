// canvas-ask: one question to the owner with one answer (ASK-01 to ASK-04). The
// owner's answer goes to the hub through the shell; the card draws itself from the
// stored item, so an answered Ask shows its line after every reload (ANS-02).
import { CanvasCard, clock, headLine, needsYouWords } from "../kinds/card.js";
import { answerSheet, approveArea, reasonRow } from "../kinds/answer-area.js";
import { deepEqual, h } from "./base.js";

const FORMS = ["yesno", "one", "several", "text", "number", "confirm", "approve", "point", "fields"];
const KEYS = ["question", "context", "form", "options", "recommended", "min", "max", "unit", "step", "default",
  "fields", "submit"];
// The blocks a point Ask takes the click of: tag -> [action kind, what to click].
const POINT_CHILDREN = {
  "canvas-plot": ["plot-click", "a point on the plot"], "canvas-image": ["image-click", "a spot on the picture"],
  "canvas-model": ["model-mark", "a spot on the model"], "canvas-scene": ["scene-mark", "a spot on the 3D view"],
};
const FIELD_TYPES = ["number", "one", "onoff", "text"];
const MAX_FIELDS = 12;
const MAX_QUESTION = 300;
const MAX_CONTEXT = 1000;
const MAX_TEXT = 4000;
const SENDING_MS = 4000;

const formOf = (config) => config.form || (config.options ? "one" : "text");

/** The options as ``{id, label, description?, image?}``, the recommended one first. */
function optionsOf(config) {
  const all = (config.options || []).map((o) => (typeof o === "string" ? {id: o, label: o}
    : {...o, label: o.label === undefined ? o.id : o.label}));
  const at = all.findIndex((o) => o.id === config.recommended);
  if (at > 0) all.unshift(...all.splice(at, 1));
  return all;
}

function withUnit(config, value) {
  return config.unit ? `${value} ${config.unit}` : String(value);
}

/** The limits of a number as the reason text, or null without limits. */
function limitText(config) {
  const {min, max} = config;
  if (min !== undefined && max !== undefined) return `between ${min} and ${max}${config.unit ? " " + config.unit : ""}`;
  if (min !== undefined) return `at least ${withUnit(config, min)}`;
  if (max !== undefined) return `at most ${withUnit(config, max)}`;
  return null;
}

/** Why a field's draft value is not valid, or null. */
function fieldProblem(field, raw) {
  if (field.type !== "number") return null;
  const text = String(raw).trim();
  const value = Number(text);
  if (text === "" || !Number.isFinite(value)) return limitText(field) || "enter a number";
  const out = (field.min !== undefined && value < field.min) || (field.max !== undefined && value > field.max);
  return out ? limitText(field) : null;
}

const VALUE_TYPES = {number: "number", one: "string", onoff: "boolean", text: "string"};

/** Why the ``fields`` list of a parameter form is invalid (ASK-06), or null. */
function fieldsProblem(fields) {
  if (!Array.isArray(fields) || fields.length < 1 || fields.length > MAX_FIELDS) {
    return `form "fields" needs 1 to ${MAX_FIELDS} fields`;
  }
  const ids = new Set();
  for (const field of fields) {
    if (!field || typeof field.id !== "string" || !field.id || typeof field.label !== "string") {
      return "every field needs a string id and a string label";
    }
    if (ids.has(field.id)) return `duplicate field id "${field.id}"`;
    ids.add(field.id);
    if (!FIELD_TYPES.includes(field.type)) return `field "${field.id}": type must be ${FIELD_TYPES.join(", ")}`;
    if (typeof field.value !== VALUE_TYPES[field.type]) {
      return `field "${field.id}": value must be a ${VALUE_TYPES[field.type]}`;
    }
    if (field.type === "one" && !(Array.isArray(field.options) && field.options.includes(field.value)
      && field.options.every((o) => typeof o === "string"))) {
      return `field "${field.id}": options must be strings and include the value`;
    }
  }
  return null;
}

const rawValue =(field, value) => (field.type === "number" ? String(value) : value);
const fieldValue = (field, raw) => (field.type === "number" ? Number(raw) : raw);

/** The ids of the fields whose draft differs from the value the agent gave. */
const changedFields = (config, draft) => config.fields
  .filter((f) => fieldValue(f, draft.values[f.id]) !== f.value).map((f) => f.id);

/** Why the draft cannot be sent yet, or null. ``child`` is a point Ask's block. */
function problemOf(config, draft, child) {
  const form = formOf(config);
  if (form === "point") return draft.point ? null : `click ${POINT_CHILDREN[child.localName][1]}`;
  if (form === "fields") {
    for (const field of config.fields) {
      const problem = fieldProblem(field, draft.values[field.id]);
      if (problem) return `${field.label}: ${problem}`;
    }
    return null;
  }
  if (form === "text") return draft.text.trim() ? null : "type an answer";
  if (form === "number") {
    const text = draft.number.trim();
    const value = Number(text);
    if (text === "" || !Number.isFinite(value)) return limitText(config) || "enter a number";
    const low = config.min !== undefined && value < config.min;
    return low || (config.max !== undefined && value > config.max) ? limitText(config) : null;
  }
  const other = draft.otherOn;
  if (other && !draft.other.trim()) return "type your other answer";
  if (form === "one" && !draft.picked.length && !other) return "pick an option";
  if (form === "several" && !draft.picked.length && !other) return "pick at least one option";
  return null;
}

/** The default as words: option labels for option ids, the unit for numbers. */
function defaultWords(config) {
  const labels = new Map(optionsOf(config).map((o) => [o.id, o.label]));
  const one = (d) => (labels.has(d) ? labels.get(d) : typeof d === "number" ? withUnit(config, d) : String(d));
  return [].concat(config.default).map(one).join(", ");
}

/** A clicked point as words, whatever block gave it. */
function pointWords(point) {
  if (Array.isArray(point.point)) {
    return `${point.part ? point.part + " " : ""}surface point (${point.point.join(", ")})`;
  }
  if ("trace" in point) return `trace ${point.trace}, point ${point.index} (x ${point.x}, y ${point.y})`;
  return `picture pixel (${point.x}, ${point.y})`;
}

/** The answer of a parameter form as words: the changed fields, or "no change". */
function fieldsWords(config, answer) {
  const fields = new Map(config.fields.map((f) => [f.id, f]));
  const shown = (id) => {
    const field = fields.get(id);
    const value = answer.values[id];
    const text = field && field.type === "onoff" ? (value ? "on" : "off") : String(value);
    return `${field ? field.label : id} ${field && field.unit ? text + " " + field.unit : text}`;
  };
  return answer.changed.length ? `changed ${answer.changed.map(shown).join(", ")}` : "no change";
}

/** The stored value as the answered line's text. */
function summary(config, value) {
  if (!value) return "";
  const labels = new Map(optionsOf(config).map((o) => [o.id, o.label]));
  const {answer, other, note} = value;
  let text;
  if (formOf(config) === "point") text = pointWords(answer);
  else if (formOf(config) === "fields") text = fieldsWords(config, answer);
  else if (Array.isArray(answer)) {
    text = answer.map((id) => (labels.has(id) ? labels.get(id) : id)).join(", ");
    if (other) text += (text ? ", " : "") + `Other: ${other}`;
  } else if (typeof answer === "number") text = withUnit(config, answer);
  else if (answer && typeof answer === "object" && answer.decision) {
    text = answer.decision === "approved" ? "approved" : `sent back: ${answer.reason}`;
  } else if (answer && typeof answer === "object") text = `change: ${answer.change}`;
  else text = String(answer);
  return note ? `${text} · note: ${note}` : text;
}

/** The draft of an answer already given, for Change. */
function draftOf(config, value) {
  const draft = freshDraft(config);
  const answer = value ? value.answer : undefined;
  if (!value) return draft;
  if (formOf(config) === "point") draft.point = answer;
  else if (formOf(config) === "fields") {
    for (const field of config.fields) draft.values[field.id] = rawValue(field, answer.values[field.id]);
  } else if (Array.isArray(answer)) draft.picked = answer;
  if (typeof answer === "string") draft.text = answer;
  if (typeof answer === "number") draft.number = String(answer);
  draft.otherOn = Boolean(value.other);
  draft.other = value.other || "";
  draft.note = value.note || "";
  draft.noteOpen = Boolean(value.note);
  return draft;
}

function freshDraft(config) {
  const given = config.default === undefined ? [] : [].concat(config.default);
  const known = new Set(optionsOf(config).map((o) => o.id));
  const form = formOf(config);
  return {
    picked: given.filter((d) => known.has(d)).slice(0, form === "one" ? 1 : 8),
    otherOn: false, other: "",
    text: form === "text" && config.default !== undefined ? String(config.default) : "",
    number: form === "number" && config.default !== undefined ? String(config.default) : "",
    note: "", noteOpen: false, point: undefined,
    values: Object.fromEntries((config.fields || []).map((f) => [f.id, rawValue(f, f.value)])),
    base: JSON.stringify(config.fields),
  };
}

export class CanvasAsk extends CanvasCard {
  static kind = "ask";
  static schema = {
    question: "string!", context: "string", form: FORMS.join("|"), options: "array",
    recommended: "string", min: "number", max: "number", unit: "string", step: "number",
    fields: "array", submit: "string",
  };

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(answerSheet())) this.shadowRoot.adoptedStyleSheets = [...sheets, answerSheet()];
  }

  get isOpen() {
    return !this.state.answered;
  }

  validate(config) {
    const outer = super.validate(config);
    if (outer) return outer;
    const unknown = Object.keys(config).find((key) => !KEYS.includes(key));
    if (unknown) return `unknown config key "${unknown}"`;
    if (config.question.length > MAX_QUESTION) return `question is longer than ${MAX_QUESTION} characters`;
    if (config.context && config.context.length > MAX_CONTEXT) return `context is longer than ${MAX_CONTEXT} characters`;
    const form = formOf(config);
    const options = config.options || [];
    const ids = new Set();
    for (const option of options) {
      const id = typeof option === "string" ? option : option && option.id;
      if (typeof id !== "string" || !id) return "every option is a string or an object with a string id";
      if (ids.has(id)) return `duplicate option id "${id}"`;
      ids.add(id);
    }
    if (["one", "several"].includes(form) && (options.length < 2 || options.length > 8)) {
      return `form "${form}" needs 2 to 8 options, not ${options.length}`;
    }
    if (config.recommended !== undefined && !ids.has(config.recommended)) {
      return `recommended "${config.recommended}" is not one of the options`;
    }
    if (config.min !== undefined && config.max !== undefined && config.min > config.max) {
      return "min is larger than max";
    }
    if (config.fields !== undefined && form !== "fields") return 'fields belongs to form "fields"';
    if (form === "fields") return fieldsProblem(config.fields);
    if (form === "point" && !this.pointChild()) {
      return 'form "point" needs one child block: canvas-plot, canvas-image, canvas-model or canvas-scene';
    }
    return null;
  }

  /** The one block a point Ask takes the click of, or undefined. */
  pointChild() {
    const blocks = [...this.children].filter((child) => child.localName !== "script");
    return blocks.length === 1 && POINT_CHILDREN[blocks[0].localName] ? blocks[0] : undefined;
  }

  /**
   * The config an answer says it saw: this one, and for a point Ask the data of the block
   * pointed at as it was when the owner pointed, so the hub refuses a point made on data
   * that changed since (M31 F7).
   */
  seenConfig() {
    const child = this.pointChild();
    if (!child || formOf(this._config) !== "point") return this._config;
    const {draft} = this.state;
    return {...this._config, _child: draft && draft.childSeen ? draft.childSeen : child.readConfig()};
  }

  /** True while ``child`` is the block of an open point Ask (its click is the answer). */
  pointsAt(child) {
    return Boolean(this._config) && formOf(this._config) === "point"
      && (!this.state.answered || this.state.editing) && child === this.pointChild();
  }

  /**
   * Take the child's click as the answer. Returns true when taken, so the block
   * records no action of its own; a click of another kind or an Ask that is not
   * open for pointing is left to the block.
   */
  takePoint(child, kind, value) {
    if (!this.pointsAt(child) || POINT_CHILDREN[child.localName][0] !== kind) return false;
    const draft = this.state.draft || (this.state.draft = freshDraft(this._config));
    draft.point = value;
    draft.childSeen = child.readConfig();
    child.showPoint(value);
    if (this.sync) this.sync();
    return true;
  }

  /** Draw from the stored item: answered, its value and its receipt (ASK-04). */
  applyStoredItem() {
    const items = window.agentCanvas && window.agentCanvas.answerItems;
    if (!items) return;
    const stored = items[this.getAttribute("data-canvas-id")];
    const item = stored && stored.state === "answered" ? stored : undefined;
    const previous = this.state.item;
    if (deepEqual(item, previous)) return;
    const patch = {item, answered: Boolean(item), at: item && item.time ? clock(item.time) : undefined};
    if (!previous || !item || previous.time !== item.time) {
      Object.assign(patch, {editing: false, sending: false, draft: undefined});
    }
    this.setState(patch);
  }

  card(config) {
    const settled = this.state.answered && !this.state.editing;
    const open = !this.state.answered;
    const waits = open && config.default !== undefined
      ? `goes on with ${defaultWords(config)} unless you change it` : needsYouWords(this.state, "answered");
    const spec = {
      label: headLine("ask"), words: waits, title: config.question,
      text: settled ? undefined : config.context, answered: settled,
      slot: !settled || formOf(config) === "point", // a pointed-at block stays, with its mark
      answer: settled ? this.answeredLine(config) : this.form(config),
    };
    if (formOf(config) === "point") {
      const stored = this.state.item && this.state.item.value;
      this.markPoint(settled ? stored && stored.answer : this.state.draft.point);
    }
    return spec;
  }

  /** Show (or remove) the owner's point on the block once it has drawn itself. */
  markPoint(point) {
    const child = this.pointChild();
    child.whenRendered().then(() => (point ? child.showPoint(point) : child.hidePoint()));
  }

  answeredLine(config) {
    const {item, at} = this.state;
    const said = item ? summary(config, item.value) : "";
    const receipt = !item ? null : item.read
      ? `read by the agent ${clock(item.read) || ""}`.trim() : "not read by the agent yet";
    return h("div", {class: "line"},
      h("span", {class: "said"}, `Answered${at ? " " + at : ""}${said ? ": " + said : ""}`),
      receipt ? h("span", {class: "receipt"}, receipt) : null,
      h("button", {type: "button", class: "link", onclick: () => this.change(config)}, "Change"));
  }

  change(config) {
    const item = this.state.item;
    this.setState({editing: true, draft: draftOf(config, item && item.value)});
  }

  get draft() {
    return this.state.draft;
  }

  /** Send the one Answer; a second press before the hub replies sends nothing. */
  send(answer, other = null) {
    if (this.state.sending) return;
    this.state.sending = true;
    setTimeout(() => {
      this.state.sending = false;
      if (this.sync) this.sync();
    }, SENDING_MS);
    const note = this.draft.note.trim();
    window.agentCanvas.answer(this, {answer, other, note: note || null});
    if (this.sync) this.sync();
  }

  form(config) {
    const form = formOf(config);
    const stale = form === "fields" && this.state.draft && this.state.draft.base !== JSON.stringify(config.fields);
    if (!this.state.draft || stale) this.state.draft = freshDraft(config);
    const draft = this.draft;
    const previous = this.state.editing && this.state.item ? this.state.item.value : undefined;
    const answered = previous ? previous.answer : undefined;
    const syncs = [];
    this.sync = () => syncs.forEach((fn) => fn());

    const noteBox = h("div", {class: "note-box"});
    const drawNote = () => {
      if (!draft.noteOpen) {
        noteBox.replaceChildren(h("button", {type: "button", class: "link",
          onclick: () => { draft.noteOpen = true; drawNote(); }}, "Add a note"));
        return;
      }
      const field = h("textarea", {"aria-label": "Note", maxlength: MAX_TEXT, rows: 2});
      field.value = draft.note;
      field.addEventListener("input", () => { draft.note = field.value; });
      noteBox.replaceChildren(field);
    };
    drawNote();

    const area = h("div", {class: "answer-form"});
    const parts = [];
    const pressed = (button, on) => {
      if (on) button.classList.add("current");
      return button;
    };
    const quick = (label, answer, on) => {
      const button = h("button", {type: "button", onclick: () => this.send(answer)}, label);
      syncs.push(() => { button.disabled = Boolean(this.state.sending); });
      return pressed(button, on);
    };

    if (form === "yesno") {
      parts.push(h("div", {class: "row"}, quick("Yes", "yes", answered === "yes"), quick("No", "no", answered === "no")));
    } else if (form === "approve") {
      parts.push(approveArea((value) => this.send(value), answered && answered.decision));
    } else if (form === "confirm") {
      const row = h("div", {class: "row"});
      const buttons = () => row.replaceChildren(quick("Keep", "keep", answered === "keep"),
        pressed(h("button", {type: "button", onclick: ask}, "Change…"), answered && answered.change));
      const ask = () => row.replaceChildren(reasonRow({
        label: "What should change?", send: "Send", onSend: (text) => this.send({change: text}), onCancel: buttons,
      }));
      buttons();
      parts.push(row);
    } else {
      parts.push(this.input(form, config, draft, syncs));
    }
    parts.push(noteBox);
    area.replaceChildren(...parts);
    if (this.state.editing) {
      area.append(h("button", {type: "button", class: "link", onclick: () => this.setState({editing: false, draft: undefined})}, "Cancel"));
    }
    this.sync();
    return area;
  }

  /** The forms with one Answer button: ``one``, ``several``, ``text``, ``number``, ``point`` and ``fields``. */
  input(form, config, draft, syncs) {
    const child = this.pointChild();
    const answer = h("button", {type: "button", class: "submit", onclick: () => {
      if (problemOf(config, draft, child)) return;
      this.send(this.answerOf(form, config, draft), draft.otherOn ? draft.other.trim() : null);
    }}, form === "fields" && config.submit ? config.submit : "Answer");
    const reason = h("span", {class: "reason", role: "status"});
    syncs.push(() => {
      const problem = problemOf(config, draft, child);
      answer.disabled = Boolean(problem) || Boolean(this.state.sending);
      answer.title = problem || "";
      reason.textContent = problem || "";
    });
    const refresh = () => this.sync();
    let control;
    if (form === "text") {
      control = h("textarea", {"aria-label": "Your answer", maxlength: MAX_TEXT, rows: 3});
      control.value = draft.text;
      control.addEventListener("input", () => { draft.text = control.value; refresh(); });
    } else if (form === "number") {
      const field = h("input", {type: "number", class: "num", "aria-label": "Your answer",
        min: config.min, max: config.max, step: config.step});
      field.value = draft.number;
      field.addEventListener("input", () => { draft.number = field.value; refresh(); });
      control = config.unit ? h("div", {class: "row"}, field, h("span", {class: "meta"}, config.unit)) : field;
    } else if (form === "point") {
      control = h("div", {class: "point-line meta"});
      syncs.push(() => {
        control.textContent = draft.point ? `Your point: ${pointWords(draft.point)}` : `Click ${POINT_CHILDREN[child.localName][1]}.`;
      });
    } else if (form === "fields") {
      control = this.fieldList(config, draft, syncs);
    } else {
      control = this.optionList(form, config, draft, refresh);
    }
    return h("div", {class: "answer-input"}, control, h("div", {class: "row"}, answer, reason));
  }

  answerOf(form, config, draft) {
    if (form === "text") return draft.text.trim();
    if (form === "number") return Number(draft.number);
    if (form === "point") return draft.point;
    if (form === "fields") {
      const values = Object.fromEntries(config.fields.map((f) => [f.id, fieldValue(f, draft.values[f.id])]));
      return {values, changed: changedFields(config, draft)};
    }
    return optionsOf(config).map((o) => o.id).filter((id) => draft.picked.includes(id));
  }

  /** The labelled rows of a parameter form; a changed field shows "changed (was ...)". */
  fieldList(config, draft, syncs) {
    const list = h("div", {class: "fields"});
    config.fields.forEach((field, index) => {
      const name = `field-${index}`;
      const set = (raw) => { draft.values[field.id] = raw; this.sync(); };
      const was = field.type === "onoff" ? (field.value ? "on" : "off") : withUnit(field, field.value);
      let control;
      if (field.type === "one") {
        control = h("select", {id: name}, ...field.options.map((o) => h("option", {value: o}, o)));
        control.value = draft.values[field.id];
        control.addEventListener("change", () => set(control.value));
      } else if (field.type === "onoff") {
        control = h("input", {id: name, type: "checkbox"});
        control.checked = draft.values[field.id];
        control.addEventListener("change", () => set(control.checked));
      } else {
        control = h("input", {id: name, type: field.type === "number" ? "number" : "text", class: "num",
          min: field.min, max: field.max, step: "any", maxlength: MAX_TEXT});
        control.value = draft.values[field.id];
        control.addEventListener("input", () => set(control.value));
      }
      const tag = h("span", {class: "changed-tag"}, `changed (was ${was})`);
      const row = h("div", {class: "field", "data-field": field.id},
        h("label", {for: name}, field.label), h("span", {class: "row"}, control,
          field.unit && field.type === "number" ? h("span", {class: "meta"}, field.unit) : null), tag);
      syncs.push(() => {
        const changed = changedFields(config, draft).includes(field.id);
        row.classList.toggle("changed", changed);
        tag.hidden = !changed;
      });
      list.append(row);
    });
    return list;
  }

  optionList(form, config, draft, refresh) {
    const multi = form === "several";
    const list = h("div", {class: "opts", role: multi ? "group" : "radiogroup"});
    const otherInput = h("input", {type: "text", "aria-label": "Other answer", placeholder: "Other…", maxlength: MAX_TEXT});
    otherInput.value = draft.other;
    otherInput.addEventListener("input", () => { draft.other = otherInput.value; refresh(); });
    const buttons = [];
    const mark = () => {
      for (const [button, id] of buttons) {
        const on = id === null ? draft.otherOn : draft.picked.includes(id);
        button.setAttribute("aria-checked", String(on));
      }
      otherInput.hidden = !draft.otherOn;
      refresh();
    };
    const option = (id, content) => {
      const button = h("button", {type: "button", class: "opt", role: multi ? "checkbox" : "radio",
        "data-id": id === null ? "other" : id, onclick: () => {
          if (id === null) {
            draft.otherOn = !draft.otherOn || !multi;
            if (!multi && draft.otherOn) draft.picked = [];
            if (draft.otherOn) queueMicrotask(() => otherInput.focus());
          } else if (multi) {
            draft.picked = draft.picked.includes(id) ? draft.picked.filter((x) => x !== id) : [...draft.picked, id];
          } else {
            draft.picked = [id];
            draft.otherOn = false;
          }
          mark();
        }}, h("span", {class: "mark"}), ...content);
      buttons.push([button, id]);
      return button;
    };
    for (const o of optionsOf(config)) {
      const first = o.id === config.recommended;
      list.append(option(o.id, [
        o.image ? h("img", {src: new URL(o.image, document.baseURI).href, alt: ""}) : null,
        h("span", {class: "what"}, h("span", {}, o.label),
          o.description ? h("span", {class: "meta"}, o.description) : null),
        first ? h("span", {class: "tag"}, "recommended") : null,
      ]));
    }
    list.append(option(null, [h("span", {}, "Other…")]), otherInput);
    mark();
    return list;
  }
}
