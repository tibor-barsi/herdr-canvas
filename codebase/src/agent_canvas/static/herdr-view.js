'use strict';
// Herdr-style window parts: sidebar, tab bar and split cards (no shell code).
// HerdrView.mount(root, callbacks) returns {update(herdr, sessions), show(sessionId), destroy()}.
// `herdr` is the hub's herdr view, `sessions` the list of the `tabs` window message.
// Each card with a session holds an empty `.hv-frame` (data-session, data-page); the
// card and its frame survive updates as long as pane and session stay the same, so the
// host can keep an iframe in it. callbacks.onFrame(slot, sessionId, page) fires after
// each update for every card with a session whose machine is reachable.
// With `herdr.machines` (one entry per remote machine: name, state, detail, other) the
// sidebar groups spaces under machine headings, this computer first; a machine that is not
// online shows its detail, and its cards a note instead of a frame.
// callbacks.onMachineOnline(name, sessionIds) fires when a machine's state changes to online.
const HerdrView = (() => {
  const EMPTY = { available: false, focus: null, spaces: [], other: [] };

  function h(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }

  const icon = (cls) => h('span', 'hv-ic ' + cls);

  function statusMark(status) {
    if (status === 'working') return icon('hv-spin');
    if (status === 'blocked' || status === 'done') return h('span', 'hv-dot ' + status);
    return null;
  }

  const worst = (statuses) => ['blocked', 'working', 'done'].find((s) => statuses.includes(s));
  const panesOf = (tabs) => tabs.flatMap((t) => t.panes);
  // Rectangles {x, y, w, h} (fractions of the card area) per pane id from a split tree;
  // a missing tree or one that does not name exactly the tab's panes gives a row.
  function layout(tab) {
    const all = tab.panes.map((p) => p.pane);
    const ids = tab.panes.filter(isAgent).map((p) => p.pane);
    const rects = new Map();
    const place = (node, x, y, w, h) => {
      if (node.pane) return rects.set(node.pane, { x, y, w, h });
      const total = node.children.reduce((n, c) => n + c.weight, 0);
      let at = 0;
      for (const c of node.children) {
        const f = c.weight / total;
        if (node.dir === 'row') place(c, x + at * w, y, f * w, h);
        else place(c, x, y + at * h, w, f * h);
        at += f;
      }
    };
    const leaves = (n) => (n.pane ? [n.pane] : n.children.flatMap(leaves));
    const tree = tab.tree && leaves(tab.tree).length === all.length && all.every((id) => leaves(tab.tree).includes(id))
      ? prune(tab.tree, new Set(ids)) : null;
    if (tree) place(tree, 0, 0, 1, 1);
    if (rects.size === ids.length && ids.every((id) => rects.has(id))) return rects;
    rects.clear();
    ids.forEach((id, i) => rects.set(id, { x: i / ids.length, y: 0, w: 1 / ids.length, h: 1 }));
    return rects;
  }
  const isAgent = (p) => Boolean(p.app || p.session);
  // The tree without leaves of plain shell panes; a row or column left with one child becomes that child.
  function prune(node, agents) {
    if (node.pane) return agents.has(node.pane) ? node : null;
    const kids = node.children.map((c) => prune(c, agents)).filter(Boolean);
    if (kids.length < 2) return kids[0] && { ...kids[0], weight: node.weight };
    return { ...node, children: kids };
  }
  const AWAY = { offline: 'is offline', connecting: 'is connecting', 'no-canvas': 'has no canvas here', 'port-clash': 'cannot be shown here' };
  const pageName = (p) => p.replace(/\.[^.]+$/, '');

  function mount(root, cb = {}) {
    let herdr = EMPTY;
    let sessions = new Map();
    let lastFocus = null;
    let sel = { space: null, tab: null, pane: null, other: false, otherSession: null, otherMachine: null };
    let lastStates = new Map(); // machine name -> state at the last update
    const folded = new Set(JSON.parse(localStorage.getItem('hv.folded') || '[]')); // folded machine groups (null: this computer)
    const pages = new Map(); // session id -> {page, seen}: a page tab clicked, until the hub confirms
    const cards = new Map(); // card key -> {el, head, tabs, frame}

    root.classList.add('hv');
    const side = h('div', 'hv-side');
    const main = h('div', 'hv-main');
    const bar = h('div', 'hv-bar');
    const area = h('div', 'hv-cards');
    const noAgents = h('div', 'hv-none hv-empty', 'No agent sessions in this tab');
    main.append(bar, area);
    root.replaceChildren(side, main);
    let shownPill = null; // the active pill last scrolled into view
    // A plain mouse wheel scrolls the tab bar sideways; a trackpad's sideways swipe scrolls it natively.
    bar.addEventListener('wheel', (e) => {
      if (e.deltaX || !e.deltaY) return;
      bar.scrollLeft += e.deltaY;
      e.preventDefault();
    }, { passive: false });

    const spaceOf = (id) => herdr.spaces.find((s) => s.id === id);
    const machineList = () => herdr.machines || [];
    const grouped = () => machineList().length > 0;
    const machineNamed = (name) => machineList().find((m) => m.name === name);
    // Machine groups in sidebar order: this computer (null), then the given order.
    const groupNames = () => {
      const names = machineList().map((m) => m.name);
      for (const s of herdr.spaces) if (s.machine && !names.includes(s.machine)) names.push(s.machine);
      return grouped() ? [null, ...names] : [null];
    };
    const away = (name) => {
      const m = machineNamed(name);
      return m && m.state !== 'online' ? m : null;
    };
    const inGroup = (space, name) => !grouped() || (space.machine ?? null) === name;
    const othersOf = (name) => (name ? machineNamed(name)?.other || [] : herdr.other).filter((id) => sessions.has(id));
    const others = () => othersOf(sel.otherMachine);
    // The sidebar's rows in order: spaces of a group, then its "Not in Herdr" row.
    const rowList = () => groupNames().flatMap((name) => [
      ...herdr.spaces.filter((s) => inGroup(s, name)).map((s) => ({ space: s.id, machine: name })),
      ...(othersOf(name).length ? [{ other: true, machine: name }] : []),
    ]);
    function setFold(name, on) {
      if (folded.has(name) === on) return;
      if (on) folded.add(name);
      else folded.delete(name);
      localStorage.setItem('hv.folded', JSON.stringify([...folded]));
    }
    const pagesIn = (ids) => ids.reduce((n, id) => n + (sessions.get(id)?.pages.length || 0), 0);
    const sessionIds = (panes) => panes.map((p) => p.session).filter((id) => id && sessions.has(id));

    function normalize() {
      if (!herdr.spaces.length) sel.other = true;
      if (sel.other) {
        if (!others().includes(sel.otherSession)) sel.otherSession = others()[0] || null;
        return;
      }
      const space = spaceOf(sel.space) || herdr.spaces.find((s) => s.active) || herdr.spaces[0];
      if (space.id !== sel.space) sel.tab = null;
      sel.space = space.id;
      const tab = space.tabs.find((t) => t.id === sel.tab) || space.tabs.find((t) => t.active) || space.tabs[0];
      if (tab?.id !== sel.tab) sel.pane = null;
      sel.tab = tab?.id || null;
      const panes = tab?.panes || [];
      if (!panes.some((p) => p.terminal === sel.pane)) sel.pane = (panes.find((p) => p.focused) || {}).terminal || null;
    }

    function pick(change, call) {
      Object.assign(sel, change);
      normalize();
      render();
      call?.();
    }

    function renderSide() {
      const head = h('div', 'hv-shead');
      const toggle = icon('hv-fold');
      toggle.title = 'Fold sidebar (Ctrl+Shift+B)';
      toggle.onclick = () => root.classList.toggle('folded');
      head.append(h('span', 'hv-logo'), h('span', null, 'Canvas'), h('span', 'hv-grow'), toggle);
      const rows = h('div', 'hv-rows');
      const spaceRow = (space) => {
        const panes = panesOf(space.tabs);
        const row = h('div', 'hv-row' + (!sel.other && space.id === sel.space ? ' on' : ''));
        row.title = space.name;
        const tile = h('i', 'hv-tile', space.name.charAt(0).toUpperCase());
        tile.style.background = space.color;
        const count = pagesIn(sessionIds(panes));
        row.append(tile, h('span', 'hv-name', space.name), h('span', 'hv-grow'));
        if (count) row.append(h('span', 'hv-cnt', count));
        const mark = statusMark(worst(panes.map((p) => p.status)));
        if (mark) row.append(mark);
        row.onclick = () => pick({ space: space.id, other: false }, () => cb.onSpace?.(space.id));
        return row;
      };
      const otherRow = (name) => {
        const row = h('div', 'hv-row' + (sel.other && sel.otherMachine === name ? ' on' : ''));
        row.title = 'Not in Herdr';
        row.append(h('i', 'hv-tile other', '?'), h('span', 'hv-name hv-m', 'Not in Herdr'), h('span', 'hv-grow'), h('span', 'hv-cnt', pagesIn(othersOf(name))));
        row.onclick = () => pick({ other: true, otherMachine: name }, () => cb.onOther?.(sel.otherSession));
        return row;
      };
      for (const name of groupNames()) {
        if (grouped()) {
          const m = machineNamed(name);
          const head = h('div', 'hv-mhead');
          head.dataset.machine = name ?? '';
          head.title = name ?? 'This computer';
          head.append(h('span', 'hv-name', name ?? 'This computer'), h('span', 'hv-grow'));
          if (m && m.state !== 'online') head.append(h('span', 'hv-mstate', m.state.replace('-', ' ')));
          head.append(h('span', 'hv-chev' + (folded.has(name) ? ' shut' : '')));
          head.onclick = () => { setFold(name, !folded.has(name)); render(); };
          rows.append(head);
          if (m && m.state !== 'online' && m.detail) rows.append(h('div', 'hv-mnote', m.detail));
          if (folded.has(name)) continue;
        }
        for (const space of herdr.spaces) if (inGroup(space, name)) rows.append(spaceRow(space));
        if (othersOf(name).length) rows.append(otherRow(name));
      }
      side.replaceChildren(head, h('div', 'hv-sec', 'Spaces'), rows);
    }

    function renderBar() {
      bar.replaceChildren();
      if (sel.other) {
        for (const id of others()) {
          const pill = h('div', 'hv-pill' + (id === sel.otherSession ? ' on' : ''), sessions.get(id).title);
          pill.dataset.session = id;
          pill.onclick = () => pick({ otherSession: id }, () => cb.onOther?.(id));
          bar.append(pill);
        }
      } else {
        for (const tab of spaceOf(sel.space).tabs) {
          const pill = h('div', 'hv-pill' + (tab.id === sel.tab ? ' on' : ''));
          if (tab.panes.some((p) => p.app === 'claude-code')) pill.append(icon('hv-claude'));
          pill.append(h('span', null, tab.name));
          const mark = statusMark(worst(tab.panes.map((p) => p.status)));
          if (mark) pill.append(mark);
          pill.onclick = () => pick({ tab: tab.id, pane: null }, () => cb.onTab?.(tab.id));
          bar.append(pill);
        }
      }
      const on = bar.querySelector('.hv-pill.on');
      const onKey = sel.other ? 'o:' + sel.otherSession : sel.tab;
      if (on && onKey !== shownPill) on.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      shownPill = onKey;
    }

    function card(key, session) {
      let c = cards.get(key);
      if (c) return c;
      const frame = session ? h('div', 'hv-frame') : h('div', 'hv-none', 'no canvas');
      c = { el: h('div', 'hv-card'), head: h('div', 'hv-chead'), tabs: h('div', 'hv-ptabs'), frame, select: null };
      c.el.append(c.head, c.tabs, frame);
      // Any press in the card selects it, before the target sees it; the card in focus sends nothing.
      c.el.addEventListener('pointerdown', () => !c.el.classList.contains('focus') && c.select?.(), true);
      cards.set(key, c);
      return c;
    }

    function fill(c, { name, app, status, focus, session, machine, onFocus }) {
      c.el.classList.toggle('focus', focus);
      c.head.replaceChildren();
      if (app === 'claude-code') c.head.append(icon('hv-claude'));
      c.head.append(h('span', null, name), h('span', 'hv-grow'));
      const mark = statusMark(status);
      if (mark) c.head.append(mark);
      c.select = onFocus;
      c.tabs.replaceChildren();
      const gone = away(machine);
      const want = session && !gone ? 'hv-frame' : 'hv-none';
      if (c.frame.className !== want) {
        const frame = h('div', want);
        c.el.replaceChild(frame, c.frame);
        c.frame = frame;
      }
      if (want === 'hv-none') c.frame.textContent = gone ? gone.detail || `${gone.name} ${AWAY[gone.state] || gone.state}` : 'no canvas';
      if (!session) return;
      c.el.dataset.session = session.id;
      const shown = pages.get(session.id)?.page || session.active_page;
      for (const page of session.pages) {
        const pt = h('span', 'hv-pt' + (page === shown ? ' on' : ''), pageName(page));
        pt.title = page;
        pt.onclick = () => {
          pages.set(session.id, { page, seen: session.active_page });
          render();
          cb.onPage?.(session.id, page);
        };
        c.tabs.append(pt);
      }
      if (want === 'hv-frame') {
        c.frame.dataset.session = session.id;
        c.frame.dataset.page = shown || '';
      }
    }

    function renderCards() {
      const wanted = [];
      if (sel.other) {
        const s = sessions.get(sel.otherSession);
        if (s) wanted.push({ key: 'o:' + s.id, name: s.title, focus: true, session: s, machine: sel.otherMachine });
      } else {
        const space = spaceOf(sel.space);
        const tab = space.tabs.find((t) => t.id === sel.tab);
        const rects = layout(tab || { panes: [] });
        for (const p of (tab?.panes || []).filter(isAgent)) {
          const session = sessions.get(p.session);
          wanted.push({
            rect: rects.get(p.pane),
            key: p.terminal + '|' + (session?.id || ''), name: p.name, app: p.app, status: p.status, session,
            machine: space.machine ?? null,
            focus: p.terminal === sel.pane,
            onFocus: () => pick({ pane: p.terminal }, () => cb.onPane?.(p.terminal)),
          });
        }
      }
      for (const [key, c] of cards) {
        if (!wanted.some((w) => w.key === key)) {
          c.el.remove();
          cards.delete(key);
        }
      }
      noAgents.remove();
      if (!wanted.length) area.append(noAgents);
      for (const w of wanted) {
        const c = card(w.key, w.session);
        fill(c, w);
        const r = w.rect || { x: 0, y: 0, w: 1, h: 1 };
        // 4px margin around the area and a 3px inset on every card: cards sit 6px apart, 7px from the edge
        Object.assign(c.el.style, {
          left: `calc(7px + (100% - 8px) * ${r.x})`, top: `calc(7px + (100% - 8px) * ${r.y})`,
          width: `calc((100% - 8px) * ${r.w} - 6px)`, height: `calc((100% - 8px) * ${r.h} - 6px)`,
        });
        area.append(c.el); // appending in order also reorders kept cards
        if (w.session && c.frame.classList.contains('hv-frame')) cb.onFrame?.(c.frame, w.session.id, c.frame.dataset.page);
      }
    }

    function render() {
      renderSide();
      renderBar();
      renderCards();
    }

    function update(next, list) {
      herdr = next || EMPTY;
      const states = new Map(machineList().map((m) => [m.name, m.state]));
      const back = [...states].filter(([n, st]) => st === 'online' && lastStates.has(n) && lastStates.get(n) !== 'online').map(([n]) => n);
      lastStates = states;
      sessions = new Map(list.map((s) => [s.id, s]));
      for (const [id, p] of pages) {
        if (sessions.get(id)?.active_page !== p.seen) pages.delete(id);
      }
      const focus = JSON.stringify(herdr.focus || null);
      if (focus !== lastFocus) {
        lastFocus = focus;
        const pane = herdr.spaces.flatMap((s) => panesOf(s.tabs)).find((p) => p.pane === herdr.focus?.pane);
        sel = { ...sel, space: herdr.focus?.space, tab: herdr.focus?.tab, pane: pane?.terminal, other: false };
      }
      normalize();
      render();
      for (const n of back) cb.onMachineOnline?.(n, [...sessions.values()].filter((x) => x.machine === n).map((x) => x.id));
    }

    // Select the card of a session the host opened; returns its pane, null when not in Herdr.
    function show(id) {
      for (const space of herdr.spaces) {
        for (const tab of space.tabs) {
          const pane = tab.panes.find((p) => p.session === id);
          if (pane) {
            setFold(space.machine ?? null, false);
            pick({ space: space.id, tab: tab.id, pane: pane.terminal, other: false });
            return pane;
          }
        }
      }
      const machine = groupNames().find((name) => othersOf(name).includes(id));
      if (machine !== undefined) {
        setFold(machine, false);
        pick({ other: true, otherMachine: machine, otherSession: id });
      }
      return null;
    }

    // ---- keyboard navigation: the same moves as the clicks, asking Herdr the same way ----

    function goSpace(delta, index) {
      const rows = rowList();
      const now = rows.findIndex((r) => (r.other ? sel.other && sel.otherMachine === r.machine : !sel.other && r.space === sel.space));
      const to = rows[index ?? (now + delta + rows.length) % rows.length];
      if (!to) return;
      setFold(to.machine, false);
      if (to.other) pick({ other: true, otherMachine: to.machine }, () => cb.onOther?.(sel.otherSession));
      else pick({ space: to.space, other: false }, () => cb.onSpace?.(to.space));
    }

    // Fold or open the machine group of the shown space; false when the sidebar has no groups.
    function foldMachine() {
      if (!grouped()) return false;
      const name = sel.other ? sel.otherMachine : spaceOf(sel.space)?.machine ?? null;
      setFold(name, !folded.has(name));
      render();
    }

    function goTab(delta, index) {
      if (sel.other) {
        const ids = others();
        const id = ids[index ?? (ids.indexOf(sel.otherSession) + delta + ids.length) % ids.length];
        if (id) pick({ otherSession: id }, () => cb.onOther?.(id));
        return;
      }
      const tabs = spaceOf(sel.space)?.tabs || [];
      const id = tabs[index ?? (tabs.findIndex((t) => t.id === sel.tab) + delta + tabs.length) % tabs.length]?.id;
      if (id) pick({ tab: id, pane: null }, () => cb.onTab?.(id));
    }

    // The agent cards of the shown tab with their rectangles (Herdr's split layout).
    function shownCards() {
      const tab = sel.other ? null : spaceOf(sel.space)?.tabs.find((t) => t.id === sel.tab);
      return { panes: (tab?.panes || []).filter(isAgent), rects: layout(tab || { panes: [] }) };
    }

    // Next card in Herdr's order (delta) or the nearest one on a side of the focused card.
    function goPane(dir, delta) {
      const { panes, rects } = shownCards();
      const at = panes.findIndex((p) => p.terminal === sel.pane);
      let to = null;
      if (delta) to = panes[(at + delta + panes.length) % panes.length];
      else if (at >= 0) {
        const c = rects.get(panes[at].pane);
        const side = {
          left: (r) => c.x - (r.x + r.w), right: (r) => r.x - (c.x + c.w),
          up: (r) => c.y - (r.y + r.h), down: (r) => r.y - (c.y + c.h),
        }[dir];
        const across = dir === 'left' || dir === 'right'
          ? (r) => Math.min(r.y + r.h, c.y + c.h) - Math.max(r.y, c.y)
          : (r) => Math.min(r.x + r.w, c.x + c.w) - Math.max(r.x, c.x);
        const near = panes.filter((p) => p !== panes[at] && side(rects.get(p.pane)) > -1e-6)
          .map((p) => ({ p, gap: side(rects.get(p.pane)), over: across(rects.get(p.pane)) }))
          .sort((x, y) => (y.over > 1e-6) - (x.over > 1e-6) || x.gap - y.gap || y.over - x.over);
        to = near[0]?.p;
      } else to = panes[0];
      if (to && to.terminal !== sel.pane) pick({ pane: to.terminal }, () => cb.onPane?.(to.terminal));
    }

    // Next or previous page tab of the focused card.
    function goPage(delta) {
      const pane = shownCards().panes.find((p) => p.terminal === sel.pane);
      const session = sessions.get(sel.other ? sel.otherSession : pane?.session);
      if (!session?.pages.length) return;
      const shown = pages.get(session.id)?.page || session.active_page;
      const list = session.pages;
      const page = list[(list.indexOf(shown) + delta + list.length) % list.length];
      pages.set(session.id, { page, seen: session.active_page });
      render();
      cb.onPage?.(session.id, page);
    }

    // A press inside a card's page frame never reaches this document; the window
    // loses focus to the frame instead.
    function onBlur() {
      const frame = document.activeElement;
      if (frame?.tagName !== 'IFRAME') return;
      for (const c of cards.values()) {
        if (c.el.contains(frame) && !c.el.classList.contains('focus')) c.select?.();
      }
    }
    window.addEventListener('blur', onBlur);

    return {
      update,
      show,
      goSpace,
      foldMachine,
      goTab,
      goPane,
      goPage,
      destroy() {
        window.removeEventListener('blur', onBlur);
        root.replaceChildren();
        root.classList.remove('hv', 'folded');
      },
    };
  }

  return { mount };
})();
