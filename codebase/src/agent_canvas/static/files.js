// Opening dropped files (PAGE-06, VIEW-09, VIEW-10).
// The shell hands in what it owns through ``fileUi.init``; nothing else is read from it.
"use strict";

(function () {
  const MAX_BYTES = 64 * 1024 * 1024;
  const NO_SESSION = "No running session to open it in";

  let context = null;
  let dialog = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function refusal(response) {
    try {
      return (await response.json()).message || `HTTP ${response.status}`;
    } catch (error) {
      return `HTTP ${response.status}`;
    }
  }

  async function uploadOne(session, file) {
    if (!context.allowed(file.name)) {
      context.notice(`${file.name} was not opened: only HTML, Markdown, PDF and pictures can be opened.`);
      return null;
    }
    if (file.size > MAX_BYTES) {
      context.notice(`${file.name} was not opened: it is larger than 64 MB.`);
      return null;
    }
    const url = `/api/sessions/${encodeURIComponent(session)}/files?name=${encodeURIComponent(file.name)}`;
    try {
      const response = await fetch(url, {
        method: "POST", headers: {"Content-Type": "application/octet-stream"}, body: file,
      });
      if (response.ok) return await response.json();
      context.notice(`${file.name} was not opened: ${await refusal(response)}`);
    } catch (error) {
      context.notice(`${file.name} was not opened: the hub did not answer.`);
    }
    return null;
  }

  // Files go one after the other; the last one that arrived is the one shown.
  async function openFiles(session, files) {
    let last = null;
    for (const file of files) last = (await uploadOne(session, file)) || last;
    if (last) context.openPage(last.session, last.page);
  }

  // ---- drop targets -----------------------------------------------------------

  function carriesFiles(event) {
    const types = event.dataTransfer ? Array.from(event.dataTransfer.types || []) : [];
    return types.includes("Files");
  }

  // A file dropped on a session's card opens in that session.
  function tabUnder(event) {
    return event.target.closest ? event.target.closest(".hv-card[data-session]") : null;
  }

  function markDrop(wrapper) {
    for (const old of document.querySelectorAll(".hv-card.drop-target")) {
      if (old !== wrapper) old.classList.remove("drop-target");
    }
    if (wrapper) wrapper.classList.add("drop-target");
  }

  function endDrag() {
    document.body.classList.remove("file-drag");
    markDrop(null);
  }

  function onDrag(event) {
    if (!carriesFiles(event) || dialog) return;
    event.preventDefault();
    document.body.classList.add("file-drag");
    markDrop(tabUnder(event));
  }

  function onDrop(event) {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    const wrapper = tabUnder(event);
    const files = Array.from(event.dataTransfer.files);
    endDrag();
    if (dialog || !files.length) return;
    if (wrapper) openFiles(wrapper.dataset.session, files);
    else askSession(files);
  }

  document.addEventListener("dragenter", onDrag);
  document.addEventListener("dragover", onDrag);
  document.addEventListener("dragleave", (event) => {
    if (event.relatedTarget === null) endDrag();
  });
  document.addEventListener("drop", onDrop);

  // ---- the session dialog (VIEW-09) --------------------------------------------

  function closeDialog() {
    if (dialog) dialog.remove();
    dialog = null;
  }

  function sessionLabel(session) {
    const project = String(session.project || "").split("/").filter(Boolean).pop() || "project";
    return `${project} · ${session.agent} · ${session.title}`;
  }

  function askSession(files) {
    const running = context.sessions().filter((s) => !s.ended && s.state !== "ended");
    dialog = element("div", "file-dialog");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", "Open in which session?");
    const box = element("form", "file-dialog-box");
    box.append(element("h2", "", files.length === 1 ? `Open ${files[0].name} in` : `Open ${files.length} files in`));
    const close = element("button", "file-cancel", running.length ? "Cancel" : "Close");
    close.type = "button";
    close.addEventListener("click", closeDialog);
    if (!running.length) {
      box.append(element("p", "file-none", NO_SESSION), close);
    } else {
      const active = context.activeId();
      const chosen = running.some((s) => s.id === active) ? active : running[0].id;
      const group = element("div", "file-sessions");
      group.setAttribute("role", "radiogroup");
      for (const session of running) {
        const label = element("label", "file-session");
        const radio = element("input");
        radio.type = "radio";
        radio.name = "file-session";
        radio.value = session.id;
        radio.checked = session.id === chosen;
        label.append(radio, element("span", "", sessionLabel(session)));
        group.append(label);
      }
      const open = element("button", "file-confirm", "Open");
      open.type = "submit";
      const buttons = element("div", "file-buttons");
      buttons.append(close, open);
      box.append(group, buttons);
      box.addEventListener("submit", (event) => {
        event.preventDefault();
        const picked = box.querySelector("input:checked");
        closeDialog();
        if (picked) openFiles(picked.value, files);
      });
    }
    dialog.addEventListener("keydown", (event) => {
      event.stopPropagation(); // the shell's single-key shortcuts must not fire here
      if (event.key === "Escape") closeDialog();
    });
    dialog.append(box);
    document.body.append(dialog);
    (box.querySelector("input:checked") || close).focus();
  }

  // The keyboard's way to open files: the browser's file chooser, then the same dialog as a drop.
  function pick() {
    const input = element("input");
    input.type = "file";
    input.multiple = true;
    input.addEventListener("change", () => {
      const files = Array.from(input.files);
      if (files.length && !dialog) askSession(files);
    });
    input.click();
  }

  window.fileUi = {
    pick,
    init(given) { context = given; },
    isDialogOpen: () => dialog !== null,
  };
})();
