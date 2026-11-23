// Answer areas shared by the cards (ASK-02, PLAN-01): the one-line reason field and
// the approval buttons. The Ask element and the shell's approval card (P26.9) both
// draw ``approveArea``, so the approval answer is the same in both places.
import { h } from "../blocks/base.js";

/** Longest reason of a send-back or a change (PLAN-01, A-90). */
export const MAX_REASON = 300;

export const ANSWER_CSS = `
.answer { display: grid; gap: 8px; }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.opts { display: grid; gap: 6px; }
.opt { display: flex; align-items: center; gap: 8px; text-align: left; width: 100%; padding: 7px 10px; }
.opt .mark { width: 16px; height: 16px; flex: none; border: 2px solid var(--ac-muted); border-radius: 50%; }
.opt[role="checkbox"] .mark { border-radius: 3px; }
.opt[aria-checked="true"] { border-color: var(--ac-accent); box-shadow: 0 0 0 1px var(--ac-accent); }
.opt[aria-checked="true"] .mark { background: var(--ac-accent); border-color: var(--ac-accent); }
.opt img { width: 48px; height: 48px; object-fit: cover; border-radius: 4px; }
.opt .what { display: grid; }
.tag { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--ac-fg); border: 1px solid var(--ac-warn); border-radius: 9px; padding: 0 7px; margin-left: auto; }
button.current { border-color: var(--ac-accent); box-shadow: 0 0 0 1px var(--ac-accent); }
button.link { background: none; border: 0; padding: 0; color: var(--ac-accent); text-decoration: underline; }
.num { width: 9em; }
.reason { color: var(--ac-muted); font-size: 12.8px; }
.line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
.fields { display: grid; grid-template-columns: fit-content(36em) auto; justify-content: start; gap: 8px 12px; margin-bottom: 14px; }
.field label { min-width: 14em; }
@media (max-width: 420px) { .fields { grid-template-columns: minmax(0, 1fr); } .field label { min-width: 0; } }
.field .row { justify-self: start; flex-wrap: nowrap; }
.note-box { margin-top: 8px; }
.field { display: grid; grid-template-columns: subgrid; grid-column: 1 / -1; align-items: center; gap: 4px 12px; padding: 4px 8px; border-left: 3px solid transparent; }
.field.changed { border-left-color: var(--ac-accent); background: var(--ac-subtle); }
.changed-tag { grid-column: 1 / -1; width: 0; min-width: 100%; font-size: 12.8px; font-weight: 600; color: var(--ac-fg); }
.point-line { min-height: 1.4em; margin-bottom: 6px; }
.receipt { color: var(--ac-muted); font-size: 12.8px; }
.receipt.ended { margin-top: 8px; }
`;

let answerSheetObject = null;

/** The stylesheet of the answer areas (created on first use). */
export function answerSheet() {
  if (!answerSheetObject) {
    answerSheetObject = new CSSStyleSheet();
    answerSheetObject.replaceSync(ANSWER_CSS);
  }
  return answerSheetObject;
}

/**
 * A one-line required field with Send and Cancel: Enter sends, Esc cancels.
 * ``onSend(text)`` gets the trimmed text; ``onCancel()`` closes the field.
 */
export function reasonRow({label, send, onSend, onCancel}) {
  const input = h("input", {type: "text", maxlength: MAX_REASON, "aria-label": label, placeholder: label});
  const button = h("button", {type: "button", class: "submit", disabled: true,
    onclick: () => onSend(input.value.trim())}, send);
  input.addEventListener("input", () => { button.disabled = input.value.trim() === ""; });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && input.value.trim()) onSend(input.value.trim());
    else if (event.key === "Escape") onCancel();
  });
  const row = h("div", {class: "row"}, input, button,
    h("button", {type: "button", onclick: onCancel}, "Cancel"));
  queueMicrotask(() => input.focus());
  return row;
}

/**
 * The approval answer area: Approve and "Send back…" (PLAN-01). ``send`` gets
 * PLAN-01's value, ``{decision: "approved"}`` or ``{decision: "sent-back", reason}``;
 * ``current`` is the decision already given, shown on its button.
 */
export function approveArea(send, current) {
  const area = h("div", {class: "answer-approve"});
  const buttons = () => {
    const approve = h("button", {type: "button", class: "submit" + (current === "approved" ? " current" : ""),
      onclick: () => send({decision: "approved"})}, "Approve");
    const back = h("button", {type: "button", class: current === "sent-back" ? "current" : "",
      onclick: reason}, "Send back…");
    area.replaceChildren(h("div", {class: "row"}, approve, back));
  };
  const reason = () => area.replaceChildren(reasonRow({
    label: "Reason for sending it back", send: "Send back",
    onSend: (text) => send({decision: "sent-back", reason: text}), onCancel: buttons,
  }));
  buttons();
  return area;
}
