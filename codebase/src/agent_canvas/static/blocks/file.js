// canvas-file: a file the agent made (CNT-03): a type badge, the name, its folder, the
// size, date and machine as given, a note, and Copy, which puts the absolute path on the
// clipboard through the shell (DO-02, the hub checks the path is written in the page file).
// "Open" appears only for a viewer type directly in the session folder, whose absolute path
// the shell hands over with the stored answers (A-171); it uses the document block's route.
import { CanvasBlock, h } from "./base.js";

const MAX_PATH = 500;
const VIEWER_NAME = /^[^/\\\0]+\.(md|markdown|pdf|png|jpe?g|gif|webp|svg)$/i;
const ABSOLUTE = /^(\/|[A-Za-z]:[\\/])/;

const CSS = `
.file { display: flex; gap: 12px; align-items: flex-start; }
.file-badge { flex: none; min-width: 3.2em; padding: 6px 4px; text-align: center;
  font: 700 .75rem/1 ui-monospace, Menlo, Consolas, monospace; letter-spacing: .03em;
  color: var(--ac-accent); border: 1.5px solid var(--ac-accent); border-radius: 6px; }
.file-body { flex: 1 1 auto; min-width: 0; }
.file-name { font-weight: 600; overflow-wrap: anywhere; }
.file-folder, .file-facts { color: var(--ac-muted); font-size: 12.8px; overflow-wrap: anywhere; }
.file-note { margin-top: 4px; }
.file-actions { flex: none; display: flex; gap: 8px; }
`;
const ownSheet = new CSSStyleSheet();
ownSheet.replaceSync(CSS);

/** The page name of ``path`` when it is a viewer file directly in ``folder``, else null. */
export function openableName(path, folder) {
  if (typeof folder !== "string" || !folder || !path.startsWith(folder + "/")) return null;
  const name = path.slice(folder.length + 1);
  return VIEWER_NAME.test(name) ? name : null;
}

export class CanvasFile extends CanvasBlock {
  static schema = {path: "string!", note: "string", size: "string", date: "string", machine: "string"};

  constructor() {
    super();
    this.folder = undefined;
    this._onAnswers = () => {
      if (window.agentCanvas.sessionFolder !== this.folder) this.reloadSource();
    };
  }

  connectedCallback() {
    super.connectedCallback();
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(ownSheet)) this.shadowRoot.adoptedStyleSheets = [...sheets, ownSheet];
    document.addEventListener("agentcanvas:answers", this._onAnswers);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("agentcanvas:answers", this._onAnswers);
  }

  validate(config) {
    if (!ABSOLUTE.test(config.path) || config.path.length > MAX_PATH || config.path.endsWith("/")) {
      return `"path" must be the absolute path of a file (at most ${MAX_PATH} characters)`;
    }
    return null;
  }

  render(config, wrapper) {
    const cut = config.path.lastIndexOf("/");
    const name = config.path.slice(cut + 1);
    const folder = config.path.slice(0, cut) || "/";
    const dot = name.lastIndexOf(".");
    const kind = dot > 0 ? name.slice(dot + 1, dot + 5).toUpperCase() : "FILE";
    const facts = [config.size, config.date, config.machine].filter(Boolean).join(" · ");
    const actions = h("div", {class: "file-actions"});
    this.folder = window.agentCanvas.sessionFolder;
    const openName = openableName(config.path, this.folder);
    if (openName) {
      actions.append(h("button", {type: "button", onclick: () => window.agentCanvas.openFile(openName)}, "Open"));
    }
    actions.append(h("button", {
      type: "button", "aria-label": `Copy path of ${name}`,
      onclick: () => window.agentCanvas.copyText("path", config.path),
    }, "Copy"));
    wrapper.replaceChildren(h("div", {class: "file"},
      h("div", {class: "file-badge", "aria-hidden": "true"}, kind),
      h("div", {class: "file-body"},
        h("div", {class: "file-name"}, name),
        h("div", {class: "file-folder"}, folder),
        facts ? h("div", {class: "file-facts"}, facts) : null,
        config.note ? h("div", {class: "file-note"}, config.note) : null),
      actions));
  }
}
