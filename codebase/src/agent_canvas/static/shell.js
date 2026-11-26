// Trusted shell: the Herdr view (sidebar, tab bar, one card per pane), the
// open pages in sandboxed frames (one per page, the active one shown, SES-15), live updates, the
// frames' heartbeat (PAGE-10) and ready report (PAGE-09). Accepts messages only from
// those frames (SEC-09).
"use strict";

const HEARTBEAT_TIMEOUT_MS = 3000;
const READY_TIMEOUT_MS = 2000;
const NOT_READY_WARNING = "Document did not report ready; reloading the page.";
const RATE_LIMIT_PER_SECOND = 100;
const MAX_MESSAGE_BYTES = 1024 * 1024;
// The messages a page frame may send (P33.2): type -> size limit (bytes of JSON),
// whether a frame that is not shown may send it (``hidden``: its own load, errors and
// kept state), its field names and its handler. The guard and the dispatch both read
// this table. The capture result carries the page screenshot (10 MB). A page cannot
// make the shell send: ``send`` is not a frame message type.
const MAX_SCREENSHOT_MESSAGE_BYTES = 10 * 1024 * 1024;
const FRAME_MESSAGES = new Map([
  ["heartbeat", {limit: MAX_MESSAGE_BYTES, hidden: true, fields: [], handle: onHeartbeat}],
  ["ready", {limit: MAX_MESSAGE_BYTES, hidden: true, fields: [], handle: onReady}],
  ["report", {limit: MAX_MESSAGE_BYTES, hidden: true, fields: ["name", "data"],
    handle: (m, record) => handleReport(m.name, m.data, record)}],
  ["reload", {limit: MAX_MESSAGE_BYTES, hidden: true, fields: ["scrollX", "scrollY"],
    handle: onReload}],
  ["navigate", {limit: MAX_MESSAGE_BYTES, hidden: false, fields: ["page"],
    handle: (m) => handleNavigate(m.page)}],
  ["action", {limit: MAX_MESSAGE_BYTES, hidden: false, fields: ["action"],
    handle: (m) => handleAction(m.action)}],
  ["emit", {limit: MAX_MESSAGE_BYTES, hidden: false,
    fields: ["name", "kind", "value", "delivery", "target"], handle: handleEmit}],
  ["key", {limit: MAX_MESSAGE_BYTES, hidden: false, fields: ["key", "ctrl", "shift", "alt", "editable"],
    handle: handleKeyMessage}],
  // a file is dragged over the frame: no names, no contents
  ["drag-notice", {limit: 100, hidden: false, fields: [], handle: onFrameDrag}],
  ["capture-result", {limit: MAX_SCREENSHOT_MESSAGE_BYTES, hidden: false,
    fields: ["id", "ok", "viewport", "warnings", "png", "error"],
    handle: (m) => window.drawUi.onCaptureResult(m)}],
  // The comment layer's reports (COM-18, SEC-09): a selection, a marker click, the
  // anchors it did not find again and the picture of a selection (the screenshot limit).
  ["comment-selection", {limit: MAX_MESSAGE_BYTES, hidden: false,
    fields: ["kind", "anchor", "target", "rect", "text_inside", "data", "notice"],
    handle: (m) => onCommentSelection(m)}],
  ["comment-marker", {limit: MAX_MESSAGE_BYTES, hidden: false, fields: ["token", "action"],
    handle: (m) => onCommentMarker(m)}],
  ["comment-lost", {limit: MAX_MESSAGE_BYTES, hidden: false, fields: ["items"],
    handle: (m) => onCommentLost(m)}],
  ["comment-picture", {limit: MAX_SCREENSHOT_MESSAGE_BYTES, hidden: false,
    fields: ["token", "ok", "png", "error"], handle: (m) => onCommentPicture(m)}],
  // The cards' answers (ANS-02, SEC-09); the relay checks the rest. A forged one
  // reaches only the items of the shown page.
  ["answer", {limit: 200 * 1024, hidden: false, fields: ["id", "value", "seen"],
    handle: (m) => answerRelay.onFrameAnswer(m)}],
  ["tick", {limit: 10 * 1024, hidden: false, fields: ["id", "ticked", "seen"],
    handle: (m) => answerRelay.onFrameTick(m)}],
  ["relay-open", {limit: 4 * 1024, hidden: true, fields: ["token", "href"],
    handle: (m, record, ports) => openRelay(m, ports, record)}],
  // the headings the shell asked the shown page for (KEY-05)
  ["contents", {limit: 64 * 1024, hidden: false, fields: ["items", "current"],
    handle: (m) => pageContents.onItems(m)}],
  // a block's position, kept for the frame's next load (D-55)
  ["block-state", {limit: 1024, hidden: true, fields: ["id", "state"],
    handle: (m, record) => rememberBlockState(m, record.url)}],
  // the reading place, kept for the frame's next load (D-56)
  ["scroll-pos", {limit: 200, hidden: true, fields: ["x", "y"], handle: rememberScroll}],
]);
const MAX_STATE_PAGES = 100;
const MAX_STATE_BLOCKS = 50;
const MAX_DRAFT_ACTIONS = 50;
const VIEWER_NAME = /^[^/\\\0]+\.(md|markdown|pdf|png|jpe?g|gif|webp|svg)$/i;
const PAGE_NAME = /^[^/\\\0]+\.(html|md|markdown|pdf|png|jpe?g|gif|webp|svg)$/i;
const MAX_LIVE_FRAMES = 8;

const main = document.querySelector("main");
const notice = document.getElementById("notice");
const noticeText = document.getElementById("notice-text");
const warning = document.getElementById("warning");
const askBar = document.getElementById("ask-bar");
window.__reports = [];
window.__errors = [];
// Per-tab drafts: {actions, actions_dropped} (glossary "draft"); the actions come from the frame.
window.__drafts = {};
window.__guard = {
  accepted: {},
  dropped: {source: 0, type: 0, size: 0, rate: 0, token: 0, private: 0, hidden: 0},
};

let socket = null;
let currentUrl = null;
// SES-15: frame url -> {element, url, session, old, token, relayOpen, port, ...}, in the
// order of use (the last shown at the end); ``active`` is the one on screen, null for none.
const liveFrames = new Map();
let active = null;
const scrollPlaces = new Map(); // frame url -> {x, y}, in memory only (D-56)
const blockStates = new Map(); // frame url -> {block id: state}, in memory only (D-55)
// ANS-02: the relay serves a document only after it answered the token sent when the
// frame's load event fired (``record.token``; ``record.relayOpen`` once answered, M26 F1).
// The document that is leaving the frame is gone by then and never sees the token. Only a
// load the shell started gets a token (``record.started``), and the answer must name the
// page's own address, which holds the session's page token (A-577).

function showNotice(text) {
  noticeText.textContent = text;
  notice.classList.add("visible");
}

// M5: owner input (button/choice events, question answers) sent while the hub is
// away is kept here and sent when the socket is open again. Page reports are not
// queued: they describe a page state that is stale by then.
const MAX_KEPT = 50; // errors kept in the shell, as in the hub
const MAX_REPORTS = 500; // reports kept for the tests' counters
const QUEUED_TYPES = new Set(["event", "ask-answer", "ask-dismiss"]);
const MAX_OUTBOX = 100;
const outbox = [];
let hubOffline = false;
const offlineBanner = document.getElementById("offline");

// A message type no table row knows, or a field its row does not name, goes to the
// console instead of passing in silence (P33.2): type and field names only, never
// values, each name once and at most MAX_UNKNOWN_NOTES, so a page cannot flood it.
// The page's messages have a budget of their own: a page that uses its budget up does
// not silence a mismatch between the hub and this window. The names are the sender's
// choice: anything but printable ASCII becomes "?" (line breaks, text direction marks).
const UNKNOWN_NOTE = "agent-canvas: unknown message";
const MAX_UNKNOWN_NOTES = 20;
const pageNotes = new Set();
const hubNotes = new Set();

function notesFor(where) {
  return where === "from the page" ? pageNotes : hubNotes;
}

function noteUnknown(where, type, field) {
  const notes = notesFor(where);
  const name = (text) => JSON.stringify(String(text).replace(/[^\x20-\x7E]/g, "?").slice(0, 40));
  const note = field === undefined
    ? `${UNKNOWN_NOTE} ${where}: type ${name(type)}`
    : `${UNKNOWN_NOTE} field ${where}: ${name(type)} has ${name(field)}`;
  if (notes.has(note) || notes.size >= MAX_UNKNOWN_NOTES) return;
  notes.add(note);
  console.warn(note);
}

function noteUnknownFields(where, message, row) {
  const notes = notesFor(where);
  for (const field in message) {
    if (notes.size >= MAX_UNKNOWN_NOTES) return;
    if (field !== "type" && !row.fields.includes(field)) noteUnknown(where, message.type, field);
  }
}

function sendToHub(message) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
  } else if (QUEUED_TYPES.has(message.type) && outbox.length < MAX_OUTBOX) {
    outbox.push(message);
  }
}

function setOffline(offline) {
  if (hubOffline === offline) return;
  hubOffline = offline;
  document.body.classList.toggle("offline", offline);
  offlineBanner.classList.toggle("visible", offline);
  window.drawUi.updateBar();
}

function flushOutbox() {
  while (outbox.length) sendToHub(outbox.shift());
}

// COM-16: comment changes wait in their own queue, counted with the one above.
const commentOutbox = window.createOutbox({
  isOffline: () => hubOffline,
  onChange: () => renderCommentPanel(),
  onApplied: (entry, data) => { if (entry.view) addSavedRecord(entry.view.key, data); },
  onRefused: (entry, message) => showNotice(message),
  onFlushed: () => requestComments(),
});

// ANS-02: stored answers go to the frame, the frame's answers and ticks to the hub.
const answerRelay = window.createAnswerRelay({
  activeTab, poolOf, postToFrame, notify: showNotice,
  isOldVersion: () => viewing !== null,
  requestItems: (session, page) => sendToHub({type: "answers-get", session, page}),
  submit: submitAnswer, showCopied, copyFailed: showCopyFailed,
});

// HUB-09: card answers and ticks wait in the comment outbox while the hub is away,
// at most MAX_OUTBOX of them.
function submitAnswer(path, body) {
  if (commentOutbox.count((waiting) => waiting.includes("/answers/")) >= MAX_OUTBOX) {
    const message = "Offline: too many answers waiting; wait for the canvas to reconnect";
    return Promise.resolve({ok: false, data: {message}});
  }
  return commentOutbox.submit(path, body);
}

// DO-02: "Copied: <first line>" for 2 s; when the clipboard refuses, the text is
// shown in a field to select and copy by hand.
const COPIED_MS = 2000;
const copiedNote = document.getElementById("copied");
let copiedTimer = null;
let copyFrame = null; // the frame whose Copy is being answered (SES-15)

// The pressed button's label follows the result, in the frame that asked even if hidden by now.
function postCopyResult(ok) {
  const target = copyFrame && copyFrame.element.isConnected && copyFrame.element.contentWindow;
  if (target) target.postMessage({type: "copy-result", ok}, "*");
}

function showCopied(text, copied) {
  postCopyResult(copied);
  clearTimeout(copiedTimer);
  copiedNote.replaceChildren();
  if (copied) {
    copiedNote.append(`Copied: ${text}`);
    copiedTimer = setTimeout(() => copiedNote.classList.remove("visible"), COPIED_MS);
  } else {
    const field = document.createElement("textarea");
    field.readOnly = true;
    field.value = text;
    field.rows = Math.min(6, text.split("\n").length);
    field.setAttribute("aria-label", "Command to copy");
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "Close";
    close.addEventListener("click", () => copiedNote.classList.remove("visible"));
    copiedNote.append("Select the text and press Ctrl+C:", field, close);
    copiedNote.classList.add("visible");
    field.focus();
    field.select();
    return;
  }
  copiedNote.classList.add("visible");
}

// A copy refused after the owner's click says why, where "Copied" would be: the notice
// above is cleared by the page's next heartbeat, within a second (A-442).
const COPY_FAILED_MS = 6000;

function showCopyFailed(reason) {
  postCopyResult(false);
  clearTimeout(copiedTimer);
  copiedNote.replaceChildren(`Copy failed: ${reason}`);
  copiedNote.classList.add("visible");
  copiedTimer = setTimeout(() => copiedNote.classList.remove("visible"), COPY_FAILED_MS);
}

// The errors of a page's frame; the shown one's are ``window.__errors`` and its badge (PAGE-08).
const errorBadge = document.getElementById("tab-badge");

function setErrors(record, errors) {
  record.errors = errors;
  if (record !== active) return;
  window.__errors = errors;
  errorBadge.hidden = !errors.length;
  errorBadge.title = errors.map((e) => e.message).join("\n");
}

// Start loading the record's page in its frame; every load begins with a clean slate
// of errors, in the shell and at the hub.
function beginLoad(record) {
  record.epoch += 1;
  record.loadCount = 0;
  record.readyCount = 0;
  setErrors(record, []);
  sendToHub({type: "page-report", url: record.url, name: "clear-errors", data: null});
  record.lastHeartbeat = performance.now();
  record.token = null;
  record.relayOpen = false;
  closePrivatePort(record);
  if (record === active) {
    notice.classList.remove("visible");
    answerRelay.onLoadBegin();
  }
  record.started = true;
  record.element.src = record.url;
  if (!record.element.isConnected) main.prepend(record.element);
}

// The frame's document finished loading: offer it the token that opens the relay, but
// only when the shell started this load.
function onFrameLoaded(record) {
  record.token = null;
  closePrivatePort(record);
  if (!record.started) return strayLoad(record);
  record.started = false;
  record.token = crypto.randomUUID();
  if (record.element.contentWindow) {
    record.element.contentWindow.postMessage({type: "relay-open", token: record.token}, "*");
  }
}

// A document the shell did not load into the frame, or one that is not the page it
// loaded, gets no relay and no port; the frame goes back to its page once, as a page that
// never reports ready does (PAGE-09).
function strayLoad(record) {
  record.relayOpen = false;
  if (record === active) {
    answerRelay.onLoadBegin();
    warning.textContent = NOT_READY_WARNING;
    warning.classList.add("visible");
  }
  if (record.readyRetries < 1) {
    record.readyRetries += 1;
    beginLoad(record);
  }
}

// The helper's answer to the token: the page's address and the port it made (A-577).
function openRelay(message, ports, record) {
  if (record.token === null || message.token !== record.token) return;
  record.token = null;
  if (message.href !== new URL(record.url, location.href).href || ports.length !== 1) {
    return strayLoad(record);
  }
  record.port = ports[0];
  record.port.onmessage = (event) => privateMessage(event.data, record);
  record.relayOpen = true;
  if (record === active) {
    answerRelay.onFrameReady(true);
    sendSigns();
  }
}

function frameElement(record) {
  const element = document.createElement("iframe");
  element.title = "Page";
  element.setAttribute("sandbox", "allow-scripts");
  element.addEventListener("load", () => onFrameLoaded(record));
  return element;
}

function reloadFrame() {
  if (!active) return;
  // A hung frame cannot navigate itself, so replace the element: this
  // discards the frame and its renderer state.
  const fresh = frameElement(active);
  fresh.id = "frame";
  active.element.remove();
  active.element = fresh;
  beginLoad(active);
}

function frameOf(source) {
  for (const record of liveFrames.values()) {
    if (source && record.element.contentWindow === source) return record;
  }
  return null;
}

function dropFrame(record) {
  closePrivatePort(record);
  record.element.remove();
  liveFrames.delete(record.url);
}

// SES-15: a frame that leaves the screen keeps its document but takes no owner input
// (inert, hidden by the style sheet) and leaves comment mode and playing media; an
// earlier version, or a page of a closed tab, is not kept.
function hideFrame(record) {
  record.element.removeAttribute("id");
  record.element.inert = true;
  if (record.old || !tabs.some((t) => t.id === record.session)) return dropFrame(record);
  if (record.element.contentWindow) {
    record.element.contentWindow.postMessage({type: "frame-hidden"}, "*");
  }
}

// Only the MAX_LIVE_FRAMES most recently shown frames stay; a dropped one loads again
// when shown, with its kept block state and scroll place (D-55, D-56).
function trimFrames() {
  for (const record of liveFrames.values()) {
    if (liveFrames.size <= MAX_LIVE_FRAMES) return;
    if (record !== active) dropFrame(record);
  }
}

function newFrame(url) {
  const record = {
    url, session: activeId, old: viewing !== null, errors: [], recent: [],
    started: false, token: null, relayOpen: false, port: null, lastHeartbeat: 0, epoch: 0,
    loadCount: 0, readyCount: 0, readyRetries: 0,
    pendingScroll: scrollPlaces.get(url) || null,
  };
  record.element = frameElement(record);
  return record;
}

function loadFrame(url) {
  if (active) hideFrame(active);
  active = null;
  errorBadge.hidden = true;
  if (url === null) {
    currentUrl = null;
    answerRelay.onLoadBegin();
    commentsPageChanged();
    newsPageChanged();
    return;
  }
  currentUrl = url;
  warning.classList.remove("visible");
  notice.classList.remove("visible");
  const kept = liveFrames.get(url);
  active = kept || newFrame(url);
  liveFrames.delete(url);
  liveFrames.set(url, active);
  active.element.id = "frame";
  active.element.inert = false;
  active.lastHeartbeat = performance.now();
  if (kept) setErrors(active, active.errors);
  else {
    trimFrames();
    beginLoad(active);
  }
  commentsPageChanged();
  newsPageChanged();
  if (kept && active.relayOpen) {
    answerRelay.onFrameReady(true);
  } else {
    answerRelay.onLoadBegin();
    answerRelay.onPageChanged();
  }
  if (kept && active.readyCount > 0) {
    syncHighlight();
    commentsOnReady();
  }
}

// ---- the private channel (DO-02, CNT-01, CNT-03, SEC-09) ---------------------------
//
// Copy and Open reach the shell only over the MessagePort that this load's helper holds
// in a closure; a page script cannot send on it. The same request through
// ``window.postMessage`` is refused.
const PRIVATE_MESSAGES = new Map([
  ["copy", {fields: ["id", "step", "kind", "text"], handle: (m) => answerRelay.onFrameCopy(m)}],
  ["open-file", {fields: ["path"], handle: (m) => answerRelay.onFrameOpen(m)}],
]);
const PRIVATE_LIMIT = 1024;
let warnedPlain = false;

function closePrivatePort(record) {
  if (record.port) record.port.close();
  record.port = null;
}

function privateMessage(message, record = active) {
  const row = message ? PRIVATE_MESSAGES.get(message.type) : undefined;
  if (!row) {
    if (message && typeof message.type === "string") noteUnknown("from the page", message.type);
    return drop("type");
  }
  if (record !== active) return drop("hidden");
  if (message.type === "copy") copyFrame = record;
  if (!rateAllowed(record, performance.now())) {
    if (message.type === "copy") showCopyFailed("the page sent too many messages; press Copy again.");
    return drop("rate");
  }
  if (JSON.stringify(message).length > PRIVATE_LIMIT) return drop("size");
  const accepted = window.__guard.accepted;
  accepted[message.type] = (accepted[message.type] || 0) + 1;
  noteUnknownFields("from the page", message, row);
  row.handle(message);
}

// ---- message guard (SEC-09) ----------------------------------------------------

function rateAllowed(record, now) {
  const recent = record.recent;
  while (recent.length && now - recent[0] > 1000) {
    recent.shift();
  }
  if (recent.length >= RATE_LIMIT_PER_SECOND) return false;
  recent.push(now);
  return true;
}

function drop(reason) {
  window.__guard.dropped[reason] += 1;
}

function guardedMessage(event) {
  // A hidden frame of a `look` talks to render.js, not to the page logic here.
  if (window.canvasRender.owns(event.source)) return;
  const record = frameOf(event.source);
  if (!record) return drop("source");
  if (!rateAllowed(record, performance.now())) return drop("rate");
  const message = event.data;
  if (!message || typeof message.type !== "string") return drop("type");
  if (PRIVATE_MESSAGES.has(message.type)) {
    if (!warnedPlain) {
      console.warn(`agent-canvas: a "${message.type}" message outside the private channel was refused`);
    }
    warnedPlain = true;
    return drop("private");
  }
  const row = FRAME_MESSAGES.get(message.type);
  if (row === undefined) {
    noteUnknown("from the page", message.type);
    return drop("type");
  }
  if (JSON.stringify(message).length > row.limit) return drop("size");
  // SES-15: owner input only comes from the frame on screen.
  if (record !== active && !row.hidden) return drop("hidden");
  const accepted = window.__guard.accepted;
  accepted[message.type] = (accepted[message.type] || 0) + 1;
  noteUnknownFields("from the page", message, row);
  row.handle(message, record, event.ports);
}

function rememberBlockState(message, url) {
  if (typeof message.id !== "string") return;
  if (!blockStates.has(url) && blockStates.size >= MAX_STATE_PAGES) {
    blockStates.delete(blockStates.keys().next().value);
  }
  const states = blockStates.get(url) || {};
  if (message.id in states || Object.keys(states).length < MAX_STATE_BLOCKS) {
    states[message.id] = message.state;
    blockStates.set(url, states);
  }
}

function rememberScroll(message, record) {
  if (record.readyCount === 0 || record.pendingScroll) return;
  if (!scrollPlaces.has(record.url) && scrollPlaces.size >= MAX_STATE_PAGES) {
    scrollPlaces.delete(scrollPlaces.keys().next().value);
  }
  scrollPlaces.set(record.url, {x: Number(message.x) || 0, y: Number(message.y) || 0});
}

function onHeartbeat(message, record) {
  record.lastHeartbeat = performance.now();
  if (record === active) notice.classList.remove("visible");
}

function onReady(message, record) {
  record.lastHeartbeat = performance.now();
  record.readyCount += 1;
  if (record === active) {
    syncHighlight();
    commentsOnReady();
  }
  const states = blockStates.get(record.url);
  const target = record.element.contentWindow;
  if (states) target.postMessage({type: "restore-state", states}, "*");
  if (record.pendingScroll) {
    const {x, y} = record.pendingScroll;
    target.postMessage({type: "restore-scroll", x, y}, "*");
    record.pendingScroll = null;
  }
}

function onReload(message, record) {
  record.pendingScroll = {x: Number(message.scrollX) || 0, y: Number(message.scrollY) || 0};
  beginLoad(record);
}

// A shortcut the helper forwards from inside the frame (DRAW-01, DRAW-03,
// FB-04). The helper already decided whether the page's focus is editable.
function handleKeyMessage(message) {
  if (typeof message.key !== "string" || message.key.length > 20) return;
  window.drawUi.handleKey({
    key: message.key, ctrl: message.ctrl === true, shift: message.shift === true,
    alt: message.alt === true, editable: message.editable === true,
  });
}

// A file dragged over the frame: the frame stops taking pointer input, so the
// drop lands on the shell (files.js handles it from there).
// A page can post the notice without any drag, so the shield falls by itself:
// after DRAG_NOTICE_MS without a drag event over the shell, or at the next pointer
// move (a real drag moves no pointer events).
const DRAG_NOTICE_MS = 3000;
let dragNoticeTimer = null;
function dropDragShield() {
  clearTimeout(dragNoticeTimer);
  document.body.classList.remove("file-drag");
}
function armDragShield() {
  clearTimeout(dragNoticeTimer);
  dragNoticeTimer = setTimeout(dropDragShield, DRAG_NOTICE_MS);
}
function onFrameDrag() {
  document.body.classList.add("file-drag");
  armDragShield();
}
document.addEventListener("dragover", () => {
  if (document.body.classList.contains("file-drag")) armDragShield();
});
document.addEventListener("pointermove", () => {
  if (document.body.classList.contains("file-drag")) dropDragShield();
});

// A viewer that could not show its file tells the hub, which logs it (VIEW-14).
function relayViewerError(data, record) {
  if (!record.old) sendToHub({type: "page-report", url: record.url, name: "viewer-error", data});
}

function handleReport(name, data, record) {
  window.__reports.push({name, data});
  if (window.__reports.length > MAX_REPORTS) window.__reports.shift();
  // An earlier version is not the live page: its reports stay in the shell.
  const relay = !record.old;
  if (name === "error") {
    setErrors(record, [...record.errors, data].slice(-MAX_KEPT));
    if (relay) sendToHub({type: "page-report", url: record.url, name, data});
  } else if (name === "loaded" && relay) {
    sendToHub({type: "page-report", url: record.url, name, data: null});
  } else if (name === "viewer-error") {
    relayViewerError(data, record);
  }
}

window.addEventListener("message", guardedMessage);

// ---- watchdogs -----------------------------------------------------------------

setInterval(() => {
  if (active && performance.now() - active.lastHeartbeat > HEARTBEAT_TIMEOUT_MS) {
    showNotice("Page unresponsive");
  }
}, 250);

// PAGE-09: every document the frame loads must report ready. A page that
// navigated itself away (for example to about:blank) never does. The load
// event does not bubble but is seen in the capture phase.
main.addEventListener("load", (event) => {
  const record = Array.from(liveFrames.values()).find((r) => r.element === event.target);
  if (!record) return;
  record.loadCount += 1;
  const expected = record.loadCount;
  const startedIn = record.epoch;
  setTimeout(() => {
    if (startedIn !== record.epoch || !record.element.isConnected) return;
    if (record.readyCount >= expected) {
      if (record === active) warning.classList.remove("visible");
      record.readyRetries = 0;
      return;
    }
    if (record === active) {
      warning.textContent = NOT_READY_WARNING;
      warning.classList.add("visible");
    }
    if (record.readyRetries < 1) {
      record.readyRetries += 1;
      beginLoad(record);
    }
  }, READY_TIMEOUT_MS);
}, true);

document.getElementById("notice-reload").addEventListener("click", reloadFrame);

// ---- tabs ----------------------------------------------------------------------

const tabs = [];            // {id, project, agent, title, ..., page, updated}
let activeId = null;
let viewing = null;         // {page, version} while an earlier version is shown

function activeTab() {
  return tabs.find((t) => t.id === activeId) || null;
}

function projectName(tab) {
  const parts = String(tab.project || "").split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "project";
}

function tabName(tab) {
  return `${projectName(tab)} · ${tab.agent} · ${tab.title}`;
}

function draftOf(id) {
  const draft = window.__drafts[id] || (window.__drafts[id] = {});
  // Tolerate partial drafts set from outside (tests, older shapes).
  draft.actions = draft.actions || [];
  draft.actions_dropped = draft.actions_dropped || 0;
  return draft;
}

// What ``draw.js`` needs from this file.
window.__shell = {
  activeTab,
  draftOf,
  api,
  getFrame: () => active && active.element,
  isViewing: () => viewing !== null,
  viewing: () => viewing,
  outboxPending: () => outbox.length + commentOutbox.size(),
  outboxBytes: () => commentOutbox.bytes(),
  isOffline: () => hubOffline,
  commentsBusy: () => commentOutbox.busy(),
  commentKey: (key, mods) => commentKey(key, mods),
  windowKey: (key, mods) => windowKey(key, mods),
  unsentComments: () => unsentComments(),
  refreshComments: () => requestComments(),
};

// SES-07, SES-11: sessions with news count in the title; ``tab.stamp`` orders them by
// recency for "next update".
let stampCounter = 0;

function hasQuestion(tab) {
  return tab.id !== activeId && (tab.asks || []).length > 0;
}

function badged(tab) {
  return Boolean(tab.updated) || hasQuestion(tab);
}

function markNews(tab, asked) {
  tab.stamp = ++stampCounter;
  if (!asked) tab.updated = true;
}

// A viewer page (Markdown, PDF, picture) is loaded as its viewer document (VIEW-02).
function frameUrl(tab, page) {
  const query = [];
  if (VIEWER_NAME.test(page)) query.push("ac-view=1");
  const suffix = query.length ? `?${query.join("&")}` : "";
  return tab.base + encodeURIComponent(page) + suffix;
}

function upsertTab(incoming) {
  let tab = tabs.find((t) => t.id === incoming.id);
  if (!tab) {
    tab = {updated: false, page: null, asks: []};
    tabs.push(tab);
  }
  Object.assign(tab, incoming);
  tab.pages = [...(incoming.pages || [])];
  if (!tab.page || !tab.pages.includes(tab.page)) tab.page = incoming.active_page;
  return tab;
}

function renderTabs() {
  for (const record of Array.from(liveFrames.values())) {
    if (record !== active && !tabs.some((t) => t.id === record.session)) dropFrame(record);
  }
  drawView();
  const tab = activeTab();
  const news = tabs.filter(badged).length;
  const base = tab ? tabName(tab) : "agent-canvas";
  document.title = news ? `(${news}) ${base}` : base;
  renderAsks();
  window.drawUi.updateBar(); // the tab's newest send or its end (FB-10, ANS-08)
}

// ---- the Herdr view: sidebar, tab bar, one card per pane (herdr-view.js) -------------
//
// The view decides which card has the focus; the shown session (``activeId``) follows it.
// The focused card's frame slot stays empty: ``#content`` (page frames, send button)
// lies over it, so the page frames never move in the document (a moved frame reloads).
// The other cards hold a plain frame of their session's page: view only, no relay.

const content = document.getElementById("content");
const herdrRoot = document.getElementById("herdr");
let herdr = null;           // the hub's last ``herdr`` message
let shownSlot = null;
const slotSize = new ResizeObserver(() => placeContent());
const view = HerdrView.mount(herdrRoot, {
  onSpace: (space) => focusHerdr({space}),
  onTab: (tab) => focusHerdr({tab}),
  onPane: (terminal) => focusHerdr({terminal}),
  onOther: () => followView(),
  onPage: openPageOf,
  onFrame: placeFrame,
  onMachineOnline: reloadMachine,
});

const herdrPanes = () => (herdr ? herdr.spaces.flatMap((s) => s.tabs.flatMap((t) => t.panes)) : []);
const focusedSlot = () => herdrRoot.querySelector(".hv-card.focus .hv-frame");

// The sessions in the sidebar's order: those in Herdr's panes, then the others.
function sessionOrder() {
  const ids = herdrPanes().map((p) => p.session).filter((id) => tabs.some((t) => t.id === id));
  return [...new Set(ids), ...tabs.map((t) => t.id).filter((id) => !ids.includes(id))];
}

// Every session no pane holds goes under "Not in Herdr" of its machine, also before the hub's next poll.
function drawView() {
  const paired = new Set(herdrPanes().map((p) => p.session));
  const loose = tabs.filter((t) => !paired.has(t.id));
  const other = loose.filter((t) => !t.machine).map((t) => t.id);
  const machines = ((herdr && herdr.machines) || []).map((m) => (
    {...m, other: loose.filter((t) => t.machine === m.name).map((t) => t.id)}));
  view.update({...(herdr || {available: false, focus: null, spaces: []}), other, machines},
    tabs.map((t) => ({...t, active_page: t.page})));
  followView();
}

function onHerdr(message) {
  herdr = message;
  drawView();
}

// A machine is back online: its pages may have changed while it was away, so every frame
// of its sessions loads again (the shown one now, kept ones when next shown).
function reloadMachine(machine, ids) {
  for (const slot of herdrRoot.querySelectorAll(".hv-frame")) {
    const frame = slot.querySelector("iframe");
    if (frame && ids.includes(slot.dataset.session)) frame.src = frame.getAttribute("src");
  }
  for (const record of Array.from(liveFrames.values())) {
    if (!ids.includes(record.session)) continue;
    if (record === active) reloadFrame();
    else dropFrame(record);
  }
}

function followView() {
  const slot = focusedSlot();
  const id = slot ? slot.dataset.session : null;
  if (id !== activeId) setActive(id);
  placeContent();
}

function placeContent() {
  const slot = focusedSlot();
  if (slot !== shownSlot) {
    slotSize.disconnect();
    if (slot) slotSize.observe(slot);
    shownSlot = slot;
  }
  content.hidden = !slot;
  if (!slot) return;
  const head = slot.closest(".hv-card").querySelector(".hv-chead");
  if (errorBadge.parentElement !== head) head.append(errorBadge); // a redraw empties the head
  const box = slot.getBoundingClientRect();
  Object.assign(content.style, {
    left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px`,
  });
}

function placeFrame(slot, sessionId, page) {
  const tab = tabs.find((t) => t.id === sessionId);
  let frame = slot.querySelector("iframe");
  if (!tab || !page || slot.closest(".hv-card").classList.contains("focus")) {
    frame?.remove();
    return;
  }
  if (!frame) {
    frame = el("iframe");
    frame.title = `${tab.title} (view only)`;
    frame.setAttribute("sandbox", "allow-scripts");
    slot.append(frame);
  }
  const url = frameUrl(tab, page);
  if (frame.getAttribute("src") !== url) frame.src = url;
}

// A click in the view: the window follows at once, then Herdr; a target Herdr already
// has in focus is not sent (no echo of a focus the hub reported).
function focusHerdr(target) {
  followView();
  const focus = (herdr && herdr.focus) || {};
  const same = target.terminal
    ? herdrPanes().some((p) => p.terminal === target.terminal && p.pane === focus.pane)
    : target.space ? target.space === focus.space : target.tab === focus.tab;
  if (!same) api("POST", "/api/herdr/focus", target);
}

function openPageOf(id, page) {
  const tab = tabs.find((t) => t.id === id);
  if (!tab) return;
  if (id === activeId) switchPage(tab, page);
  else tab.page = page;
}

// The window opens a session itself (next update, a card's link, a reload): its card takes
// the focus and Herdr is asked to focus its pane.
function activate(id) {
  drawView();
  const pane = view.show(id);
  if (pane && herdr.focus?.pane !== pane.pane) {
    api("POST", "/api/herdr/focus", {terminal: pane.terminal});
  }
  if (focusedSlot()?.dataset.session === id) setActive(id);
  else followView();
}

function setActive(id) {
  const tab = tabs.find((t) => t.id === id) || null;
  activeId = tab && tab.id;
  if (tab) tab.updated = false;
  window.__errors = [];
  loadFrame(tab && tab.page ? frameUrl(tab, tab.page) : null);
  window.drawUi.updateBar();
  renderTabs(); // last: a view that moves the focus again sets its own session
}

// Open the session's card on this page; a closed session is unhidden first and
// opened when its tab arrives in the next tabs message.
let pendingOpen = null;     // {id, page} of a closed session being reopened

function openSessionPage(id, page) {
  const tab = tabs.find((t) => t.id === id);
  if (tab) {
    if (page) tab.page = page;
    activate(id);
    return;
  }
  pendingOpen = {id, page};
  api("POST", `/api/sessions/${encodeURIComponent(id)}/unhide`, {}).then(openPending);
}

function openPending() {
  const tab = pendingOpen && tabs.find((t) => t.id === pendingOpen.id);
  if (!tab) return false;
  if (pendingOpen.page) tab.page = pendingOpen.page;
  pendingOpen = null;
  activate(tab.id);
  return true;
}

// A banner's button, pressed from the keyboard when the banner is on screen.
const pressVisible = (bannerId, buttonId) => {
  const banner = document.getElementById(bannerId);
  const button = document.getElementById(buttonId);
  if (!banner.classList.contains("visible") || button.hidden) return false;
  button.click();
  return true;
};

// What each window key does (KEY-01 to KEY-03, herdr-canvas): action name before the ``:`` ->
// handler, given the part after it. A handler that returns false leaves the key unused.
const WINDOW_ACTIONS = {
  "sidebar.toggle": () => { herdrRoot.classList.toggle("folded"); },
  "contents.open": () => { if (active) pageContents.ask(postToFrame); },
  "space.next": () => view.goSpace(1),
  "space.prev": () => view.goSpace(-1),
  "space.select": (n) => view.goSpace(0, n - 1),
  "machine.fold": () => view.foldMachine(),
  "tab.next": () => view.goTab(1),
  "tab.prev": () => view.goTab(-1),
  "tab.select": (n) => view.goTab(0, n - 1),
  "pane.go": (side) => view.goPane(side),
  "pane.next": () => view.goPane(null, 1),
  "pane.prev": () => view.goPane(null, -1),
  "page.next": () => view.goPage(1),
  "page.prev": () => view.goPage(-1),
  "page.pin": () => {
    const shown = view.shownPage();
    if (!shown) return false;
    api("POST", "/api/home/pages", {session: shown.session, page: shown.page, pin: !shown.pinned});
  },
  "file.open": () => window.fileUi.pick(),
  "notice.reload": () => pressVisible("notice", "notice-reload"),
  "update.reload": () => pressVisible("update-bar", "update-reload"),
  "update.cancel": () => pressVisible("update-bar", "update-cancel"),
  "changes.dismiss": () => pressVisible("changes-bar", "changes-dismiss"),
  "asks.focus": () => {
    const control = document.querySelector("#ask-bar button, #ask-bar textarea, #ask-bar input");
    if (!control) return false;
    control.focus();
  },
};

// The keys of the window; the key rules (not while editing unless Ctrl or Alt is held,
// forwarded from the frame) are applied by the caller. True when handled.
function windowKey(key, mods = {}) {
  if (pageContents.isOpen()) return pageContents.key(key);
  if (keyMap.is("help.open", key, mods)) {
    keyHelp.open();
    return true;
  }
  const actions = keyMap.actionsOf(key, mods);
  // In comment mode a key of the comment keys is theirs (KMAP-04: the vim L is also the lasso).
  if (commentModeOn() && actions.some((a) => keyMap.scopeOf(a) === "comment")) return false;
  for (const action of actions) {
    const [name, argument] = action.split(":");
    const handler = name.startsWith("comment.") ? () => commentPanelKey(name.slice(8)) : WINDOW_ACTIONS[name];
    if (handler && handler(argument) !== false) return true;
  }
  return false;
}

// ---- opening files (VIEW-09, PAGE-06) ------------------------------------------------------

window.fileUi.init({
  allowed: (name) => PAGE_NAME.test(name) && !/\.draft\.html$/i.test(name),
  notice: showNotice,
  activeId: () => activeId,
  sessions: () => tabs,
  openPage: openSessionPage,
});

function switchPage(tab, page) {
  if (!PAGE_NAME.test(page)) return;
  if (!tab.pages.includes(page)) tab.pages.push(page);
  tab.page = page;
  renderTabs();
  loadFrame(frameUrl(tab, page));
}

function handleNavigate(page) {
  const tab = activeTab();
  if (viewing !== null || !tab || typeof page !== "string") return;
  switchPage(tab, page);
}

function cleanTarget(target) {
  const text = (key, limit) => (typeof target[key] === "string"
    ? target[key].slice(0, limit) : null);
  return {
    tag: text("tag", 20) || "",
    href: text("href", 500) || "",
    canvas_id: text("canvas_id", 200),
    selector: text("selector", 500),
    text: text("text", 80) || "",
  };
}

// Keep the latest MAX_DRAFT_ACTIONS actions and count what fell off (FB-05).
// SEC-09: an action recorded with no recent click or key press of the owner goes to
// the hub as ``no_gesture`` with the next send, which marks it as not from the owner.
function recordAction(tab, record) {
  if (!navigator.userActivation.isActive) record.no_gesture = true;
  const draft = draftOf(tab.id);
  draft.actions.push(record);
  while (draft.actions.length > MAX_DRAFT_ACTIONS) {
    draft.actions.shift();
    draft.actions_dropped += 1;
  }
  window.drawUi.updateBar();
  return record;
}

// Actions blocks record besides the plain ``click`` (5.4).
const BLOCK_ACTION_KINDS = [
  "select", "input", "plot-click", "plot-select", "image-click", "model-mark", "scene-mark",
];

function handleAction(action) {
  const tab = activeTab();
  if (viewing !== null || !tab || !action) return;
  const isBlockAction = BLOCK_ACTION_KINDS.includes(action.kind);
  if (action.kind !== "click" && !isBlockAction) return;
  recordAction(tab, {
    kind: action.kind,
    time: String(action.time || ""),
    target: cleanTarget(action.target || {}),
    value: isBlockAction && action.value !== undefined ? action.value : null,
    at: Array.isArray(action.at) ? action.at.slice(0, 2).map(Number) : null,
    event: null,
    card: action.card === true,
  });
}

// Actions that produced an event, waiting for the hub to name it.
const eventRefs = new Map();
let nextEventRef = 1;

const EMIT_KINDS = ["custom", "button", "choice", "text"];

// The event target the hub stores (5.3): canvas id, selector and text only.
function eventTarget(target) {
  if (!target || typeof target !== "object") return null;
  const text = (key, limit) => (typeof target[key] === "string"
    ? target[key].slice(0, limit) : null);
  return {canvas_id: text("canvas_id", 200), selector: text("selector", 500),
    text: text("text", 80)};
}

// PAGE-07: relay an ``emit`` (a ``custom`` event) or a block's ``button``,
// ``choice`` or ``text`` event to the hub and record its action. SEC-09: one that
// arrives with no recent click or key press of the owner (none in the frame or the
// shell, which a frame's activation reaches too) goes as ``no_gesture`` and the hub
// marks it as not from the owner.
function handleEmit(message) {
  const tab = activeTab();
  const kind = message.kind === undefined ? "custom" : message.kind;
  if (viewing !== null || !tab || !EMIT_KINDS.includes(kind)) return;
  let value = message.value === undefined ? null : message.value;
  if (kind === "custom") {
    if (typeof message.name !== "string") return;
    value = {name: message.name, value};
  }
  const target = eventTarget(message.target);
  const action = recordAction(tab, {
    kind, time: new Date().toISOString(), target, value, at: null, event: null,
  });
  const ref = nextEventRef++;
  eventRefs.set(ref, action);
  sendToHub({
    type: "event", ref, session: tab.id, kind, page: tab.page, value, target,
    delivery: message.delivery === "next-message" ? "next-message" : "now",
    ...(navigator.userActivation.isActive ? {} : {no_gesture: true}),
  });
}

async function api(method, path, body) {
  try {
    const response = await fetch(path, {
      method,
      headers: body ? {"Content-Type": "application/json"} : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    return response.ok ? await response.json() : null;
  } catch (error) {
    return null;
  }
}

// ---- hub messages --------------------------------------------------------------------

// SES-07: a shown page never changes the shown session, except in a window launched by
// that show (``initial``). Another tab only gets
// an "updated" badge.
function onShow(message, initial) {
  const tab = upsertTab(message.tab);
  if (!PAGE_NAME.test(message.page)) return;
  if (!tab.pages.includes(message.page)) tab.pages.push(message.page);
  tab.page = message.page;
  const active = activeTab();
  const isTarget = active !== null && active.id === tab.id;
  if (initial) {
    activate(tab.id);
  } else if (isTarget) {
    renderTabs();
    // A repeated ``show`` of the page on screen keeps the document (the file
    // watcher already updates it in place); agents call ``show`` after every
    // rewrite and must not lose scroll, block state or running scripts.
    const url = frameUrl(tab, message.page);
    if (url !== currentUrl) loadFrame(url);
    else if (active.readyCount < active.loadCount) beginLoad(active);
  } else {
    if (!initial) markNews(tab, false);
    renderTabs();
  }
}

// FB-06: the hub says when a session gains its first or loses its last listener.
function setListening(sessionId, listening, watching) {
  const tab = tabs.find((t) => t.id === sessionId);
  if (!tab) return;
  tab.listening = Boolean(listening);
  tab.watching = Boolean(watching);
  window.drawUi.updateBar(); // the receipt line says whether the agent listens (FB-10)
}

// After the shell reloaded, by itself for an update or by hand: back to the tab, page and
// version the owner was on (SHELL-03).
function restoreView(restore) {
  const tab = tabs.find((t) => t.id === restore.session);
  if (!tab) return false;
  if (restore.page && !tab.pages.includes(restore.page)) return false; // the page is gone (#74)
  if (restore.page) tab.page = restore.page;
  activate(tab.id);
  return true;
}

function onTabs(message) {
  const incoming = message.sessions.map((t) => t.id);
  const viewed = activeTab() ? activeTab().page : null;
  for (const tab of message.sessions) upsertTab(tab);
  for (let i = tabs.length - 1; i >= 0; i--) {
    if (!incoming.includes(tabs[i].id)) tabs.splice(i, 1);
  }
  renderTabs(); // a session that is gone leaves its card; the shown one follows the view
  answerRelay.onTabs();
  const now = activeTab();
  if (viewed && now && now.page !== viewed && !message.show) {
    loadFrame(now.page ? frameUrl(now, now.page) : null); // the page was archived (LIFE-04)
    window.drawUi.updateBar();
  }
  const restore = window.shellUpdate.takeRestore();
  if (restore && restoreView(restore)) return;
  if (openPending()) return;
  if (message.show) {
    const tab = tabs.find((t) => t.id === message.show.session);
    if (tab) onShow({tab, page: message.show.page,
      url: frameUrl(tab, message.show.page)}, true);
  }
}

// ---- question cards and awaited blocks (CLI-04 to CLI-06) -------------------------

function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

// Tell the frame which blocks an ``ask --block`` waits on (it outlines them).
function syncHighlight() {
  const tab = activeTab();
  if (!active || !tab || active.session !== tab.id) return;
  const ids = (tab.asks || []).filter((a) => a.block).map((a) => a.block);
  postToFrame({type: "highlight", ids});
}

// RES-02: the owner's choice or Dismiss on a result card; true when the hub took it.
async function answerResult(session, body) {
  const answer = await api("POST", `/api/sessions/${encodeURIComponent(session)}/result/answer`, body);
  if (!answer) showNotice("The answer was not saved; try again.");
  return Boolean(answer);
}

// RES-02: a file chip that is not a page copies its path.
async function copyPath(path) {
  try {
    await navigator.clipboard.writeText(path);
    return true;
  } catch (error) {
    showNotice("The path could not be copied.");
    return false;
  }
}

// POOL-03: the sessions of a project share one pool; its pages, comments and answers are the
// pool's, so a message names the pool or any card of it and counts for every card of the pool.
function poolOf(id) {
  return tabs.find((t) => t.id === id)?.pool || id;
}

// Show the active tab's open asks above the page (cards.js draws them).
function renderAsks() {
  if (window.shellCards) {
    window.shellCards.sync(activeTab(), askBar, {
      offline: () => hubOffline,
      answer: (session, ask, value) => sendToHub({type: "ask-answer", session, ask, value}),
      dismiss: (session, ask) => sendToHub({type: "ask-dismiss", session, ask}),
      result: answerResult,
      openPage: openSessionPage,
      copy: copyPath,
    });
  }
  syncHighlight();
}
document.addEventListener("shellcards-ready", renderAsks);

// SES-07: a new ask never changes the shown session; another one counts as news.
function onAskOpened(message) {
  const tab = upsertTab(message.tab);
  const active = activeTab();
  if (active === null || active.id !== tab.id) markNews(tab, true);
  renderTabs();
}

// A data file in the session folder changed: the page's blocks may reload it
// (BLK-09). Only the live pages of the session in the frames are told, shown or not.
function onFileChanged(message) {
  if (typeof message.path !== "string") return;
  for (const record of liveFrames.values()) {
    if (poolOf(record.session) !== poolOf(message.session) || record.old) continue;
    record.element.contentWindow.postMessage({type: "file-changed", path: message.path}, "*");
  }
}

function onSendState(message) {
  const tab = tabs.find((t) => t.id === message.session);
  if (tab) tab.send = message.send; // FB-10
  window.drawUi.updateBar();
}

function onEventCreated(message) {
  const action = eventRefs.get(message.ref);
  eventRefs.delete(message.ref);
  if (action) action.event = message.event;
  window.drawUi.updateBar();
}

function onUpdate(message) {
  for (const frame of herdrRoot.querySelectorAll(".hv-frame iframe")) {
    if (frame.getAttribute("src") === message.url) frame.src = message.url; // a view-only card
  }
  if (!liveFrames.has(message.url)) return;
  if (message.url === currentUrl) pageContents.close(); // its indexes are of the old page
  liveFrames.get(message.url).element.contentWindow.postMessage(
    {type: "update", html: message.html, version: message.version, viewer: message.viewer,
      digest: message.digest},
    "*");
  if (message.url === currentUrl) {
    commentsVersionChanged();
    newsUpdated(message.version);
  }
}

// The messages the hub sends this window (P33.2, ARC-04): type -> field names and
// handler. The hub's own copy is ``WINDOW_MESSAGES`` in ``hub/messages.py``.
const HUB_MESSAGES = new Map([
  ["hello", {fields: ["build", "version"], handle: (m) => window.shellUpdate.onHello(m)}],
  ["tabs", {fields: ["sessions", "closed", "show"], handle: onTabs}],
  ["herdr", {fields: ["available", "focus", "spaces", "machines", "other"], handle: onHerdr}],
  ["show", {fields: ["session", "page", "url", "tab"], handle: (m) => onShow(m, false)}],
  ["ask-opened", {fields: ["session", "tab"], handle: onAskOpened}],
  ["listening", {fields: ["session", "listening", "watching"],
    handle: (m) => setListening(m.session, m.listening, m.watching)}],
  ["send-state", {fields: ["session", "send"], handle: onSendState}],
  ["event-created", {fields: ["ref", "event"], handle: onEventCreated}],
  ["file-changed", {fields: ["session", "path"], handle: onFileChanged}],
  ["comments", {fields: ["session", "page", "next", "comments", "unsent"],
    handle: (m) => onCommentsMessage(m)}],
  ["answers", {fields: ["session", "page", "items", "folder"],
    handle: (m) => answerRelay.onHubMessage(m)}],
  ["render", {fields: ["id", "url", "width", "height", "scheme", "section", "full", "settle_ms",
    "audit", "picture", "answers"], handle: (m) => handleRender(m)}],  // looked up by name per message, as the old chain did (test_shell_06 replaces it)
  ["update", {fields: ["url", "version", "html", "viewer", "digest"], handle: onUpdate}],
]);

function connect() {
  socket = new WebSocket(`ws://${location.host}/ws/shell`);
  socket.addEventListener("open", () => {
    setOffline(false);
    flushOutbox();
    reportWindow();
    if (commentOutbox.size()) commentOutbox.flush(); else requestComments();
    answerRelay.onPageChanged();
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const row = HUB_MESSAGES.get(message.type);
    if (row) {
      noteUnknownFields("from the hub", message, row);
      row.handle(message);
    } else {
      noteUnknown("from the hub", message.type);
    }
  });
  socket.addEventListener("close", () => {
    setOffline(true);
    setTimeout(connect, 1000);
  });
}

// ---- what's new since the owner last looked (NEW-01, NEW-03) --------------------------

// A version counts as seen after SEEN_AFTER_MS as the active page of a visible window
// (A-95). Only this file reports it, from the owner's own view: a `look` renders in a
// hidden frame that never reaches here, and the hub never counts a page it serves.
const SEEN_AFTER_MS = 2000;
const MAX_SIGNS = 200;
const changesBar = document.getElementById("changes-bar");
const changesText = document.getElementById("changes-text");
const changesDismiss = document.getElementById("changes-dismiss");
// {session, page, version, since, sinceTime, result, signsSent, dismissedVersion} of the page
// shown live; the marks are hidden while the shown version is the one the owner dismissed (NEW-05)
let news = null;
let seenTimer = null;

function stopSeenTimer() {
  clearTimeout(seenTimer);
  seenTimer = null;
}

function armSeen() {
  stopSeenTimer();
  if (!news || news.version === null || document.visibilityState !== "visible") return;
  const watched = news;
  seenTimer = setTimeout(() => {
    const tab = activeTab();
    if (news !== watched || !tab || tab.id !== watched.session || tab.page !== watched.page) return;
    sendToHub({type: "seen", session: watched.session, page: watched.page, version: watched.version});
  }, SEEN_AFTER_MS);
}
document.addEventListener("visibilitychange", armSeen);

function newsPageChanged() {
  stopSeenTimer();
  changesBar.classList.remove("visible");
  const tab = activeTab();
  news = null;
  if (currentUrl === null || viewing !== null || !tab || !tab.page) return;
  // A kept frame (SES-15) may still show the signs of the last visit: they are cleared.
  news = {session: tab.id, page: tab.page, version: null, since: null, sinceTime: null,
          result: null, signsSent: Boolean(active && active.relayOpen), dismissedVersion: null};
  fetchNews(news);
}

// The hub compares the shown page with the version the owner saw when it was opened;
// that baseline stays until the owner leaves the page, even after the new version is seen.
async function fetchNews(state) {
  const since = state.since === null ? "" : `&since=${state.since}`;
  const answer = await api("GET",
    `/api/sessions/${encodeURIComponent(state.session)}/changes?page=${encodeURIComponent(state.page)}${since}`);
  if (news !== state || !answer || !Number.isInteger(answer.version)) return;
  state.version = answer.version;
  if (state.since === null && Number.isInteger(answer.since)) {
    state.since = answer.since;
    state.sinceTime = answer.since_time;
  }
  state.result = answer.count > 0 ? answer : null;
  drawChangesLine();
  sendSigns();
  armSeen();
}

function shownResult() {
  return news && news.dismissedVersion !== news.version ? news.result : null;
}

changesDismiss.addEventListener("click", () => {
  if (!news) return;
  news.dismissedVersion = news.version;
  drawChangesLine();
  sendSigns();
});

function drawChangesLine() {
  const result = shownResult();
  changesBar.classList.toggle("visible", Boolean(result));
  if (!result) return;
  const noun = result.count === 1 ? "change" : "changes";
  changesText.textContent = `${result.count} ${noun} since ${formatTime(news.sinceTime)}`;
}

// The signs are drawn by the helper in the comment layer's host, never in the page. They
// go only to a frame that answered this load's token, and again after each new load.
function sendSigns() {
  if (!news || !active || !active.relayOpen || !(news.result || news.signsSent)) return;
  const result = shownResult() || {added: [], changed: []};
  const signs = [
    ...result.added.map((id) => ({id, sign: "new"})),
    ...result.changed.map((id) => ({id, sign: "changed"})),
  ].filter((s) => typeof s.id === "string" && s.id.length <= 200).slice(0, MAX_SIGNS);
  news.signsSent = signs.length > 0;
  postToFrame({type: "change-signs", signs});
}

// A new version of the page on screen: compare again from the same baseline and wait
// another 2 s before it counts as seen.
function newsUpdated(version) {
  if (!news || !Number.isInteger(version)) return;
  news.version = version;
  armSeen();
  fetchNews(news);
}

// ---- look: window size and renders for the agent (LOOK-02, LOOK-03) ------------------

const WINDOW_REPORT_DEBOUNCE_MS = 250;

// Tell the hub the size of the page frame (every frame fills ``main``) and the colour
// scheme, so that an agent's `look` renders what the owner sees.
function reportWindow() {
  sendToHub({
    type: "window-info",
    width: main.clientWidth,
    height: main.clientHeight,
    scheme: window.canvasRender.currentScheme(),
    build: window.shellUpdate.loadedBuild || undefined,
  });
}

let windowReportTimer = null;
function scheduleWindowReport() {
  clearTimeout(windowReportTimer);
  windowReportTimer = setTimeout(reportWindow, WINDOW_REPORT_DEBOUNCE_MS);
}

new ResizeObserver(scheduleWindowReport).observe(main);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", scheduleWindowReport);

// The hub asked for a picture of a page: render it in a hidden frame and answer.
async function handleRender(request) {
  const result = await window.canvasRender.run(request);
  sendToHub({type: "render-result", id: request.id, ...result});
}

function formatTime(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

// ---- comments (COM-01 to COM-06, COM-15, COM-18; comment-feature.js) ----------------

function postToFrame(message) {
  if (active && active.element.contentWindow) active.element.contentWindow.postMessage(message, "*");
}

// An agent's reply or done in a tab that is not shown gives it the "updated" badge
// (RPL-04): some comment is unread now that was not before. In a pool, only the tabs
// that list the page get it.
function badgeInactiveTab(message, before) {
  const wasUnread = new Set(before ? before.comments.filter((c) => c.unread).map((c) => c.n) : []);
  if (!message.comments.some((c) => c.unread && !wasUnread.has(c.n))) return;
  const inactive = tabs.filter((t) => t.id !== activeId && poolOf(t.id) === poolOf(message.session)
    && (t.id === message.session || (t.pages || []).includes(message.page)));
  for (const tab of inactive) markNews(tab, false);
  if (inactive.length) renderTabs();
}

// The tabs' side of a page's comments from the hub: the news count and the send button.
function commentsArrived(message, before) {
  badgeInactiveTab(message, before);
  window.drawUi.updateBar();
}

// commentPages and commentTokens are not used here: browser tests read them by name.
const {
  commentPages, commentTokens, requestComments, renderCommentPanel, addSavedRecord, commentKey,
  unsentComments, commentsOf, onCommentsMessage, commentsPageChanged, commentsVersionChanged,
  commentsOnReady, onCommentSelection, onCommentPicture, onCommentMarker, onCommentLost,
  commentModeOn, updateCommentUi, commentPanelKey,
} = window.createCommentFeature({
  main, activeTab, poolOf, viewing: () => viewing, isOffline: () => hubOffline, commentOutbox,
  postToFrame, sendToHub, api, showNotice, drop,
  updateBar: () => window.drawUi.updateBar(), commentsArrived,
});

// KMAP-02: the key profile and the owner's keys.toml; no key works until they arrive, and a bad
// entry is reported and ignored. The overview saves changes through the same route.
function applyKeys() {
  postToFrame({type: "keys", keys: keyMap.forwarded()});
  updateCommentUi();
}

keyHelp.connect({save: (body) => api("POST", "/api/keys", body), changed: applyKeys});
api("GET", "/api/keys").then((answer) => {
  if (!answer) return;
  const problems = keyMap.configure(answer);
  keyHelp.report(problems);
  if (problems.length) showNotice(`keys.toml was partly ignored: ${problems.join("; ")}`);
  applyKeys();
});

connect();
