// canvas-scene: a multi-part 3D viewer (STL, STEP, GLB) with a part list, view
// buttons, a section plane and a mark mode (SCN-01 to SCN-08). Parts load in
// parallel and appear as they arrive; the camera, section and per-part settings
// live in ``this.state`` (the element), so they survive page updates (SCN-06).
import { CanvasBlock, checkSchema, h, latchWheel } from "./base.js";
import { markSprite, round } from "./model.js";
import { PartList } from "./scene-list.js";
import { fetchBytes, loadSceneLibs, parseFile, disposeObject, extensionOf } from "./scene-load.js";
import { sceneSheet } from "./scene-style.js";
import { sheet } from "./style.js";

const PART_EXTENSIONS = [".stl", ".step", ".stp", ".glb"];
const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const DEFAULT_HEIGHT = 480;
const CLICK_DISTANCE = 4; // px between press and release that still counts as a click
const FILL = 0.82; // share of the limiting view dimension that the parts fill
const CAP_LIGHTEN = 0.3; // how far the cut faces are lightened towards white
// Distinct, muted colours for parts that have none of their own (light and dark).
const PALETTE = [
  "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#9c755f",
];
const VIEWS = {
  z: {iso: [1, -1, 0.8], top: [0, -0.001, 1], front: [0, -1, 0], side: [1, 0, 0]},
  y: {iso: [1, 0.8, 1], top: [0, 1, 0.001], front: [0, 0, 1], side: [1, 0, 0]},
};
const AXES = ["x", "y", "z"];

const stem = (src) => {
  const name = decodeURIComponent(new URL(src, document.baseURI).pathname).split("/").pop();
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
};

/** Problem text for one part entry of the config, or null. */
function partProblem(part) {
  if (part === null || typeof part !== "object" || Array.isArray(part)) {
    return "must be an object";
  }
  const problem = checkSchema(part, {
    src: "string!", name: "string", group: "string", colour: "string",
    opacity: "number", visible: "boolean", split: "boolean",
  });
  if (problem) return problem.replace("config key", "key");
  const extension = extensionOf(part.src);
  if (!PART_EXTENSIONS.includes(extension)) {
    return `src "${part.src}" must be an .stl, .step, .stp or .glb file`;
  }
  if (part.colour !== undefined && !HEX.test(part.colour)) {
    return `colour "${part.colour}" must be a CSS hex colour such as #2a9d8f`;
  }
  if (part.opacity !== undefined && (part.opacity < 0 || part.opacity > 1)) {
    return `opacity ${part.opacity} must be between 0 and 1`;
  }
  if (part.split && ![".step", ".stp"].includes(extension)) {
    return `split only works for STEP files, not ${part.src}`;
  }
  return null;
}

/** Problem text for a complete scene config (``parts`` present), or null. */
function sceneProblem(config) {
  if (config.height !== undefined && config.height < 80) return '"height" must be at least 80';
  if (!Array.isArray(config.parts) || !config.parts.length) return '"parts" must list at least one part';
  for (const [index, part] of config.parts.entries()) {
    const problem = partProblem(part);
    if (problem) return `part ${index + 1}: ${problem}`;
  }
  return null;
}

// The part entries with defaults filled in and unique names.
function normaliseParts(parts) {
  const seen = new Map();
  return parts.map((raw) => {
    let name = raw.name || stem(raw.src);
    const count = (seen.get(name) || 0) + 1;
    seen.set(name, count);
    if (count > 1) name = `${name} (${count})`;
    return {
      src: raw.src, name, group: raw.group || null, colour: raw.colour || null,
      opacity: raw.opacity ?? 1, visible: raw.visible ?? true, split: Boolean(raw.split),
      key: `${raw.src}|${name}|${raw.split ? "split" : ""}`,
    };
  });
}

export class CanvasScene extends CanvasBlock {
  static schema = {
    parts: "array", src: "string", units: "string", height: "number", up: "z|y",
  };
  static inPlace = true;

  constructor() {
    super();
    this.entries = [];
    this.loading = 0;
    this.reported = new Set();
    this.disposed = false;
    this.renderer = null;
  }

  connectedCallback() {
    if (this.disposed) {
      // Moved in the DOM: the GPU resources are gone, build the view again.
      this.disposed = false;
      this._config = undefined;
    }
    super.connectedCallback();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.teardown();
  }

  get renderIdle() {
    return super.renderIdle && this.loading === 0;
  }

  validate(config) {
    if (config.parts === undefined) {
      if (config.src === undefined) return 'config needs "parts" or "src" (a manifest .json file)';
      return extensionOf(config.src) === ".json" ? null : `src "${config.src}" must be a .json manifest`;
    }
    return sceneProblem(config);
  }

  // ---- config and manifest (SCN-01) ------------------------------------------------

  async resolveScene(config) {
    let manifest = {};
    if (config.parts === undefined) {
      const response = await fetch(config.src, {cache: "no-store"});
      if (!response.ok) throw new Error(`could not read manifest ${config.src} (${response.status})`);
      try {
        manifest = await response.json();
      } catch (error) {
        throw new Error(`manifest ${config.src} is not valid JSON`);
      }
      if (manifest === null || typeof manifest !== "object" || Array.isArray(manifest)) {
        throw new Error(`manifest ${config.src} must be a JSON object`);
      }
    }
    const scene = {...manifest, parts: config.parts ?? manifest.parts};
    for (const key of ["units", "height", "up"]) {
      if (config[key] !== undefined) scene[key] = config[key];
    }
    const problem = checkSchema(scene, {
      parts: "array", units: "string", height: "number", up: "z|y",
    }) || sceneProblem(scene);
    if (problem) throw new Error(config.parts === undefined ? `manifest ${config.src}: ${problem}` : problem);
    return scene;
  }

  // ---- rendering ---------------------------------------------------------------------

  async render(config, wrapper) {
    const scene = await this.resolveScene(config);
    const libs = await loadSceneLibs();
    const sameView = this.renderer && wrapper === this.viewWrapper;
    if (sameView && (scene.up || "z") === this.up) {
      this.reconcile(scene);
      return;
    }
    this.teardown();
    this.build(libs, scene, wrapper);
  }

  build(libs, scene, wrapper) {
    const {THREE, OrbitControls} = libs;
    this.THREE = THREE;
    this.libs = libs;
    this.up = scene.up || "z";
    this.viewWrapper = wrapper;
    this.shadowRoot.adoptedStyleSheets = [sheet, sceneSheet];
    const state = this.state;
    if (state.up !== this.up) state.view = null; // a camera for the other axis is wrong
    state.up = this.up;
    state.parts = state.parts || {};
    state.section = state.section || {axis: null, value: null, flip: false};
    state.collapsed = state.collapsed || {};
    this.autoFit = !state.view;
    this.cutOn = {value: 0};
    this.plane = new THREE.Plane();

    this.buildDom(wrapper);
    this.attach(wrapper); // the renderer measures the laid-out viewer
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: true, preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 1000);
    this.camera.up.set(0, this.up === "z" ? 0 : 1, this.up === "z" ? 1 : 0);
    this.scene.add(this.camera);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(0.4, 0.6, 1);
    this.camera.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6);
    fill.position.set(-0.8, -0.3, -0.6);
    this.camera.add(fill);
    latchWheel(this.canvas);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.addEventListener("start", () => { this.autoFit = false; });
    this.controls.addEventListener("change", () => this.cameraChanged());
    if (state.view) {
      this.camera.position.fromArray(state.view.position);
      this.controls.target.fromArray(state.view.target);
      this.controls.update();
    }
    this.watchScheme();
    this.watchSize();
    this.bindMarking();
    this.markSprites = [];
    this.restoreMarks();
    this.setMarking(Boolean(state.marking));
    this.resize();
    this.reconcile(scene);
    this.viewer.classList.add("interactive");
  }

  buildDom(wrapper) {
    this.canvas = h("canvas");
    this.status = h("div", {class: "scene-status", role: "status", hidden: true});
    this.viewer = h("div", {class: "viewer"}, this.canvas, this.status);
    this.list = new PartList({
      setVisible: (ids, visible) => this.patchParts(ids, {visible}),
      setOpacity: (ids, opacity) => this.patchParts(ids, {opacity}),
      setColour: (id, colour) => this.patchParts([id], {colour}),
      toggleGroup: (name) => {
        this.state.collapsed[name] = !this.state.collapsed[name];
        this.syncList();
      },
    });
    this.sizeNote = h("span", {class: "size-note muted"});
    wrapper.className = "block scene";
    wrapper.replaceChildren(
      h("div", {class: "scene-main"}, this.viewer, this.buildTools()),
      h("div", {class: "scene-side"}, this.list.element));
  }

  buildTools() {
    const button = (label, onclick, extra) => h("button", {type: "button", onclick, ...extra}, label);
    const views = ["iso", "top", "front", "side"].map(
      (name) => button(name, () => this.setView(name), {"aria-label": `${name} view`}));
    const view = h("div", {class: "group", role: "group", "aria-label": "View"},
      h("span", {class: "group-label"}, "View"), ...views,
      button("reset", () => this.resetView(), {title: "Back to the initial camera"}),
      button("fit", () => this.fitVisible(), {title: "Fit the visible parts"}));
    this.axisButtons = {};
    const axes = [null, ...AXES].map((axis) => {
      const node = button(axis ? axis.toUpperCase() : "off", () => this.setSectionAxis(axis), {
        "aria-pressed": "false", "aria-label": axis ? `Section plane ${axis.toUpperCase()}` : "Section off",
      });
      this.axisButtons[axis] = node;
      return node;
    });
    this.sectionSlider = h("input", {
      type: "range", min: "0", max: "1000", value: "500", "aria-label": "Section position",
    });
    this.sectionSlider.addEventListener("input", () => this.moveSection());
    this.sectionValue = h("span", {class: "section-value"});
    this.flipButton = button("flip", () => this.flipSection(), {title: "Keep the other side"});
    this.sectionExtra = h("span", {class: "section-extra", hidden: true},
      this.sectionSlider, this.sectionValue, this.flipButton);
    this.sectionBox = h("div", {class: "group", role: "group", "aria-label": "Section plane"},
      h("span", {class: "group-label"}, "Section"), ...axes, this.sectionExtra);
    this.markToggle = button("Mark", () => this.setMarking(!this.state.marking), {
      class: "mark-toggle", "aria-pressed": "false",
    });
    const marks = h("div", {class: "group"}, this.markToggle,
      button("Clear marks", () => this.clearMarks()));
    return h("div", {class: "scene-tools"}, view, this.sectionBox, marks, this.sizeNote);
  }

  // ---- parts and entries ------------------------------------------------------------

  /** All rows of the part list, in config order. */
  get parts() {
    return this.entries.flatMap((entry) => entry.parts);
  }

  /** A plain description of every part, for tests and tools. */
  partInfo() {
    return this.parts.map((part) => ({
      id: part.id, name: part.name, group: part.group, status: part.status,
      visible: this.setting(part, "visible"), opacity: this.setting(part, "opacity"),
      colour: this.colourOf(part), error: part.error,
    }));
  }

  makePart(entry, id, name, group) {
    return {
      entry, id, name, group, status: "pending", progress: 0, error: null,
      object: null, materials: [], box: null, native: null,
    };
  }

  newEntry(cfg, index) {
    const entry = {cfg, index, parts: [], promise: null};
    entry.parts = [this.makePart(entry, cfg.key, cfg.name, cfg.group)];
    return entry;
  }

  // Bring the entries in line with ``scene``; loaded parts and settings stay.
  reconcile(scene) {
    const wanted = normaliseParts(scene.parts);
    const old = new Map(this.entries.map((entry) => [entry.cfg.key, entry]));
    this.entries = wanted.map((cfg, index) => {
      const entry = old.get(cfg.key);
      old.delete(cfg.key);
      if (!entry) return this.newEntry(cfg, index);
      entry.cfg = cfg;
      entry.index = index;
      for (const part of entry.parts) {
        if (!cfg.split) part.group = cfg.group;
        else part.group = cfg.group || stem(cfg.src);
      }
      return entry;
    });
    for (const entry of old.values()) this.removeEntry(entry);
    this.units = scene.units || "";
    this.height = scene.height || DEFAULT_HEIGHT;
    this.viewer.style.height = `${this.height}px`;
    this.list.element.style.setProperty("--scene-height", `${this.height}px`);
    for (const part of this.parts) this.applyPart(part);
    for (const entry of this.entries) this.loadIfWanted(entry);
    this.partsChanged();
    this.resize();
  }

  loadIfWanted(entry) {
    if (entry.promise) return;
    if (entry.parts.some((part) => this.setting(part, "visible"))) this.startLoad(entry);
  }

  removeEntry(entry) {
    entry.removed = true;
    for (const part of entry.parts) this.removePartObject(part);
  }

  removePartObject(part) {
    if (!part.object) return;
    this.scene.remove(part.object);
    disposeObject(part.object);
    part.object = null;
    part.materials = [];
  }

  // ---- loading (SCN-05) ----------------------------------------------------------------

  startLoad(entry) {
    this.loading += 1;
    for (const part of entry.parts) {
      part.status = "loading";
      part.progress = 0;
      part.error = null;
    }
    entry.promise = this.loadEntry(entry).finally(() => {
      this.loading -= 1;
      this.partsChanged();
      if (this.loading === 0) {
        this.viewer.classList.add("ready");
        this._notifyIdle();
      }
    });
    this.viewer.classList.remove("ready");
    this.partsChanged();
  }

  async loadEntry(entry) {
    const {src, split} = entry.cfg;
    const url = new URL(src, document.baseURI).href;
    try {
      const bytes = await fetchBytes(url, (fraction) => {
        for (const part of entry.parts) part.progress = fraction ?? 0.5;
        this.syncList();
      });
      const solids = await parseFile(this.libs, src, bytes, split);
      if (entry.removed || !this.renderer) {
        for (const solid of solids) disposeObject(solid.object);
        return;
      }
      this.install(entry, solids);
    } catch (error) {
      if (entry.removed) return;
      this.failEntry(entry, error.message || String(error));
    }
  }

  failEntry(entry, message) {
    for (const part of entry.parts) {
      part.status = "error";
      part.error = message;
    }
    const text = `canvas-scene: part "${entry.cfg.name}": ${message}`;
    if (this.reported.has(text)) return;
    this.reported.add(text);
    window.agentCanvas.report("error", {
      source: "block", message: text, line: null,
      canvas_id: this.getAttribute("data-canvas-id") || null,
    });
  }

  // Put the parsed solids in the scene, replacing the placeholder row of a split file.
  install(entry, solids) {
    const {cfg} = entry;
    const placeholder = entry.parts[0];
    let parts;
    if (cfg.split) {
      const group = cfg.group || stem(cfg.src);
      const seen = new Map();
      parts = solids.map((solid, index) => {
        let name = solid.name || `${cfg.name} ${index + 1}`;
        const count = (seen.get(name) || 0) + 1;
        seen.set(name, count);
        if (count > 1) name = `${name} (${count})`;
        return this.makePart(entry, `${cfg.src}#${name}`, name, group);
      });
      this.inheritSettings(placeholder, parts);
      entry.parts = parts;
    } else {
      parts = [placeholder];
    }
    parts.forEach((part, index) => this.fill(part, solids[index], entry));
    this.partsChanged();
    if (this.autoFit) this.fitInitial();
    this.draw();
  }

  // A split file was shown through its placeholder row: its children start shown too.
  inheritSettings(placeholder, children) {
    const settings = this.state.parts[placeholder.id];
    if (!settings) return;
    delete this.state.parts[placeholder.id];
    for (const child of children) {
      this.state.parts[child.id] = {...settings, ...this.state.parts[child.id]};
    }
  }

  fill(part, solid, entry) {
    part.object = solid.object;
    part.status = "ready";
    part.progress = 1;
    const materials = new Set();
    solid.object.traverse((node) => {
      if (!node.isMesh) return;
      node.userData.part = part;
      const list = Array.isArray(node.material) ? node.material : [node.material];
      list.forEach((material) => materials.add(material));
    });
    part.materials = [...materials];
    for (const material of part.materials) this.prepareMaterial(material, entry);
    part.native = part.materials.find((m) => m.userData.native)?.color.clone() || null;
    this.scene.add(part.object);
    part.object.updateMatrixWorld(true);
    part.box = new this.THREE.Box3().setFromObject(part.object);
    this.applyPart(part);
  }

  // Remember the file's own look and let the cut faces show in a flat colour.
  prepareMaterial(material, entry) {
    const THREE = this.THREE;
    material.userData.nativeColour = material.color ? material.color.clone() : null;
    material.userData.nativeOpacity = material.opacity;
    material.userData.nativeTransparent = material.transparent;
    material.userData.cap = {value: new THREE.Vector3(1, 1, 1)};
    const {cap} = material.userData;
    const cutOn = this.cutOn;
    material.onBeforeCompile = (shader) => {
      shader.uniforms.uCutOn = cutOn;
      shader.uniforms.uCap = cap;
      shader.fragmentShader = "uniform float uCutOn;\nuniform vec3 uCap;\n"
        + shader.fragmentShader.replace("#include <dithering_fragment>",
          "#include <dithering_fragment>\n"
          + "if (uCutOn > 0.5 && !gl_FrontFacing) gl_FragColor.rgb = uCap;");
    };
    material.customProgramCacheKey = () => "canvas-scene-cut";
    material.userData.entryIndex = entry.index;
  }

  // ---- part settings (SCN-02) --------------------------------------------------------------

  setting(part, key) {
    const own = this.state.parts[part.id];
    if (own && own[key] !== undefined) return own[key];
    const {cfg} = part.entry;
    return key === "colour" ? cfg.colour : cfg[key];
  }

  colourOf(part) {
    const chosen = this.setting(part, "colour");
    if (chosen) return chosen;
    if (part.native) return `#${part.native.getHexString()}`;
    return PALETTE[part.entry.index % PALETTE.length];
  }

  patchParts(ids, patch) {
    const wanted = new Set(ids);
    for (const part of this.parts) {
      if (!wanted.has(part.id)) continue;
      this.state.parts[part.id] = {...this.state.parts[part.id], ...patch};
      this.applyPart(part);
      if (patch.visible) this.loadIfWanted(part.entry);
    }
    this.partsChanged();
  }

  // Push visibility, opacity and colour of ``part`` into its three.js objects.
  applyPart(part) {
    if (!part.object) return;
    const THREE = this.THREE;
    part.object.visible = this.setting(part, "visible");
    const opacity = this.setting(part, "opacity");
    const chosen = this.setting(part, "colour");
    for (const material of part.materials) {
      const {nativeColour, nativeOpacity, nativeTransparent} = material.userData;
      const override = chosen || (nativeColour ? null : PALETTE[part.entry.index % PALETTE.length]);
      if (override) material.color.set(override);
      else material.color.copy(nativeColour);
      const effective = nativeOpacity * opacity;
      const transparent = effective < 1 || nativeTransparent;
      if (material.transparent !== transparent) material.needsUpdate = true;
      material.opacity = effective;
      material.transparent = transparent;
      material.depthWrite = effective >= 1;
      const rgb = material.color.getRGB({}, THREE.SRGBColorSpace);
      material.userData.cap.value.set(
        ...[rgb.r, rgb.g, rgb.b].map((c) => c + (1 - c) * CAP_LIGHTEN));
    }
  }

  isShown(part) {
    return Boolean(part.object) && this.setting(part, "visible");
  }

  // Something about the parts changed: list, size note, section range, picture.
  partsChanged() {
    if (!this.renderer) return;
    this.syncList();
    this.syncSection();
    this.updateSizeNote();
    this.updateClip();
    this.draw();
  }

  syncList() {
    if (!this.list) return;
    const groups = [];
    const byName = new Map();
    for (const part of this.parts) {
      const name = part.group;
      if (!byName.has(name)) {
        const group = {name, collapsed: Boolean(name && this.state.collapsed[name]), parts: []};
        byName.set(name, group);
        groups.push(group);
      }
      byName.get(name).parts.push({
        id: part.id, name: part.name, status: part.status, error: part.error,
        progress: part.progress, visible: this.setting(part, "visible"),
        opacity: this.setting(part, "opacity"), colour: this.colourOf(part),
      });
    }
    // Ungrouped parts come first, like the top level of a tree.
    groups.sort((a, b) => (a.name === null ? -1 : 0) - (b.name === null ? -1 : 0));
    this.list.update(groups);
    this.updateStatus();
  }

  updateStatus() {
    const all = this.parts;
    const waiting = all.filter((part) => part.status === "loading").length;
    this.status.hidden = waiting === 0;
    if (waiting) {
      const done = all.filter((part) => part.status === "ready").length;
      this.status.textContent = `Loading ${waiting} of ${all.length} parts… (${done} ready)`;
    }
  }

  updateSizeNote() {
    const box = this.visibleBox();
    if (!box) {
      this.sizeNote.textContent = "";
      return;
    }
    const size = box.getSize(new this.THREE.Vector3()).toArray();
    const unit = this.units ? ` ${this.units}` : "";
    this.sizeNote.textContent = size.map((v) => Number(v.toPrecision(4))).join(" × ") + unit;
    this.bounds = {min: box.min.toArray().map(round), max: box.max.toArray().map(round)};
  }

  boxOf(parts) {
    const box = new this.THREE.Box3();
    for (const part of parts) if (part.box) box.union(part.box);
    return box.isEmpty() ? null : box;
  }

  visibleBox() {
    return this.boxOf(this.parts.filter((part) => this.isShown(part)));
  }

  // The depth range follows the size of everything that is loaded.
  updateClip() {
    const box = this.boxOf(this.parts);
    if (!box) return;
    const diagonal = box.getSize(new this.THREE.Vector3()).length() || 1;
    this.diagonal = diagonal;
    this.camera.near = diagonal * 0.005;
    this.camera.far = diagonal * 200;
    this.camera.updateProjectionMatrix();
  }

  // ---- camera (SCN-03) ---------------------------------------------------------------------

  cameraChanged() {
    if (!this.autoFit) {
      this.state.view = {
        position: this.camera.position.toArray(), target: this.controls.target.toArray(),
      };
    }
    this.draw();
  }

  direction(name) {
    return new this.THREE.Vector3(...VIEWS[this.up][name]).normalize();
  }

  // Put the camera on ``direction`` so that the projected box fills FILL of the
  // view's limiting dimension. The distance is refined on the real projection.
  placeCamera(box, direction) {
    const THREE = this.THREE;
    const centre = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-6);
    const corners = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => new THREE.Vector3(
      i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y,
      i & 4 ? box.max.z : box.min.z));
    const dir = direction.clone().normalize();
    let distance = radius * 3;
    for (let step = 0; step < 8; step++) {
      this.camera.position.copy(centre).addScaledVector(dir, distance);
      this.camera.lookAt(centre);
      this.camera.updateMatrixWorld(true);
      const half = Math.max(...corners.map(
        (c) => { const p = c.clone().project(this.camera); return Math.max(Math.abs(p.x), Math.abs(p.y)); }));
      const ratio = half / FILL;
      if (Math.abs(ratio - 1) < 0.01) break;
      distance = Math.max(radius * 0.2, distance * ratio);
    }
    this.camera.position.copy(centre).addScaledVector(dir, distance);
    this.controls.target.copy(centre);
    this.controls.update();
    this.draw();
  }

  setView(name) {
    const box = this.visibleBox() || this.boxOf(this.parts);
    this.autoFit = false;
    if (box) this.placeCamera(box, this.direction(name));
    this.cameraChanged();
  }

  fitVisible() {
    const box = this.visibleBox();
    if (!box) return;
    this.autoFit = false;
    this.placeCamera(box, this.camera.position.clone().sub(this.controls.target).normalize());
    this.cameraChanged();
  }

  // The initial camera: iso, fitted to the parts that the config shows.
  initialBox() {
    const shown = this.parts.filter((part) => part.box && part.entry.cfg.visible);
    return this.boxOf(shown) || this.visibleBox();
  }

  fitInitial() {
    const box = this.initialBox();
    if (box) this.placeCamera(box, this.direction("iso"));
  }

  resetView() {
    const box = this.initialBox();
    if (!box) return;
    this.autoFit = false;
    this.placeCamera(box, this.direction("iso"));
    this.cameraChanged();
  }

  // ---- section plane (SCN-04) ------------------------------------------------------------------

  setSectionAxis(axis) {
    const section = this.state.section;
    const changed = section.axis !== axis;
    section.axis = axis;
    if (axis && (changed || section.value === null)) {
      const box = this.visibleBox();
      const index = AXES.indexOf(axis);
      section.value = box ? (box.min.getComponent(index) + box.max.getComponent(index)) / 2 : 0;
    }
    this.syncSection();
    this.draw();
  }

  // Slider position (0..1000) to a coordinate across the visible box.
  moveSection() {
    const box = this.visibleBox();
    const section = this.state.section;
    if (!box || !section.axis) return;
    const index = AXES.indexOf(section.axis);
    const low = box.min.getComponent(index);
    const high = box.max.getComponent(index);
    section.value = low + (Number(this.sectionSlider.value) / 1000) * (high - low);
    this.syncSection();
    this.draw();
  }

  flipSection() {
    this.state.section.flip = !this.state.section.flip;
    this.syncSection();
    this.draw();
  }

  syncSection() {
    if (!this.sectionBox) return;
    const section = this.state.section;
    for (const [axis, node] of Object.entries(this.axisButtons)) {
      const key = axis === "null" ? null : axis;
      node.setAttribute("aria-pressed", String(section.axis === key));
    }
    const box = this.visibleBox();
    const active = Boolean(section.axis) && Boolean(box);
    this.sectionExtra.hidden = !section.axis;
    this.sectionSlider.disabled = !active;
    this.flipButton.disabled = !active;
    this.cutOn.value = active ? 1 : 0;
    this.renderer.clippingPlanes = active ? [this.plane] : [];
    if (!active) {
      this.sectionValue.textContent = "";
      return;
    }
    const index = AXES.indexOf(section.axis);
    const low = box.min.getComponent(index);
    const high = box.max.getComponent(index);
    const fraction = high > low ? (section.value - low) / (high - low) : 0.5;
    if (this.sectionBox.getRootNode().activeElement !== this.sectionSlider) {
      this.sectionSlider.value = String(Math.round(Math.min(Math.max(fraction, 0), 1) * 1000));
    }
    this.sectionValue.textContent = `${section.axis.toUpperCase()} = ${Number(section.value.toPrecision(3))}${this.units ? ` ${this.units}` : ""}`;
    const normal = new this.THREE.Vector3().setComponent(index, section.flip ? 1 : -1);
    this.plane.set(normal, section.flip ? -section.value : section.value);
  }

  // ---- drawing -------------------------------------------------------------------------------

  draw() {
    if (this.renderer) this.renderer.render(this.scene, this.camera);
  }

  resize() {
    if (!this.renderer) return;
    const width = this.viewer.clientWidth;
    const height = this.viewer.clientHeight;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.draw();
  }

  watchSize() {
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(this.viewer);
  }

  // The background follows the page's light or dark scheme.
  paintBackground() {
    if (!this.renderer) return;
    const background = getComputedStyle(this).getPropertyValue("--ac-subtle").trim();
    this.renderer.setClearColor(new this.THREE.Color(background || "#f3f5f8"));
    this.draw();
  }

  watchScheme() {
    this.scheme = window.matchMedia("(prefers-color-scheme: dark)");
    this.onScheme = () => this.paintBackground();
    this.scheme.addEventListener("change", this.onScheme);
    this.paintBackground();
  }

  /** Free every GPU resource and listener; the next ``render`` builds again. */
  teardown() {
    if (!this.renderer) return;
    this.disposed = true;
    if (this.observer) this.observer.disconnect();
    if (this.scheme) this.scheme.removeEventListener("change", this.onScheme);
    this.controls.dispose();
    for (const entry of this.entries) this.removeEntry(entry);
    this.entries = [];
    this.clearSprites();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer = this.controls = this.observer = this.scheme = null;
    this.viewWrapper = null;
  }

  // ---- marks (SCN-07) --------------------------------------------------------------------------

  setMarking(on) {
    this.state.marking = on;
    this.markToggle.setAttribute("aria-pressed", String(on));
    this.viewer.classList.toggle("marking", on);
  }

  bindMarking() {
    let press = null;
    this.canvas.addEventListener("pointerdown", (event) => {
      press = {x: event.clientX, y: event.clientY};
    });
    this.canvas.addEventListener("pointerup", (event) => {
      const start = press;
      press = null;
      if (!start || !(this.state.marking || this.pointing)) return;
      if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > CLICK_DISTANCE) return;
      this.markAt(event);
    });
  }

  // The surface point under the pointer: only parts that are shown and not cut away.
  pick(event) {
    const THREE = this.THREE;
    const rect = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1);
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(ndc, this.camera);
    const targets = this.parts.filter((p) => this.isShown(p) && this.setting(p, "opacity") > 0.02);
    const cutting = this.cutOn.value > 0.5;
    const hits = raycaster.intersectObjects(targets.map((p) => p.object), true);
    const hit = hits.find((candidate) => !cutting || this.plane.distanceToPoint(candidate.point) >= 0);
    return hit ? {hit, ray: raycaster.ray} : null;
  }

  markAt(event) {
    const picked = this.pick(event);
    if (!picked) return;
    const {hit, ray} = picked;
    const normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
    if (normal.dot(ray.direction) > 0) normal.negate(); // face the viewer
    const marks = this.state.marks = this.state.marks || [];
    const mark = {
      point: hit.point.toArray().map(round), normal: normal.toArray().map(round),
      label: marks.length + 1, part: hit.object.userData.part.name,
    };
    marks.push(mark);
    this.addSprite(mark);
    this.draw();
    this.action("scene-mark", mark, event);
  }

  addSprite(mark) {
    const THREE = this.THREE;
    const size = (this.diagonal || 1) * 0.07;
    const sprite = markSprite(THREE, mark.label, size);
    sprite.position.fromArray(mark.point).addScaledVector(
      new THREE.Vector3(...mark.normal), size * 0.3);
    this.scene.add(sprite);
    this.markSprites.push(sprite);
  }

  restoreMarks() {
    for (const mark of this.state.marks || []) this.addSprite(mark);
  }

  clearSprites() {
    for (const sprite of this.markSprites || []) {
      this.scene.remove(sprite);
      sprite.material.map.dispose();
      sprite.material.dispose();
    }
    this.markSprites = [];
  }

  /** The one mark of a point Ask (ASK-05): it replaces every mark before it. */
  showPoint(mark) {
    this.clearMarks();
    this.state.pointed = true;
    this.state.marks = [{...mark, label: 1}];
    this.restoreMarks();
    this.draw();
  }

  hidePoint() {
    if (!this.state.pointed) return;
    this.state.pointed = false;
    this.clearMarks();
  }

  clearMarks() {
    this.state.marks = [];
    this.clearSprites();
    this.draw();
  }

  // ---- changed files (BLK-09) ---------------------------------------------------------------------

  // A part file changed: load that file again and keep the settings of its parts.
  fileChanged(path) {
    super.fileChanged(path); // the manifest
    if (!this.renderer || typeof path !== "string") return;
    for (const entry of this.entries) {
      const resolved = decodeURIComponent(new URL(entry.cfg.src, document.baseURI).pathname);
      if (resolved.endsWith("/" + path)) this.reloadEntry(entry);
    }
  }

  reloadEntry(entry) {
    if (entry.promise === null) return; // never loaded: it loads fresh when shown
    entry.promise.then(() => {
      if (entry.removed || !this.renderer) return;
      for (const part of entry.parts) this.removePartObject(part);
      if (entry.cfg.split) {
        entry.parts = [this.makePart(entry, entry.cfg.key, entry.cfg.name, entry.cfg.group)];
      }
      entry.promise = null;
      this.startLoad(entry);
    });
  }

  // ---- BLK-06 ----------------------------------------------------------------------------------------

  /** The viewer as an image, for screenshots (WebGL is not captured by snapdom). */
  async snapshot() {
    this.draw();
    return {image: this.canvas, rect: this.canvas.getBoundingClientRect()};
  }
}
