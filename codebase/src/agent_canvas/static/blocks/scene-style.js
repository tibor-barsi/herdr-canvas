// Extra stylesheet of canvas-scene (the shared block sheet is in style.js). It is
// adopted next to the shared one, so the scene's own rules stay in this file.
const CSS = `
.scene {
  display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-start;
  container: scene / inline-size;
}
.scene-main { flex: 1 1 380px; min-width: 0; }
.scene-side { flex: 0 1 290px; min-width: 230px; width: 290px; }
@container scene (max-width: 681px) { .scene-side { flex-basis: 100%; width: 100%; } }
.scene .viewer { background: var(--ac-subtle); }
.scene-status {
  position: absolute; left: 8px; bottom: 8px; padding: 2px 8px; font-size: 12px;
  border-radius: 10px; color: var(--ac-fg); background: var(--ac-surface);
  border: 1px solid var(--ac-border); pointer-events: none;
}
.scene-tools { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 8px; align-items: center; }
.scene-tools .group { display: flex; gap: 4px; align-items: center; }
.scene-tools .group-label { font-size: 12px; color: var(--ac-muted); margin-right: 2px; }
.scene button { padding: 2px 9px; font-size: 13px; }
.scene button[aria-pressed="true"] {
  background: var(--ac-accent); border-color: var(--ac-accent); color: var(--ac-accent-fg);
}
.scene input[type="range"] {
  min-width: 0; margin: 0; padding: 0; border: 0; background: none;
  accent-color: var(--ac-accent);
}
.scene-tools input[type="range"] { width: 120px; }
.part-list input[type="range"] { width: 100%; }
.scene .section-value { font-size: 12px; color: var(--ac-muted); min-width: 8em; }
.scene .size-note { margin-left: auto; font-size: 12px; }

.part-list {
  font-size: 13px; max-height: var(--scene-height, 480px); overflow-x: hidden; overflow-y: auto;
}
.part-list h3 { margin: 0 0 4px; font-size: 13px; font-weight: 600; }
.part-list .count { color: var(--ac-muted); font-weight: 400; }
.part-row, .group-row {
  display: grid; align-items: center; column-gap: 6px; min-height: 26px;
  border-bottom: 1px solid var(--ac-border);
}
.part-row { grid-template-columns: 16px 16px minmax(0, 1fr) 72px; padding-left: 18px; }
.group-row { grid-template-columns: 16px 16px minmax(0, 1fr) 72px; font-weight: 600; }
.part-row input[type="checkbox"], .group-row input[type="checkbox"] {
  width: 14px; height: 14px; margin: 0; padding: 0; accent-color: var(--ac-accent);
}
.chevron {
  display: flex; align-items: center; justify-content: center; width: 16px; height: 16px;
  padding: 0 !important; border: 0 !important; background: none !important;
}
.chevron svg { fill: var(--ac-muted); display: block; }
.chevron[aria-expanded="false"] svg { transform: rotate(-90deg); }
.section-extra { display: contents; }
.section-extra[hidden] { display: none; }
.swatch {
  position: relative; display: block; width: 14px; height: 14px; border-radius: 3px;
  border: 1px solid var(--ac-border); cursor: pointer; overflow: hidden;
}
.swatch input {
  position: absolute; inset: 0; width: 100%; height: 100%; min-width: 0; padding: 0;
  border: 0; opacity: 0; cursor: pointer;
}
.part-name { min-width: 0; overflow-wrap: anywhere; line-height: 1.25; padding: 2px 0; }
.part-row[data-status="pending"] .part-name { color: var(--ac-muted); }
.part-row[data-status="error"] .part-name { color: var(--ac-danger); }
.part-note { grid-column: 3 / -1; font-size: 12px; color: var(--ac-muted); padding-bottom: 2px; }
.part-note.error { color: var(--ac-danger); }
.part-bar { grid-column: 1 / -1; height: 2px; background: transparent; }
.part-bar > div { height: 100%; width: 0; background: var(--ac-accent); }
.part-row[data-status="ready"] .part-bar, .part-row[data-status="pending"] .part-bar { display: none; }
`;

export const sceneSheet = new CSSStyleSheet();
sceneSheet.replaceSync(CSS);
