// The part list of canvas-scene (SCN-02): group rows and part rows with a
// checkbox, a colour swatch and an opacity slider. The rows are built once per
// structure; later updates only set values, so a slider that is being dragged
// is never replaced.
import { h } from "./base.js";

const mean = (values) => values.reduce((a, b) => a + b, 0) / (values.length || 1);

function slider(label, onInput) {
  const input = h("input", {
    type: "range", min: "0", max: "1", step: "0.05", "aria-label": label,
  });
  input.addEventListener("input", () => onInput(Number(input.value)));
  return input;
}

// A small down-pointing triangle (SVG, so that it does not depend on a font).
function triangle() {
  const holder = document.createElement("span");
  holder.innerHTML = '<svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">'
    + '<polygon points="1.5,3 8.5,3 5,7.5"></polygon></svg>';
  return holder.firstChild;
}

export class PartList {
  /**
   * ``handlers``: ``setVisible(ids, bool)``, ``setOpacity(ids, number)``,
   * ``setColour(id, hex)`` and ``toggleGroup(name)``.
   */
  constructor(handlers) {
    this.handlers = handlers;
    this.title = h("h3", {}, "Parts ");
    this.count = h("span", {class: "count"});
    this.title.append(this.count);
    this.body = h("div", {role: "group", "aria-label": "Parts"});
    this.element = h("div", {class: "part-list"}, this.title, this.body);
    this.signature = null;
    this.rows = new Map();
    this.groups = [];
  }

  /** Show ``groups`` = ``[{name, collapsed, parts: [{id, name, ...}]}]``. */
  update(groups) {
    const signature = JSON.stringify(
      groups.map((g) => [g.name, g.collapsed, g.parts.map((p) => [p.id, p.name])]));
    if (signature !== this.signature) this.build(groups);
    this.signature = signature;
    this.sync(groups);
  }

  build(groups) {
    this.rows.clear();
    this.groups = [];
    const elements = [];
    for (const group of groups) {
      if (group.name !== null) elements.push(this.groupRow(group));
      if (group.collapsed) continue;
      for (const part of group.parts) elements.push(this.partRow(part, group.name !== null));
    }
    this.body.replaceChildren(...elements);
  }

  groupRow(group) {
    const ids = group.parts.map((p) => p.id);
    const chevron = h("button", {
      type: "button", class: "chevron", "aria-expanded": String(!group.collapsed),
      "aria-label": `${group.collapsed ? "Expand" : "Collapse"} group ${group.name}`,
      onclick: () => this.handlers.toggleGroup(group.name),
    }, triangle());
    const check = h("input", {type: "checkbox", "aria-label": `Show group ${group.name}`});
    check.addEventListener("change", () => this.handlers.setVisible(ids, check.checked));
    const name = h("span", {class: "part-name", title: group.name}, group.name,
      h("span", {class: "count"}, ` ${ids.length}`));
    const opacity = slider(`Opacity of group ${group.name}`,
      (value) => this.handlers.setOpacity(ids, value));
    this.groups.push({check, opacity, ids});
    return h("div", {class: "group-row"}, chevron, check, name, opacity);
  }

  partRow(part, grouped) {
    const check = h("input", {type: "checkbox", "aria-label": `Show ${part.name}`});
    check.addEventListener("change", () => this.handlers.setVisible([part.id], check.checked));
    const colour = h("input", {type: "color", "aria-label": `Colour of ${part.name}`});
    colour.addEventListener("input", () => this.handlers.setColour(part.id, colour.value));
    const swatch = h("label", {class: "swatch", title: "Change colour"}, colour);
    const name = h("span", {class: "part-name", title: part.name}, part.name);
    const opacity = slider(`Opacity of ${part.name}`,
      (value) => this.handlers.setOpacity([part.id], value));
    const note = h("div", {class: "part-note", hidden: true});
    const fill = h("div");
    const row = h("div", {class: "part-row", "data-part": part.id},
      check, swatch, name, opacity, note, h("div", {class: "part-bar"}, fill));
    if (!grouped) row.style.paddingLeft = "0";
    this.rows.set(part.id, {row, check, colour, swatch, opacity, note, fill, name});
    return row;
  }

  sync(groups) {
    const parts = groups.flatMap((g) => g.parts);
    this.count.textContent = `(${parts.length})`;
    const byId = new Map(parts.map((p) => [p.id, p]));
    for (const [id, refs] of this.rows) this.syncPart(refs, byId.get(id));
    const active = this.element.getRootNode().activeElement;
    for (const refs of this.groups) {
      const members = refs.ids.map((id) => byId.get(id));
      const shown = members.filter((p) => p.visible).length;
      refs.check.checked = shown === members.length;
      refs.check.indeterminate = shown > 0 && shown < members.length;
      if (active !== refs.opacity) refs.opacity.value = String(mean(members.map((p) => p.opacity)));
    }
  }

  syncPart(refs, part) {
    const active = this.element.getRootNode().activeElement;
    refs.row.dataset.status = part.status;
    refs.check.checked = part.visible;
    refs.swatch.style.background = part.colour;
    if (active !== refs.colour) refs.colour.value = part.colour;
    if (active !== refs.opacity) refs.opacity.value = String(part.opacity);
    refs.fill.style.width = `${Math.round((part.progress || 0) * 100)}%`;
    const note = part.status === "error" ? part.error
      : part.status === "pending" ? "not loaded yet" : "";
    refs.note.hidden = !note;
    refs.note.textContent = note || "";
    refs.note.classList.toggle("error", part.status === "error");
    refs.name.title = part.status === "error" ? `${part.name}: ${part.error}` : part.name;
  }
}
