// Trusted shell: notices that the hub was updated while this tab stayed open
// (SHELL-03, SHELL-04). The page records the build it was loaded with (a meta
// tag the hub fills in); the hub names its build on every (re)connect. A
// different build means this tab runs old JavaScript: reload it by itself when
// the owner has nothing unsaved, else show a banner and let the owner decide.
"use strict";

(function () {
  const RESTORE_KEY = "agent-canvas-restore";
  const RELOADED_KEY = "agent-canvas-reloaded-for";
  const meta = document.querySelector('meta[name="agent-canvas-build"]');
  // Unfilled placeholder (a page not served by the hub): no identity, no checks.
  const loadedBuild = meta && !meta.content.startsWith("__") ? meta.content : "";
  const banner = document.getElementById("update-bar");
  let restore = readRestore();

  function readRestore() {
    try {
      const stored = sessionStorage.getItem(RESTORE_KEY);
      sessionStorage.removeItem(RESTORE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch (error) {
      return null;
    }
  }

  // The view to come back to after a reload: only returned once.
  function takeRestore() {
    const taken = restore;
    restore = null;
    return taken;
  }

  function saveRestore() {
    const shell = window.__shell;
    const tab = shell.activeTab();
    const viewing = shell.viewing();
    const state = {
      session: tab ? tab.id : null,
      page: viewing ? viewing.page : tab ? tab.page : null,
      version: viewing ? viewing.version : null,
      time: viewing ? viewing.time : null,
    };
    try {
      sessionStorage.setItem(RESTORE_KEY, JSON.stringify(state));
    } catch (error) {
      // No storage: the reload then opens the tab the hub names.
    }
  }

  // A reload by hand keeps the view too (#74): sessionStorage lives as long as the
  // window, so a fresh window finds nothing and follows Herdr. An update reload has
  // saved its own state already.
  window.addEventListener("pagehide", () => {
    try {
      if (sessionStorage.getItem(RESTORE_KEY) === null) saveRestore();
    } catch (error) {
      // No storage: the reload then follows Herdr.
    }
  });

  function reloadNow() {
    saveRestore();
    location.reload();
  }

  // Everything the owner has typed, drawn or recorded and not yet sent.
  function hasUnsaved() {
    const shell = window.__shell;
    const ui = window.drawUi;
    if (ui.isSending() || shell.outboxPending() > 0) return true;
    // Saved comments are not counted: the hub holds them (COM-04).
    for (const id of Object.keys(window.__drafts)) {
      const draft = shell.draftOf(id);
      if (draft.actions.some((a) => !a.event)) return true;
    }
    if (window.commentsUi.hasTypedText(document.getElementById("comment-panel"))) return true;
    const typed = document.querySelectorAll(".cbox textarea, #comment-panel .rform textarea");
    for (const field of typed) {
      if (field.value.trim()) return true;
    }
    return Boolean(window.shellCards) && window.shellCards.hasTyped();
  }

  function showBanner() {
    banner.classList.add("visible");
  }

  function onHello(message) {
    const build = message.build;
    if (!loadedBuild || typeof build !== "string" || build === loadedBuild) {
      banner.classList.remove("visible");
      return;
    }
    let reloadedBefore = false;
    try {
      reloadedBefore = sessionStorage.getItem(RELOADED_KEY) === build;
    } catch (error) {
      reloadedBefore = true; // cannot remember: never risk a reload loop
    }
    if (hasUnsaved() || reloadedBefore) {
      showBanner();
      return;
    }
    sessionStorage.setItem(RELOADED_KEY, build);
    reloadNow();
  }

  // Reload with changes still waiting in the outbox asks first, in the banner.
  const reloadButton = document.getElementById("update-reload");
  const cancelButton = document.getElementById("update-cancel");
  const bannerText = banner.querySelector("span");
  const bannerWords = bannerText.textContent;

  function askBeforeReload(waiting) {
    bannerText.textContent = `${waiting} change${waiting === 1 ? " is" : "s are"} still waiting ` +
      "and will be lost on reload.";
    reloadButton.textContent = "Reload anyway";
    cancelButton.hidden = false;
  }

  function stopAsking() {
    bannerText.textContent = bannerWords;
    reloadButton.textContent = "Reload";
    cancelButton.hidden = true;
  }

  reloadButton.addEventListener("click", () => {
    const waiting = window.__shell.outboxPending();
    if (waiting > 0 && cancelButton.hidden) askBeforeReload(waiting); else reloadNow();
  });
  cancelButton.addEventListener("click", stopAsking);
  window.shellUpdate = {loadedBuild, onHello, hasUnsaved, takeRestore};
})();
