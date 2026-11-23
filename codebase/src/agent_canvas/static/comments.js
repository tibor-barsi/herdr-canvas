// Trusted shell: the comment box and the comment panel (COM-03, COM-06; layout
// variant A of prototype/comments/). shell.js wires them. Comment texts are
// shown as text and never leave the shell (COM-15): the frame only gets
// numbers, kinds, anchors and statuses.
//
// The panel (P22.4): entries in number order, the Open/Done/All filters, chips,
// the lost section, edit and delete of drafts, hover and select linked to the
// markers by number. Mark done, Reply and Reopen call callbacks of the shell
// (RPL-05). The reply fields are kept per comment number outside the entries,
// so a push that redraws the list keeps what the owner is typing (RPL-04).
"use strict";

(function () {
  const ICONS = {
    text: '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3h9M8 3v7.5" ' +
      'stroke="currentColor" stroke-width="1.7" fill="none"/><path d="M2 13.5h12" ' +
      'stroke="currentColor" stroke-width="2.6" opacity=".5"/></svg>',
    point: '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 15s5-5.2 5-8.5A5 5 ' +
      '0 0 0 3 6.5C3 9.8 8 15 8 15z" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
      '<circle cx="8" cy="6.5" r="1.8" fill="currentColor"/></svg>',
    lasso: '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 10.5C1 8 2.5 3.2 ' +
      '8 3s7 3.6 4.5 6S6.5 11.5 4 10.5c-.8 1.6-.3 3.4 1.6 3.9" fill="none" stroke="currentColor" ' +
      'stroke-width="1.5" stroke-linecap="round"/></svg>',
    rect: '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3" width="12" ' +
      'height="10" rx="1" fill="none" stroke="currentColor" stroke-width="1.5" ' +
      'stroke-dasharray="3 2"/></svg>',
  };
  const KIND_LABEL = {text: "Text", point: "Point", rect: "Rectangle", lasso: "Lasso"};
  const CHIP_TEXT = {
    draft: "draft", sent: "sent", seen: "seen", answered: "answered", done: "✓ done",
  };
  const READ_BEFORE_LOST = new Set(["seen", "answered", "done"]);  // statuses a lost chip keeps (COM-08)
  const CHIP_TITLE = {
    draft: "not sent yet", sent: "delivered to the session", seen: "the agent has read it",
    answered: "the agent replied", done: "you marked it done",
  };
  const BOX_WIDTH = 300;
  const BOX_GAP = 12;
  const BOX_MARGIN = 8;
  const FILTERS = [["open", "Open"], ["done", "Done"], ["all", "All"]];

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function icon(kind) {
    const holder = make("span", "kd");
    holder.title = KIND_LABEL[kind] || kind;
    holder.innerHTML = ICONS[kind] || "";   // fixed markup above, never page text
    return holder;
  }

  // What a comment points at, for the entry and the box: the target's text,
  // else its canvas id or selector, else the kind.
  function anchorLabel(comment) {
    const target = comment.target || {};
    const label = String(target.text || "").trim() ||
      (target.canvas_id ? `#${target.canvas_id}` : "") || target.selector || "";
    return (label || KIND_LABEL[comment.kind] || "").slice(0, 80);
  }

  // ---- the box (COM-03) -----------------------------------------------------------

  // Where a box of ``size`` goes beside ``rect`` inside ``area`` (all in the same
  // pixels, top-left origin): right of the shape, else left, below, above; the
  // first place where it fits whole. When none fits it is moved inside.
  function placeBox(rect, size, area) {
    const limitX = area.width - size.width - BOX_MARGIN;
    const limitY = area.height - size.height - BOX_MARGIN;
    const clampX = (x) => Math.max(BOX_MARGIN, Math.min(x, limitX));
    const clampY = (y) => Math.max(BOX_MARGIN, Math.min(y, limitY));
    const fits = (x, y) => x >= BOX_MARGIN && y >= BOX_MARGIN && x <= limitX && y <= limitY;
    const right = rect.x + rect.w + BOX_GAP;
    const left = rect.x - BOX_GAP - size.width;
    const below = rect.y + rect.h + BOX_GAP;
    const above = rect.y - BOX_GAP - size.height;
    if (fits(right, clampY(rect.y))) return {x: right, y: clampY(rect.y)};
    if (fits(left, clampY(rect.y))) return {x: left, y: clampY(rect.y)};
    if (fits(clampX(rect.x), below)) return {x: clampX(rect.x), y: below};
    if (fits(clampX(rect.x), above)) return {x: clampX(rect.x), y: above};
    return {x: clampX(right), y: clampY(rect.y)};
  }

  /**
   * Open the comment box next to a selection.
   *
   * ``spec``: ``number`` the comment will get, ``kind``, ``label``, ``rect``
   * (the shape in the container's pixels), ``onSave(text)`` and ``onClose()``;
   * ``text`` and ``title`` when an existing comment is edited.
   * Enter saves a non-empty text, Shift+Enter makes a new line, Esc closes only
   * the box (its text is discarded). Returns ``{element, close, note}``.
   */
  function openCommentBox(container, spec) {
    const box = make("div", "cbox");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", spec.title || "New comment");
    const head = make("div", "h");
    const title = make("span", "", ` ${KIND_LABEL[spec.kind] || spec.kind}` +
      (spec.label ? ` · ${spec.label}` : ""));
    title.classList.add("what");
    head.append(icon(spec.kind), make("b", "", `#${spec.number}`), title);
    const field = make("textarea");
    field.placeholder = "Comment for the agent (Shift+Enter: new line)";
    field.setAttribute("aria-label", "Comment text");
    field.value = spec.text || "";
    const foot = make("div", "f");
    const keys = make("span", "keys");
    keys.append(make("kbd", "", "Enter"), " save · ", make("kbd", "", "Esc"), " close");
    const save = make("button", "primary", "Save");
    save.type = "button";
    foot.append(keys, make("span", "sp"), save);
    const note = make("div", "note");
    note.setAttribute("role", "status");
    box.append(head, field, note, foot);
    box.style.visibility = "hidden";
    container.append(box);

    const place = () => {
      const size = {width: Math.min(BOX_WIDTH, container.clientWidth - 2 * BOX_MARGIN),
        height: box.offsetHeight};
      box.style.width = `${size.width}px`;
      const spot = placeBox(spec.rect, {width: size.width, height: box.offsetHeight},
        {width: container.clientWidth, height: container.clientHeight});
      box.style.left = `${Math.round(spot.x)}px`;
      box.style.top = `${Math.round(spot.y)}px`;
      box.style.visibility = "";
    };
    place();

    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      box.remove();
      spec.onClose();
    };
    const submit = () => {
      const text = field.value.trim();
      if (text) spec.onSave(text);
    };
    field.addEventListener("keydown", (event) => {
      // Ctrl+Enter keeps its meaning (send) and goes on to the shell's handler.
      if (event.key === "Enter" && event.ctrlKey) return;
      event.stopPropagation();
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    });
    save.addEventListener("click", submit);
    setTimeout(() => { if (!closed) field.focus(); }, 0);
    return {
      element: box, close, field,
      note: (text) => { note.textContent = text; },
      reposition: place,
    };
  }

  // ---- the panel (COM-06, COM-07, COM-09) -----------------------------------------------

  // panel root -> {page, scope, filter, selected, forms: number -> {element, field},
  // kept: scope -> forms with text of the pages left, last}
  const states = new WeakMap();

  function stateOf(root, page, scope) {
    let state = states.get(root);
    if (!state) {
      state = {page, scope, filter: "open", selected: null, forms: new Map(), kept: new Map(),
        last: null, folded: new Set()};
      states.set(root, state);
    }
    if (state.scope !== scope) {
      const typed = new Map([...state.forms].filter(([, form]) => form.field.value.trim()));
      if (typed.size) state.kept.set(state.scope, typed); else state.kept.delete(state.scope);
      Object.assign(state, {page, scope, selected: null});
      state.forms = state.kept.get(scope) || new Map();
      state.kept.delete(scope);
    }
    return state;
  }

  // Whether the panel holds an open reply field (it is then drawn whatever the filter).
  function hasForms(root) {
    const state = states.get(root);
    return Boolean(state) && state.forms.size > 0;
  }

  // Whether any reply field, drawn or kept for another page, holds text.
  function hasTypedText(root) {
    const state = states.get(root);
    if (!state) return false;
    const all = [state.forms, ...state.kept.values()];
    return all.some((forms) => [...forms.values()].some((form) => form.field.value.trim()));
  }

  // Folded entries are kept in memory per page and number (COM-21).
  function foldKey(state, number) {
    return `${state.scope}\n${number}`;
  }

  function redraw(root, state) {
    const {page, comments, callbacks} = state.last;
    renderComments(root, page, comments, callbacks);
  }

  function clock(iso) {
    const time = new Date(iso);
    if (Number.isNaN(time.getTime())) return "";
    return `${String(time.getHours()).padStart(2, "0")}:${String(time.getMinutes()).padStart(2, "0")}`;
  }

  function chipText(comment) {
    if (comment.lost) return READ_BEFORE_LOST.has(comment.status) ? `${CHIP_TEXT[comment.status]} · lost` : "lost";
    if (comment.status === "sent" && comment.delivery === "next-message") return "sent · next msg";
    return CHIP_TEXT[comment.status] || comment.status;
  }

  function button(label, onClick, className) {
    const element = make("button", className || "", label);
    element.type = "button";
    element.addEventListener("click", (event) => {
      event.stopPropagation();
      onClick();
    });
    return element;
  }

  // The reply field of one comment (RPL-05): Enter saves, Shift+Enter makes a new
  // line, Esc cancels. Created once and moved into each redraw of the list.
  function replyForm(root, state, number, callbacks) {
    const element = make("div", "rform");
    const field = make("textarea");
    field.placeholder = "Reply (Shift+Enter: new line)";
    field.setAttribute("aria-label", `Reply to comment ${number}`);
    const note = make("div", "note");
    note.setAttribute("role", "status");
    element.append(field, note);
    const close = () => {
      state.forms.delete(number);
      redraw(root, state);
    };
    let saving = false;
    field.addEventListener("keydown", async (event) => {
      if (event.key === "Enter" && event.ctrlKey) return;
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        const text = field.value.trim();
        if (!text || saving) return;
        saving = true;
        const result = await callbacks.reply(number, text);
        saving = false;
        if (result.ok) close(); else note.textContent = result.data.message || "The reply was not saved.";
      }
    });
    field.addEventListener("click", (event) => event.stopPropagation());
    return {element, field};
  }

  function openReply(root, state, number) {
    if (!state.forms.has(number)) {
      state.forms.set(number, replyForm(root, state, number, state.last.callbacks));
    }
    redraw(root, state);
    state.forms.get(number).field.focus();
  }

  // Without the shell's callback a button is shown disabled.
  function actionButtons(comment, callbacks, open) {
    const actions = make("div", "acts");
    const n = comment.n;
    if (comment.sent === null) {
      actions.append(button("Edit", () => callbacks.edit(n)),
        button("Delete", () => callbacks.remove(n)));
      return actions;
    }
    const later = (name, label, className) => {
      const element = button(label, () => (name === "reply" ? open(n) : callbacks[name](n)), className);
      if (!callbacks[name]) {
        element.disabled = true;
        element.title = "Not available in this version";
      }
      return element;
    };
    if (comment.status === "done") actions.append(later("reopen", "Reopen"));
    else actions.append(later("done", "Mark done", "done"), later("reply", "Reply"));
    return actions;
  }

  function replyBlock(reply) {
    const block = make("div", reply.from ? "rp" : "rp me");
    const who = make("div", "who");
    who.append(make("b", "", reply.from || "you"), ` · ${clock(reply.at)}`);
    block.append(who, make("div", "rt", reply.text));
    return block;
  }

  function buildEntry(root, comment, state, callbacks) {
    const entry = make("div", `ent st-${comment.status}`);
    entry.dataset.n = String(comment.n);
    entry.tabIndex = 0;
    entry.classList.toggle("sel", state.selected === comment.n);
    const chip = make("span", `chip ${comment.status}${comment.lost ? " lost" : ""}` +
      `${comment.unread ? " unread" : ""}`, chipText(comment));
    chip.title = comment.lost ? "what it pointed at is gone after a page change"
      : CHIP_TITLE[comment.status] || "";
    const circle = make("span", `cn ${comment.status === "draft" ? "draft" : `st-${comment.status}`}` +
      `${comment.lost ? " lost" : ""}`, String(comment.n));
    const head = make("div", "eh");
    const foldKeyOfEntry = foldKey(state, comment.n);
    const folded = state.folded.has(foldKeyOfEntry) && !state.forms.has(comment.n);
    entry.classList.toggle("folded", folded);
    // A span, not a button: the glyph comes from the stylesheet so the entry's buttons stay its actions.
    const fold = make("span", "fold");
    const toggle = (event) => {
      event.stopPropagation();
      if (folded) state.folded.delete(foldKeyOfEntry); else state.folded.add(foldKeyOfEntry);
      redraw(root, state);
    };
    fold.setAttribute("role", "button");
    fold.tabIndex = 0;
    fold.addEventListener("click", toggle);
    fold.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle(event);
      }
    });
    fold.title = folded ? "Unfold" : "Fold to one line";
    fold.setAttribute("aria-label", `${folded ? "Unfold" : "Fold"} comment ${comment.n}`);
    fold.setAttribute("aria-expanded", String(!folded));
    if (folded) {
      const replies = (comment.replies || []).length;
      head.append(fold, circle, icon(comment.kind), make("span", "tx1", comment.text));
      if (replies) head.append(make("span", "rc", `↩${replies}`));
      entry.append(head);
    } else {
      head.append(fold, circle, icon(comment.kind), make("span", "tg", anchorLabel(comment)), chip);
      entry.append(head);
    }
    const quote = comment.anchor && comment.anchor.quote;
    if (!folded && comment.kind === "text" && quote) entry.append(make("div", "q", `“${quote}”`));
    if (!folded) entry.append(make("div", "tx", comment.text));
    if (!folded) for (const reply of comment.replies || []) entry.append(replyBlock(reply));
    if (comment.pending) return entry;
    if (!callbacks.readOnly && !folded) {
      const form = state.forms.get(comment.n);
      if (form) entry.append(form.element);
      entry.append(actionButtons(comment, callbacks, (n) => openReply(root, state, n)));
    }
    const choose = () => {
      if (folded) {
        state.folded.delete(foldKeyOfEntry);
        state.selected = comment.n;
        redraw(root, state);
        if (callbacks.select) callbacks.select(comment.n);
        return;
      }
      state.selected = comment.n;
      for (const other of entry.parentNode.querySelectorAll(".ent")) {
        other.classList.toggle("sel", other === entry);
      }
      if (callbacks.select) callbacks.select(comment.n);
    };
    entry.addEventListener("click", choose);
    entry.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target === entry) {
        event.preventDefault();
        choose();
      }
    });
    // A lost comment has no marker to light up (COM-07).
    if (!comment.lost && callbacks.hover) {
      entry.addEventListener("mouseenter", () => callbacks.hover(comment.n));
      entry.addEventListener("mouseleave", () => callbacks.hover(null));
    }
    return entry;
  }

  /**
   * Draw the panel of one page into ``root``.
   *
   * ``comments`` are the records of 5.13 with ``status``; ``callbacks`` has
   * ``select(n)``, ``edit(n)`` and ``remove(n)`` for drafts, ``hover(n | null)``
   * and optionally ``done(n)``, ``reopen(n)`` and ``reply(n, text)`` (a promise of
   * ``{ok, data}``), and ``scope()`` (what tells one page from another; default the
   * page name). With ``readOnly`` the entries have no buttons (COM-14). The panel
   * keeps its filter, the selected number and the open
   * reply fields between calls, and the focus and caret in a reply field across
   * a redraw. All texts are set as text.
   */
  function renderComments(root, page, comments, callbacks) {
    const state = stateOf(root, page, callbacks.scope ? callbacks.scope() : page);
    state.last = {page, comments, callbacks};
    for (const number of state.forms.keys()) {
      if (!comments.some((c) => c.n === number)) state.forms.delete(number);
    }
    const typing = [...state.forms.values()].find((form) => form.field === document.activeElement);
    const caret = typing && {
      start: typing.field.selectionStart, end: typing.field.selectionEnd,
      scroll: typing.field.scrollTop,
    };
    root.classList.remove("strip");
    const before = root.querySelector(".plist");
    const scrolled = before ? before.scrollTop : 0;
    const open = comments.filter((c) => c.status !== "done");
    const counts = {open: open.length, done: comments.length - open.length, all: comments.length};
    const head = make("div", "ph");
    const title = make("div", "t");
    title.append(make("b", "", "Comments"), make("span", "dim", page));
    const waiting = callbacks.waiting ? callbacks.waiting() : 0;
    if (waiting) {
      const wait = make("span", "wait", "…");
      wait.title = `Offline: ${waiting} change${waiting === 1 ? "" : "s"} waiting`;
      title.append(wait);
    }
    const filters = make("div", "filters");
    for (const [key, label] of FILTERS) {
      const filter = make("button", "", `${label} ${counts[key]}`);
      filter.type = "button";
      filter.dataset.filter = key;
      filter.setAttribute("aria-pressed", String(state.filter === key));
      filter.addEventListener("click", () => {
        state.filter = key;
        if (callbacks.filter) callbacks.filter(key);
        redraw(root, state);
      });
      filters.append(filter);
    }
    const tools = make("div", "ptools");
    const allFolded = comments.length > 0 && comments.every((c) => state.folded.has(foldKey(state, c.n)));
    const foldAll = button(allFolded ? "Unfold all" : "Fold all", () => {
      for (const c of comments) {
        if (allFolded) state.folded.delete(foldKey(state, c.n)); else state.folded.add(foldKey(state, c.n));
      }
      redraw(root, state);
    }, "foldall");
    tools.append(filters, foldAll);
    if (callbacks.collapse) {
      const collapse = button("", callbacks.collapse, "collapse");
      collapse.title = "Collapse the comments";
      collapse.setAttribute("aria-label", "Collapse the comments");
      title.append(collapse);
    }
    head.append(title, tools);
    const list = make("div", "plist");
    const shown = comments
      .filter((c) => state.filter === "all" || state.forms.has(c.n) ||
        (state.filter === "done") === (c.status === "done"))
      .sort((a, b) => (a.pending ? Infinity : a.n) - (b.pending ? Infinity : b.n));
    for (const comment of shown.filter((c) => !c.lost)) list.append(buildEntry(root, comment, state, callbacks));
    const lost = shown.filter((c) => c.lost);
    if (lost.length) {
      list.append(make("div", "lgrp", "Lost after a page change"));
      for (const comment of lost) list.append(buildEntry(root, comment, state, callbacks));
    }
    if (!shown.length) {
      list.append(make("div", "empty", comments.length
        ? "Nothing in this filter."
        : callbacks.readOnly ? "No comments were made on this version."
          : "No comments yet. Press C, then drag around what you mean."));
    }
    root.replaceChildren(head, list);
    list.scrollTop = scrolled;
    if (typing && typing.field.isConnected) {
      typing.field.focus({preventScroll: true});
      typing.field.setSelectionRange(caret.start, caret.end);
      typing.field.scrollTop = caret.scroll;
    }
  }

  // The collapsed panel: a thin strip with the open count (COM-06, A-76).
  function renderStrip(root, openCount, onOpen) {
    root.classList.add("strip");
    const button = make("button", "stripbutton");
    button.type = "button";
    button.title = "Show the comments";
    button.setAttribute("aria-label", `Show the comments (${openCount} open)`);
    button.append(make("span", openCount ? "cn" : "cn done", String(openCount)), make("span", "word", "Comments"));
    button.addEventListener("click", onOpen);
    root.replaceChildren(button);
  }

  // The shell selects an entry (a marker was clicked) or clears the selection.
  function select(root, number) {
    const state = states.get(root);
    if (state) {
      state.selected = number;
      if (state.folded.delete(foldKey(state, number)) && state.last && !root.classList.contains("strip")) redraw(root, state);
    }
    for (const entry of root.querySelectorAll(".ent")) {
      entry.classList.toggle("sel", Number(entry.dataset.n) === number);
    }
  }

  // The entry of a marker the pointer is on, or none (COM-07).
  function highlight(root, number) {
    for (const entry of root.querySelectorAll(".ent")) {
      entry.classList.toggle("hot", Number(entry.dataset.n) === number);
    }
  }

  window.renderComments = renderComments;
  window.commentsUi = {
    renderComments, renderStrip, openCommentBox, placeBox, select, highlight, anchorLabel,
    hasForms, hasTypedText,
  };
})();
