// The one stylesheet shared by every block: system font stack, one palette that
// follows prefers-color-scheme. Blocks adopt the same CSSStyleSheet object.
const CSS = `
:host {
  display: block;
  margin: 12px 0;
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
    Arial, sans-serif;
  color: var(--ac-fg);
  --ac-fg: #1f2328;
  --ac-muted: #59636e;
  --ac-surface: #ffffff;
  --ac-subtle: #f3f5f8;
  --ac-border: #d1d9e0;
  --ac-accent: #2457c5;
  --ac-accent-fg: #ffffff;
  --ac-danger: #c62828;
  --ac-ok: #1a7f37;
}
@media (prefers-color-scheme: dark) {
  :host {
    --ac-fg: #e6edf3;
    --ac-muted: #9aa6b2;
    --ac-surface: #1c2128;
    --ac-subtle: #262c35;
    --ac-border: #3d444d;
    --ac-accent: #6e9bff;
    --ac-accent-fg: #0d1117;
    --ac-danger: #ff7b72;
    --ac-ok: #56d364;
  }
}
*, *::before, *::after { box-sizing: border-box; }
.block {
  background: var(--ac-block-bg, var(--ac-surface));
  border: var(--ac-block-border, 1px solid var(--ac-border));
  border-radius: 8px;
  padding: var(--ac-block-padding, 12px 14px);
}
.block-error {
  border-color: var(--ac-danger);
  color: var(--ac-danger);
}
.block-error code { font-family: ui-monospace, Menlo, Consolas, monospace; }
button {
  font: inherit;
  color: inherit;
  background: var(--ac-subtle);
  border: 1px solid var(--ac-border);
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
}
button:hover:not(:disabled) { border-color: var(--ac-accent); }
button:focus-visible, input:focus-visible, textarea:focus-visible,
[tabindex]:focus-visible { outline: 2px solid var(--ac-accent); outline-offset: 2px; }
button:disabled { opacity: 0.5; cursor: default; }
button.primary, button.submit {
  background: var(--ac-accent);
  border-color: var(--ac-accent);
  color: var(--ac-accent-fg);
}
button.danger { color: var(--ac-danger); border-color: var(--ac-danger); }
.muted { color: var(--ac-muted); }
input, textarea, select {
  font: inherit;
  color: inherit;
  background: var(--ac-surface);
  border: 1px solid var(--ac-border);
  border-radius: 6px;
  padding: 6px 8px;
  width: 100%;
}
select { width: auto; }
input[type=checkbox], input[type=radio] { accent-color: var(--ac-accent); }

/* choices */
.options { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
.option {
  display: flex; flex-direction: column; gap: 6px; text-align: left; padding: 10px;
}
.option img { width: 100%; border-radius: 4px; display: block; }
.option .title { font-weight: 600; }
.option[aria-checked="true"] {
  border-color: var(--ac-accent);
  box-shadow: 0 0 0 2px var(--ac-accent);
}
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }

/* textbox */
.label { display: block; margin-bottom: 4px; font-weight: 600; }
textarea { min-height: 5em; resize: vertical; }

/* table */
.table-wrap { overflow: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--ac-border); }
th { cursor: pointer; user-select: none; white-space: nowrap; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
th[aria-sort="ascending"]::after { content: " \\25B2"; font-size: 0.75em; }
th[aria-sort="descending"]::after { content: " \\25BC"; font-size: 0.75em; }
tbody tr[aria-selected] { cursor: pointer; }
tbody tr:hover { background: var(--ac-subtle); }
tbody tr[aria-selected="true"] { background: color-mix(in srgb, var(--ac-accent) 18%, transparent); }

/* progress */
.head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
.track { height: 8px; border-radius: 4px; background: var(--ac-subtle); overflow: hidden; }
.fill { height: 100%; width: 0; background: var(--ac-accent); transition: width 0.2s ease; }
.status-done .fill { background: var(--ac-ok); }
.status-failed .fill { background: var(--ac-danger); }
.detail { margin-top: 6px; color: var(--ac-muted); }
.log { margin-top: 6px; }
.log summary { cursor: pointer; color: var(--ac-muted); }
.log-text { margin: 6px 0 0; padding: 8px 10px; overflow: auto; border-radius: 6px;
  background: var(--ac-subtle); font-size: 12px; line-height: 1.4; white-space: pre; }
.confirm { display: inline-flex; gap: 8px; align-items: center; }
.actions[hidden], .confirm[hidden] { display: none; }

/* markdown */
.markdown > :first-child { margin-top: 0; }
.markdown > :last-child { margin-bottom: 0; }
.markdown pre, .markdown code { font-family: ui-monospace, Menlo, Consolas, monospace; }
.markdown pre { background: var(--ac-subtle); padding: 8px 10px; border-radius: 6px; overflow: auto; }
.markdown :not(pre) > code { background: var(--ac-subtle); padding: 1px 4px; border-radius: 4px; }
.markdown img { max-width: 100%; }
.markdown a { color: var(--ac-accent); }
.markdown table { margin: 8px 0; }

/* plot: Plotly draws its own SVG; the block only gives it room */
.plot { overflow: hidden; max-width: 100%; }

/* plot axis bar: one group per axis, quiet until used */
.axis-bar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px;
  margin-top: 6px; padding-top: 8px; border-top: 1px solid var(--ac-border);
  font-size: 12px; color: var(--ac-muted);
}
.axis-group { display: inline-flex; align-items: center; gap: 6px; }
.axis-name { min-width: 1.5em; font-weight: 600; color: var(--ac-fg); }
.axis-scale { display: inline-flex; }
.axis-bar button { padding: 1px 8px; font-size: 12px; line-height: 1.5; border-radius: 5px; }
.axis-scale button:first-child { border-radius: 5px 0 0 5px; }
.axis-scale button:last-child { border-radius: 0 5px 5px 0; margin-left: -1px; }
.axis-scale button[aria-pressed="true"] {
  background: color-mix(in srgb, var(--ac-accent) 16%, var(--ac-surface));
  border-color: var(--ac-accent); color: var(--ac-accent); font-weight: 600;
}
.axis-bar input {
  width: 5.2em; padding: 1px 6px; font-size: 12px; line-height: 1.5; border-radius: 5px;
  text-align: right; font-variant-numeric: tabular-nums;
}
.axis-bar input[aria-invalid="true"] { border-color: var(--ac-danger); }
.axis-note { flex-basis: 100%; font-style: italic; }
.axis-note[hidden] { display: none; }

/* image */
.image-view {
  position: relative; display: inline-block; max-width: 100%; overflow: hidden;
  line-height: 0; border-radius: 4px; cursor: grab; touch-action: none;
  user-select: none; background: var(--ac-subtle);
}
.image-view.panning { cursor: grabbing; }
.point-mark {
  position: absolute; width: 18px; height: 18px; margin: -9px 0 0 -9px; box-sizing: border-box;
  border: 3px solid #e8590c; border-radius: 50%; background: rgba(255, 255, 255, 0.6);
  box-shadow: 0 0 0 2px #fff; pointer-events: none;
}
.image-view img {
  display: block; max-width: 100%; max-height: 480px;
  transform-origin: 0 0; -webkit-user-drag: none;
}

.image-frame { position: relative; display: inline-block; max-width: 100%; }
.image-view:focus-visible { outline-offset: -2px; }
.enlarge {
  position: absolute; top: 6px; right: 6px; width: 26px; height: 26px; padding: 0;
  display: grid; place-items: center; line-height: 0; border-radius: 6px;
  background: color-mix(in srgb, var(--ac-surface) 85%, transparent);
  color: var(--ac-fg); opacity: 0.8;
}
.enlarge:hover:not(:disabled), .enlarge:focus-visible { opacity: 1; }
.overlay {
  position: absolute; inset: 0; display: grid; place-items: center; overflow: hidden;
  background: rgba(10, 12, 16, 0.88);
}
.overlay .image-view { max-width: none; border-radius: 2px; background: transparent; }
.overlay .image-view img { max-width: none; max-height: none; }
.overlay .close {
  position: absolute; top: 12px; right: 12px; width: 36px; height: 36px; padding: 0;
  border-radius: 50%; font-size: 22px; line-height: 1;
}

/* model */
.viewer { position: relative; width: 100%; border-radius: 4px; overflow: hidden; }
.viewer canvas { display: block; width: 100%; height: 100%; touch-action: none; }
.toolbar { display: flex; gap: 8px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
.toolbar button[aria-pressed="true"] {
  background: var(--ac-accent); border-color: var(--ac-accent); color: var(--ac-accent-fg);
}
.viewer.marking canvas { cursor: crosshair; }
`;

export const sheet = new CSSStyleSheet();
sheet.replaceSync(CSS);
