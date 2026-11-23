// Trusted shell: the key overview opened by ``?`` (KEY-03), made from the key map (keymap.js).
// It is also where the profile is chosen and keys are changed, all from the keyboard: move to an
// action, press the "change" key, press the new key; a key another action uses is shown and
// needs a yes. The changes are saved by the hub in the owner's keys.toml (KMAP-02).
"use strict";

const keyHelp = (function () {
  let problems = [];
  let dialog = null;
  let before = null;
  let hub = null;            // {save(body) -> answer | null, changed()} given by shell.js
  let at = 0;                // index of the selected action among the selectable rows
  let mode = "browse";       // "browse", "record" (waiting for the new key) or "confirm" (a clash)
  let adding = false;
  let pending = null;        // {action, list, reset, clash}
  let message = "";

  const selectable = () => keyMap.groups().flatMap(([, rows]) => rows).filter((row) => row.id);
  const chosen = () => selectable()[at];

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function status() {
    const row = chosen();
    if (mode === "record") {
      return `${adding ? "Adding a key to" : "New key for"} "${row.what}": press it now (${keyMap.names("help.close")} cancels).`;
    }
    if (mode === "confirm") {
      const used = [...pending.clash].map(([id, list]) => `${keyMap.label(list)} of "${selectable().find((r) => r.id === id).what}"`);
      return `Already used: ${used.join("; ")}. ${keyMap.names("help.change")} takes it from there, ${keyMap.names("help.close")} cancels.`;
    }
    return message;
  }

  function build() {
    const box = element("div", "key-help-box");
    const title = element("h2", "", "Keyboard shortcuts");
    title.id = "key-help-title";
    const names = keyMap.profiles().map((p) => (p.name === keyMap.profile() ? `[${p.name}]` : p.name));
    const profile = element("p", "key-help-profile", `Profile: ${names.join("  ")}  (${keyMap.names("help.profile.prev")} ${keyMap.names("help.profile.next")} to choose)`);
    profile.id = "key-help-profile";
    const line = element("p", "key-help-status", status());
    line.id = "key-help-status";
    line.setAttribute("role", "status");
    box.append(title, profile, line);
    let index = 0;
    for (const [heading, rows] of keyMap.groups()) {
      const part = element("section");
      const list = element("dl");
      for (const row of rows) {
        const on = row.id !== null && index++ === at;
        const dt = element("dt", on ? "sel" : "");
        const kbd = element("kbd", "", mode === "record" && on ? "…" : row.keys);
        dt.append(kbd);
        const dd = element("dd", on ? "sel" : "", row.what + (row.edited ? "  (changed)" : ""));
        if (row.id) dt.dataset.action = dd.dataset.action = row.id;
        if (on) dt.id = "key-help-current";
        list.append(dt, dd);
      }
      part.append(element("h3", "", heading), list);
      box.append(part);
    }
    if (problems.length) box.append(element("p", "key-help-problems", `keys.toml was partly ignored: ${problems.join("; ")}`));
    const shadowed = keyMap.shadowed();
    if (shadowed.length) {
      box.append(element("p", "key-help-note", `While commenting, ${keyMap.label(shadowed)} belong to the comment keys.`));
    }
    box.append(element("p", "key-help-note",
      `${keyMap.names("help.up")} ${keyMap.names("help.down")} move · ${keyMap.names("help.change")} change · ` +
      `${keyMap.names("help.add")} add a key · ${keyMap.names("help.reset")} reset · ` +
      `${keyMap.names("help.reset.all")} reset all · ${keyMap.names("help.open")} or ${keyMap.names("help.close")} closes. ` +
      "A profile is a .toml file in the keys folder of the config; your changes go to keys.toml."));
    return box;
  }

  function render() {
    const box = dialog.querySelector(".key-help-box");
    const top = box ? box.scrollTop : 0;
    dialog.replaceChildren(build());
    const fresh = dialog.querySelector(".key-help-box");
    fresh.scrollTop = top;
    dialog.querySelector("#key-help-current")?.scrollIntoView({block: "nearest"});
  }

  async function save(body) {
    const answer = hub ? await hub.save(body) : null;
    mode = "browse";
    pending = null;
    if (!answer) message = "The change was not saved.";
    else {
      problems = keyMap.configure(answer);
      hub.changed();
      message = "Saved.";
    }
    if (dialog) render();
  }

  function commit({action, list, reset, clash}) {
    const keys = keyMap.ownerKeys();
    const set = (id, value) => {
      if (JSON.stringify(value) === JSON.stringify(keyMap.profileKeys(id))) delete keys[id];
      else keys[id] = value;
    };
    if (reset) delete keys[action]; else set(action, list);
    for (const [id, taken] of clash) set(id, keyMap.current(id).filter((b) => !taken.includes(b)));
    return save({keys});
  }

  function propose(action, list, reset) {
    pending = {action, list, reset, clash: keyMap.clashes(action, list)};
    if (pending.clash.size) {
      mode = "confirm";
      render();
    } else commit(pending);
  }

  function step(delta) {
    const count = selectable().length;
    at = (at + delta + count) % count;
    message = "";
    render();
  }

  function pickProfile(delta) {
    const list = keyMap.profiles();
    const next = list[(list.findIndex((p) => p.name === keyMap.profile()) + delta + list.length) % list.length];
    if (next) save({profile: next.name});
  }

  // A key press while the overview is open; true when it was used.
  function key(name, mods) {
    if (mode === "record") {
      const binding = keyMap.bindingOf(name, mods);
      if (keyMap.is("help.close", name, mods)) mode = "browse";
      else if (binding) {
        const row = chosen();
        const list = adding ? [...keyMap.current(row.id), binding] : [binding];
        mode = "browse";
        propose(row.id, list.filter((b, i) => list.indexOf(b) === i), false);
        return true;
      }
      render();
      return true;
    }
    if (mode === "confirm") {
      if (keyMap.is("help.change", name, mods)) commit(pending);
      else if (keyMap.is("help.close", name, mods)) {
        mode = "browse";
        pending = null;
        render();
      }
      return true;
    }
    if (keyMap.is("help.open", name, mods) || keyMap.is("help.close", name, mods)) close();
    else if (keyMap.is("help.up", name, mods)) step(-1);
    else if (keyMap.is("help.down", name, mods)) step(1);
    else if (keyMap.is("help.change", name, mods) || keyMap.is("help.add", name, mods)) {
      adding = keyMap.is("help.add", name, mods);
      mode = "record";
      render();
    } else if (keyMap.is("help.reset", name, mods)) propose(chosen().id, keyMap.profileKeys(chosen().id), true);
    else if (keyMap.is("help.reset.all", name, mods)) save({keys: {}});
    else if (keyMap.is("help.profile.prev", name, mods)) pickProfile(-1);
    else if (keyMap.is("help.profile.next", name, mods)) pickProfile(1);
    else return false;
    return true;
  }

  const isOpen = () => dialog !== null;

  function open() {
    if (dialog) return;
    before = document.activeElement;
    dialog = element("div");
    dialog.id = "key-help";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "key-help-title");
    dialog.tabIndex = -1;
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Tab") event.preventDefault();
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) close();
    });
    at = 0;
    mode = "browse";
    message = "";
    render();
    document.body.append(dialog);
    dialog.focus();
  }

  function close() {
    if (!dialog) return;
    dialog.remove();
    dialog = null;
    if (before && before.isConnected) before.focus();
    before = null;
  }

  const report = (list) => { problems = list; };
  const connect = (given) => { hub = given; };

  return {open, close, isOpen, report, key, connect};
})();
