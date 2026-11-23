// Trusted shell: the answer relay (ANS-02, SEC-09). It hands the stored items of the
// page in the frame to the frame, only that page's (5.16), and passes the frame's
// `answer` and `tick` messages to the hub with the owner's cookie. The page and
// session of a request come from the active tab, never from the message, so a
// forged message reaches only the items of the page that is shown. Answers and
// ticks go through the shell's outbox, so they wait while the hub is away (HUB-09).
// An answer or tick that arrives with no recent click or key press of the owner goes
// as ``no_gesture``; the hub marks it as not from the owner (SEC-09).
// A `copy` message names a Do step, or a file path or source line (`kind`, `text`) that
// the hub must find in the page file; the shell puts the hub's text on the clipboard,
// only just after a real click (DO-02, CNT-03, CNT-04, A-88). An `open-file` needs one too.
// Only the helper can send `copy` (over the private port, after the owner's click), so a
// copy refused here says why; a second one within the gap stays silent (A-441).
"use strict";

(function () {
  const MAX_ID = 200;
  const MAX_TICKS = 50;
  const COPY_GAP_MS = 1000;
  const NOTE_CHARS = 80;
  const MAX_STEPS = 20;
  const MAX_COPY_TEXT = 500;
  const COPY_KINDS = ["path", "source"];
  const OPENABLE = /^[^/\\\0]+\.(md|markdown|pdf|png|jpe?g|gif|webp|svg)$/i;

  function plain(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  /**
   * Make the relay. ``activeTab()`` gives the shown tab (``id``, ``page``),
   * ``postToFrame(message)`` writes to the frame, ``requestItems(session, page)``
   * asks the hub for a page's items, ``isOldVersion()`` tells whether an earlier
   * version is shown, ``notify(text)`` shows a notice, ``submit(path, body)`` sends
   * a request through the outbox (resolves to ``{ok, data}``) and
   * ``showCopied(text, copied)`` shows the "Copied" note, or the text in a field to
   * select when the clipboard refused it; ``copyFailed(reason)`` says why a copy failed.
   */
  function createAnswerRelay({
    activeTab, postToFrame, requestItems, isOldVersion, notify, submit, showCopied, copyFailed,
  }) {
    const items = new Map();
    const folders = new Map();
    let lastCopy = -Infinity;
    let live = false;
    let sentEnded = null;
    const keyOf = (session, page) => `${session}\n${page}`;

    function toFrame() {
      const tab = activeTab();
      if (!live || !tab || !tab.page) return;
      const known = items.get(keyOf(tab.id, tab.page));
      const folder = folders.get(keyOf(tab.id, tab.page));
      if (!known) return;
      sentEnded = tab.state === "ended"; // the cards then say no agent will read (ANS-08)
      postToFrame({type: "answers", items: known, folder, ended: sentEnded});
    }

    function ask() {
      const tab = activeTab();
      if (tab && tab.page) requestItems(tab.id, tab.page);
    }

    async function post(tail, body) {
      const tab = activeTab();
      if (!live || !tab || !tab.page || isOldVersion()) return;
      const path = `/api/sessions/${encodeURIComponent(tab.id)}/answers/${tail}`;
      const result = await submit(path, {page: tab.page, ...body});
      if (!result.ok) notify(result.data.message || "The answer was not saved.");
    }

    const activated = () => navigator.userActivation.isActive;

    async function copy(message) {
      const tab = activeTab();
      const now = Date.now();
      if (isOldVersion() || now - lastCopy < COPY_GAP_MS) return;
      if (!live || !tab || !tab.page) return copyFailed("the page is still loading; press Copy again.");
      if (!activated()) return copyFailed("the browser did not count it as your click; press Copy again.");
      lastCopy = now;
      const query = new URLSearchParams({page: tab.page, ...message});
      let text;
      try {
        const response = await fetch(
          `/api/sessions/${encodeURIComponent(tab.id)}/answers/copy?${query}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) return copyFailed(data.message || `the canvas answered ${response.status}.`);
        text = data.text;
      } catch (error) {
        return copyFailed("the canvas is not reachable.");
      }
      if (typeof text !== "string") return;
      const first = text.split("\n")[0];
      const note = first.length > NOTE_CHARS || first !== text ? `${first.slice(0, NOTE_CHARS)}…` : first;
      try {
        await navigator.clipboard.writeText(text);
        showCopied(note, true);
      } catch (error) {
        showCopied(text, false);
      }
    }

    // Only a plain file name of a viewer type leaves the shell; the hub checks it again.
    async function open(message) {
      const tab = activeTab();
      const {path} = message;
      if (!live || !tab || !tab.page || isOldVersion() || !activated()) return;
      if (typeof path !== "string" || path.length > MAX_ID || !OPENABLE.test(path)) return;
      try {
        const response = await fetch(`/api/sessions/${encodeURIComponent(tab.id)}/open-file`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({name: path}),
        });
        if (!response.ok) notify((await response.json()).message || "The file was not opened.");
      } catch (error) {
        notify("The file was not opened.");
      }
    }

    return {
      /** The hub's ``answers`` message: keep the page's items, show them if shown. */
      onHubMessage(message) {
        if (typeof message.session !== "string" || typeof message.page !== "string") return;
        if (!plain(message.items)) return;
        items.set(keyOf(message.session, message.page), message.items);
        folders.set(keyOf(message.session, message.page), message.folder);
        const tab = activeTab();
        if (tab && tab.id === message.session && tab.page === message.page) toFrame();
      },
      /** The frame starts loading a page: the document in it is not served until it is ready. */
      onLoadBegin() {
        live = false;
      },
      /**
       * A document in the frame said ready; ``current`` tells whether it is the page
       * of the load in progress. Give it what is known, ask for the rest.
       */
      onFrameReady(current) {
        if (!current) return;
        live = true;
        toFrame();
        ask();
      },
      /** The shown page changed (a tab, a page, a version). */
      onPageChanged: ask,
      /** The tabs changed: tell the frame when its session has ended since (ANS-08). */
      onTabs() {
        const tab = activeTab();
        if (tab && (tab.state === "ended") !== sentEnded) toFrame();
      },
      onFrameAnswer(message) {
        const {id, value, seen} = message;
        if (typeof id !== "string" || !id || id.length > MAX_ID || !plain(value)) return;
        const gesture = activated() ? {} : {no_gesture: true};
        return post("answer", {id, value, seen: plain(seen) ? seen : undefined, ...gesture});
      },
      onFrameTick(message) {
        const {id, ticked} = message;
        if (typeof id !== "string" || !id || id.length > MAX_ID) return;
        if (!Array.isArray(ticked) || ticked.length > MAX_TICKS) return;
        if (!ticked.every((n) => Number.isInteger(n))) return;
        return post("tick", {id, ticked, ...(activated() ? {} : {no_gesture: true})});
      },
      /** A Do step's Copy ``{id, step}``, or a path or source line ``{kind, text}``; the text copied comes from the hub. */
      onFrameCopy(message) {
        const {id, step, kind, text} = message;
        if (COPY_KINDS.includes(kind)) {
          if (typeof text !== "string" || !text || text.length > MAX_COPY_TEXT) return;
          return copy({kind, text});
        }
        if (typeof id !== "string" || !id || id.length > MAX_ID) return;
        if (!Number.isInteger(step) || step < 1 || step > MAX_STEPS) return;
        return copy({id, step});
      },
      /** A document block's Open: ``{path}``, a plain file name in the session folder (CNT-01). */
      onFrameOpen(message) {
        return open(message);
      },
    };
  }

  window.createAnswerRelay = createAnswerRelay;
})();
