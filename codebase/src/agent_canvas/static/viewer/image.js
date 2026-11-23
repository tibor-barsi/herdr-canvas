// Picture viewer (VIEW-06, VIEW-14): Fit, 100 %, Ctrl+wheel zoom around the pointer,
// drag to pan, scrollbars. The picture is always shown through <img>, so an SVG's
// scripts never run.
//
// Interface for the comment layer (P24.4): window.acImageView() returns
//   {scale, x, y, width, height}
// width and height are the picture's pixels; x and y are where its pixel (0, 0)
// lies in the frame's viewport, in CSS px (as getBoundingClientRect reports).
// Frame point = (x + scale * u, y + scale * v) for picture pixel (u, v), and
// back: u = (px - x) / scale. Read it at use time; it changes with zoom and scroll.
//
// window.acViewer is the one interface of all viewers (4.2): kind, space,
// mount(root, url) -> the text root (null for a picture), update(message), mounted,
// and for a space other than page-px toSpace(cx, cy), fromSpace(u, v), size(),
// crop(box), reveal(box). The document gets "agentcanvas:view" whenever zoom,
// scroll or size changed, and "agentcanvas:updated" once a picture is shown.
(() => {
  const MIN_SCALE = 0.1;
  const MAX_SCALE = 8;
  const MAX_PIXELS = 50e6; // A-74
  const WHEEL_RATE = 0.0015;
  const PROBLEM = { // VIEW-14: the owner's sentence for each reason code
    "image-undecodable": "the picture is damaged or in a format the window cannot read. Ask the agent to make it again.",
    "image-too-large": "the picture is too large (over 50 megapixels). Ask the agent to make a smaller one.",
  };

  const style = document.createElement("style");
  style.textContent = `
    html, body { margin: 0; height: 100%; overflow: hidden; background: #f4f4f4; }
    [data-scroller] { position: fixed; inset: 0; overflow: auto; cursor: grab; }
    [data-scroller].panning { cursor: grabbing; }
    [data-stage] { display: flex; min-width: 100%; min-height: 100%;
      width: max-content; height: max-content; }
    [data-stage] img { margin: auto; flex: none; user-select: none; }
    [data-bar] { position: fixed; top: 8px; right: 24px; display: flex; gap: 4px;
      align-items: center; font: 13px system-ui, sans-serif; background: rgba(255,255,255,.9);
      border: 1px solid #bbb; border-radius: 6px; padding: 3px; z-index: 2; }
    [data-bar] button { font: inherit; padding: 2px 8px; }
    [data-bar] output { min-width: 4em; text-align: right; color: #333; }
    [data-notice] { margin: 2em; font: 16px system-ui, sans-serif; color: #333; }
    html[data-ac-commenting] [data-scroller] { cursor: crosshair; }
  `;
  document.head.append(style);

  const here = new URL(location.href);
  const version = here.searchParams.get("v");
  const fileUrl = new URL(here);
  fileUrl.searchParams.delete("ac-view");
  const name = decodeURIComponent(here.pathname.split("/").pop());

  const scroller = document.createElement("div");
  scroller.dataset.scroller = "";
  const stage = document.createElement("div");
  stage.dataset.stage = "";
  const img = document.createElement("img");
  img.draggable = false;
  img.crossOrigin = "anonymous"; // the hub's wildcard CORS keeps crops readable (COM-12)
  img.alt = name;
  stage.append(img);
  scroller.append(stage);

  const bar = document.createElement("div");
  bar.dataset.bar = "";
  const fitButton = Object.assign(document.createElement("button"), {textContent: "Fit"});
  const fullButton = Object.assign(document.createElement("button"), {textContent: "100 %"});
  const percent = document.createElement("output");
  bar.append(fitButton, fullButton, percent);
  fitButton.type = fullButton.type = "button";

  let scale = 1;
  let fitting = true;
  let mounted = false;
  let loading = null; // {resolve, keep} while a picture is loading

  function fitScale() {
    const wide = scroller.clientWidth / img.naturalWidth;
    const tall = scroller.clientHeight / img.naturalHeight;
    return Math.min(1, wide, tall);
  }

  function setScale(value) {
    scale = value;
    img.style.width = `${img.naturalWidth * scale}px`;
    img.style.height = `${img.naturalHeight * scale}px`;
    percent.textContent = `${Math.round(scale * 100)} %`;
    viewChanged();
  }

  function viewChanged() {
    document.dispatchEvent(new Event("agentcanvas:view"));
  }

  function fit() {
    fitting = true;
    setScale(fitScale());
    scroller.scrollTo(0, 0);
  }

  // Zoom so that the picture point under frame point (px, py) stays under it.
  function zoomAround(value, px, py) {
    fitting = false;
    const before = img.getBoundingClientRect();
    const u = (px - before.left) / scale;
    const v = (py - before.top) / scale;
    setScale(Math.min(MAX_SCALE, Math.max(Math.min(MIN_SCALE, fitScale()), value)));
    placeAt(u, v, px, py);
  }

  // Scroll so that picture pixel (u, v) lies under frame point (px, py).
  function placeAt(u, v, px, py) {
    const now = img.getBoundingClientRect();
    scroller.scrollLeft += now.left + u * scale - px;
    scroller.scrollTop += now.top + v * scale - py;
  }

  function fail(reason) {
    finish();
    scroller.remove();
    bar.remove();
    const notice = document.createElement("p");
    notice.dataset.notice = "";
    notice.textContent = `This file could not be shown${PROBLEM[reason] ? `: ${PROBLEM[reason]}` : "."}`;
    document.body.append(notice);
    const canvas = window.agentCanvas;
    if (canvas && canvas.report) {
      canvas.report("viewer-error", {page: name, version: version === null ? null : Number(version), reason});
    }
  }

  window.acImageView = () => {
    const rect = img.getBoundingClientRect();
    return {scale, x: rect.left, y: rect.top, width: img.naturalWidth, height: img.naturalHeight};
  };

  function finish() {
    mounted = true;
    if (loading) loading.resolve(null);
    loading = null;
  }

  // Load ``url`` into the picture; resolves when it is shown or has failed.
  function load(url, keep) {
    return new Promise((resolve) => {
      // The latest update wins; the one it replaces is reported when the latest is shown.
      const earlier = loading;
      loading = {resolve: (value) => { if (earlier) earlier.resolve(value); resolve(value); }, keep};
      img.src = url;
    });
  }

  function mount(root, url) {
    root.append(scroller, bar);
    return load(url, null);
  }

  // A new version keeps zoom and centre while the picture keeps its size
  // (VIEW-08); another size starts at Fit.
  async function update(message) {
    await ready;
    const next = new URL(fileUrl);
    next.searchParams.set("t", String(message.version));
    const now = window.acImageView();
    const keep = fitting ? null : {
      scale, width: now.width, height: now.height,
      u: (scroller.clientWidth / 2 - now.x) / scale,
      v: (scroller.clientHeight / 2 - now.y) / scale,
    };
    await load(next.pathname + next.search, keep);
  }

  window.acViewer = {
    kind: "image",
    space: "image-px",
    mount,
    update,
    get mounted() { return mounted; },
    get ready() { return ready; },
    size: () => ({w: img.naturalWidth, h: img.naturalHeight}),
    toSpace(cx, cy) {
      const at = window.acImageView();
      return {x: (cx - at.x) / at.scale, y: (cy - at.y) / at.scale};
    },
    fromSpace(u, v) {
      const at = window.acImageView();
      return {x: at.x + u * at.scale, y: at.y + v * at.scale};
    },
    // The picture's own pixels inside ``box`` (picture pixels), cut to the picture.
    crop(box) {
      const x0 = Math.max(0, Math.floor(box.x));
      const y0 = Math.max(0, Math.floor(box.y));
      const x1 = Math.min(img.naturalWidth, Math.ceil(box.x + box.w));
      const y1 = Math.min(img.naturalHeight, Math.ceil(box.y + box.h));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, x1 - x0);
      canvas.height = Math.max(1, y1 - y0);
      canvas.getContext("2d").drawImage(
        img, x0, y0, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height);
      return {canvas, x: x0, y: y0};
    },
    // Scroll so that ``box`` (picture pixels) is in view; centred when it was not.
    reveal(box) {
      const a = this.fromSpace(box.x, box.y);
      const b = this.fromSpace(box.x + box.w, box.y + box.h);
      if (a.x >= 0 && a.y >= 0 && b.x <= scroller.clientWidth && b.y <= scroller.clientHeight) return;
      placeAt(box.x + box.w / 2, box.y + box.h / 2, scroller.clientWidth / 2, scroller.clientHeight / 2);
    },
  };

  fitButton.addEventListener("click", fit);
  fullButton.addEventListener("click", () => {
    zoomAround(1, scroller.clientWidth / 2, scroller.clientHeight / 2);
  });

  scroller.addEventListener("wheel", (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    const lines = event.deltaMode === 1 ? 16 : 1;
    zoomAround(scale * Math.exp(-event.deltaY * lines * WHEEL_RATE), event.clientX, event.clientY);
  }, {passive: false});

  // In comment mode the helper stops these events before they get here (COM-01).
  scroller.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("[data-bar]")) return;
    if (event.clientX >= scroller.clientWidth || event.clientY >= scroller.clientHeight) return;
    scroller.setPointerCapture(event.pointerId);
    scroller.classList.add("panning");
    let last = [event.clientX, event.clientY];
    const move = (e) => {
      scroller.scrollLeft -= e.clientX - last[0];
      scroller.scrollTop -= e.clientY - last[1];
      last = [e.clientX, e.clientY];
    };
    const stop = () => {
      scroller.classList.remove("panning");
      scroller.removeEventListener("pointermove", move);
      scroller.removeEventListener("pointerup", stop);
      scroller.removeEventListener("pointercancel", stop);
    };
    scroller.addEventListener("pointermove", move);
    scroller.addEventListener("pointerup", stop);
    scroller.addEventListener("pointercancel", stop);
  });

  window.addEventListener("resize", () => {
    if (fitting) setScale(fitScale());
    else viewChanged();
  });
  scroller.addEventListener("scroll", viewChanged);

  img.addEventListener("error", () => fail("image-undecodable"));
  img.addEventListener("load", () => {
    if (img.naturalWidth * img.naturalHeight > MAX_PIXELS) return fail("image-too-large");
    const keep = loading && loading.keep;
    if (keep && keep.width === img.naturalWidth && keep.height === img.naturalHeight) {
      fitting = false;
      setScale(keep.scale);
      placeAt(keep.u, keep.v, scroller.clientWidth / 2, scroller.clientHeight / 2);
    } else {
      fit();
    }
    finish();
  });
  const ready = mount(document.body, fileUrl.pathname + fileUrl.search).then(() => {
    document.dispatchEvent(new CustomEvent("agentcanvas:updated"));
  });
})();
