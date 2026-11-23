// The look of the interaction kinds (KIND-02): variant V2 of the owner's pick
// (D-51), "tinted card with label strip", as one stylesheet text. The page
// cards (shadow roots) and the shell's cards (KIND-05) adopt the same sheet.
// Colours come from the --ac-* palette; the :host rule only supplies the three
// variables the block palette lacks.

export const KIND_CSS = `
:host {
  --ac-bg: #ffffff; --ac-warn: #9a6700; --ac-alt: #6f42c1;
}
@media (prefers-color-scheme: dark) {
  :host { --ac-bg: #14181d; --ac-warn: #e3b341; --ac-alt: #b69cf5; }
}
.kind-wrap { background: none; border: 0; padding: 0; }

/* one colour per kind: needs-you amber, report blue, decision purple, alert red, live green */
.k {
  --kc: var(--ac-accent); --pad: var(--kpad, 14px); --r: 14px; --edge: 1px;
  position: relative; min-width: 0; padding: var(--pad); font-size: 14.7px; line-height: 21px;
  color: var(--ac-fg);
  background: color-mix(in srgb, var(--kc) 9%, var(--ac-surface));
  border: var(--edge) solid color-mix(in srgb, var(--kc) 50%, var(--ac-border));
  border-radius: var(--r);
}
.k.need { --kc: var(--ac-warn); --r: 20px; }
.k.report { --r: 4px; }
.k.decision { --kc: var(--ac-alt); --edge: 2px; border-style: dashed; }
.k.alert { --kc: var(--ac-danger); }
.k.live { --kc: var(--ac-ok); }

/* label strip: solid, with the icon and the kind's name */
.kh {
  display: flex; align-items: center; gap: 8px;
  margin: calc(-1 * var(--pad)) calc(-1 * var(--pad)) 0;
  padding: 7px var(--pad); background: var(--kc); color: var(--ac-bg);
  border-radius: calc(var(--r) - var(--edge)) calc(var(--r) - var(--edge)) 0 0;
}
.k.need > .kh { padding-left: 16px; padding-right: 16px; }
.ic { width: 20px; height: 20px; flex: none; fill: none; stroke: currentColor;
  stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.kl { font-weight: 700; font-size: 12.5px; letter-spacing: .06em; text-transform: uppercase; }
.kt { margin-left: auto; font-size: 12.8px; white-space: nowrap; }

/* Alert: a hazard stripe under the strip (a separate band, so the text sits on solid colour) */
.hazard {
  height: 8px; margin: 0 calc(-1 * var(--pad));
  background: repeating-linear-gradient(-45deg, var(--ac-bg) 0 5px, var(--kc) 5px 10px);
}

.kb { margin-top: 12px; }
.kb > * + * { margin-top: 8px; }
.kb p { margin: 0; }
.kb p + p { margin-top: 6px; }
.q { font-weight: 650; }
.kb ul, .kb ol { margin: 0; padding-left: 1.3rem; }
.kb li + li { margin-top: 5px; }
.lines { white-space: pre-line; }
.meta { color: var(--ac-muted); font-size: 12.8px; }
.why summary { cursor: pointer; font-weight: 600; }
.kc { display: flow-root; }
.kc ::slotted(*) { --kpad: 12px; }
.answer:empty { display: none; }

/* answered: the part goes quiet and gets a check mark */
.k.answered { background: var(--ac-subtle); border-color: var(--ac-border); }
.k.answered > .kh { background: var(--ac-muted); }

/* the pulse (KIND-03): open needs-you parts only; the blink of Live's icon is no pulse (A-104) */
@keyframes kind-glow {
  0%, 100% { box-shadow: 0 0 0 0 transparent; }
  50% { box-shadow: 0 0 18px 3px color-mix(in srgb, var(--kc) 38%, transparent); }
}
@keyframes kind-blink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .35; transform: scale(.7); }
}
.k.pulse { animation: kind-glow 2.4s ease-in-out infinite; }
.k.live > .kh .ic { animation: kind-blink 2s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .k, .ic { animation: none !important; }
  .k.pulse { box-shadow: 0 0 12px 2px color-mix(in srgb, var(--kc) 35%, transparent); }
}
`;

let sheetObject = null;

/** The stylesheet object for shadow roots that adopt it (created on first use). */
export function kindSheet() {
  if (!sheetObject) {
    sheetObject = new CSSStyleSheet();
    sheetObject.replaceSync(KIND_CSS);
  }
  return sheetObject;
}

// Icons of the reference (categories.html): [tag, attributes] per shape, 24 x 24.
const P = (d) => ["path", {d}];
export const ICONS = {
  ask: [P("M4 5h16v11H9l-5 4z"), P("M10 8.7a2 2 0 1 1 3 1.7c-.7.4-1 .8-1 1.5"), P("M12 14.2h.01")],
  do: [["rect", {x: 3, y: 4, width: 18, height: 16, rx: 2}], P("M8 10l3 2-3 2"), P("M13 15h4")],
  report: [P("M6 3h8l4 4v14H6z"), P("M14 3v4h4"), P("M9 12h6M9 16h6")],
  decision: [P("M3 12h6l4-6h7M9 12l4 6h7"), P("M17 3l3 3-3 3"), P("M17 15l3 3-3 3")],
  alert: [P("M12 3l10 18H2z"), P("M12 10v5"), P("M12 18h.01")],
  live: [["circle", {cx: 12, cy: 12, r: 2, fill: "currentColor"}],
    P("M7.5 7.5a6 6 0 0 0 0 9M16.5 7.5a6 6 0 0 1 0 9M4.5 4.5a10 10 0 0 0 0 15M19.5 4.5a10 10 0 0 1 0 15")],
  check: [P("M5 12.5l5 5 9-10.5")],
};
