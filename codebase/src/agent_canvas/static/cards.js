// The shell's question, approval and result cards (CLI-04, PLAN-01, PLAN-02, RES-02,
// KIND-05): drawn by the card module (question and approval as an Ask, the result as a
// Report with an Ask part for its decision), inside a shadow root that adopts the same
// stylesheets as a page card. Agent text is set as text, never as HTML.
import { sheet } from "./blocks/style.js";
import { h } from "./blocks/base.js";
import { clock, drawCard, headLine, textNodes } from "./kinds/card.js";
import { answerSheet, approveArea } from "./kinds/answer-area.js";
import { kindSheet } from "./kinds/style.js";

const SHELL_CSS = `
:host { margin: 0; }
.pick { display: inline-flex; align-items: center; gap: 6px; }
.pick input { width: auto; }
.ask-text { flex: 1 1 14em; min-width: 8em; width: auto; }
.hint { color: var(--ac-muted); }
.chips { gap: 6px; }
.chip { padding: 2px 10px; border-radius: 12px; font-size: 13px; }
.kb > .k { --kpad: 12px; }
.result-scroll { max-height: 30vh; overflow: auto; }
`;
let shellSheet = null;
function sheets() {
  if (!shellSheet) {
    shellSheet = new CSSStyleSheet();
    shellSheet.replaceSync(SHELL_CSS);
  }
  return [sheet, kindSheet(), answerSheet(), shellSheet];
}

const cards = new Map();   // ask id -> {el, host, session, decision}
const lines = new Map();   // ask id -> {el, session}: answered approvals (PLAN-02)
const results = new Map(); // session id -> {el, id, state}: the session's result card

function button(label, className, onclick) {
  return h("button", {type: "button", class: className, onclick}, label);
}

/** The answer controls of a question card (CLI-04): choices, multi-pick, text field. */
function questionInputs(ask, answer) {
  const parts = [];
  if (ask.choices.length && !ask.multi) {
    parts.push(h("div", {class: "row"}, ...ask.choices.map(
      (label) => button(label, "ask-choice", () => answer([label])))));
  } else if (ask.choices.length) {
    const boxes = ask.choices.map((label) => h("input", {type: "checkbox", value: label}));
    parts.push(h("div", {class: "row"},
      ...boxes.map((box) => h("label", {class: "pick"}, box, box.value)),
      button("Submit", "ask-submit submit", () => {
        const picked = boxes.filter((b) => b.checked).map((b) => b.value);
        if (picked.length) answer(picked);
      })));
  }
  if (ask.text) {
    const field = h("input", {type: "text", class: "ask-text", "aria-label": "Your answer"});
    const send = () => { if (field.value.trim()) answer(field.value); };
    field.addEventListener("keydown", (event) => { if (event.key === "Enter") send(); });
    parts.push(h("div", {class: "row"}, field, button("Send", "ask-send submit", send)));
  }
  return h("div", {class: "answer-form"}, ...parts);
}

function build(tab, ask, hooks) {
  const entry = {session: tab.id, decision: null};
  const answer = (value) => {
    if (ask.approval) entry.decision = value;
    entry.el.classList.add("sent");
    if (hooks.offline()) {
      entry.el.querySelector(".ask-note").textContent =
        "Not connected: this answer is kept and sent when the hub is back.";
    }
    hooks.answer(tab.id, ask.ask, value);
  };
  let control;
  if (ask.block) control = h("p", {class: "hint ask-hint"}, "Answer in the highlighted element on the page.");
  else if (ask.approval) control = approveArea(answer);
  else control = questionInputs(ask, answer);
  // The question and details stay in the light DOM, slotted into the card, so that the
  // card's text is the page's text (and styled by shell.html).
  const host = h("div", {class: "ask-host"}, h("p", {class: "q"}, ask.question),
    ask.details ? h("div", {class: "details"}, ...textNodes(ask.details)) : null);
  const root = host.attachShadow({mode: "open"});
  root.adoptedStyleSheets = sheets();
  const card = drawCard({
    kind: "ask", label: headLine("ask"), words: "waits for you", slot: true, open: true,
    answer: control,
  });
  // The outer group is named "Question"; the inner name would match a choice's label.
  card.removeAttribute("aria-label");
  card.removeAttribute("role");
  root.append(card);
  // Keys typed in a card are not the shell's shortcuts.
  host.addEventListener("keydown", (event) => event.stopPropagation());
  const dismiss = button("×", "ask-dismiss", () => {
    entry.el.classList.add("sent");
    hooks.dismiss(tab.id, ask.ask);
  });
  dismiss.setAttribute("aria-label", "Dismiss question");
  entry.el = h("section", {class: "ask-card", role: "group", "aria-label": "Question",
    "data-ask": ask.ask, "data-session": tab.id},
  h("div", {class: "ask-row"}, host, dismiss), h("p", {class: "ask-note"}));
  entry.host = host;
  return entry;
}

/** A file chip of the result card: a page of the session opens, any other copies its path. */
function fileChip(tab, file, hooks) {
  const chip = button(file.name, "chip", async () => {
    if (file.page) return hooks.openPage(tab.id, file.page);
    if (!await hooks.copy(file.path)) return undefined;
    chip.textContent = "Copied";
    setTimeout(() => { chip.textContent = file.name; }, 1500);
    return undefined;
  });
  chip.title = file.page ? `Open ${file.name}` : `Copy the path ${file.path}`;
  return chip;
}

/** The result card (RES-02): a Report; its decision is an Ask part that pulses. */
function buildResult(tab, result, hooks) {
  const entry = {session: tab.id, id: result.id, state: result.state};
  const send = (body) => {
    entry.el.classList.add("sent");
    Promise.resolve(hooks.result(tab.id, {result: result.id, ...body})).then((done) => {
      if (!done) entry.el.classList.remove("sent");
    });
  };
  const decided = result.state === "decided";
  const extra = [];
  if (!decided) {
    const [first, ...rest] = result.summary.trim().split("\n");
    const chips = result.files.length
      ? [h("div", {class: "row chips"}, ...result.files.map((f) => fileChip(tab, f, hooks)))] : [];
    extra.push(h("div", {class: "result-scroll"},
      h("p", {class: "q"}, first), ...textNodes(rest.join("\n")), ...chips));
  }
  if (!decided && result.decision) {
    extra.push(drawCard({
      kind: "ask", label: headLine("ask"), words: "decision waiting", open: true,
      title: `One decision left: ${result.decision}`,
      answer: h("div", {class: "row"}, ...result.choices.map(
        (label) => button(label, "ask-choice", () => send({choice: label})))),
    }));
  }
  if (!decided) extra.push(h("div", {class: "row"}, button("Dismiss", "result-dismiss", () => send({dismiss: true}))));
  const card = drawCard({
    kind: "report", label: headLine("report", "result"), words: decided ? "decided" : "from the agent",
    text: decided ? `Decided: ${result.decided}` : null, extra,
  });
  const host = h("div", {class: "ask-host"});
  host.attachShadow({mode: "open"}).adoptedStyleSheets = sheets();
  host.shadowRoot.append(card);
  host.addEventListener("keydown", (event) => event.stopPropagation());
  const close = button("×", "ask-dismiss", () => send({dismiss: true}));
  close.setAttribute("aria-label", "Close the result");
  entry.el = h("section", {class: "result-card", role: "group", "aria-label": "Result",
    "data-result": result.id, "data-session": tab.id},
  h("div", {class: "ask-row"}, host, decided ? close : null));
  return entry;
}

function showLine(id, entry) {
  const {decision} = entry;
  const when = clock(new Date().toISOString());
  const text = decision.decision === "approved" ? `Approved ${when}`
    : `Sent back ${when}: ${decision.reason}`;
  const close = button("×", "ask-dismiss", () => { line.el.remove(); lines.delete(id); });
  close.setAttribute("aria-label", "Close");
  const line = {session: entry.session, el: h("section", {class: "ask-line", role: "status"},
    h("span", {class: "ask-line-text"}, text), close)};
  lines.set(id, line);
}

/**
 * Show the open asks of ``tab`` in ``bar``. Cards are kept between calls so typed text
 * survives; an approval the owner answered turns into a one-line mark that stays until
 * closed or until the session shows its next card (PLAN-02). The session's result card
 * (RES-02) follows the asks. ``hooks``: ``answer(session, ask, value)``, ``dismiss(session,
 * ask)``, ``offline()``, ``result(session, body)``, ``openPage(session, page)``, ``copy(path)``.
 */
function sync(tab, bar, hooks) {
  const asks = tab ? tab.asks || [] : [];
  const wanted = new Set(asks.map((a) => a.ask));
  for (const [id, entry] of Array.from(cards)) {
    if (tab && wanted.has(id) && entry.session === tab.id) continue;
    entry.el.remove();
    cards.delete(id);
    if (entry.decision && !wanted.has(id)) showLine(id, entry);
  }
  for (const ask of asks) {
    if (!cards.has(ask.ask)) {
      for (const [id, line] of Array.from(lines)) {
        if (line.session === tab.id) { line.el.remove(); lines.delete(id); }
      }
      cards.set(ask.ask, build(tab, ask, hooks));
    }
    const entry = cards.get(ask.ask);
    entry.el.classList.remove("sent");
    entry.el.querySelector(".ask-note").textContent = ask.waiting || ask.block ? ""
      : "No agent is waiting for this answer; it will be queued for the agent.";
  }
  syncResult(tab, hooks);
  const shown = [...lines.values()].filter((l) => tab && l.session === tab.id).map((l) => l.el);
  for (const line of lines.values()) if (!shown.includes(line.el)) line.el.remove();
  const resultEls = Array.from(results.values(), (e) => e.el);
  for (const el of [...shown, ...Array.from(cards.values(), (e) => e.el), ...resultEls]) {
    if (el.parentNode !== bar) bar.append(el);
  }
  bar.hidden = bar.children.length === 0;
}

/** Keep the result card of ``tab`` drawn; other sessions' cards go (they come back on a visit). */
function syncResult(tab, hooks) {
  const result = tab ? tab.result : null;
  for (const [session, entry] of Array.from(results)) {
    if (result && session === tab.id && entry.id === result.id && entry.state === result.state) continue;
    entry.el.remove();
    results.delete(session);
  }
  if (result && !results.has(tab.id)) results.set(tab.id, buildResult(tab, result, hooks));
}

/** True while a card holds typed text or a ticked box (SHELL-04). */
function hasTyped() {
  for (const {host} of cards.values()) {
    for (const field of host.shadowRoot.querySelectorAll("input")) {
      if (field.type === "checkbox" ? field.checked : field.value.trim()) return true;
    }
  }
  return false;
}

window.shellCards = {sync, hasTyped};
document.dispatchEvent(new Event("shellcards-ready"));
