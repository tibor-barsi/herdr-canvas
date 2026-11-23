// canvas-table: sortable by header click; a row click -> `select` action whose
// value is the list of selected row keys (key column value, else row index).
import { CanvasBlock, h } from "./base.js";

function compare(a, b) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, {numeric: true});
}

// A column of numbers (empty cells allowed) is right-aligned so digits line up.
function isNumericColumn(rows, column) {
  const cells = rows.map((row) => row[column]).filter((v) => v !== undefined && v !== null);
  return cells.length > 0 && cells.every((v) => typeof v === "number");
}

export class CanvasTable extends CanvasBlock {
  static schema = {
    columns: "array!", rows: "array!", key: "string", select: "none|single|multi",
  };

  validate(config) {
    if (!config.columns.every((c) => typeof c === "string")) {
      return 'config key "columns" must list column names (strings)';
    }
    if (!config.rows.every(Array.isArray)) return 'config key "rows" must be a list of lists';
    if (config.key !== undefined && !config.columns.includes(config.key)) {
      return `key "${config.key}" is not one of the columns`;
    }
    return null;
  }

  render(config, wrapper) {
    this.config = config;
    const keys = config.rows.map((row, i) => this.keyOf(row, i));
    this.state.selected = (this.state.selected || []).filter((k) => keys.includes(k));
    if (config.select === "single") this.state.selected = this.state.selected.slice(0, 1);
    const sort = this.state.sort;
    if (sort && !config.columns.includes(sort.column)) this.state.sort = null;

    this.numeric = config.columns.map((_, c) => isNumericColumn(config.rows, c));
    this.head = h("tr", {}, ...config.columns.map((name, c) =>
      h("th", {scope: "col", class: this.numeric[c] ? "num" : "",
        onclick: () => this.sortBy(name)}, name)));
    this.body = h("tbody");
    wrapper.replaceChildren(h("div", {class: "table-wrap"},
      h("table", {}, h("thead", {}, this.head), this.body)));
    this.paint();
  }

  keyOf(row, index) {
    const column = this.config.key;
    return column === undefined ? index : row[this.config.columns.indexOf(column)];
  }

  sortBy(name) {
    const sort = this.state.sort;
    const direction = sort && sort.column === name && sort.direction === "ascending"
      ? "descending" : "ascending";
    this.state.sort = {column: name, direction};
    this.paint();
  }

  // Rebuild the header marks and body rows from the current state.
  paint() {
    const {columns, rows, select} = this.config;
    const sort = this.state.sort;
    [...this.head.children].forEach((th, i) => {
      if (sort && columns[i] === sort.column) th.setAttribute("aria-sort", sort.direction);
      else th.removeAttribute("aria-sort");
    });
    let order = rows.map((_, i) => i);
    if (sort) {
      const col = columns.indexOf(sort.column);
      const sign = sort.direction === "ascending" ? 1 : -1;
      order.sort((a, b) => sign * compare(rows[a][col], rows[b][col]) || a - b);
    }
    this.body.replaceChildren(...order.map((i) => {
      const key = this.keyOf(rows[i], i);
      const row = h("tr", {}, ...columns.map((_, c) =>
        h("td", {class: this.numeric[c] ? "num" : ""},
          rows[i][c] === undefined || rows[i][c] === null ? "" : String(rows[i][c]))));
      if (select !== "none") {
        row.setAttribute("aria-selected", String(this.state.selected.includes(key)));
        row.addEventListener("click", (event) => this.toggle(key, event));
      }
      return row;
    }));
  }

  toggle(key, event) {
    const current = this.state.selected;
    if (this.config.select === "single") this.state.selected = [key];
    else this.state.selected = current.includes(key)
      ? current.filter((k) => k !== key) : [...current, key];
    const keys = this.config.rows.map((row, i) => this.keyOf(row, i));
    const ordered = keys.filter((k) => this.state.selected.includes(k));
    this.paint();
    this.action("select", ordered, event);
  }
}
