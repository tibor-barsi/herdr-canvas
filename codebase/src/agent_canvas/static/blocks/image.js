// canvas-image: an image with wheel zoom, drag pan, double-click reset and
// clicks reported in image pixels (`image-click`). An enlarge button (or Enter
// on the focused picture) shows the same picture in a full-frame overlay with
// the same gestures (IMG-01 to IMG-03).
import { CanvasBlock, h, latchWheel } from "./base.js";
import { sheet } from "./style.js";

const MAX_ZOOM = 40;
const DRAG_THRESHOLD = 4; // px; a smaller movement between press and release is a click
const OVERLAY_MARGIN = 64; // px kept free around the enlarged picture

// Static markup, never built from page text.
const ENLARGE_ICON = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" '
  + 'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
  + 'stroke-linejoin="round" aria-hidden="true"><path d="M9.5 2.5h4v4M6.5 13.5h-4v-4'
  + 'M13.5 2.5l-4.5 4.5M2.5 13.5L7 9"/></svg>';

/**
 * A picture with wheel zoom, drag pan and double-click reset. ``zoom`` is the
 * ``{scale, x, y}`` object that holds the view; ``onclick(pixel, event)`` gets
 * a click (not a drag) in image pixels.
 */
class ZoomView {
  constructor(img, zoom, onclick) {
    this.img = img;
    this.zoom = zoom;
    this.onclick = onclick;
    this.view = h("div", {class: "image-view", tabindex: "0"}, img);
    this.bind();
  }

  apply() {
    const {scale, x, y} = this.zoom;
    this.img.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    this.placePoint();
  }

  /** Show the point of a point Ask (image pixels), or none with ``null`` (ASK-05). */
  setPoint(pixel) {
    this.point = pixel;
    if (!pixel) {
      if (this.pointMark) this.pointMark.remove();
      this.pointMark = null;
      return;
    }
    if (!this.pointMark) {
      this.pointMark = h("div", {class: "point-mark", "aria-hidden": "true"});
      this.view.append(this.pointMark);
    }
    this.placePoint();
  }

  placePoint() {
    if (!this.pointMark || !this.img.naturalWidth) return;
    const {scale, x, y} = this.zoom;
    // Percentages of the view, which is as large as the unzoomed picture.
    const left = this.point.x / this.img.naturalWidth * scale * 100;
    const top = this.point.y / this.img.naturalHeight * scale * 100;
    this.pointMark.style.cssText = `left:calc(${left}% + ${x}px);top:calc(${top}% + ${y}px)`;
  }

  // Keep the picture covering the visible area.
  clamp() {
    const zoom = this.zoom;
    zoom.x = Math.min(0, Math.max(this.img.offsetWidth * (1 - zoom.scale), zoom.x));
    zoom.y = Math.min(0, Math.max(this.img.offsetHeight * (1 - zoom.scale), zoom.y));
  }

  zoomAt(event) {
    const zoom = this.zoom;
    const rect = this.view.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const next = Math.min(MAX_ZOOM, Math.max(1, zoom.scale * Math.exp(-event.deltaY * 0.002)));
    const ratio = next / zoom.scale;
    zoom.x = px - (px - zoom.x) * ratio;
    zoom.y = py - (py - zoom.y) * ratio;
    zoom.scale = next;
    this.clamp();
    this.apply();
  }

  // The pixel of the picture under a pointer position.
  pixelAt(event) {
    const rect = this.img.getBoundingClientRect();
    return {
      x: Math.floor((event.clientX - rect.left) / rect.width * this.img.naturalWidth),
      y: Math.floor((event.clientY - rect.top) / rect.height * this.img.naturalHeight),
    };
  }

  reset() {
    Object.assign(this.zoom, {scale: 1, x: 0, y: 0});
    this.apply();
  }

  bind() {
    let drag = null;
    latchWheel(this.view);
    this.view.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.zoomAt(event);
    }, {passive: false});
    this.view.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const zoom = this.zoom;
      drag = {sx: event.clientX, sy: event.clientY, x: zoom.x, y: zoom.y, moved: false};
      this.view.setPointerCapture(event.pointerId);
    });
    this.view.addEventListener("pointermove", (event) => {
      if (!drag) return;
      const dx = event.clientX - drag.sx;
      const dy = event.clientY - drag.sy;
      if (Math.hypot(dx, dy) > DRAG_THRESHOLD) drag.moved = true;
      if (!drag.moved) return;
      this.zoom.x = drag.x + dx;
      this.zoom.y = drag.y + dy;
      this.clamp();
      this.view.classList.add("panning");
      this.apply();
    });
    this.view.addEventListener("pointerup", (event) => {
      const finished = drag;
      drag = null;
      this.view.classList.remove("panning");
      if (!finished || finished.moved) return;
      this.onclick(this.pixelAt(event), event);
    });
    this.view.addEventListener("dblclick", () => this.reset());
  }
}

export class CanvasImage extends CanvasBlock {
  static schema = {src: "string!", alt: "string"};

  disconnectedCallback() {
    this.closeOverlay(false);
    super.disconnectedCallback();
  }

  async render(config, wrapper) {
    this.closeOverlay(false);
    this.state.zoom = this.state.zoom || {scale: 1, x: 0, y: 0};
    this.revision = this.revision || 0;
    this.img = h("img", {alt: config.alt || "", draggable: "false"});
    this.main = new ZoomView(this.img, this.state.zoom, (pixel, event) => {
      this.action("image-click", pixel, event);
    });
    this.view = this.main.view;
    this.view.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.target !== this.view) return;
      event.preventDefault(); // else Enter would also press the close button that gets the focus
      this.openOverlay();
    });
    this.enlarge = h("button", {
      type: "button", class: "enlarge", title: "Enlarge", "aria-label": "Enlarge image",
      onclick: () => this.openOverlay(),
    });
    this.enlarge.innerHTML = ENLARGE_ICON;
    await this.load(this.img, config.src);
    wrapper.replaceChildren(h("div", {class: "image-frame"}, this.view, this.enlarge));
    this.main.apply();
    if (this.state.point) this.main.setPoint(this.state.point);
  }

  /** Mark the owner's point of a point Ask (ASK-05), in image pixels; ``null`` removes it. */
  showPoint(pixel) {
    this.state.point = pixel;
    if (this.main) this.main.setPoint(pixel);
    if (this.overlay) this.overlay.view.setPoint(pixel);
  }

  hidePoint() {
    if (this.state.point) this.showPoint(null);
  }

  // Wait for the picture; a changed file gets a new query so no cache is used.
  load(img, src) {
    const url = new URL(src, document.baseURI);
    if (this.revision) url.searchParams.set("r", String(this.revision));
    return new Promise((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error(`could not load image ${src}`));
      img.src = url.href;
    });
  }

  // ---- the overlay (IMG-01 to IMG-03) -----------------------------------------------

  openOverlay() {
    if (this.overlay || !this.img.naturalWidth) return;
    const img = h("img", {alt: this.img.alt, draggable: "false"});
    const zoom = {scale: 1, x: 0, y: 0};
    const view = new ZoomView(img, zoom, (pixel, event) => {
      this.action("image-click", pixel, event);
    });
    if (this.state.point) view.setPoint(this.state.point);
    const close = h("button", {
      type: "button", class: "close", title: "Close (Esc)", "aria-label": "Close",
      onclick: () => this.closeOverlay(),
    }, "×");
    const backdrop = h("div", {
      class: "overlay", role: "dialog", "aria-modal": "true", "aria-label": "Enlarged image",
    }, view.view, close);
    const host = h("div", {class: "ac-image-overlay"});
    // Inline style: the shared stylesheet gives every host a margin and a font.
    host.style.cssText = "position:fixed;inset:0;margin:0;z-index:2147483000;";
    const root = host.attachShadow({mode: "open"});
    root.adoptedStyleSheets = [sheet];
    root.append(backdrop);
    this.overlay = {host, root, img, view, close, backdrop};
    this.bindOverlay();
    document.body.append(host);
    this.load(img, this._config.src).then(() => this.fitOverlay()).catch(() => this.closeOverlay());
    close.focus();
  }

  bindOverlay() {
    const {backdrop, close} = this.overlay;
    this.onOverlayKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        this.closeOverlay();
      } else if (event.key === "Tab") {
        event.preventDefault(); // the close button is the only stop
        close.focus();
      }
    };
    this.onOverlayResize = () => this.fitOverlay();
    window.addEventListener("keydown", this.onOverlayKey, true);
    window.addEventListener("resize", this.onOverlayResize);
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) this.closeOverlay();
    });
    backdrop.addEventListener("wheel", (event) => event.preventDefault(), {passive: false});
  }

  // Size the picture to the frame, small pictures up as well; keeps the zoom valid.
  fitOverlay() {
    if (!this.overlay) return;
    const {img, view} = this.overlay;
    const room = (length) => Math.max(1, length - OVERLAY_MARGIN);
    const fit = Math.min(room(window.innerWidth) / img.naturalWidth,
      room(window.innerHeight) / img.naturalHeight);
    img.style.width = `${Math.round(img.naturalWidth * fit)}px`;
    img.style.height = `${Math.round(img.naturalHeight * fit)}px`;
    view.clamp();
    view.apply();
  }

  closeOverlay(restoreFocus = true) {
    if (!this.overlay) return;
    window.removeEventListener("keydown", this.onOverlayKey, true);
    window.removeEventListener("resize", this.onOverlayResize);
    this.overlay.host.remove();
    this.overlay = null;
    if (restoreFocus && this.enlarge) this.enlarge.focus();
  }

  // BLK-09: load the changed file into the same element, keeping zoom and pan.
  async reloadSource() {
    if (!this.img || !this._config || (this._wrapper && this._wrapper.isError)) {
      super.reloadSource();
      return;
    }
    this.revision += 1;
    try {
      await this.load(this.img, this._config.src);
      this.main.clamp();
      this.main.apply();
      if (this.overlay) await this.load(this.overlay.img, this._config.src);
    } catch (error) {
      this.showError(error.message);
    }
  }
}
