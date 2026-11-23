// Hidden-frame rendering for ``look`` (LOOK-03 to LOOK-06, LOOK-09).
//
// The owner's window (shell.js) and the hub's render host page (render.html, for
// the headless fallback) both load this file. ``prepare`` puts a page in a
// sandboxed frame of the requested size, waits until the page and its blocks are
// rendered, and measures it. ``run`` (the window) then captures the frame with
// the helper's snapdom path and crops it; the render host leaves the screenshot
// to the browser.
"use strict";

(function () {
  const SECTION_PADDING = 8;
  const MAX_FRAME_HEIGHT = 16000;
  const MAX_PNG_CHARS = 9 * 1024 * 1024;
  const PREPARE_PASSES = 3;
  const DEFAULT_SETTLE_MS = 5000;
  const CAPTURE_TIMEOUT_MS = 6000;
  const AUDIT_TIMEOUT_MS = 4000;
  const RUN_DEADLINE_MS = 9000;
  const MAX_ERRORS = 50;
  const SCHEMES = ["light", "dark"];

  const frames = new Set();     // frames of renders in progress
  let nextId = 1;

  /** True for the window of a hidden render frame (the shell ignores its messages). */
  function owns(source) {
    if (source === null || source === undefined) return false;
    for (const frame of frames) {
      if (frame.contentWindow === source) return true;
    }
    return false;
  }

  /**
   * The box of an element, padded and clamped to the image; null if it has no
   * visible area. The same maths as ``crop_region`` in hub/looks.py.
   */
  function cropBox(rect, padding, width, height) {
    if (!(rect.width > 0) || !(rect.height > 0)) return null;
    const left = Math.max(0, Math.floor(rect.x - padding));
    const top = Math.max(0, Math.floor(rect.y - padding));
    const right = Math.min(width, Math.ceil(rect.x + rect.width + padding));
    const bottom = Math.min(height, Math.ceil(rect.y + rect.height + padding));
    if (right <= left || bottom <= top) return null;
    return {x: left, y: top, width: right - left, height: bottom - top};
  }

  function currentScheme() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function clip(value, limit) {
    return String(value === undefined || value === null ? "" : value).slice(0, limit);
  }

  function normalizeError(data) {
    return {
      source: clip(data.source || "script", 20),
      message: clip(data.message, 500),
      line: Number.isInteger(data.line) ? data.line : null,
      canvas_id: typeof data.canvas_id === "string" ? data.canvas_id : null,
    };
  }

  function failure(message, code) {
    const error = new Error(message);
    error.code = code || "";
    return error;
  }

  // Messages with the page inside one render frame: replies are matched by id;
  // the page's own reports (load, errors) are collected.
  function listen(frame, errors, seen) {
    const waiting = new Map();
    let markLoaded;
    const loaded = new Promise((resolve) => { markLoaded = resolve; });
    function onMessage(event) {
      if (event.source !== frame.contentWindow) return;
      const message = event.data;
      if (!message || typeof message.type !== "string") return;
      if (message.type === "report") {
        if (message.name === "loaded") markLoaded(true);
        else if (message.name === "viewer-error" && message.data && typeof message.data.reason === "string") {
          seen.viewerError = clip(message.data.reason, 40);
        }
        else if (message.name === "error" && message.data && typeof message.data === "object"
            && errors.length < MAX_ERRORS) errors.push(normalizeError(message.data));
      } else if (waiting.has(message.id)) {
        const resolve = waiting.get(message.id);
        waiting.delete(message.id);
        resolve(message);
      }
    }
    window.addEventListener("message", onMessage);
    function ask(message, timeoutMs) {
      const id = "r" + nextId++;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          waiting.delete(id);
          reject(failure("the page did not answer the renderer"));
        }, Math.max(100, timeoutMs));
        waiting.set(id, (reply) => { clearTimeout(timer); resolve(reply); });
        frame.contentWindow.postMessage(Object.assign({id}, message), "*");
      });
    }
    return {loaded, ask, stop: () => window.removeEventListener("message", onMessage)};
  }

  // The helper in a render frame switches focusing off when it sees this marker.
  function markedUrl(url) {
    const marked = new URL(url, location.href);
    marked.searchParams.set("ac-render", "1");
    return marked.href;
  }

  function styleHidden(wrapper, width, height) {
    wrapper.style.cssText = "position:fixed;left:0;top:0;opacity:0;pointer-events:none;"
      + `z-index:-1;overflow:hidden;width:${width}px;height:${height}px;`;
  }

  function styleVisible(wrapper, width, height) {
    wrapper.style.cssText = `position:absolute;left:0;top:0;width:${width}px;height:${height}px;`;
  }

  /**
   * Load ``request.url`` in a sandboxed frame of ``request.width`` by
   * ``request.height`` inside ``host`` and get it ready for a picture.
   *
   * The frame is off-screen and inert unless ``visible`` (the render host page),
   * has the shell frame's sandbox and CSP (the hub adds the CSP to the page) and
   * never takes focus. Resolves with ``{data, ask, dispose}``; ``data`` holds
   * ``errors``, ``notes``, ``rect`` (the section's box), ``frame_height``,
   * ``settled``, ``audit`` and ``viewer_error`` (the reason a viewer
   * could not show its file, VIEW-14). Rejects with an error whose ``code`` is
   * ``section`` when the element is not on the page. ``track`` receives the
   * function that removes the frame, at once, so that a caller can cut it short.
   */
  async function prepare(request, host, visible, track) {
    const settleMs = Number(request.settle_ms) || DEFAULT_SETTLE_MS;
    const started = performance.now();
    const left = () => settleMs - (performance.now() - started);
    const wrapper = document.createElement("div");
    wrapper.setAttribute("aria-hidden", "true");
    if (!visible) wrapper.setAttribute("inert", "");
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("title", "render");
    frame.setAttribute("tabindex", "-1");
    frame.style.cssText = "border:0;display:block;width:100%;height:100%;background:#fff;";
    const resize = (height) => (visible ? styleVisible : styleHidden)(
      wrapper, request.width, height);
    resize(request.height);
    wrapper.append(frame);
    frames.add(frame);
    const errors = [];
    const notes = [];
    const seen = {viewerError: null};
    const conversation = listen(frame, errors, seen);
    const dispose = () => {
      conversation.stop();
      frames.delete(frame);
      wrapper.remove();
    };
    if (track) track(dispose);
    try {
      host.append(wrapper);
      frame.src = markedUrl(request.url);
      if (await Promise.race([conversation.loaded, sleep(left()).then(() => false)]) !== true) {
        notes.push("the page did not finish loading in time");
      }
      // The stored answers, as the window hands them over, so answered cards look answered.
      if (request.answers && request.answers.items) {
        frame.contentWindow.postMessage(
          {type: "answers", items: request.answers.items, folder: request.answers.folder}, "*");
      }
      const wantsHeight = Boolean(request.full || request.section);
      const ask = (timeoutMs) => conversation.ask({
        type: "render-prepare", timeout: Math.max(300, timeoutMs),
        section: typeof request.section === "string" ? request.section : null,
      }, timeoutMs + 1500);
      let reply = await ask(left());
      // The checks look at the page at the size the owner has, before the frame
      // grows for a full-page picture.
      let audit = null;
      if (request.audit !== false) {
        audit = await conversation.ask(
          {type: "render-audit", viewport_height: request.height}, AUDIT_TIMEOUT_MS)
          .then((answer) => answer.result, () => {
            notes.push("the page checks did not finish in time");
            return null;
          });
      }
      // The checks take seconds and the page goes on growing meanwhile (blocks,
      // images, late scripts): measure again, or the picture ends at the old height.
      if (wantsHeight && request.audit !== false) {
        reply = await ask(Math.min(1500, Math.max(300, left())));
      }
      let frameHeight = request.height;
      for (let pass = 0; wantsHeight && pass < PREPARE_PASSES; pass++) {
        const wanted = Math.min(MAX_FRAME_HEIGHT, Math.max(request.height, reply.height));
        if (wanted === frameHeight) break;
        frameHeight = wanted;
        resize(frameHeight);
        await sleep(120);
        reply = await ask(Math.min(1500, Math.max(300, left())));
      }
      if (wantsHeight && reply.height > MAX_FRAME_HEIGHT) {
        notes.push(`the page is taller than ${MAX_FRAME_HEIGHT}px; the picture ends there`);
      }
      if (!reply.settled) {
        notes.push("the page did not settle in time (a block or image is still "
          + "working); it was captured as it was");
      }
      if (typeof request.section === "string") checkSection(request.section, reply);
      return {
        data: {
          ok: true, errors, notes, settled: Boolean(reply.settled), audit,
          viewer_error: seen.viewerError,
          rect: reply.rect, frame_height: frameHeight,
        },
        ask: conversation.ask,
        dispose,
      };
    } catch (error) {
      dispose();
      throw error;
    }
  }

  function checkSection(id, reply) {
    if (!reply.found) {
      throw failure(`no element with id or data-canvas-id "${id}" on the page`, "section");
    }
    if (!reply.rect || !(reply.rect.width > 0) || !(reply.rect.height > 0)) {
      throw failure(`the element "${id}" has no visible area (is it hidden?)`, "section");
    }
  }

  function loadImage(dataUrl) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("the captured image cannot be decoded"));
      image.src = dataUrl;
    });
  }

  async function cropPicture(dataUrl, box) {
    const image = await loadImage(dataUrl);
    const canvas = document.createElement("canvas");
    canvas.width = box.width;
    canvas.height = box.height;
    canvas.getContext("2d").drawImage(
      image, box.x, box.y, box.width, box.height, 0, 0, box.width, box.height);
    return canvas.toDataURL("image/png");
  }

  // Capture the prepared frame with the helper's snapdom path (as a send does).
  async function capture(prepared, request) {
    const reply = await prepared.ask({type: "capture", points: [], boxes: []}, CAPTURE_TIMEOUT_MS);
    if (!reply.ok) throw failure(reply.error || "the screenshot failed");
    for (const warning of reply.warnings || []) {
      if (warning && warning.reason) {
        prepared.data.notes.push(`${warning.canvas_id || warning.selector || "canvas"}: ${warning.reason}`);
      }
    }
    if (typeof request.section !== "string") return reply.png;
    const data = prepared.data;
    const box = cropBox(data.rect, SECTION_PADDING, request.width, data.frame_height);
    if (!box) throw failure(`the element "${request.section}" is outside the page`, "section");
    return cropPicture(reply.png, box);
  }

  // Keep the owner's focus where it was, whatever the rendered page tried.
  function keepFocus() {
    const focused = document.activeElement;
    return () => {
      if (focused && focused.isConnected && document.activeElement !== focused
          && typeof focused.focus === "function") {
        focused.focus({preventScroll: true});
      }
    };
  }

  /**
   * Render ``request`` in the owner's window and answer for the hub. Never
   * rejects: a failure is ``{ok: false, error, code}``.
   */
  async function run(request) {
    const restoreFocus = keepFocus();
    const disposers = [];
    let timer = null;
    const work = (async () => {
      const prepared = await prepare(request, document.body, false, (d) => disposers.push(d));
      // A request without a picture (the audit after ``show``) captures nothing.
      const dataUrl = request.picture === false ? "," : await capture(prepared, request);
      const png = dataUrl.slice(dataUrl.indexOf(",") + 1);
      if (png.length > MAX_PNG_CHARS) {
        throw failure("the picture is larger than 10 MB; use --section or a smaller size");
      }
      const data = prepared.data;
      return {
        ok: true, png, scheme: currentScheme(), errors: data.errors,
        audit: data.audit, notes: data.notes, viewer_error: data.viewer_error,
      };
    })();
    const deadline = new Promise((resolve) => {
      timer = setTimeout(() => resolve({ok: false, error: "the render took too long"}), RUN_DEADLINE_MS);
    });
    try {
      return await Promise.race([work, deadline]);
    } catch (error) {
      return {ok: false, error: String(error && error.message ? error.message : error),
        code: error && error.code ? error.code : ""};
    } finally {
      clearTimeout(timer);
      work.catch(() => {});
      for (const dispose of disposers) dispose();
      restoreFocus();
    }
  }

  // The render host page: prepare in its body and keep the frame for the
  // browser's screenshot. Resolves with plain data for ``page.evaluate``.
  async function prepareHost(request) {
    try {
      const prepared = await prepare(request, document.body, true);
      window.canvasRender.current = prepared;
      return prepared.data;
    } catch (error) {
      return {ok: false, error: String(error && error.message ? error.message : error),
        code: error && error.code ? error.code : ""};
    }
  }

  window.canvasRender = {
    owns, run, prepare, prepareHost, cropBox, currentScheme, SCHEMES, current: null,
  };
})();
