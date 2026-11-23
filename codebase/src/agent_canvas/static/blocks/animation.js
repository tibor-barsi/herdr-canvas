// canvas-animation: a video (``src``) or a sequence of pictures (``frames``) with play and
// pause, one-frame steps, a position slider, speed and loop (CNT-02). It never plays sound
// (the video is always muted and has no sound control) and plays by itself only with
// ``autoplay``. The send screenshot and ``look`` show the current frame (BLK-06, A-101).
// Both media load with ``crossorigin="anonymous"`` so a canvas drawn from them stays readable
// (early check 19). A rewrite keeps the position and the playing state when the media is the same.
// The position goes to the shell (``agentcanvas:block-state``) and comes back after the frame
// reloads, e.g. when the owner leaves the tab and returns: the block returns paused (CNT-02, D-55).
import { CanvasBlock, h } from "./base.js";

const SPEEDS = [0.25, 0.5, 1, 2, 4];
const MAX_FRAMES = 300;
const VIDEO_STEP_FPS = 30;
const SLIDER_STEPS = 1000;
const REPORT_MS = 500; // while playing, how often the position goes to the shell
const MAX_HEIGHT = 480; // px, as for canvas-image

const CSS = `
.anim-stage { display: grid; place-items: center; background: var(--ac-subtle);
  border-radius: 4px; overflow: hidden; line-height: 0; }
.anim-stage video, .anim-stage img { display: block; max-width: 100%; max-height: ${MAX_HEIGHT}px; }
.anim-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }
.anim-bar button { min-width: 4.5em; }
.anim-bar button[aria-pressed="true"] {
  background: var(--ac-accent); border-color: var(--ac-accent); color: var(--ac-accent-fg);
}
.anim-slider { flex: 1 1 140px; min-width: 100px; padding: 0; accent-color: var(--ac-accent); }
.anim-speed { font: inherit; color: inherit; background: var(--ac-subtle);
  border: 1px solid var(--ac-border); border-radius: 6px; padding: 5px 6px; }
.anim-where { color: var(--ac-muted); font-variant-numeric: tabular-nums; min-width: 6em; }
`;
const ownSheet = new CSSStyleSheet();
ownSheet.replaceSync(CSS);

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

function same(src, path) {
  const resolved = decodeURIComponent(new URL(src, document.baseURI).pathname);
  return resolved.endsWith("/" + path);
}

export class CanvasAnimation extends CanvasBlock {
  static inPlace = true;
  static schema = {
    src: "string", frames: "array", fps: "number", autoplay: "boolean",
    loop: "boolean", speed: "number", alt: "string",
  };

  constructor() {
    super();
    this.revision = 0;
    this.mediaKey = null;
    this.playing = false;
    this.position = 0; // frames (picture sequence only; a video keeps its own clock)
    this.lastReport = 0;
  }

  connectedCallback() {
    super.connectedCallback();
    this._onRestore = () => this.restore();
    document.addEventListener("agentcanvas:restore-state", this._onRestore);
    // The owner left the page; it comes back paused where it was (CNT-02, SES-15).
    this._onHidden = () => { if (this.playing) this.pause(); };
    document.addEventListener("agentcanvas:hidden", this._onHidden);
    const sheets = this.shadowRoot.adoptedStyleSheets;
    if (!sheets.includes(ownSheet)) this.shadowRoot.adoptedStyleSheets = [...sheets, ownSheet];
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("agentcanvas:restore-state", this._onRestore);
    document.removeEventListener("agentcanvas:hidden", this._onHidden);
    this.stop();
  }

  validate(config) {
    if ((config.src === undefined) === (config.frames === undefined)) {
      return 'give either "src" (a video) or "frames" (a list of pictures)';
    }
    if (config.frames !== undefined) {
      if (!config.frames.length || config.frames.length > MAX_FRAMES
        || !config.frames.every((f) => typeof f === "string")) {
        return `"frames" must be 1 to ${MAX_FRAMES} file names`;
      }
    }
    if (config.fps !== undefined && config.fps <= 0) return '"fps" must be above 0';
    if (config.speed !== undefined && !SPEEDS.includes(config.speed)) {
      return `"speed" must be one of ${SPEEDS.join(", ")}`;
    }
    return null;
  }

  get isVideo() {
    return this._config.src !== undefined;
  }

  get fps() {
    return this._config.fps || (this.isVideo ? VIDEO_STEP_FPS : 10);
  }

  async render(config, wrapper, before) {
    if (!wrapper.firstChild) this.build(wrapper);
    const key = JSON.stringify([config.src, config.frames]);
    if (key !== this.mediaKey) {
      this.stop();
      this.mediaKey = null;
      this.position = 0;
      await this.loadMedia(config);
      this.mediaKey = key;
      this.setSpeed(config.speed || 1);
      if (config.autoplay) this.play();
      this.restore();
    }
    if (!before || before.loop !== config.loop) this.loopButton.setAttribute("aria-pressed", String(Boolean(config.loop)));
    if (before && before.speed !== config.speed) this.setSpeed(config.speed || 1);
    if (this.video) this.video.loop = Boolean(config.loop);
    this.media.setAttribute("aria-label", config.alt || "Animation");
    this.update();
  }

  build(wrapper) {
    this.stage = h("div", {class: "anim-stage"});
    this.playButton = h("button", {type: "button", onclick: () => (this.playing ? this.pause() : this.play())}, "Play");
    this.backButton = h("button", {type: "button", "aria-label": "One frame back", onclick: () => this.step(-1)}, "◂ Step");
    this.nextButton = h("button", {type: "button", "aria-label": "One frame forward", onclick: () => this.step(1)}, "Step ▸");
    this.slider = h("input", {
      type: "range", class: "anim-slider", min: "0", max: "0", step: "1", value: "0", "aria-label": "Position",
      oninput: () => this.seekTo(Number(this.slider.value)),
    });
    this.where = h("span", {class: "anim-where", "aria-live": "off"});
    this.speedSelect = h("select", {
      class: "anim-speed", "aria-label": "Speed", onchange: () => this.setSpeed(Number(this.speedSelect.value)),
    }, ...SPEEDS.map((s) => h("option", {value: String(s), selected: s === 1}, `${s}×`)));
    this.loopButton = h("button", {
      type: "button", "aria-pressed": "false",
      onclick: () => {
        const on = this.loopButton.getAttribute("aria-pressed") !== "true";
        this.loopButton.setAttribute("aria-pressed", String(on));
        if (this.video) this.video.loop = on;
      },
    }, "Loop");
    wrapper.append(this.stage, h("div", {class: "anim-bar"}, this.playButton, this.backButton,
      this.nextButton, this.slider, this.where, this.speedSelect, this.loopButton));
  }

  get looping() {
    return this.loopButton.getAttribute("aria-pressed") === "true";
  }

  // ---- loading ------------------------------------------------------------------------

  url(path) {
    const url = new URL(path, document.baseURI);
    if (this.revision) url.searchParams.set("r", String(this.revision));
    return url.href;
  }

  async loadMedia(config) {
    this.video = null;
    this.images = null;
    if (config.src !== undefined) {
      const video = h("video", {muted: true, playsinline: true, preload: "auto", crossorigin: "anonymous"});
      video.muted = true;
      video.defaultMuted = true;
      video.volume = 0;
      video.addEventListener("ended", () => this.ended());
      await new Promise((resolve, reject) => {
        video.onloadeddata = resolve;
        video.onerror = () => reject(new Error(
          `could not load video ${config.src} (WebM plays everywhere; MP4 only where the browser has the codec)`));
        video.src = this.url(config.src);
      });
      this.video = video;
      this.media = video;
    } else {
      this.images = await Promise.all(config.frames.map((path) => new Promise((resolve, reject) => {
        const img = h("img", {crossorigin: "anonymous", alt: ""});
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error(`could not load picture ${path}`));
        img.src = this.url(path);
      })));
      this.media = this.images[0];
    }
    this.stage.replaceChildren(this.media);
    this.slider.max = String(this.isVideo ? SLIDER_STEPS : this.images.length - 1);
    this.nextButton.disabled = this.backButton.disabled = false;
  }

  // ---- playing ------------------------------------------------------------------------

  play() {
    if (this.playing) return;
    this.playing = true;
    if (this.isVideo) {
      if (this.video.ended) this.video.currentTime = 0;
      this.video.play().catch(() => this.pause());
    } else {
      if (this.position >= this.images.length - 1) this.position = 0;
      this.lastTick = performance.now();
    }
    this.tick = () => this.frameTick();
    this.raf = requestAnimationFrame(this.tick);
    this.update();
  }

  pause() {
    this.playing = false;
    if (this.video) this.video.pause();
    cancelAnimationFrame(this.raf);
    this.update();
    this.reportState();
  }

  // Tell the shell where the animation is, so a reloaded frame can put it back (D-55).
  reportState() {
    const id = this.getAttribute("data-canvas-id");
    const at = this.isVideo ? this.video.currentTime : this.position;
    document.dispatchEvent(new CustomEvent("agentcanvas:block-state", {detail: {id, state: {key: this.mediaKey, at}}}));
    this.lastReport = performance.now();
  }

  restore() {
    const saved = (window.acRestoredState || {})[this.getAttribute("data-canvas-id")];
    if (!saved || saved.key !== this.mediaKey || typeof saved.at !== "number") return;
    delete window.acRestoredState[this.getAttribute("data-canvas-id")];
    this.pause();
    if (this.isVideo) this.video.currentTime = saved.at;
    else this.position = clamp(saved.at, 0, this.images.length - 1);
    this.update();
  }

  stop() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    if (this.video) this.video.pause();
  }

  ended() {
    if (!this.looping) this.pause();
  }

  frameTick() {
    if (!this.playing) return;
    if (!this.isVideo) {
      const now = performance.now();
      this.position += (now - this.lastTick) / 1000 * this.fps * this.speed;
      this.lastTick = now;
      const last = this.images.length - 1;
      if (this.position > last) {
        if (this.looping) this.position %= this.images.length;
        else {
          this.position = last;
          this.pause();
          return;
        }
      }
    }
    this.update();
    if (performance.now() - this.lastReport > REPORT_MS) this.reportState();
    this.raf = requestAnimationFrame(this.tick);
  }

  get speed() {
    return Number(this.speedSelect.value);
  }

  setSpeed(value) {
    this.speedSelect.value = String(value);
    if (this.video) this.video.playbackRate = value;
  }

  step(direction) {
    this.pause();
    if (this.isVideo) {
      const next = this.video.currentTime + direction / this.fps;
      this.video.currentTime = clamp(next, 0, this.video.duration);
    } else {
      this.position = clamp(Math.round(this.position) + direction, 0, this.images.length - 1);
    }
    this.update();
    this.reportState();
  }

  seekTo(value) {
    if (this.isVideo) this.video.currentTime = value / SLIDER_STEPS * this.video.duration;
    else this.position = value;
    this.update();
    this.reportState();
  }

  // Bring the picture, the slider and the labels in line with the position.
  update() {
    this.playButton.textContent = this.playing ? "Pause" : "Play";
    this.playButton.setAttribute("aria-label", this.playing ? "Pause" : "Play");
    if (this.isVideo) {
      const {currentTime, duration} = this.video;
      if (this.shadowRoot.activeElement !== this.slider) {
        this.slider.value = String(Math.round(currentTime / duration * SLIDER_STEPS));
      }
      this.where.textContent = `${currentTime.toFixed(1)} / ${duration.toFixed(1)} s`;
      return;
    }
    const index = Math.floor(this.position);
    if (this.media !== this.images[index]) {
      this.media = this.images[index];
      this.stage.replaceChildren(this.media);
      this.media.setAttribute("aria-label", this._config.alt || "Animation");
    }
    this.slider.value = String(index);
    this.where.textContent = `frame ${index + 1} / ${this.images.length}`;
  }

  // ---- BLK-09: a changed file keeps position and settings ---------------------------------

  fileChanged(path) {
    const config = this._config;
    if (!config || typeof path !== "string") return;
    const paths = config.src !== undefined ? [config.src] : config.frames;
    if (paths.some((p) => same(p, path))) this.reloadSource();
  }

  async reloadSource() {
    if (!this._config || (this._wrapper && this._wrapper.isError)) {
      super.reloadSource();
      return;
    }
    const at = this.isVideo ? this.video.currentTime : this.position;
    const resume = this.playing;
    this.revision += 1;
    this.stop();
    try {
      await this.loadMedia(this._config);
    } catch (error) {
      this.showError(error.message);
      return;
    }
    if (this.isVideo) this.video.currentTime = at;
    else this.position = clamp(at, 0, this.images.length - 1);
    if (this.video) this.video.loop = this.looping;
    this.setSpeed(this.speed);
    if (resume) this.play();
    else this.update();
  }

  // ---- BLK-06: the current frame as an image for screenshots ---------------------------

  /** The frame on screen, for the send screenshot (a video is drawn onto a canvas). */
  async snapshot() {
    const rect = this.media.getBoundingClientRect();
    if (!this.isVideo) return {image: this.media, rect};
    const video = this.video;
    if (video.seeking) await new Promise((resolve) => video.addEventListener("seeked", resolve, {once: true}));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(rect.width));
    canvas.height = Math.max(1, Math.round(rect.height));
    const scale = Math.min(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
    const width = video.videoWidth * scale;
    const height = video.videoHeight * scale;
    canvas.getContext("2d").drawImage(video, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
    return {image: canvas, rect};
  }
}
