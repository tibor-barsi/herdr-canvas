// Trusted shell: the outbox of comment changes (COM-16). While the hub is away,
// saves, edits, deletions, replies, done and reopen wait here in order and are
// sent one by one when it is back. Kept in memory only.
"use strict";

(function () {
  const CAP_BYTES = 20 * 1024 * 1024;
  const RETRY_MS = 1000;
  const TOO_MUCH = "Offline: too much waiting; wait for the canvas to reconnect";
  const UNREACHABLE = "The hub is not reachable.";

  /**
   * Make an outbox.
   *
   * ``isOffline()`` tells whether the hub connection is down. ``onChange()`` is
   * called when the queue changes. ``onApplied(entry, data)`` is called for a
   * queued request the hub accepted, ``onRefused(entry, message)`` for one it
   * refused (dropped); ``onFlushed()`` when the queue has been emptied.
   */
  function createOutbox({isOffline, onChange, onApplied, onRefused, onFlushed}) {
    const queue = [];
    let bytes = 0;
    let flushing = false;
    let inflight = false;
    let retry = null;
    let counter = 0;

    async function post(path, body) {
      try {
        const response = await fetch(path, {
          method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
        });
        return {ok: response.ok, data: await response.json().catch(() => ({}))};
      } catch (error) {
        return {ok: false, unreachable: true, data: {message: UNREACHABLE}};
      }
    }

    function enqueue(path, body, view, first) {
      const size = JSON.stringify(body).length;
      const cap = Number(window.__outboxCapBytes) || CAP_BYTES;
      if (bytes + size > cap) return {ok: false, data: {message: TOO_MUCH}};
      const entry = {path, body, size, view};
      if (first) queue.unshift(entry); else queue.push(entry);
      bytes += size;
      scheduleRetry();
      onChange();
      return {ok: true, queued: true, data: {}};
    }

    function scheduleRetry() {
      if (retry !== null) return;
      retry = setTimeout(() => {
        retry = null;
        if (!isOffline()) flush();
      }, RETRY_MS);
    }

    /**
     * Send a change now, or queue it when the hub is away or older changes wait.
     * Resolves to ``{ok, data}``, plus ``queued: true`` when it was queued. A
     * refusal by the hub is never queued. Every change carries a ``request_id``
     * that the hub answers again without applying, should the answer be lost.
     */
    async function submit(path, plain, view) {
      counter += 1;
      const body = {...plain, request_id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${counter}`};
      if (queue.length || inflight || isOffline()) return enqueue(path, body, view);
      inflight = true;
      onChange();
      let result;
      try {
        result = await post(path, body);
      } finally {
        inflight = false;
      }
      if (result.unreachable) return enqueue(path, body, view, true);
      onChange();
      if (queue.length) flush();
      return result;
    }

    async function flush() {
      if (flushing) return;
      if (inflight) return scheduleRetry();
      flushing = true;
      try {
        while (queue.length) {
          const head = queue[0];
          const result = await post(head.path, head.body);
          if (result.unreachable) {
            scheduleRetry();
            return;
          }
          queue.shift();
          bytes -= head.size;
          if (result.ok) onApplied(head, result.data);
          else onRefused(head, result.data.message || "A change was not saved.");
          onChange();
        }
        onFlushed();
      } finally {
        flushing = false;
      }
    }

    return {
      submit, flush,
      size: () => queue.length,
      count: (matches) => queue.filter((entry) => matches(entry.path)).length,
      busy: () => queue.length > 0 || inflight,
      bytes: () => bytes,
      views: () => queue.map((entry) => entry.view).filter(Boolean),
    };
  }

  window.createOutbox = createOutbox;
})();
