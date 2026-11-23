// Trusted shell: the table of contents of the shown page (KEY-05). The page's helper lists its
// headings and does the scrolling (PAGE-01); this file only shows the list and takes the keys.
"use strict";

const pageContents = (function () {
  let root = null;
  let list = null;
  let before = null;
  let asked = false;
  let send = null;
  let selected = 0;
  let timer = null;
  const ANSWER_MS = 2000;

  const isOpen = () => root !== null;

  function ask(post) {
    if (root) return close();
    send = post;
    asked = true;
    clearTimeout(timer);
    timer = setTimeout(() => { asked = false; }, ANSWER_MS);
    post({ type: "contents-get" });
  }

  function select(index) {
    const rows = list.children;
    selected = Math.min(Math.max(index, 0), rows.length - 1);
    for (const [i, row] of Array.from(rows).entries()) row.setAttribute("aria-selected", String(i === selected));
    rows[selected]?.scrollIntoView({ block: "nearest" });
  }

  function go(index) {
    close();
    send({ type: "contents-go", index });
  }

  function onItems(message) {
    if (!asked || !Array.isArray(message.items)) return;
    asked = false;
    clearTimeout(timer);
    before = document.activeElement;
    const box = document.createElement("div");
    box.className = "key-help-box";
    const title = document.createElement("h2");
    title.id = "page-contents-title";
    title.textContent = "Contents";
    list = document.createElement("ul");
    for (const [index, item] of message.items.slice(0, 300).entries()) {
      if (!item || typeof item.text !== "string" || !Number.isInteger(item.level)) continue;
      const row = document.createElement("li");
      row.dataset.level = String(Math.min(Math.max(Number(item.level) || 1, 1), 6));
      row.style.setProperty("--indent", String(row.dataset.level - 1));
      row.textContent = String(item.text).slice(0, 120);
      row.setAttribute("role", "option");
      row.dataset.index = String(index);
      row.addEventListener("click", () => go(index));
      list.append(row);
    }
    list.setAttribute("role", "listbox");
    box.append(title);
    if (list.children.length) box.append(list);
    else {
      const none = document.createElement("p");
      none.textContent = "No headings";
      box.append(none);
    }
    root = document.createElement("div");
    root.id = "page-contents";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-labelledby", "page-contents-title");
    root.tabIndex = -1;
    root.addEventListener("keydown", (event) => {
      if (event.key === "Tab") event.preventDefault();
      if (event.key === "Enter" && list.children.length) {
        event.preventDefault();
        go(Number(list.children[selected].dataset.index));
      }
    });
    root.addEventListener("click", (event) => {
      if (event.target === root) close();
    });
    root.append(box);
    document.body.append(root);
    root.focus();
    if (list.children.length) select(Math.max(Array.from(list.children).findIndex((r) => r.dataset.index === String(message.current)), 0));
  }

  // The keys while the list is open (the key map names them); always handled.
  function key(name) {
    if (keyMap.is("contents.close", name) || keyMap.is("contents.open", name)) close();
    else if (keyMap.is("contents.next", name)) select(selected + 1);
    else if (keyMap.is("contents.prev", name)) select(selected - 1);
    return true;
  }

  function close() {
    if (!root) return;
    root.remove();
    root = null;
    asked = false;
    clearTimeout(timer);
    if (before && before.isConnected) before.focus();
    before = null;
  }

  return { ask, isOpen, onItems, key, close };
})();
