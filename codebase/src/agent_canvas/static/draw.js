// Trusted shell: the send icon, keyboard shortcuts and send (DRAW-05, FB-04;
// draw mode was withdrawn in revision 12). Loaded before shell.js, which
// hands over its internals through ``window.__shell`` and calls ``window.drawUi``.
"use strict";

(function () {
  const CAPTURE_TIMEOUT_MS = 5000;

  const sendButton = document.getElementById("send-button");
  const sendToast = document.getElementById("send-toast");
  const mainArea = document.querySelector("main");

  let shell = null;           // internals of shell.js, set on first use
  let sending = false;
  let toastTimer = null;
  const seenSend = new Map(); // tab id -> the newest send as last seen, to catch it turning read
  let nextCapture = 1;
  const captures = new Map(); // capture id -> resolve

  function internals() {
    if (!shell) shell = window.__shell;
    return shell;
  }

  function currentDraft() {
    const tab = internals().activeTab();
    return tab ? internals().draftOf(tab.id) : null;
  }

  // ---- shortcuts -------------------------------------------------------------------

  const EDITABLE_INPUTS = new Set([
    "text", "search", "url", "tel", "email", "password", "number", "date",
    "datetime-local", "month", "time", "week",
  ]);

  function isEditable(element) {
    if (!element || element.nodeType !== 1) return false;
    if (element.isContentEditable) return true;
    if (element.tagName === "TEXTAREA" || element.tagName === "SELECT") return true;
    return element.tagName === "INPUT" && EDITABLE_INPUTS.has((element.type || "text").toLowerCase());
  }

  // ``descriptor``: {key, ctrl, shift, alt, editable}. Returns True when handled. Keys with Ctrl
  // or Alt also work in a text field; the plain keys are the page's there.
  function handleKey(descriptor) {
    const key = String(descriptor.key || "");
    const mods = {ctrl: descriptor.ctrl, shift: descriptor.shift, alt: descriptor.alt};
    if (keyHelp.isOpen()) return keyHelp.key(key, mods);
    if (keyMap.is("send.now", key, mods)) {
      sendDraft();
      return true;
    }
    if (descriptor.editable && !mods.ctrl && !mods.alt) return false;
    // The window keys (KEY-01 to KEY-03) come before the comment keys; in comment mode
    // windowKey leaves the comment keys to commentKey (KMAP-04).
    if (internals().windowKey(key, mods)) return true;
    return internals().commentKey(key, mods);
  }

  document.addEventListener("keydown", (event) => {
    if (event.metaKey) return;
    const handled = handleKey({
      key: event.key, ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey,
      editable: isEditable(event.target),
    });
    if (handled) event.preventDefault();
  });

  // ---- send icon -----------------------------------------------------------------

  // The draft is empty without actions that did not already produce an event
  // (glossary); a click in an answer card produced its own (FB-05). Comments not
  // sent count as draft content (COM-10).
  const counts = (action) => !action.event && !action.card;

  function isEmpty(draft) {
    return !draft.actions.some(counts) && internals().unsentComments().comments === 0;
  }

  // The send icon shows only while something waits to be sent.
  function updateBar() {
    const draft = currentDraft();
    const empty = !draft || isEmpty(draft);
    sendButton.hidden = empty;
    sendButton.disabled =
      sending || empty || internals().isViewing() || internals().isOffline() ||
      internals().commentsBusy();
    announceRead(internals().activeTab());
  }

  // FB-10: a send seen unread that turns read gets one short message.
  function announceRead(tab) {
    const send = tab && tab.send;
    if (!send) return;
    const before = seenSend.get(tab.id);
    seenSend.set(tab.id, send);
    if (before && before.time === send.time && !before.read && send.read) showToast("Read by the agent");
  }

  sendButton.addEventListener("click", () => sendDraft());

  // A short floating line that fades out; each call shows it again.
  function showToast(text, error = false, ms = 2500) {
    sendToast.textContent = text;
    sendToast.classList.toggle("error", error);
    sendToast.classList.remove("visible");
    void sendToast.offsetWidth; // restart the fade
    sendToast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => sendToast.classList.remove("visible"), ms);
  }

  // ---- capture and send (DRAW-05) --------------------------------------------------

  function captureTimeout() {
    return Number(window.__captureTimeoutMs) || CAPTURE_TIMEOUT_MS;
  }

  // Ask the helper for the page image; resolves with its answer or, after the
  // timeout, with a failure (the page may be hung, PAGE-10).
  function requestCapture() {
    const frame = internals().getFrame();
    const id = nextCapture++;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        captures.delete(id);
        const seconds = captureTimeout() / 1000;
        resolve({ok: false, error: `screenshot timed out after ${seconds} s`});
      }, captureTimeout());
      captures.set(id, (result) => { clearTimeout(timer); resolve(result); });
      frame.contentWindow.postMessage({type: "capture", id}, "*");
    });
  }

  function onCaptureResult(result) {
    const resolve = captures.get(result.id);
    if (!resolve) return;
    captures.delete(result.id);
    resolve(result);
  }

  function loadImage(source) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("the page image could not be decoded"));
      image.src = source;
    });
  }

  // The page image at the viewport size, as base64 PNG (1 image px per CSS px).
  async function scaled(dataUrl, viewport) {
    const image = await loadImage(dataUrl);
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const target = canvas.getContext("2d");
    target.drawImage(image, 0, 0, viewport.width, viewport.height);
    return canvas.toDataURL("image/png").split(",")[1];
  }

  function fallbackViewport() {
    return {
      width: Math.round(mainArea.clientWidth), height: Math.round(mainArea.clientHeight),
      scroll_x: 0, scroll_y: 0,
    };
  }

  async function sendDraft() {
    const tab = internals().activeTab();
    const draft = currentDraft();
    if (!tab || !draft || sending || isEmpty(draft)) return;
    if (internals().isViewing() || internals().isOffline() || internals().commentsBusy()) return;
    sending = true;
    updateBar();
    try {
      await deliver(tab, draft);
    } finally {
      sending = false;
      updateBar();
    }
  }

  async function deliver(tab, draft) {
    const capture = await requestCapture();
    const viewport = capture.viewport || fallbackViewport();
    let screenshot = null;
    let error = capture.ok ? null : capture.error || "screenshot failed";
    if (capture.ok) {
      try {
        screenshot = await scaled(capture.png, viewport);
      } catch (failure) {
        error = `screenshot failed: ${failure.message}`;
      }
    }
    const answer = await internals().api("POST", `/api/sessions/${encodeURIComponent(tab.id)}/send`, {
      delivery: "now", message: "", page: tab.page,
      pages: tab.pages.filter((name) => name !== tab.page),
      actions: draft.actions, actions_dropped: draft.actions_dropped, viewport,
      screenshot, screenshot_error: screenshot ? null : error,
      screenshot_warnings: capture.warnings || [],
    });
    if (!answer) {
      showToast("Not sent: the hub refused the send. Your draft is kept.", true, 8000);
      return;
    }
    clearDraft(draft);
    if (error) showToast(`Sent without a screenshot (${error}).`, true, 8000);
    else if (tab.state === "ended") showToast("Sent \u2014 but the session has ended", true);
    else showToast("Sent \u2014 agent will read it next turn");
    internals().refreshComments(); // the hub marked the comments sent
  }

  function clearDraft(draft) {
    draft.actions.length = 0;
    draft.actions_dropped = 0;
    updateBar();
  }

  window.drawUi = {
    handleKey, isEditable, updateBar, onCaptureResult, isEmpty,
    isSending: () => sending,
  };
})();
