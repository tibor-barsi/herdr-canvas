// Helper injected first in every page's <head>: heartbeat, reports and live
// updates. It talks only to the shell through postMessage (PAGE-10, PAGE-12) and
// accepts messages only from its parent window (SEC-09).
(function () {
  "use strict";
  if (window.agentCanvas) return;

  const HELPER_ATTRIBUTE = "data-agent-canvas-helper";
  const IDIOMORPH_URL = "/static/vendor/idiomorph/idiomorph.min.js";
  const AUDIT_URL = "/static/audit.js";
  const MAX_BLOCKED = 50;
  const JAVASCRIPT_TYPES = new Set([
    "module", "text/javascript", "application/javascript",
    "application/x-javascript", "text/ecmascript", "application/ecmascript",
    "text/jscript", "text/livescript", "text/x-javascript", "text/x-ecmascript",
  ]);
  const HEAD_OPEN = /<head(?:\s[^>]*)?>/i;
  const HTML_OPEN = /<html(?:\s[^>]*)?>/i;

  // A sandboxed page has an opaque origin, so ``import()`` in this classic
  // script has no usable base URL: resolve library URLs against the script's own.
  const HELPER_URL = document.currentScript ? document.currentScript.src : location.href;
  function libraryUrl(path) {
    return new URL(path, HELPER_URL).href;
  }

  // Digest of the source this frame was served (PAGE-13); an update of the same source
  // would only morph away what the page's scripts have built since.
  let loadedDigest = document.currentScript ? document.currentScript.dataset.source : undefined;

  function post(message) {
    window.parent.postMessage(message, "*");
  }

  // ---- the private channel to the shell (DO-02, CNT-03, CNT-01, A-340) ------------------
  //
  // This helper makes one MessagePort pair and hands the shell its other end with the
  // first answer to the shell's ``relay-open`` token, together with the page address it
  // was loaded at (A-577). The port lives only in this closure, so a page script cannot
  // send on it, and Copy and Open of the page's blocks go over it alone: a plain
  // ``postMessage`` of the same kind is refused by the shell. The handler runs first and
  // in the capture phase, answers the shell's message only (``source`` is the parent),
  // and keeps the message from every later listener. The natives, the parent and the
  // address are kept now, before any page script can replace them.
  const eventSource = Object.getOwnPropertyDescriptor(MessageEvent.prototype, "source").get;
  const eventData = Object.getOwnPropertyDescriptor(MessageEvent.prototype, "data").get;
  const stopEvent = Event.prototype.stopImmediatePropagation;
  const portSend = MessagePort.prototype.postMessage;
  const shellWindow = window.parent;
  const loadedAt = location.href;
  const privateChannel = new MessageChannel();
  let portGiven = false;
  window.addEventListener("message", (event) => {
    const data = eventData.call(event);
    if (!data || data.type !== "relay-open") return;
    stopEvent.call(event);
    if (eventSource.call(event) !== shellWindow) return;
    const transfer = portGiven ? [] : [privateChannel.port2];
    portGiven = true;
    shellWindow.postMessage({type: "relay-open", token: data.token, href: loadedAt}, "*", transfer);
  }, true);

  function sendPrivate(message) {
    if (portGiven) portSend.call(privateChannel.port1, message);
    else console.warn("agent-canvas: Copy and Open refused: the page has no private channel to the window.");
  }

  // A render frame (look, show audit) is marked with ``?ac-render=1`` by
  // render.js. Its page must not take the owner's keyboard focus: ``inert`` on
  // the wrapper does not reach into the frame's own document, so focusing is
  // switched off here, before any page script runs (LOOK-03a).
  if (new URLSearchParams(location.search).has("ac-render")) {
    const nothing = function () {};
    for (const prototype of [HTMLElement.prototype, SVGElement.prototype]) {
      Object.defineProperty(prototype, "focus", {
        value: nothing, configurable: true, writable: true,
      });
    }
    window.focus = nothing;
  }

  // The frame has an opaque origin and never holds credentials, but snapdom
  // compares URLs with location.origin (the URL's origin in Chromium) and so
  // fetches same-site assets with credentials "include". A wildcard CORS
  // response then fails, so downgrade that to "omit" (PAGE-12, SEC-06).
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    if (init && init.credentials === "include") {
      init = Object.assign({}, init, {credentials: "omit"});
    }
    return nativeFetch(input, init);
  };

  // Every canvas that was given a WebGL context, for screenshots (DRAW-06): the
  // page cannot be asked later which canvases draw with WebGL.
  const webglCanvases = new Set();
  const webglSeen = new WeakSet();
  const nativeGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
    const context = nativeGetContext.call(this, type, ...rest);
    if (context && /^(experimental-)?webgl2?$/.test(String(type))) {
      if (!webglSeen.has(this)) {
        webglSeen.add(this);
        webglCanvases.add(new WeakRef(this));
      }
    }
    return context;
  };

  function report(name, data) {
    post({type: "report", name, data});
  }

  // ---- comment mode: stop page input first (COM-01) ----------------------------
  //
  // Registered before any page script can add a listener, so that in comment
  // mode clicks never reach the page: this one listener per event type stops
  // them in the capture phase. The comment layer (comments-layer.js, loaded
  // below) only gets the events it needs for its gestures. Wheel, scrollbars
  // and keys are not touched, so the page still scrolls.
  const IS_RENDER_FRAME = new URLSearchParams(location.search).has("ac-render");
  const COMMENT_KINDS = ["text", "point", "rect", "lasso"];
  const mode = {on: false, kind: "rect"};
  const GUARDED_EVENTS = [
    "click", "dblclick", "auxclick", "mousedown", "mouseup", "pointerdown",
    "pointerup", "contextmenu", "dragstart", "selectstart",
  ];
  const SELECTION_EVENTS = ["pointerdown", "pointerup", "mousedown", "mouseup", "selectstart"];
  function commentGuard(event) {
    if (!mode.on) return;
    const layer = window.agentCanvas && window.agentCanvas.commentLayer;
    if (layer) layer.handle(event);
    // The text kind needs the browser's own selection: its pointer and
    // selection defaults stay, the page still never sees the events. The browser's
    // own context menu stays too.
    const keepDefault = event.type === "contextmenu" ||
      (mode.kind === "text" && SELECTION_EVENTS.includes(event.type));
    if (!keepDefault) event.preventDefault();
    event.stopImmediatePropagation();
  }
  for (const name of GUARDED_EVENTS) window.addEventListener(name, commentGuard, true);

  // ---- emit (PAGE-07) --------------------------------------------------------

  const EMIT_DELIVERIES = ["now", "next-message"];
  const BLOCK_EVENT_KINDS = ["button", "choice", "text"];
  const BLOCK_ACTION_KINDS = [
    "select", "input", "plot-click", "plot-select", "image-click", "model-mark", "scene-mark",
  ];

  function plainValue(value) {
    return value === undefined ? null : JSON.parse(JSON.stringify(value));
  }

  // The event target for an element, or for a plain canvas id (a string).
  function targetOf(target) {
    if (target instanceof Element) return describeTarget(target);
    if (typeof target === "string" && target !== "") {
      return {canvas_id: target, selector: null, text: null};
    }
    return null;
  }

  // Ask the shell to create a ``custom`` event; the shell also records the
  // matching action. ``options.target`` (an element or a canvas id) names the
  // element the event comes from. Invalid calls are ignored.
  function emit(name, value, options) {
    if (typeof name !== "string" || name === "") return;
    const delivery = options && options.delivery !== undefined
      ? options.delivery : "now";
    if (!EMIT_DELIVERIES.includes(delivery)) return;
    let plain;
    try {
      plain = plainValue(value);
    } catch (error) {
      return;
    }
    const target = targetOf(options && options.target);
    post({type: "emit", name: name.slice(0, 200), value: plain, delivery, target});
  }

  // For blocks: an event of kind ``button``, ``choice`` or ``text`` from
  // ``element``, whose ``data-canvas-id`` becomes ``target.canvas_id``.
  function blockEvent(kind, element, value, options) {
    if (mode.on) return; // COM-01: comment mode creates no block events
    if (!BLOCK_EVENT_KINDS.includes(kind) || !(element instanceof Element)) return;
    const delivery = options && options.delivery !== undefined
      ? options.delivery : "now";
    if (!EMIT_DELIVERIES.includes(delivery)) return;
    let plain;
    try {
      plain = plainValue(value);
    } catch (error) {
      return;
    }
    post({type: "emit", kind, value: plain, delivery, target: describeTarget(element)});
  }

  // For the cards: hand the owner's answer or ticked steps of the element to the
  // shell, which sends them to the hub for this page (ANS-02, SEC-09).
  function sendAnswer(type, element, field, value, seen) {
    if (mode.on || !(element instanceof Element)) return; // COM-01
    const id = element.getAttribute("data-canvas-id");
    let plain;
    let shown;
    try {
      plain = plainValue(value);
      shown = seen === undefined ? undefined : plainValue(seen);
    } catch (error) {
      return;
    }
    if (id) post({type, id, [field]: plain, seen: shown});
  }

  // The config the card is showing travels with an answer, so that the hub can tell
  // when the question changed after the owner saw it.
  function answer(element, value) {
    const seen = typeof element.seenConfig === "function" ? element.seenConfig() : element._config;
    sendAnswer("answer", element, "value", value, seen);
  }

  function tick(element, ticked) {
    sendAnswer("tick", element, "ticked", ticked);
  }

  // The owner's own click being handled (``isTrusted``: a script cannot make one). Copy and
  // Open go to the shell only from it, and only when it hit a visible button of a block:
  // shown, with size, in the window and the topmost element at the click point (DO-02, A-340).
  let ownerClick = null;
  window.addEventListener("click", (event) => {
    if (!event.isTrusted) return;
    ownerClick = event;
    setTimeout(() => { if (ownerClick === event) ownerClick = null; });
  }, true);

  // Why the click being handled may not ask for a Copy or an Open, or "" when it may.
  function clickRefusal(block, text) {
    const event = ownerClick;
    if (!event) return "no click of the owner.";
    const button = event.composedPath().find((node) => node instanceof HTMLButtonElement);
    const root = button && button.getRootNode();
    const host = root instanceof ShadowRoot ? root.host : null;
    if (!host || (block ? host !== block : !host.localName.startsWith("canvas-"))) {
      return "the click was not on a button of the card.";
    }
    // A file or source card's text is the one its own card holds (``text`` of copyText).
    const own = host._config || {};
    if (text !== undefined && text !== own.path && text !== own.source) return "the text is not the card's own.";
    if (!button.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return "the button is not shown.";
    const box = button.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) return "the button has no size.";
    if (box.right <= 0 || box.bottom <= 0 || box.left >= innerWidth || box.top >= innerHeight) {
      return "the button is outside the window.";
    }
    const keyboard = event.detail === 0;
    const x = keyboard ? box.left + box.width / 2 : event.clientX;
    const y = keyboard ? box.top + box.height / 2 : event.clientY;
    let top = document.elementFromPoint(x, y);
    while (top && top.shadowRoot) {
      const inner = top.shadowRoot.elementFromPoint(x, y);
      if (!inner || inner === top) break;
      top = inner;
    }
    return top && button.contains(top) ? "" : "another element covers the button.";
  }

  // A refused Copy of the owner's click says why in the console; a page script's call
  // outside a click stays silent (SEC-09, A-441).
  function refusedCopy(refusal) {
    if (refusal && ownerClick) console.warn(`agent-canvas: Copy refused: ${refusal}`);
    return refusal;
  }

  // The owner's answer to Copy is the button itself: its label says "Copied" (or "Copy
  // failed") for 2 s, where the owner is looking; the note in the shell is easy to miss
  // (#3). The shell's ``copy-result`` names no button, so the last one pressed gets it.
  const RESULT_MS = 2000;
  let copyButton = null;
  let copyButtonLabel = "";
  function markPressed() {
    const button = ownerClick.composedPath().find((node) => node instanceof HTMLButtonElement);
    if (button === copyButton && button._resultTimer) return;
    copyButton = button;
    copyButtonLabel = button.textContent;
  }

  function showCopyResult(message) {
    const button = copyButton;
    if (!button || !button.isConnected) return;
    clearTimeout(button._resultTimer);
    button.textContent = message.ok === true ? "Copied" : "Copy failed";
    button._resultTimer = setTimeout(() => { button.textContent = copyButtonLabel; button._resultTimer = null; }, RESULT_MS);
  }

  // Ask the shell to put the ``run`` text of step ``step`` (from 1) of the Do
  // ``element`` on the clipboard. Only the step number travels: the hub reads the
  // text from the page file (DO-02).
  function copy(element, step) {
    if (mode.on || !(element instanceof Element) || !Number.isInteger(step)) return;
    if (refusedCopy(clickRefusal(element))) return;
    const id = element.getAttribute("data-canvas-id");
    if (!id) return;
    markPressed();
    sendPrivate({type: "copy", id, step});
  }

  // Ask the shell to copy the path of a file card or the source line of a source card
  // (``kind`` path or source). The hub gives the text back only when the page file has it.
  function copyText(kind, text) {
    if (mode.on || typeof text !== "string" || refusedCopy(clickRefusal(null, text))) return;
    markPressed();
    sendPrivate({type: "copy", kind, text});
  }

  // Ask the shell to show a session-folder file (a Markdown or PDF named by a document
  // block) as a page. Only the name travels; the hub decides whether it may be shown (CNT-01).
  function openFile(path) {
    if (mode.on || typeof path !== "string" || clickRefusal(null)) return;
    sendPrivate({type: "open-file", path});
  }

  // The shell hands over the stored items of this page (5.16): keep them for cards
  // that appear later and tell the cards that are here.
  function setAnswerItems(message) {
    if (!message.items || typeof message.items !== "object") return;
    window.agentCanvas.sessionFolder = typeof message.folder === "string" ? message.folder : undefined;
    window.agentCanvas.answerItems = message.items;
    window.agentCanvas.sessionEnded = message.ended === true; // ANS-08
    document.dispatchEvent(new CustomEvent("agentcanvas:answers", {detail: {items: message.items}}));
  }

  // For blocks: record an owner action (``select``, ``input``, ...) of
  // ``element`` for the next send; ``at`` is the pointer position, if any.
  function blockAction(kind, element, value, at) {
    if (mode.on) return; // COM-01: comment mode records no actions
    if (!BLOCK_ACTION_KINDS.includes(kind) || !(element instanceof Element)) return;
    let plain;
    try {
      plain = plainValue(value);
    } catch (error) {
      return;
    }
    post({
      type: "action",
      action: {
        kind, time: new Date().toISOString(), target: describeTarget(element),
        value: plain, at: Array.isArray(at) ? at.slice(0, 2) : null, card: inAnswerCard(element),
      },
    });
  }

  // FB-05: a click in a card's own controls (an Ask, a Do, a Decision, an Options box with a
  // submit button), whose answer reaches the agent on its own, is kept for the next send but
  // not counted. Content an agent put inside a card counts, except the block an Ask of form
  // point is answered on.
  function inAnswerCard(element) {
    let node = element;
    for (let root = node.getRootNode(); root instanceof ShadowRoot; root = node.getRootNode()) {
      node = root.host;
    }
    try {
      if (["canvas-ask", "canvas-do", "canvas-decision"].includes(node.localName)) return true;
      if (node.localName === "canvas-choices") return typeof node.readConfig().submit === "string";
      const ask = node.parentElement && node.parentElement.closest("canvas-ask");
      return Boolean(ask) && ask.readConfig().form === "point";
    } catch (error) {
      return false;
    }
  }

  // Requests the frame's content security policy refused, for the page audit
  // (CHK-12). Only recorded here; nothing is reported to the shell.
  const blocked = [];
  document.addEventListener("securitypolicyviolation", (event) => {
    if (blocked.length >= MAX_BLOCKED) return;
    blocked.push({
      uri: String(event.blockedURI || "").slice(0, 300),
      directive: String(event.effectiveDirective || "").slice(0, 40),
    });
  });

  window.agentCanvas = {
    report, emit, blockEvent, blockAction, runPageAudit, blocked, finderReady: false,
    answer, tick, copy, copyText, openFile, answerItems: undefined, sessionFolder: undefined,
  };

  // @medv/finder gives a short unique CSS selector (FB-05). It is loaded next
  // to the helper; clicks before it is ready get a plain tag path instead.
  let finderFunction = null;
  import(libraryUrl("/static/vendor/finder/finder.js"))
    .then((module) => {
      finderFunction = module.finder;
      window.agentCanvas.finderReady = true;
    })
    .catch(() => { window.agentCanvas.finderReady = true; });

  // ---- idiomorph, loaded next to the helper ----------------------------------

  const morphLibrary = new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = IDIOMORPH_URL;
    tag.setAttribute(HELPER_ATTRIBUTE, "");
    tag.onload = resolve;
    tag.onerror = () => reject(new Error("idiomorph failed to load"));
    // Right after the helper tag so that the injected elements stay first.
    const own = document.currentScript;
    if (own) own.after(tag); else document.head.appendChild(tag);
  });

  // ---- executable scripts (PAGE-05) ------------------------------------------

  function isExecutable(script) {
    const type = (script.getAttribute("type") || "").trim().toLowerCase();
    return type === "" || JAVASCRIPT_TYPES.has(type);
  }

  // A script created by page code has async === true without an async
  // attribute; it is not part of the agent's HTML and must not count.
  function isFromHtml(script) {
    return !(script.async && !script.hasAttribute("async"));
  }

  function scriptSignature(doc) {
    return Array.from(doc.querySelectorAll("script"))
      .filter((s) => !s.hasAttribute(HELPER_ATTRIBUTE))
      .filter((s) => isExecutable(s) && isFromHtml(s))
      .map((s) => s.hasAttribute("src")
        ? "src:" + s.getAttribute("src")
        : "inline:" + s.textContent)
      .sort()
      .join("\u0000");
  }

  // Taken when parsing ends: all scripts of the HTML are in the document then.
  // DOMContentLoaded also waits for module scripts, and an update can come
  // first; it must wait for this, not reload (#4).
  const loadedSignature = new Promise((resolve) => {
    const take = () => resolve(scriptSignature(document));
    if (document.readyState !== "loading") take();
    else document.addEventListener("readystatechange", take, {once: true});
  });

  // ---- morphing (PAGE-04) ----------------------------------------------------

  function parseAgentHtml(html) {
    // Mirror the hub, which wraps fragments when serving (PAGE-02).
    const wrapped = HEAD_OPEN.test(html) || HTML_OPEN.test(html)
      ? html
      : "<!doctype html><html><head></head><body>" + html + "</body></html>";
    return new DOMParser().parseFromString(wrapped, "text/html");
  }

  function isMergeable(element) {
    if (element.hasAttribute(HELPER_ATTRIBUTE)) return false;
    const tag = element.tagName;
    return tag === "STYLE" || tag === "TITLE" ||
      (tag === "LINK" && /(^|\s)stylesheet(\s|$)/i.test(element.rel));
  }

  function mergeHead(newHead) {
    const wanted = Array.from(newHead.children).filter(isMergeable);
    const wantedKeys = new Set(wanted.map((e) => e.outerHTML));
    const kept = new Set();
    for (const element of Array.from(document.head.children).filter(isMergeable)) {
      if (wantedKeys.has(element.outerHTML)) kept.add(element.outerHTML);
      else element.remove();
    }
    for (const element of wanted) {
      if (!kept.has(element.outerHTML)) {
        document.head.appendChild(document.importNode(element, true));
      }
    }
  }

  // A new version of a Markdown file or a picture: the viewer replaces its content
  // in place and keeps the reading place (VIEW-08); then the anchors are found again.
  async function updateViewer(message) {
    const viewer = window.acViewer;
    if (!viewer || viewer.kind !== message.viewer) {
      post({type: "reload", scrollX: window.scrollX, scrollY: window.scrollY});
      return;
    }
    try {
      await morphLibrary;
      await viewer.update(message, window.Idiomorph);
    } catch (error) {
      report("error", {source: "helper", message: String(error), line: null});
      return;
    }
    document.dispatchEvent(new CustomEvent("agentcanvas:updated"));
    report("updated", {version: message.version});
  }

  async function applyUpdate(message) {
    if (typeof message.viewer === "string") return updateViewer(message);
    if (typeof message.html !== "string") return;
    if (message.digest !== undefined && message.digest === loadedDigest) {
      report("updated", {version: message.version});
      return;
    }
    loadedDigest = message.digest;
    const incoming = parseAgentHtml(message.html);
    if (scriptSignature(incoming) !== await loadedSignature) {
      post({type: "reload", scrollX: window.scrollX, scrollY: window.scrollY});
      return;
    }
    try {
      await morphLibrary;
    } catch (error) {
      report("error", {source: "helper", message: String(error), line: null});
      return;
    }
    mergeHead(incoming.head);
    // Focus inside a block's shadow root makes the block element the active
    // element; idiomorph would then skip its config child (BLK-03).
    const active = document.activeElement;
    window.Idiomorph.morph(document.body, incoming.body, {
      ignoreActiveValue: !(active && active.shadowRoot),
    });
    applyHighlight();
    document.dispatchEvent(new CustomEvent("agentcanvas:updated"));
    report("updated", {version: message.version});
  }

  // ---- awaited blocks (CLI-06) -------------------------------------------------

  const WAITING_ATTRIBUTE = "data-canvas-waiting";
  let waitingIds = [];

  function ensureHighlightStyle() {
    if (document.querySelector("style[" + HELPER_ATTRIBUTE + "]:not([data-ac-comment-style])")) return;
    const style = document.createElement("style");
    style.setAttribute(HELPER_ATTRIBUTE, "");
    style.textContent = "[" + WAITING_ATTRIBUTE + "] {" +
      " outline: 3px solid #2457c5 !important; outline-offset: 3px; }";
    document.head.appendChild(style);
  }

  // Mark the elements an ``ask --block`` waits on; the shell sends the ids.
  // Morphing drops attributes, so this also runs after every update.
  function applyHighlight() {
    if (waitingIds.length) ensureHighlightStyle();
    for (const element of document.querySelectorAll("[" + WAITING_ATTRIBUTE + "]")) {
      if (!waitingIds.includes(element.getAttribute("data-canvas-id"))) {
        element.removeAttribute(WAITING_ATTRIBUTE);
      }
    }
    for (const element of document.querySelectorAll("[data-canvas-id]")) {
      if (waitingIds.includes(element.getAttribute("data-canvas-id"))) {
        element.setAttribute(WAITING_ATTRIBUTE, "");
      }
    }
  }

  function setHighlight(message) {
    const ids = Array.isArray(message.ids) ? message.ids : [];
    waitingIds = ids.filter((id) => typeof id === "string");
    applyHighlight();
  }

  // The hub saw a data file change; blocks with that ``src`` reload it (BLK-09).
  function fileChanged(message) {
    if (typeof message.path !== "string" || message.path.length > 500) return;
    document.dispatchEvent(new CustomEvent("agentcanvas:file-changed", {
      detail: {path: message.path},
    }));
  }

  // D-55: blocks report their state (a paused animation's position); the shell keeps it
  // while the frame reloads and returns it with ``restore-state``.
  document.addEventListener("agentcanvas:block-state", (event) => {
    const {id, state} = event.detail || {};
    if (typeof id === "string") post({type: "block-state", id, state});
  });

  function restoreState(message) {
    if (!message.states || typeof message.states !== "object") return;
    window.acRestoredState = message.states;
    document.dispatchEvent(new CustomEvent("agentcanvas:restore-state"));
  }

  // D-56: the viewers (PDF, picture) scroll an inner element, pages and Markdown the window.
  function scrollPlace(x, y) {
    const scroller = document.querySelector("[data-scroller]");
    if (scroller) scroller.scrollTo(x, y);
    else window.scrollTo(x, y);
  }

  function restoreScroll(message) {
    const x = Number(message.x) || 0;
    const y = Number(message.y) || 0;
    scrollPlace(x, y);
    // Layout may still change while images and fonts load, or a viewer lays out its pages.
    window.addEventListener("load", () => scrollPlace(x, y), {once: true});
    setTimeout(() => scrollPlace(x, y), 150);
    const viewer = window.acViewer;
    if (viewer && viewer.ready) {
      viewer.ready.then(() => { scrollPlace(x, y); setTimeout(() => scrollPlace(x, y), 150); });
    }
  }

  // D-56: the shell keeps the reading place for the frame's next load.
  let scrollTimer = null;
  document.addEventListener("scroll", (event) => {
    const target = event.target;
    const inner = target !== document;
    if (inner && !(target.dataset && "scroller" in target.dataset)) return;
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      post({
        type: "scroll-pos",
        x: inner ? target.scrollLeft : window.scrollX,
        y: inner ? target.scrollTop : window.scrollY,
      });
    }, 100);
  }, true);

  // KEY-05: the headings of the page for the shell's table of contents; the shell asks, the page
  // answers with names and levels only, and scrolls when the shell names one.
  let headings = [];
  const HEADING = /^H[1-6]$/;
  // In page order, looking into the open shadow roots of the blocks.
  function collectHeadings(root, out) {
    for (const element of root.children) {
      if (HEADING.test(element.tagName)) out.push(element);
      if (element.shadowRoot) collectHeadings(element.shadowRoot, out);
      collectHeadings(element, out);
    }
    return out;
  }
  function listHeadings() {
    headings = collectHeadings(document, [])
      .filter((h) => h.getClientRects().length && h.textContent.trim())
      .slice(0, 300);
    const edge = window.innerHeight / 3;
    const atTop = window.scrollY === 0 &&
      Array.from(document.querySelectorAll("[data-scroller]")).every((e) => e.scrollTop === 0);
    const current = atTop ? 0 : headings.findLastIndex((h) => h.getBoundingClientRect().top <= edge);
    post({
      type: "contents", current: Math.max(current, 0),
      items: headings.map((h) => ({level: Number(h.tagName[1]), text: clip(h.textContent, 120)})),
    });
  }
  function goToHeading(message) {
    const heading = headings[message.index];
    if (heading) heading.scrollIntoView({block: "start", behavior: "instant"});
  }

  // The messages the window (the shell, or render.js for a render frame) sends this
  // page (P33.2): type -> field names and handler. ``relay-open`` is answered by the
  // private channel's own listener above; the comment layer's types go on to the layer.
  const PARENT_MESSAGES = new Map([
    ["update", {fields: ["html", "version", "viewer", "digest"], handle: applyUpdate}],
    ["restore-scroll", {fields: ["x", "y"], handle: restoreScroll}],
    ["restore-state", {fields: ["states"], handle: restoreState}],
    ["contents-get", {fields: [], handle: listHeadings}],
    ["contents-go", {fields: ["index"], handle: goToHeading}],
    ["highlight", {fields: ["ids"], handle: setHighlight}],
    ["capture", {fields: ["id", "points", "boxes"], handle: capture}],
    ["file-changed", {fields: ["path"], handle: fileChanged}],
    ["answers", {fields: ["items", "folder", "ended"], handle: setAnswerItems}],
    ["copy-result", {fields: ["ok"], handle: showCopyResult}],
    ["render-prepare", {fields: ["id", "timeout", "section"], handle: prepareForRender}],
    ["render-audit", {fields: ["id", "viewport_height"], handle: auditForRender}],
    ["comment-mode", {fields: ["on", "kind"], handle: setCommentMode}],
    ["keys", {fields: ["keys"],
              handle: (message) => { forwardKeys = Array.isArray(message.keys) ? message.keys : []; }}],
    ["frame-hidden", {fields: [], handle: frameHidden}],
    ["comment-markers", {fields: ["markers", "selected"], handle: toLayer}],
    ["comment-hover", {fields: ["token"], handle: toLayer}],
    ["comment-scroll", {fields: ["token"], handle: toLayer}],
    ["comment-clear", {fields: [], handle: toLayer}],
    ["comment-crop", {fields: ["token"], handle: toLayer}],
    ["comment-cursor", {fields: ["op", "big"], handle: toLayer}],
    ["change-signs", {fields: ["signs"], handle: toLayer}],
  ]);

  // As in the shell (P33.2): an unknown type or field goes to the console, names only
  // and anything but printable ASCII as "?", each once and at most MAX_UNKNOWN_NOTES.
  // One budget: only the parent window reaches this listener, never a page script.
  const UNKNOWN_NOTE = "agent-canvas: unknown message";
  const MAX_UNKNOWN_NOTES = 20;
  const unknownNoted = new Set();
  function noteUnknown(type, field) {
    const name = (text) => JSON.stringify(String(text).replace(/[^\x20-\x7E]/g, "?").slice(0, 40));
    const note = field === undefined
      ? `${UNKNOWN_NOTE} from the window: type ${name(type)}`
      : `${UNKNOWN_NOTE} field from the window: ${name(type)} has ${name(field)}`;
    if (unknownNoted.has(note) || unknownNoted.size >= MAX_UNKNOWN_NOTES) return;
    unknownNoted.add(note);
    console.warn(note);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || event.source === window) return;
    const message = event.data;
    if (!message || typeof message.type !== "string") return;
    const row = PARENT_MESSAGES.get(message.type);
    if (row) {
      for (const field in message) {
        if (unknownNoted.size >= MAX_UNKNOWN_NOTES) break;
        if (field !== "type" && !row.fields.includes(field)) noteUnknown(message.type, field);
      }
      row.handle(message);
    } else {
      noteUnknown(message.type);
      if (message.type.startsWith("comment-")) toLayer(message);
    }
  });

  // SES-15: the shell keeps this frame while another page is shown. Meanwhile it is out of
  // comment mode and plays nothing; blocks pause on ``agentcanvas:hidden`` (CNT-02).
  function frameHidden() {
    setCommentMode({on: false, kind: mode.kind});
    for (const media of document.querySelectorAll("video, audio")) media.pause();
    document.dispatchEvent(new CustomEvent("agentcanvas:hidden"));
  }

  // A file dragged in from the file manager enters the frame and the frame swallows
  // the drag: tell the shell, which puts its drop shield up (VIEW-09, SEC-09). The
  // notice carries no names and no contents.
  window.addEventListener("dragenter", (event) => {
    const types = event.dataTransfer ? Array.from(event.dataTransfer.types || []) : [];
    if (types.includes("Files")) post({type: "drag-notice"});
  }, true);

  // ---- links (PAGE-11) -------------------------------------------------------

  function clip(text, limit) {
    return String(text).trim().replace(/\s+/g, " ").slice(0, limit);
  }

  // The page name when ``url`` is a ``*.html`` file in this page's folder.
  function sameFolderPage(url) {
    const here = new URL(location.href);
    if (url.origin !== here.origin) return null;
    const folder = here.pathname.slice(0, here.pathname.lastIndexOf("/") + 1);
    if (!url.pathname.startsWith(folder)) return null;
    let name;
    try {
      name = decodeURIComponent(url.pathname.slice(folder.length));
    } catch (error) {
      return null;
    }
    const isPage = name !== "" && !name.includes("/") && /\.html$/i.test(name);
    return isPage ? name : null;
  }

  // ---- click recorder (FB-05) --------------------------------------------------

  function tagPath(element) {
    const parts = [];
    for (let e = element; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      if (!e.parentElement) break;
      const same = Array.from(e.parentElement.children).filter((c) => c.tagName === e.tagName);
      const index = same.indexOf(e) + 1;
      parts.unshift(e.tagName.toLowerCase() + (same.length > 1 ? `:nth-of-type(${index})` : ""));
    }
    return "body > " + parts.join(" > ");
  }

  function selectorOf(element) {
    const id = element.getAttribute("id");
    if (id && document.querySelectorAll("#" + CSS.escape(id)).length === 1) {
      return "#" + CSS.escape(id);
    }
    if (finderFunction) {
      try { return finderFunction(element); } catch (error) { /* fall through */ }
    }
    return tagPath(element);
  }

  // The nearest ancestor with data-canvas-id or id, looking out of shadow roots
  // (an element inside a block belongs to the block); else the last host reached.
  function owningElement(element) {
    let current = element;
    for (;;) {
      const hit = current.closest("[data-canvas-id],[id]");
      if (hit) return hit;
      const root = current.getRootNode();
      if (!(root instanceof ShadowRoot)) return current;
      current = root.host;
    }
  }

  // The nearest ancestor with data-canvas-id or id is the target; without one
  // the clicked element itself, found again through its finder selector.
  function describeTarget(element) {
    const owner = owningElement(element);
    const canvasId = owner.getAttribute("data-canvas-id") || owner.getAttribute("id");
    return {
      tag: owner.tagName.toLowerCase(),
      canvas_id: canvasId || null,
      selector: selectorOf(owner),
      text: clip(owner.innerText !== undefined ? owner.innerText : owner.textContent, 80),
    };
  }

  function recordClick(event, extra, element) {
    if (mode.on) return;
    element = element || (event.target instanceof Element ? event.target : null);
    if (!element) return;
    post({
      type: "action",
      action: {
        kind: "click",
        time: new Date().toISOString(),
        target: Object.assign(describeTarget(element), extra || {}),
        value: null,
        at: [Math.round(event.clientX), Math.round(event.clientY)],
        card: inAnswerCard(element),
      },
    });
  }

  // The absolute address of an HTML or SVG link; null for any other node.
  function linkAddress(node) {
    if (node instanceof HTMLAnchorElement && node.hasAttribute("href")) return node.href;
    if (node instanceof SVGAElement && (node.hasAttribute("href") || node.hasAttribute("xlink:href"))) {
      return new URL(node.href.baseVal, node.baseURI).href;
    }
    return null;
  }

  function onLinkClick(event) {
    // composedPath also reaches links inside a block's shadow root.
    const anchor = event.composedPath().find((node) => linkAddress(node) !== null) || null;
    if (anchor === null) {
      if (event.type === "click") recordClick(event);
      return;
    }
    event.preventDefault();
    const url = new URL(linkAddress(anchor), document.baseURI);
    const here = new URL(location.href);
    const samePlace = url.origin === here.origin && url.pathname === here.pathname &&
      url.search === here.search;
    if (samePlace && url.hash) {
      const target = document.getElementById(decodeURIComponent(url.hash.slice(1)));
      if (target) target.scrollIntoView();
      return;
    }
    const page = sameFolderPage(url);
    if (page !== null) {
      if (!samePlace) post({type: "navigate", page});
      return;
    }
    recordClick(event, {href: clip(url.href, 500)}, anchor);
  }
  window.addEventListener("click", onLinkClick, true);
  window.addEventListener("auxclick", onLinkClick, true);

  // ---- keys (FB-04, FB-09) ----------------------

  const EDITABLE_INPUTS = new Set([
    "text", "search", "url", "tel", "email", "password", "number", "date",
    "datetime-local", "month", "time", "week",
  ]);

  // The focused element, looking into open shadow roots (blocks hold inputs).
  function deepActiveElement() {
    let active = document.activeElement;
    while (active && active.shadowRoot && active.shadowRoot.activeElement) {
      active = active.shadowRoot.activeElement;
    }
    return active;
  }

  function isEditing() {
    const element = deepActiveElement();
    if (!element || element.nodeType !== 1) return false;
    if (element.isContentEditable) return true;
    if (element.tagName === "TEXTAREA" || element.tagName === "SELECT") return true;
    return element.tagName === "INPUT" &&
      EDITABLE_INPUTS.has((element.type || "text").toLowerCase());
  }

  // Shortcuts the shell handles; the page keeps the keys otherwise. Ctrl+Enter
  // (send) is forwarded even from a text field; the other keys are left to the
  // page while it is being edited, so that text-field undo keeps working.
  // The keys come from the shell's key map (KMAP-03): ``{key, ctrl, shift, comment}``.
  let forwardKeys = [];
  function isShortcut(event) {
    if (event.metaKey) return false;
    const editing = isEditing();
    return forwardKeys.some((b) => b.key === event.key && b.ctrl === event.ctrlKey &&
      b.alt === event.altKey &&
      (b.key.length === 1 || b.shift === event.shiftKey) && (b.ctrl || b.alt || !editing) &&
      (!b.comment || mode.on) && (!b.cursor || (mode.on && Boolean(window.agentCanvas.commentLayer?.cursorActive()))));
  }

  window.addEventListener("keydown", (event) => {
    if (!isShortcut(event)) return;
    event.preventDefault();
    post({
      type: "key", key: event.key, ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey,
      editable: isEditing(),
    });
  }, true);

  // ---- screenshot (DRAW-05) ----------------------------------------------

  const MAX_SCREENSHOT_CHARS = 9 * 1024 * 1024;

  function pageBackground() {
    for (const element of [document.documentElement, document.body]) {
      const colour = getComputedStyle(element).backgroundColor;
      if (colour && colour !== "transparent" && colour !== "rgba(0, 0, 0, 0)") return colour;
    }
    return "#ffffff";
  }

  // The owning block (a ``data-canvas-id`` element) of a node, looking out of
  // shadow roots; null for a node of the page itself.
  function owningBlock(node) {
    for (let current = node; current; ) {
      const hit = current.closest && current.closest("[data-canvas-id]");
      if (hit) return hit;
      const root = current.getRootNode();
      current = root instanceof ShadowRoot ? root.host : null;
    }
    return null;
  }

  function isVisible(rect, viewport) {
    return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < viewport.width && rect.top < viewport.height;
  }

  // Draw what snapdom cannot: blocks export their own image (``snapshot``), and
  // raw WebGL canvases are copied when their buffer was preserved. Others are
  // listed as warnings (DRAW-06, BLK-06).
  async function mergeCanvases(context, viewport) {
    const warnings = [];
    const owned = new Set();
    for (const block of document.querySelectorAll("[data-canvas-id]")) {
      if (typeof block.snapshot !== "function") continue;
      owned.add(block);
      if (!isVisible(block.getBoundingClientRect(), viewport)) continue;
      try {
        const {image, rect} = await block.snapshot();
        context.drawImage(image, rect.left, rect.top, rect.width, rect.height);
      } catch (error) {
        warnings.push({
          canvas_id: block.getAttribute("data-canvas-id"), selector: selectorOf(block),
          reason: "snapshot-failed: " + String(error && error.message ? error.message : error),
        });
      }
    }
    for (const reference of Array.from(webglCanvases)) {
      const canvas = reference.deref();
      if (!canvas) { webglCanvases.delete(reference); continue; }
      const rect = canvas.getBoundingClientRect();
      if (!canvas.isConnected || !isVisible(rect, viewport)) continue;
      const block = owningBlock(canvas);
      if (block && owned.has(block)) continue;
      if (keepsBuffer(canvas)) {
        context.drawImage(canvas, rect.left, rect.top, rect.width, rect.height);
      } else {
        warnings.push({
          canvas_id: block ? block.getAttribute("data-canvas-id") : null,
          selector: selectorOf(canvas), reason: "webgl-not-captured",
        });
      }
    }
    return warnings;
  }

  // A WebGL canvas can be read after the frame only with preserveDrawingBuffer.
  function keepsBuffer(canvas) {
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    const attributes = gl && gl.getContextAttributes ? gl.getContextAttributes() : null;
    return Boolean(attributes && attributes.preserveDrawingBuffer);
  }

  // snapdom copies a <style> inside the body into its picture next to the
  // classes it generates from the computed styles. The copy out-specifies
  // those classes, and a var() in it cannot see the custom properties of
  // :root (the picture has no :root), so the element lost its borders,
  // backgrounds and fonts. The live computed styles already carry the result
  // of every rule, so the copies are left out ('remove' keeps the geometry);
  // an <svg>'s own <style> is kept, it styles the svg's content.
  const SNAPDOM_OPTIONS = {
    scale: 1, dpr: 1, exclude: ["body style:not(svg style)"], excludeMode: "remove",
  };

  // Render the body with snapdom and crop it to the visible area: one image
  // pixel per CSS pixel, so mark coordinates are image coordinates.
  async function renderViewport(viewport) {
    const {snapdom} = await import(libraryUrl("/static/vendor/snapdom/snapdom.mjs"));
    const body = document.body;
    const rendered = await (await snapdom(body, SNAPDOM_OPTIONS)).toCanvas();
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const context = canvas.getContext("2d");
    context.fillStyle = pageBackground();
    context.fillRect(0, 0, canvas.width, canvas.height);
    // getBoundingClientRect is relative to the visible area, so this is the
    // crop at scroll_x, scroll_y.
    const box = body.getBoundingClientRect();
    // dpr 1 and scale 1 make the bitmap one pixel per CSS pixel; snapdom pads
    // it to the viewport size, so it is drawn at its natural size, not fitted
    // to the body's box.
    context.drawImage(rendered, box.left, box.top);
    const warnings = await mergeCanvases(context, viewport);
    return {png: canvas.toDataURL("image/png"), warnings};
  }

  // The picture of one region of the page, in page coordinates, through the
  // same snapdom path as the send screenshot (COM-12): the page is rendered
  // once, the region cut out, blocks and WebGL canvases drawn on it as for a
  // screenshot. ``region`` is {x, y, w, h}, whole pixels, inside the page.
  async function renderRegion(region) {
    if (window.agentCanvas.captureHang) await new Promise(() => {});
    if (window.agentCanvas.captureFailure) {
      throw new Error(String(window.agentCanvas.captureFailure));
    }
    const {snapdom} = await import(libraryUrl("/static/vendor/snapdom/snapdom.mjs"));
    const body = document.body;
    const rendered = await (await snapdom(body, SNAPDOM_OPTIONS)).toCanvas();
    const canvas = document.createElement("canvas");
    canvas.width = region.w;
    canvas.height = region.h;
    const context = canvas.getContext("2d");
    context.fillStyle = pageBackground();
    context.fillRect(0, 0, canvas.width, canvas.height);
    const box = body.getBoundingClientRect();
    context.drawImage(
      rendered, box.left + window.scrollX - region.x, box.top + window.scrollY - region.y);
    // mergeCanvases works in viewport coordinates: shift them into the crop.
    context.save();
    context.translate(window.scrollX - region.x, window.scrollY - region.y);
    const viewport = {width: window.innerWidth, height: window.innerHeight};
    const warnings = await mergeCanvases(context, viewport);
    context.restore();
    return {canvas, warnings};
  }

  async function capture(request) {
    const viewport = {
      width: window.innerWidth, height: window.innerHeight,
      scroll_x: Math.round(window.scrollX), scroll_y: Math.round(window.scrollY),
    };
    const answer = {
      type: "capture-result", id: request.id, ok: false, viewport,
      warnings: [],
    };
    try {
      // Test hooks: a page cannot gain anything from them.
      if (window.agentCanvas.captureHang) await new Promise(() => {});
      if (window.agentCanvas.captureFailure) {
        throw new Error(String(window.agentCanvas.captureFailure));
      }
      const rendered = await renderViewport(viewport);
      answer.png = rendered.png;
      answer.warnings = rendered.warnings;
      answer.ok = answer.png.length <= MAX_SCREENSHOT_CHARS;
      if (!answer.ok) {
        delete answer.png;
        answer.error = "screenshot is larger than 10 MB";
      }
    } catch (error) {
      answer.error = "screenshot failed: " + (error && error.message ? error.message : error);
    }
    post(answer);
  }

  // ---- rendering for ``look`` (LOOK-04, LOOK-09) ---------------------------------

  const TIMEOUT = Symbol("timeout");

  // Resolve when ``promise`` does, or after ``ms`` with TIMEOUT.
  function within(promise, ms) {
    return Promise.race([
      Promise.resolve(promise).then(() => true),
      new Promise((resolve) => setTimeout(() => resolve(TIMEOUT), Math.max(0, ms))),
    ]);
  }

  function blockElements() {
    return Array.from(document.querySelectorAll("*"))
      .filter((e) => typeof e.whenRendered === "function");
  }

  // Block tags the page uses that are not defined yet (the loader is a module).
  function pendingBlockTags() {
    const tags = new Set();
    for (const e of document.querySelectorAll("*")) {
      if (e.localName.startsWith("canvas-") && !customElements.get(e.localName)) {
        tags.add(e.localName);
      }
    }
    return Array.from(tags);
  }

  function imagesLoaded() {
    return Promise.all(Array.from(document.images)
      .filter((image) => !image.complete)
      .map((image) => new Promise((resolve) => {
        image.addEventListener("load", resolve, {once: true});
        image.addEventListener("error", resolve, {once: true});
      })));
  }

  // Wait until the page has loaded, every block has finished rendering, images
  // and fonts are ready; false if ``deadline`` (performance.now()) passes first.
  async function settle(deadline) {
    const left = () => deadline - performance.now();
    if (document.readyState !== "complete") {
      const loaded = new Promise((r) => window.addEventListener("load", r, {once: true}));
      if (await within(loaded, left()) === TIMEOUT) return false;
    }
    for (let round = 0; round < 20; round++) {
      for (const tag of pendingBlockTags()) {
        if (await within(customElements.whenDefined(tag), left()) === TIMEOUT) return false;
      }
      const blocks = blockElements();
      const all = Promise.all(blocks.map((block) => block.whenRendered()));
      if (await within(all, left()) === TIMEOUT) return false;
      // A render may have scheduled another (a config changed meanwhile).
      if (blocks.every((block) => block.renderIdle) && !pendingBlockTags().length) break;
    }
    // A viewer has shown its file, or has failed and said why (VIEW-14).
    const viewer = window.acViewer;
    if (viewer && viewer.ready && await within(viewer.ready, left()) === TIMEOUT) return false;
    if (await within(imagesLoaded(), left()) === TIMEOUT) return false;
    if (document.fonts && document.fonts.ready) {
      if (await within(document.fonts.ready, left()) === TIMEOUT) return false;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
    return true;
  }

  function findSection(id) {
    const byId = document.getElementById(id);
    if (byId) return byId;
    const escaped = String(id).replace(/["\\]/g, "\\$&");
    return document.querySelector('[data-canvas-id="' + escaped + '"]');
  }

  // The page's size after it settled and, for a section, the element's box in
  // page coordinates; the renderer resizes its frame and asks again.
  async function prepareForRender(request) {
    const timeout = Math.min(30000, Math.max(100, Number(request.timeout) || 5000));
    const settled = await settle(performance.now() + timeout);
    const root = document.documentElement;
    const answer = {
      type: "render-prepared", id: request.id, settled,
      height: Math.max(root.scrollHeight, document.body ? document.body.scrollHeight : 0),
      width: root.scrollWidth, found: null, rect: null,
    };
    if (typeof request.section === "string") {
      const element = findSection(request.section);
      answer.found = element !== null;
      if (element) {
        const box = element.getBoundingClientRect();
        answer.rect = {
          x: box.left + window.scrollX, y: box.top + window.scrollY,
          width: box.width, height: box.height,
        };
      }
    }
    post(answer);
  }

  // The page checks (CHK-01): ``look`` and ``show`` call this in a render frame
  // after the page settled and return its JSON result as ``audit``. The checks
  // live in audit.js, which is loaded here, on the first call; only the render
  // frames ever send ``render-audit``, so the owner's visible frame never loads it.
  let auditLoading = null;
  function loadAudit() {
    if (window.agentCanvas.auditPage) return Promise.resolve();
    if (!auditLoading) {
      auditLoading = new Promise((resolve, reject) => {
        const tag = document.createElement("script");
        tag.src = AUDIT_URL;
        tag.setAttribute(HELPER_ATTRIBUTE, "");
        tag.onload = resolve;
        tag.onerror = () => reject(new Error("audit.js failed to load"));
        document.head.appendChild(tag);
      });
    }
    return auditLoading;
  }

  async function runPageAudit(options) {
    await loadAudit();
    return window.agentCanvas.auditPage(options);
  }

  async function auditForRender(request) {
    let result;
    try {
      result = plainValue(await window.agentCanvas.runPageAudit({
        viewportHeight: Number(request.viewport_height) || window.innerHeight,
      }));
    } catch (error) {
      result = {error: "audit failed: " + String(error && error.message ? error.message : error)};
    }
    post({type: "render-audit-result", id: request.id, result: result === undefined ? null : result});
  }

  // ---- comment layer (COM-01, COM-05) ------------------------------------------
  //
  // comments-layer.js holds the gestures, the markers and the crop. It is
  // loaded here, not in render frames (``look``, thumbnails and page checks
  // never show markers). Messages for it wait until it is loaded.

  const LAYER_URLS = ["/static/anchor.js", "/static/comments-layer.js"];
  let layerLoading = null;
  // Both files load at once and run in this order: the layer needs the finders.
  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = libraryUrl(url);
      tag.async = false;
      tag.setAttribute(HELPER_ATTRIBUTE, "");
      tag.onload = resolve;
      tag.onerror = () => reject(new Error(url + " failed to load"));
      document.head.appendChild(tag);
    });
  }
  function loadLayer() {
    if (IS_RENDER_FRAME) return Promise.reject(new Error("no layer in render frames"));
    if (!layerLoading) layerLoading = Promise.all(LAYER_URLS.map(loadScript));
    return layerLoading;
  }

  function toLayer(message) {
    loadLayer().then(() => {
      const layer = window.agentCanvas.commentLayer;
      if (layer) layer.onMessage(message);
    }).catch(() => {});
  }

  function setCommentMode(message) {
    if (IS_RENDER_FRAME) return;
    mode.on = message.on === true;
    mode.kind = COMMENT_KINDS.includes(message.kind) ? message.kind : "rect";
    // The attribute shows the mode only once the layer can take a drag (A-267).
    document.documentElement.removeAttribute("data-ac-commenting");
    if (mode.on) {
      loadLayer().then(() => {
        if (mode.on) document.documentElement.setAttribute("data-ac-commenting", mode.kind);
      }).catch(() => {});
    }
    toLayer(message);
  }

  // What the layer needs from this file. Not a page API: a page can read it
  // but gains nothing, the layer only reports geometry to the shell (SEC-09).
  Object.defineProperty(window.agentCanvas, "layerSupport", {
    value: {post, describeTarget, renderRegion, mode},
  });

  // ---- reports (PAGE-08) -----------------------------------------------------

  window.addEventListener("error", (event) => {
    report("error", {
      source: "script",
      message: String(event.message),
      line: Number.isInteger(event.lineno) ? event.lineno : null,
      canvas_id: null,
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    report("error", {
      source: "script",
      message: "Unhandled rejection: " + String(event.reason),
      line: null,
      canvas_id: null,
    });
  });
  window.addEventListener("load", () => report("loaded", {}));

  post({type: "heartbeat"});
  setInterval(() => post({type: "heartbeat"}), 1000);
  document.addEventListener("DOMContentLoaded", () => post({type: "ready"}));
})();
