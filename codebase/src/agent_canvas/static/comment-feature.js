// Trusted shell: the comment feature of the window (COM-01 to COM-06, COM-15, COM-18):
// comment mode, the box, the panel, the markers, saving, and the cleaning of the
// positions the frame reports. shell.js makes it once and hands it what it needs of
// the window; comments.js draws the box and the panel.
//
// The comment text exists only here: the box and the panel are in the shell, and
// every message to the frame carries numbers, kinds, anchors, statuses and
// tokens only (COM-15). A report from the frame is used only when it carries
// the token of the open box or of a comment on the shown page (COM-18).
//
// Revision 12, HTML pages: the four selection kinds (P22.2).
"use strict";

(function () {
  // Pages the comment layer works on; the PDF viewer joins in P25.2.
  const COMMENTABLE_NAME = /\.(html|md|markdown|pdf|png|jpe?g|gif|webp|svg)$/i;

  // ---- the frame's reports, cleaned: plain functions (COM-03, COM-18) ---------------

  function finite(value, low, high) {
    return typeof value === "number" && Number.isFinite(value) && value >= low && value <= high
      ? value : null;
  }

  function cleanRect(raw) {
    if (!raw || typeof raw !== "object") return null;
    const rect = {
      x: finite(raw.x, -1e6, 1e6), y: finite(raw.y, -1e6, 1e6),
      w: finite(raw.w, 0, 1e6), h: finite(raw.h, 0, 1e6),
    };
    return Object.values(rect).includes(null) ? null : rect;
  }

  function cleanNumbers(raw, names, into) {
    for (const name of names) {
      const value = finite(raw[name], -1e6, 1e6);
      if (value === null) return false;
      into[name] = value;
    }
    return true;
  }

  function cleanPairs(raw, limit) {
    if (!Array.isArray(raw) || raw.length > limit) return null;
    const pairs = raw.map((p) => (Array.isArray(p) ? [finite(p[0], -1e6, 1e6), finite(p[1], -1e6, 1e6)] : [null]));
    return pairs.some((p) => p.includes(null)) ? null : pairs;
  }

  // A PDF's text rectangle: points from the top-left of page ``p`` (from 1).
  function cleanPdfRect(raw) {
    const rect = cleanRect(raw);
    const p = raw && finite(raw.p, 1, 1e5);
    return rect && Number.isInteger(p) ? {p, ...rect} : null;
  }

  // A viewer's shape anchor (ANC-02 to ANC-04): a picture's pixels in image-px with its
  // natural size, which decides when all its comments are lost, or a PDF's points in pdf-pt
  // on page ``p``, lost with the page (ANC-08). No fractions.
  function cleanPictureAnchor(raw, kind) {
    const anchor = {space: raw.space};
    if (raw.space === "pdf-pt") {
      anchor.p = finite(raw.p, 1, 1e5);
      if (!Number.isInteger(anchor.p)) return null;
    } else if (!cleanNumbers(raw, ["nw", "nh"], anchor)) {
      return null;
    }
    if (kind === "rect") return cleanNumbers(raw, ["x", "y", "w", "h"], anchor) ? anchor : null;
    if (kind === "point") return cleanNumbers(raw, ["x", "y"], anchor) ? anchor : null;
    const points = cleanPairs(raw.points, 200);
    const bbox = cleanRect(raw.bbox);
    if (kind !== "lasso" || !points || !bbox) return null;
    return Object.assign(anchor, {points, bbox});
  }

  // The anchor the frame reported, kept only with the fields of its kind (ANC-01 to ANC-04).
  function cleanAnchor(raw, kind) {
    if (!raw || typeof raw !== "object") return null;
    const pdf = raw.space === "pdf-pt";
    if (raw.space === "image-px" || (pdf && kind !== "text")) return cleanPictureAnchor(raw, kind);
    const anchor = {space: pdf ? "pdf-pt" : "page-px"};
    if (kind === "rect") {
      const rect = cleanRect(raw);
      if (!rect) return null;
      Object.assign(anchor, rect);
      return cleanNumbers(raw, ["fx", "fy", "fw", "fh"], anchor) ? anchor : null;
    }
    if (kind === "point") {
      return cleanNumbers(raw, ["x", "y", "fx", "fy"], anchor) ? anchor : null;
    }
    if (kind === "lasso") {
      const points = cleanPairs(raw.points, 200);
      const fpoints = cleanPairs(raw.fpoints, 200);
      const bbox = cleanRect(raw.bbox);
      if (!points || !fpoints || !bbox || points.length !== fpoints.length) return null;
      Object.assign(anchor, {points, bbox, fpoints});
      return cleanNumbers(raw, ["fx", "fy", "fw", "fh"], anchor) ? anchor : null;
    }
    const rects = Array.isArray(raw.rects) ? raw.rects.map(pdf ? cleanPdfRect : cleanRect) : null;
    if (typeof raw.quote !== "string" || !raw.quote || !rects || rects.includes(null)) return null;
    const text = (value) => (typeof value === "string" ? value.slice(0, 120) : "");
    Object.assign(anchor, {
      quote: raw.quote.slice(0, 1000), cut: raw.cut === true, before: text(raw.before),
      after: text(raw.after), rects,
    });
    return cleanNumbers(raw, ["start", "end"], anchor) ? anchor : null;
  }

  // Data coordinates over a plot (ANC-05): the plot's id and a number or a
  // [min, max] pair per axis.
  function cleanData(raw) {
    if (!raw || typeof raw !== "object") return null;
    const axis = (value) => {
      if (Array.isArray(value)) {
        const pair = value.map((v) => finite(v, -Infinity, Infinity));
        return pair.length === 2 && !pair.includes(null) ? pair : null;
      }
      return finite(value, -Infinity, Infinity);
    };
    const x = axis(raw.x);
    const y = axis(raw.y);
    if (x === null || y === null) return null;
    return {canvas_id: typeof raw.canvas_id === "string" ? raw.canvas_id.slice(0, 200) : null, x, y};
  }

  /**
   * Make the comment feature. ``main`` is the frame area the box opens over.
   * ``activeTab()`` gives the shown tab (``id``, ``page``), ``viewing()`` the earlier
   * version on screen (``{page, version}``) or null, ``isOffline()`` whether the hub is
   * away; ``commentOutbox`` is the shell's outbox (outbox.js). ``postToFrame(message)``
   * writes to the shown frame, ``sendToHub(message)`` to the hub's socket, ``api(method,
   * path)`` asks the hub, ``showNotice(text)`` shows a notice, ``drop(reason)`` counts a refused frame message,
   * ``updateBar()`` redraws the send button and ``commentsArrived(message, before)``
   * updates the tabs after the hub sent a page's comments (``before``: what was known).
   */
  function createCommentFeature({
    main, activeTab, viewing, isOffline, commentOutbox, postToFrame, sendToHub, api,
    showNotice, drop, updateBar, commentsArrived,
  }) {
    const PICTURE_TIMEOUT_MS = 5000;
    const COMMENT_KINDS = ["text", "point", "rect", "lasso"];
    const COMMENT_KIND_KEY = "agent-canvas.comment-kind";
    const BLOCK_NOTICE = "Text inside this block cannot be selected; use a point, rectangle or lasso";
    const commentPanel = document.getElementById("comment-panel");
    const commentPages = new Map();   // "session\npage" -> {comments, next}
    const hubUnsent = new Map();      // session id -> {comments, files}: the hub's count (R-16)
    const commentTokens = new Map();  // comment id -> token, for the shown page
    let commentMode = false;
    let commentKind = "rect";         // the last kind picked, kept across reloads (COM-02)
    let commentSelection = null;      // the open box: {token, anchor, target, ..., box}
    let selectedComment = null;       // number of the entry the owner selected
    let commentEditBox = null;        // the box of the draft being edited (COM-09)
    const narrowWindow = window.matchMedia("(max-width: 999px)");  // COM-06: the panel floats, comment mode does not open it
    narrowWindow.addEventListener("change", () => renderCommentPanel());
    const COMMENTS_COLLAPSED_KEY = "agent-canvas.comments-collapsed";
    let panelCollapsed = localStorage.getItem(COMMENTS_COLLAPSED_KEY) === "1";  // COM-20
    let panelOpened = false;         // the owner opened the collapsed strip
    let commentSaving = false;

    function randomToken() {
      const bytes = crypto.getRandomValues(new Uint8Array(12));
      return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    }

    function commentsKey(session, page) {
      return `${session}\n${page}`;
    }

    function shownComments() {
      const tab = activeTab();
      if (!tab || !tab.page) return null;
      const shown = commentPages.get(commentsKey(tab.id, tab.page)) || {comments: [], next: 1};
      if (viewing() === null) return shown;
      // An earlier version shows the comments made on it, as they were made (COM-14).
      const made = shown.comments.filter((c) => c.page_version === viewing().version);
      return {comments: made.map((c) => ({...c, lost: false})), next: shown.next};
    }

    // Comment mode works on a live page: not without one and not in an earlier
    // version, which shows its comments read-only (COM-14).
    function commentsAvailable() {
      const tab = activeTab();
      return Boolean(tab && tab.page && viewing() === null && COMMENTABLE_NAME.test(tab.page));
    }

    function commentsOf(session, page) {
      const entry = commentPages.get(commentsKey(session, page));
      return entry ? entry.comments : null;
    }

    function requestComments() {
      const tab = activeTab();
      if (tab && tab.page) sendToHub({type: "comments-get", session: tab.id, page: tab.page});
    }

    function tokenOf(comment) {
      let token = commentTokens.get(comment.id);
      if (!token) {
        token = randomToken();
        commentTokens.set(comment.id, token);
      }
      return token;
    }

    // What of an anchor the frame needs to find it again (ANC-06): numbers, the
    // quote and its surroundings (text of the page, not of the comment).
    function markerAnchor(anchor) {
      const out = {};
      if (!anchor) return out;
      if (typeof anchor.space === "string") out.space = anchor.space;
      for (const name of ["x", "y", "w", "h", "fx", "fy", "fw", "fh", "start", "end", "nw", "nh", "p"]) {
        if (Number.isFinite(anchor[name])) out[name] = anchor[name];
      }
      for (const name of ["quote", "before", "after"]) {
        if (typeof anchor[name] === "string") out[name] = anchor[name];
      }
      if (anchor.cut === true) out.cut = true;
      if (Array.isArray(anchor.fpoints)) out.fpoints = anchor.fpoints;
      if ((anchor.space === "image-px" || anchor.space === "pdf-pt") && Array.isArray(anchor.points)) {
        out.points = anchor.points;
      }
      return out;
    }

    // The page draws the markers of the comments the panel's filter shows (COM-22).
    let markerFilter = "open";
    const markerShown = (c) => markerFilter === "all" || (markerFilter === "done") === (c.status === "done");
    const setMarkerFilter = (key) => {
      markerFilter = key;
      sendMarkers();
    };

    function sendMarkers() {
      const shown = shownComments();
      if (!shown) return;
      const markers = shown.comments.filter(markerShown).map((c) => {
        const target = c.target || {};
        return {
          n: c.n, kind: c.kind, status: c.status, token: tokenOf(c), lost: c.lost === true,
          selector: typeof target.selector === "string" ? target.selector : null,
          canvas_id: typeof target.canvas_id === "string" ? target.canvas_id : null,
          anchor: markerAnchor(c.anchor),
        };
      });
      const selected = shown.comments.find((c) => c.n === selectedComment);
      postToFrame({
        type: "comment-markers", markers, selected: selected ? tokenOf(selected) : null,
      });
    }

    function sendCommentMode() {
      postToFrame({type: "comment-mode", on: commentMode, kind: commentKind});
    }

    function updateCommentUi() {
      document.body.classList.toggle("commenting", commentMode);
    }

    let cursorOn = false;       // the frame's keyboard cursor is on

    function setCommentMode(on) {
      if (on && !commentsAvailable()) return;
      if (commentMode === on) return;
      commentMode = on;
      cursorOn = false;
      closeCommentBox();
      updateCommentUi();
      sendCommentMode();
      renderCommentPanel();
    }

    // ``C`` and the keys that follow its rules (SES-11); the key rules (not while
    // editing, forwarded from the frame) are applied by the caller. True when handled.
    function commentKey(key, mods = {}) {
      const is = (action) => keyMap.is(action, key, mods);
      const cursor = (op) => {
        postToFrame({type: "comment-cursor", op, big: Boolean(mods.shift)});
        return true;
      };
      if (is("comment.toggle")) {
        setCommentMode(!commentMode);
        return true;
      }
      if (!commentMode) return false;
      if (is("comment.cursor")) {
        cursorOn = true;
        return cursor("enter");
      }
      if (cursorOn) {
        const side = ["left", "right", "up", "down"].find((s) => is(`comment.cursor.${s}`));
        if (side) return cursor(side);
        if (is("comment.cursor.finish")) return cursor("finish");
      }
      if (is("comment.leave")) {
        if (cursorOn) {
          cursorOn = false;
          return cursor("cancel");
        }
        if (commentSelection) closeCommentBox(); else setCommentMode(false);
        return true;
      }
      const kind = COMMENT_KINDS.find((k) => is(`comment.${k}`));
      if (!kind) return false;
      setCommentKind(kind);
      return true;
    }

    // The comment panel from the keyboard: each key presses the control the mouse would.
    // False when there is nothing to act on (no panel, no selected comment).
    function commentPanelKey(name) {
      if (commentPanel.hidden) return false;
      const strip = commentPanel.querySelector(".stripbutton");
      const press = (selector, text) => {
        const found = [...commentPanel.querySelectorAll(selector)]
          .find((e) => !e.disabled && (text === undefined || e.textContent === text));
        if (found) found.click();
        return Boolean(found);
      };
      if (name === "panel") return press(strip ? ".stripbutton" : ".collapse");
      if (name === "done") {
        toggleSelectedDone();
        return true;
      }
      if (strip) return false;
      const entries = [...commentPanel.querySelectorAll(".ent")];
      const at = entries.findIndex((e) => e.classList.contains("sel"));
      if (name === "next" || name === "prev") {
        const step = name === "next" ? 1 : -1;
        const to = at < 0 ? (step > 0 ? 0 : entries.length - 1) : (at + step + entries.length) % entries.length;
        if (!entries.length) return false;
        entries[to].click();
        entries[to].scrollIntoView({block: "nearest"});
        return true;
      }
      if (name === "fold") return press(".ent.sel .fold");
      if (name === "foldall") return press(".foldall");
      if (name === "filter") {
        const filters = [...commentPanel.querySelectorAll(".filters button")];
        const now = filters.findIndex((f) => f.getAttribute("aria-pressed") === "true");
        if (!filters.length) return false;
        filters[(now + 1) % filters.length].click();
        return true;
      }
      const label = {reply: "Reply", edit: "Edit", delete: "Delete"}[name];
      return label ? press(".ent.sel .acts button", label) : false;
    }

    // A new kind discards an open box; the choice is kept for the next load.
    function setCommentKind(kind) {
      if (!COMMENT_KINDS.includes(kind)) return;
      const changed = kind !== commentKind;
      commentKind = kind;
      try {
        localStorage.setItem(COMMENT_KIND_KEY, kind);
      } catch (error) {
        // No storage: the kind holds until the window is reloaded.
      }
      if (changed && commentMode) {
        cursorOn = false;
        closeCommentBox();
        sendCommentMode();
      }
      updateCommentUi();
    }

    try {
      const savedKind = localStorage.getItem(COMMENT_KIND_KEY);
      if (COMMENT_KINDS.includes(savedKind)) commentKind = savedKind;
    } catch (error) {
      // No storage: the default kind.
    }

    // ---- the panel -----------------------------------------------------------------------

    // The frame gets numbers' tokens only, never texts (COM-15). A lost comment has
    // no marker, so nothing is sent for it (COM-07).
    function markerToken(number) {
      const shown = shownComments();
      const found = shown && shown.comments.find((c) => c.n === number);
      return found && !found.lost ? tokenOf(found) : null;
    }

    // The box opens again with the draft's text, beside the panel; Enter saves.
    function editComment(number) {
      const tab = activeTab();
      const shown = shownComments();
      const found = shown && shown.comments.find((c) => c.n === number);
      const entry = commentPanel.querySelector(`.ent[data-n="${number}"]`);
      if (!tab || !found || !entry) return;
      if (commentEditBox) commentEditBox.close();
      const area = main.getBoundingClientRect();
      const row = entry.getBoundingClientRect();
      const box = window.commentsUi.openCommentBox(main, {
        number, kind: found.kind, title: "Edit comment", text: found.text,
        label: window.commentsUi.anchorLabel(found),
        rect: {x: commentPanel.getBoundingClientRect().left - area.left, y: row.top - area.top, w: 0, h: row.height},
        async onSave(text) {
          const result = await ownerEdit(number, {text});
          if (result.ok) box.close(); else box.note(result.data.message || "The comment was not saved.");
        },
        onClose() { if (commentEditBox === box) commentEditBox = null; },
      });
      commentEditBox = box;
      box.field.setSelectionRange(found.text.length, found.text.length);
    }

    // A change of the owner to a saved comment. Offline it waits in the outbox and
    // shows at once in the panel; the hub's push after the flush replaces that.
    async function ownerEdit(number, change) {
      const tab = activeTab();
      if (!tab || !tab.page) return {ok: false, data: {}};
      const path = `/api/sessions/${encodeURIComponent(tab.id)}/comments/edit`;
      const body = {page: tab.page, n: number, ...change};
      if (change.read) return commentRequest(path, body);
      const result = await commentOutbox.submit(path, body);
      if (result.queued) showQueuedChange(tab, number, change);
      return result;
    }

    function showQueuedChange(tab, number, change) {
      const shown = commentPages.get(commentsKey(tab.id, tab.page));
      const found = shown && shown.comments.find((c) => c.n === number);
      if (!found) return;
      if (change.text !== undefined) found.text = change.text;
      if (change.done) found.status = "done";
      if (change.reopen) found.status = "sent";
      if (change.reply) {
        found.replies = [...found.replies, {from: null, text: change.reply, at: new Date().toISOString(), sent: null}];
      }
      renderCommentPanel();
    }

    async function changeDone(number, change, failure) {
      const result = await ownerEdit(number, change);
      if (!result.ok) showNotice(result.data.message || failure);
    }

    // Selecting a comment clears its ``unread`` (RPL-05); the hub's push redraws the chip.
    function markRead(number) {
      const shown = shownComments();
      const found = shown && shown.comments.find((c) => c.n === number);
      if (found && found.unread) ownerEdit(number, {read: true});
    }

    // ``X`` in comment mode: done for the selected sent comment, reopen if it is done (RPL-05).
    function toggleSelectedDone() {
      const shown = shownComments();
      const found = shown && shown.comments.find((c) => c.n === selectedComment);
      if (!found || found.sent === null) return;
      if (found.status === "done") panelCallbacks.reopen(found.n); else panelCallbacks.done(found.n);
    }

    const panelCallbacks = {
      collapse: () => setPanelCollapsed(true),
      filter: setMarkerFilter,
      select(number) {
        selectedComment = number;
        if (viewing() === null) markRead(number);
        sendMarkers();
        const token = markerToken(number);
        if (token) postToFrame({type: "comment-scroll", token});
      },
      hover(number) {
        postToFrame({type: "comment-hover", token: number === null ? null : markerToken(number)});
      },
      edit: editComment,
      waiting: () => commentOutbox.size(),
      scope: () => {
        const tab = activeTab();
        return tab ? commentsKey(tab.id, tab.page) : "";
      },
      done: (number) => changeDone(number, {done: true}, "The comment was not marked done."),
      reopen: (number) => changeDone(number, {reopen: true}, "The comment was not reopened."),
      reply: (number, text) => ownerEdit(number, {reply: text}),
      async remove(number) {
        const tab = activeTab();
        if (!tab || !tab.page) return;
        const result = await ownerEdit(number, {delete: true});
        if (!result.ok) return showNotice(result.data.message || "The comment was not deleted.");
        const key = commentsKey(tab.id, tab.page);
        const shown = commentPages.get(key);
        if (shown) shown.comments = shown.comments.filter((c) => c.n !== number);
        if (selectedComment === number) selectedComment = null;
        if (activeTab() === tab) {
          renderCommentPanel();
          sendMarkers();
        }
      },
    };

    const readOnlyCallbacks = {
      readOnly: true,
      select: panelCallbacks.select,
      hover: panelCallbacks.hover,
      filter: setMarkerFilter,
      collapse: () => setPanelCollapsed(true),
    };

    function setPanelCollapsed(collapsed) {
      panelCollapsed = collapsed;
      localStorage.setItem(COMMENTS_COLLAPSED_KEY, collapsed ? "1" : "0");
      renderCommentPanel();
    }

    function renderCommentPanel() {
      updateBar();
      const tab = activeTab();
      const shown = shownComments();
      const key = tab && tab.page ? commentsKey(tab.id, tab.page) : null;
      const pending = commentOutbox.views().filter((v) => v.key === key).map((v) => v.record);
      // The panel is there only while the page has comments.
      commentPanel.hidden = !shown || shown.comments.length + pending.length === 0;
      if (commentPanel.hidden) return;
      commentPanel.classList.toggle("float", narrowWindow.matches);
      const open = shown.comments.filter((c) => c.status !== "done").length;
      const byItself = commentMode || open > 0 || commentOutbox.size() || window.commentsUi.hasForms(commentPanel);
      if (!panelCollapsed && (panelOpened || (byItself && !narrowWindow.matches))) {
        if (viewing() !== null) {
          window.renderComments(commentPanel, tab.page, shown.comments, readOnlyCallbacks);
          return;
        }
        window.renderComments(commentPanel, tab.page, [...shown.comments, ...pending], panelCallbacks);
      } else {
        window.commentsUi.renderStrip(commentPanel, open, () => {
          panelOpened = true;
          setPanelCollapsed(false);
        });
      }
    }

    // What the send button counts (FB-04): the active tab's comments not yet sent, and the
    // number of its pages that have them.
    function unsentComments() {
      const tab = activeTab();
      if (tab && hubUnsent.has(tab.id)) return hubUnsent.get(tab.id);
      let comments = 0;
      let files = 0;
      if (tab) {
        for (const [key, shown] of commentPages) {
          if (!key.startsWith(`${tab.id}\n`)) continue;
          const drafts = shown.comments.filter(
            (c) => c.sent === null || c.replies.some((r) => r.from === null && r.sent === null),
          ).length;
          comments += drafts;
          if (drafts) files += 1;
        }
      }
      return {comments, files};
    }

    function onCommentsMessage(message) {
      if (typeof message.session !== "string" || typeof message.page !== "string") return;
      if (!Array.isArray(message.comments)) return;
      const known = message.comments.reduce((top, c) => Math.max(top, c.n), 0);
      const next = Number.isInteger(message.next) ? message.next : known + 1;
      const key = commentsKey(message.session, message.page);
      const before = commentPages.get(key);
      commentPages.set(key, {comments: message.comments, next: Math.max(next, known + 1)});
      const unsent = message.unsent;
      if (unsent && Number.isInteger(unsent.comments) && Number.isInteger(unsent.files)) {
        hubUnsent.set(message.session, {comments: unsent.comments, files: unsent.files});
      }
      commentsArrived(message, before);
      const tab = activeTab();
      if (!tab || tab.id !== message.session || tab.page !== message.page) return;
      renderCommentPanel();
      sendMarkers();
    }

    // The shown page changed (a session, a page, a version, none): the old
    // box and tokens are void, and the page's comments are asked for.
    function commentsPageChanged() {
      commentTokens.clear();
      selectedComment = null;
      panelOpened = false;
      cursorOn = false;
      if (!commentsAvailable()) commentMode = false;
      closeCommentBox();
      if (commentEditBox) commentEditBox.close();
      updateCommentUi();
      renderCommentPanel();
      requestComments();
    }

    // A new version of the shown page: its comments get new tokens, placed on that
    // version (COM-18), and the layer finds their anchors again after its morph.
    function commentsVersionChanged() {
      commentTokens.clear();
      sendMarkers();
    }

    // A new document in the frame has no mode and no markers yet.
    function commentsOnReady() {
      postToFrame({type: "keys", keys: keyMap.forwarded()});
      if (commentMode) sendCommentMode();
      sendMarkers();
    }

    // ---- the box and its reports (COM-03, COM-18) -------------------------------------------

    function rejectReport(what) {
      drop("token");
      console.warn(`agent-canvas: dropped a ${what} report without a matching token`);
    }

    function closeCommentBox() {
      if (commentSelection) commentSelection.box.close();
    }

    // The box was closed by Esc, by a save or by a change of page: nothing of the
    // selection stays, in the shell or in the frame.
    function boxClosed(selection) {
      if (commentSelection !== selection) return;
      commentSelection = null;
      postToFrame({type: "comment-clear"});
      updateCommentUi();
    }

    function onCommentSelection(message) {
      if (!commentMode || !commentsAvailable() || message.kind !== commentKind) return;
      if (message.notice === "block-boundary") {
        if (commentKind === "text") showNotice(BLOCK_NOTICE);
        return;
      }
      cursorOn = false;
      const rect = cleanRect(message.rect);
      const anchor = cleanAnchor(message.anchor, commentKind);
      if (!rect || !anchor) return;
      closeCommentBox();
      const raw = message.target || {};
      const text = (value, limit) => (typeof value === "string" ? value.slice(0, limit) : null);
      const selection = {
        token: randomToken(), anchor, kind: commentKind, data: cleanData(message.data),
        target: {canvas_id: text(raw.canvas_id, 200), selector: text(raw.selector, 500),
          text: text(raw.text, 80) || ""},
        text_inside: text(message.text_inside, 500),
        picture: null,
      };
      selection.pictureReady = new Promise((resolve) => { selection.pictureArrived = resolve; });
      selection.box = window.commentsUi.openCommentBox(main, {
        number: isOffline() || commentOutbox.size() ? "…" : shownComments().next, kind: selection.kind,
        label: selection.kind === "text" ? anchor.quote.slice(0, 80)
          : window.commentsUi.anchorLabel({kind: selection.kind, target: selection.target}),
        rect, onSave: (text) => saveComment(selection, text),
        onClose: () => boxClosed(selection),
      });
      commentSelection = selection;
      updateCommentUi();
      postToFrame({type: "comment-crop", token: selection.token});
    }

    function onCommentPicture(message) {
      const selection = commentSelection;
      if (!selection || message.token !== selection.token) return rejectReport("picture");
      const prefix = "data:image/png;base64,";
      if (message.ok === true && typeof message.png === "string" && message.png.startsWith(prefix)) {
        selection.picture = {png: message.png.slice(prefix.length), error: null};
      } else {
        const reason = typeof message.error === "string" ? message.error : "picture failed";
        selection.picture = {png: null, error: reason.slice(0, 300)};
      }
      selection.pictureArrived();
    }

    function onCommentMarker(message) {
      const shown = shownComments();
      const found = shown && shown.comments.find((c) => commentTokens.get(c.id) === message.token);
      if (!found || !["click", "hover", "leave"].includes(message.action)) return rejectReport("marker");
      if (message.action !== "click") {
        window.commentsUi.highlight(commentPanel, message.action === "hover" ? found.n : null);
        return;
      }
      selectedComment = found.n;
      if (narrowWindow.matches) panelOpened = true;
      if (panelCollapsed) setPanelCollapsed(false); else if (narrowWindow.matches) renderCommentPanel();
      markRead(found.n);
      window.commentsUi.select(commentPanel, found.n);
      sendMarkers();
      const entry = commentPanel.querySelector(`.ent[data-n="${found.n}"]`);
      if (entry) entry.scrollIntoView({block: "nearest"});
    }

    // The layer's report of anchors it found again or did not (ANC-06): an item
    // counts only with the token of a comment on the shown page (COM-18); the hub
    // stores the change with the page's version.
    async function onCommentLost(message) {
      if (viewing() !== null) return; // A-151: only the live frame reports
      const tab = activeTab();
      const shown = shownComments();
      const items = Array.isArray(message.items) ? message.items.slice(0, 200) : [];
      const reports = [];
      for (const item of items) {
        const found = shown && item && typeof item.lost === "boolean" && typeof item.token === "string"
          ? shown.comments.find((c) => commentTokens.get(c.id) === item.token) : null;
        if (found) reports.push({n: found.n, lost: item.lost});
        else rejectReport("lost");
      }
      if (!reports.length) return;
      await commentRequest(`/api/sessions/${encodeURIComponent(tab.id)}/comments/lost`,
        {page: tab.page, reports});
    }

    async function commentRequest(path, body) {
      try {
        const response = await fetch(path, {
          method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
        });
        return {ok: response.ok, data: await response.json().catch(() => ({}))};
      } catch (error) {
        return {ok: false, data: {message: "The hub is not reachable."}};
      }
    }

    // The picture is made when the box opens; a save waits for it, at most 5 s,
    // then stores the comment with ``picture`` null and ``picture_error`` (COM-12).
    async function waitForPicture(selection) {
      const limit = Number(window.__pictureTimeoutMs) || PICTURE_TIMEOUT_MS;
      let timer = null;
      const timeout = new Promise((resolve) => { timer = setTimeout(resolve, limit, "late"); });
      const outcome = await Promise.race([selection.pictureReady, timeout]);
      clearTimeout(timer);
      if (outcome === "late" && !selection.picture) {
        selection.picture = {png: null, error: `picture timed out after ${limit / 1000} s`};
      }
    }

    // The newest version seen per page: used when the hub cannot be asked (offline).
    const knownVersions = new Map();

    // The version of ``page`` on screen: the earlier one being viewed, else the newest.
    async function shownVersion(tab, page) {
      if (viewing() !== null && viewing().page === page) return viewing().version;
      const answer = await api(
        "GET", `/api/sessions/${encodeURIComponent(tab.id)}/versions?page=${encodeURIComponent(page)}`);
      const last = answer && answer.versions[answer.versions.length - 1];
      const key = commentsKey(tab.id, page);
      if (last) knownVersions.set(key, last.version);
      return knownVersions.has(key) ? knownVersions.get(key) : null;
    }

    function addSavedRecord(key, data) {
      const shown = commentPages.get(key) || {comments: [], next: 1};
      const record = {...data, status: "draft"};
      shown.comments = [...shown.comments.filter((c) => c.n !== record.n), record];
      shown.next = Math.max(shown.next, record.n + 1);
      commentPages.set(key, shown);
    }

    async function saveComment(selection, text) {
      const tab = activeTab();
      if (commentSaving || !tab || !tab.page || commentSelection !== selection) return;
      commentSaving = true;
      selection.box.note("");
      const page = tab.page;
      try {
        await waitForPicture(selection);
        const version = await shownVersion(tab, page);
        const shownRecord = {
          n: "…", pending: true, kind: selection.kind, text, status: "draft", sent: null,
          anchor: selection.anchor, target: selection.target, replies: [],
        };
        const result = await commentOutbox.submit(`/api/sessions/${encodeURIComponent(tab.id)}/comments`, {
          page, kind: selection.kind, text, anchor: selection.anchor, target: selection.target,
          text_inside: selection.text_inside, data: selection.data, page_version: version,
          picture: selection.picture.png, picture_error: selection.picture.error,
        }, {key: commentsKey(tab.id, page), record: shownRecord});
        if (!result.ok) {
          if (commentSelection === selection) {
            selection.box.note(result.data.message || "The comment was not saved. Try again.");
          }
          return;
        }
        if (!result.queued) addSavedRecord(commentsKey(tab.id, page), result.data);
        if (commentSelection === selection) selection.box.close();
        panelOpened = true; // a new comment opens the panel, in a narrow window too
        if (activeTab() === tab && tab.page === page) {
          renderCommentPanel();
          sendMarkers();
        }
      } finally {
        commentSaving = false;
      }
    }

    updateCommentUi();

    return {
      commentPages, commentTokens, requestComments, renderCommentPanel, addSavedRecord, commentKey,
      unsentComments, commentsOf, onCommentsMessage, commentsPageChanged, commentsVersionChanged,
      commentsOnReady, onCommentSelection, onCommentPicture, onCommentMarker, onCommentLost,
      commentModeOn: () => commentMode, updateCommentUi, commentPanelKey,
    };
  }

  window.createCommentFeature = createCommentFeature;
  window.commentReports = {cleanRect, cleanPairs, cleanPdfRect, cleanAnchor, cleanData};
})();
