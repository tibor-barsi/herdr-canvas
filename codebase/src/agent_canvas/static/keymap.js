// Trusted shell: the one place that defines the keyboard shortcuts (KMAP-01). The handlers in
// shell.js, draw.js and keys.js ask this table; the overview opened by ``?`` is made from it.
// The keys themselves are not here: they come from the chosen profile file (keyprofiles/*.toml
// or the user's keys/*.toml) and the owner's own changes in keys.toml (KMAP-02), through
// ``GET /api/keys``. Keys that are not shortcuts (Enter, Space and Tab in fields and on buttons,
// Esc in dialogs and text fields) stay in the files that use them.
"use strict";

const keyMap = (function () {
  // Scope: "window" keys also work from inside the page frame; "comment" keys only in comment
  // mode (also forwarded); "cursor" keys only while the keyboard cursor of a comment is on
  // (also forwarded); "help" and "contents" keys only in that dialog. A key is the ``event.key``
  // name with ``Ctrl+``, ``Alt+`` or ``Shift+`` in front; a letter is case-sensitive, so both
  // cases are listed. The ``:N`` actions are the numbered entries.
  const ACTIONS = {};
  const add = (id, scope, group, what) => { ACTIONS[id] = [scope, group, what]; };
  const NAV = "Spaces, tabs and cards";
  add("space.next", "window", NAV, "next space (the last entry is Not in Herdr)");
  add("space.prev", "window", NAV, "previous space");
  for (let n = 1; n <= 9; n++) add(`space.select:${n}`, "window", NAV, `space ${n}`);
  add("machine.fold", "window", NAV, "fold / open the machine group of the shown space");
  add("tab.next", "window", NAV, "next tab");
  add("tab.prev", "window", NAV, "previous tab");
  for (let n = 1; n <= 9; n++) add(`tab.select:${n}`, "window", NAV, `tab ${n}`);
  for (const side of ["left", "right", "up", "down"]) {
    add(`pane.go:${side}`, "window", NAV, `card on the ${side}`);
  }
  add("pane.next", "window", NAV, "next card of the tab");
  add("pane.prev", "window", NAV, "previous card of the tab");
  add("page.next", "window", NAV, "next page tab of the card");
  add("page.prev", "window", NAV, "previous page tab of the card");
  add("sidebar.toggle", "window", "Window", "sidebar: fold / open");
  add("help.open", "window", "Window", "this overview");
  add("send.now", "window", "Window", "send to the agent");
  add("contents.open", "window", "Window", "table of contents of the page / close it");
  add("file.open", "window", "Window", "open a file in a session");
  add("asks.focus", "window", "Window", "move to the questions of the agent (then Tab, Enter)");
  add("notice.reload", "window", "Window", "reload the page (button of the warning)");
  add("update.reload", "window", "Window", "reload after an update (button of the update bar)");
  add("update.cancel", "window", "Window", "keep this version (Cancel of the update bar)");
  add("changes.dismiss", "window", "Window", "hide the change marks");
  add("comment.toggle", "window", "Comments", "comment mode with the last kind / leave it");
  add("comment.next", "window", "Comments", "next comment (selected, marker shown)");
  add("comment.prev", "window", "Comments", "previous comment");
  add("comment.done", "window", "Comments", "mark the selected comment done / reopen it");
  add("comment.reply", "window", "Comments", "reply to the selected comment");
  add("comment.edit", "window", "Comments", "edit the selected draft comment");
  add("comment.delete", "window", "Comments", "delete the selected draft comment");
  add("comment.fold", "window", "Comments", "fold / unfold the selected comment");
  add("comment.foldall", "window", "Comments", "fold / unfold all comments");
  add("comment.filter", "window", "Comments", "filter: open, done, all");
  add("comment.panel", "window", "Comments", "comment panel: collapse / show");
  add("comment.text", "comment", "Comment mode", "text comments");
  add("comment.point", "comment", "Comment mode", "point comments");
  add("comment.rect", "comment", "Comment mode", "rectangle comments");
  add("comment.lasso", "comment", "Comment mode", "lasso comments");
  add("comment.cursor", "comment", "Comment mode",
    "keyboard cursor: start, then set the point, corner or vertex, or start the text selection");
  for (const side of ["left", "right", "up", "down"]) {
    add(`comment.cursor.${side}`, "cursor", "Comment mode",
      `cursor ${side} (text: extend the selection); with Shift: bigger steps`);
  }
  add("comment.cursor.finish", "cursor", "Comment mode", "close the lasso");
  add("comment.leave", "comment", "Comment mode",
    "close the comment box, then leave comment mode");
  add("contents.next", "contents", "Table of contents", "next heading");
  add("contents.prev", "contents", "Table of contents", "previous heading");
  add("contents.close", "contents", "Table of contents", "close without moving");
  const HELP = "This overview";
  add("help.up", "help", HELP, "previous action");
  add("help.down", "help", HELP, "next action");
  add("help.change", "help", HELP, "record a new key for the action (replaces its keys)");
  add("help.add", "help", HELP, "record one more key for the action");
  add("help.reset", "help", HELP, "back to the profile's keys for the action");
  add("help.reset.all", "help", HELP, "back to the profile's keys for all actions");
  add("help.profile.prev", "help", HELP, "previous profile");
  add("help.profile.next", "help", HELP, "next profile");
  add("help.close", "help", HELP, "close this overview / cancel recording");

  // Rows of the overview for keys that are fixed: [group, keys, what].
  const FIXED = [
    ["Table of contents", "Enter", "scroll to the selected heading and close"],
  ];
  const BINDING = /^((?:Ctrl\+|Alt\+|Shift\+)*)(.|[A-Z][A-Za-z0-9]+)$/;
  const NAMES = {
    ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right",
    Escape: "Esc", ContextMenu: "Menu", " ": "Space",
  };
  const MODIFIER_KEYS = new Set(["Control", "Shift", "Alt", "Meta", "AltGraph", "CapsLock", "Dead"]);

  let table = new Map();   // action -> {list, parsed}
  let state = {profile: "herdr", profiles: [], defaults: {}, owner: {}};

  const parse = (binding) => {
    const [, prefix, key] = BINDING.exec(binding);
    return {
      key, ctrl: prefix.includes("Ctrl+"), alt: prefix.includes("Alt+"),
      shift: prefix.includes("Shift+"),
    };
  };
  // A printable key carries its Shift in its name, so Shift only counts for named keys.
  const matches = (p, key, mods) =>
    p.key === key && p.ctrl === Boolean(mods.ctrl) && p.alt === Boolean(mods.alt) &&
    (key.length === 1 || p.shift === Boolean(mods.shift));
  const isBinding = (value) => typeof value === "string" && BINDING.test(value);
  const scopeOf = (action) => ACTIONS[action][0];
  // Keys of one context cannot both be used for two actions; the other contexts never meet.
  const contextOf = (action) => (["window", "comment", "cursor"].includes(scopeOf(action)) ? "window" : scopeOf(action));

  // The binding string of a key press, or null for a modifier alone.
  function bindingOf(key, mods = {}) {
    if (MODIFIER_KEYS.has(key)) return null;
    return (mods.ctrl ? "Ctrl+" : "") + (mods.alt ? "Alt+" : "") +
      (mods.shift && key.length > 1 ? "Shift+" : "") + key;
  }

  // ``data`` is the answer of ``GET /api/keys``; returns the problems found in it.
  function configure(data) {
    const problems = [...(data.problems || [])];
    const defaults = new Map();
    const apply = (target, entries, source) => {
      for (const [id, value] of Object.entries(entries || {})) {
        const list = Array.isArray(value) ? value : [value];
        if (!Object.hasOwn(ACTIONS, id)) problems.push(`"${id}" is not an action`);
        else if (!list.every(isBinding)) problems.push(`bad key for "${id}"${source}`);
        else target.set(id, list);
      }
    };
    apply(defaults, data.defaults, " in the profile");
    const owner = new Map();
    apply(owner, data.keys, "");
    state = {
      profile: data.profile || state.profile, profiles: data.profiles || [],
      defaults: Object.fromEntries(defaults), owner: Object.fromEntries(owner),
    };
    table = new Map(Object.keys(ACTIONS).map((id) => {
      const list = owner.get(id) || defaults.get(id) || [];
      return [id, {list, parsed: list.map(parse)}];
    }));
    labelPage();
    return problems;
  }

  const is = (action, key, mods = {}) => table.get(action).parsed.some((p) => matches(p, key, mods));
  const hit = (action, event) =>
    is(action, event.key, {ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey});
  const actionsOf = (key, mods = {}) => [...table.keys()].filter((id) => is(id, key, mods));

  // What the page frame forwards to the shell: the window, comment-mode and cursor keys.
  function forwarded() {
    const out = [];
    for (const [id, {parsed}] of table) {
      const scope = scopeOf(id);
      if (scope === "window" || scope === "comment" || scope === "cursor") {
        for (const p of parsed) out.push({...p, comment: scope === "comment", cursor: scope === "cursor"});
      }
    }
    return out;
  }

  const show = (binding) => {
    const {key, ctrl, alt, shift} = parse(binding);
    return [ctrl && "Ctrl", alt && "Alt", shift && "Shift", NAMES[key] || key].filter(Boolean).join("+");
  };
  function label(list) {
    if (!list.length) return "none";
    const shown = list.filter((b) => b === b.toUpperCase() || !list.includes(b.toUpperCase()));
    return shown.map(show).join("  ");
  }

  const names = (action) => label(table.get(action).list);

  // Titles and key labels of the buttons that name their key: <button data-key-action="id">.
  function labelPage() {
    for (const element of document.querySelectorAll("[data-key-action]")) {
      const text = names(element.dataset.keyAction);
      element.title = element.title.replace(/\([^)]*\)$/, `(${text})`);
      const kbd = element.querySelector("kbd");
      if (kbd) kbd.textContent = text;
    }
  }

  // The overview: [[heading, [{id, keys, what, edited}, ...]], ...] with the keys now in force;
  // the fixed rows have no id.
  function groups() {
    const out = new Map();
    const push = (group, row) => out.set(group, [...(out.get(group) || []), row]);
    for (const [id, [, group, what]] of Object.entries(ACTIONS)) {
      push(group, {id, keys: label(table.get(id).list), what, edited: Object.hasOwn(state.owner, id)});
    }
    for (const [group, shown, what] of FIXED) push(group, {id: null, keys: shown, what, edited: false});
    return [...out];
  }

  const canon = (binding) => {
    const p = parse(binding);
    return bindingOf(p.key, p);
  };

  // The other actions of the same context that already use one of ``list``: Map(action -> bindings).
  function clashes(action, list) {
    const found = new Map();
    for (const id of Object.keys(ACTIONS)) {
      if (id === action || contextOf(id) !== contextOf(action)) continue;
      const same = table.get(id).list.filter((b) => list.some((n) => canon(n) === canon(b)));
      if (same.length) found.set(id, same);
    }
    return found;
  }

  // Window keys that a comment-mode key takes over while commenting: the shipped vim L.
  function shadowed() {
    const out = [];
    for (const id of Object.keys(ACTIONS)) {
      if (scopeOf(id) !== "window") continue;
      for (const [other, list] of clashes(id, table.get(id).list)) if (scopeOf(other) === "comment") out.push(...list);
    }
    return [...new Set(out)];
  }

  // The keys the owner changed, as the file wants them: {action: [bindings]}.
  const ownerKeys = () => ({...state.owner});
  const profileKeys = (action) => state.defaults[action] || [];

  configure({});
  return {
    configure, is, hit, actionsOf, forwarded, groups, names, bindingOf, clashes, shadowed, scopeOf,
    ownerKeys, profileKeys, label, show, profile: () => state.profile, profiles: () => state.profiles,
    current: (action) => table.get(action).list,
  };
})();
