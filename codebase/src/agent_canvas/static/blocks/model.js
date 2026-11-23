// canvas-model: STL (three.js STLLoader) and STEP (occt-import-js, WASM) parts
// with orbit controls and a mark mode. three.js and occt load only when a model
// is on the page (BLK-07). The camera is held in the element, so it survives
// page updates (BLK-03); the canvas exports itself for screenshots (BLK-06).
import { CanvasBlock, h, latchWheel, loadScript } from "./base.js";

const THREE_URL = "/static/vendor/three/three.module.js";
const STL_URL = "/static/vendor/three/addons/STLLoader.js";
const ORBIT_URL = "/static/vendor/three/addons/OrbitControls.js";
const OCCT_JS = "/static/vendor/occt-import-js/occt-import-js.js";
const OCCT_WASM = "/static/vendor/occt-import-js/occt-import-js.wasm";
const DEFAULT_COLOUR = "#8899aa";
const DEFAULT_HEIGHT = 320;
const CLICK_DISTANCE = 4; // px between press and release that still counts as a click
const VIEW_DIRECTION = [1, 0.8, 1.4]; // Z up, seen from the front right

let threeLibrary = null;
let occtLibrary = null;

// The addons import the bare name "three": map it to the vendored module. The
// map is added before the first addon is requested.
export function installImportMap() {
  if (document.querySelector('script[type="importmap"][data-agent-canvas-helper]')) return;
  const tag = document.createElement("script");
  tag.type = "importmap";
  tag.setAttribute("data-agent-canvas-helper", "");
  tag.textContent = JSON.stringify({imports: {three: new URL(THREE_URL, document.baseURI).href}});
  document.head.appendChild(tag);
}

function loadThree() {
  if (!threeLibrary) {
    installImportMap();
    threeLibrary = Promise.all([import(THREE_URL), import(STL_URL), import(ORBIT_URL)])
      .then(([three, stl, orbit]) => ({
        THREE: three, STLLoader: stl.STLLoader, OrbitControls: orbit.OrbitControls,
      }));
    threeLibrary.catch(() => { threeLibrary = null; });
  }
  return threeLibrary;
}

export function loadOcct() {
  if (!occtLibrary) {
    const wasm = new URL(OCCT_WASM, document.baseURI).href;
    occtLibrary = loadScript(OCCT_JS)
      .then(() => window.occtimportjs({locateFile: () => wasm}));
    occtLibrary.catch(() => { occtLibrary = null; });
  }
  return occtLibrary;
}

export function extensionOf(src) {
  const name = new URL(src, document.baseURI).pathname;
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : decodeURIComponent(name.slice(dot)).toLowerCase();
}

export const round = (value) => Number(value.toPrecision(6));

// A numbered round marker that is part of the scene, so screenshots show it.
export function markSprite(THREE, label, size) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const context = canvas.getContext("2d");
  context.fillStyle = "#e5484d";
  context.beginPath();
  context.arc(32, 32, 30, 0, Math.PI * 2);
  context.fill();
  context.lineWidth = 3;
  context.strokeStyle = "#ffffff";
  context.stroke();
  context.fillStyle = "#ffffff";
  context.font = "bold 34px sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(String(label), 32, 34);
  const material = new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(canvas), depthTest: false, depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(size, size, 1);
  sprite.renderOrder = 10;
  return sprite;
}

export class CanvasModel extends CanvasBlock {
  static schema = {src: "string!", units: "string", colour: "string", height: "number"};

  validate(config) {
    const extension = extensionOf(config.src);
    if (![".stl", ".step", ".stp"].includes(extension)) {
      return `src "${config.src}" must be an .stl, .step or .stp file`;
    }
    return config.height !== undefined && config.height < 80
      ? '"height" must be at least 80' : null;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.dispose();
  }

  applyBackground() {
    if (!this.renderer) return;
    const background = getComputedStyle(this).getPropertyValue("--ac-subtle").trim();
    this.renderer.setClearColor(new this.THREE.Color(background || "#f3f5f8"));
  }

  // ---- loading ---------------------------------------------------------------------

  async loadGroup(config, lib) {
    const {THREE, STLLoader} = lib;
    const response = await fetch(config.src, {cache: "no-store"});
    if (!response.ok) throw new Error(`could not read ${config.src} (${response.status})`);
    const buffer = await response.arrayBuffer();
    const geometries = [];
    if (extensionOf(config.src) === ".stl") {
      geometries.push({geometry: new STLLoader().parse(buffer)});
    } else {
      const occt = await loadOcct();
      const result = occt.ReadStepFile(new Uint8Array(buffer), null);
      if (!result.success || !result.meshes.length) {
        throw new Error(`${config.src} is not a STEP file this viewer can read`);
      }
      for (const mesh of result.meshes) geometries.push(this.fromStep(THREE, mesh));
    }
    const group = new THREE.Group();
    for (const {geometry, colour} of geometries) {
      if (!geometry.attributes.position || !geometry.attributes.position.count) {
        throw new Error(`${config.src} contains no triangles`);
      }
      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(config.colour || colour || DEFAULT_COLOUR),
        roughness: 0.55, metalness: 0.1, side: THREE.DoubleSide,
      });
      group.add(new THREE.Mesh(geometry, material));
    }
    return group;
  }

  fromStep(THREE, mesh) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position",
      new THREE.Float32BufferAttribute(mesh.attributes.position.array, 3));
    if (mesh.attributes.normal) {
      geometry.setAttribute("normal",
        new THREE.Float32BufferAttribute(mesh.attributes.normal.array, 3));
    }
    geometry.setIndex(Array.from(mesh.index.array));
    if (!mesh.attributes.normal) geometry.computeVertexNormals();
    const colour = mesh.color ? new THREE.Color(...mesh.color) : null;
    return {geometry, colour};
  }

  // ---- scene -----------------------------------------------------------------------

  async render(config, wrapper) {
    this.dispose();
    const lib = await loadThree();
    const group = await this.loadGroup(config, lib);
    const {THREE, OrbitControls} = lib;
    this.THREE = THREE;
    const height = config.height || DEFAULT_HEIGHT;
    this.canvas = h("canvas");
    this.viewer = h("div", {class: "viewer"}, this.canvas);
    this.viewer.style.height = `${height}px`;
    this.sizeNote = h("span", {class: "muted"});
    this.toggle = h("button", {
      type: "button", class: "mark-toggle", "aria-pressed": "false",
      onclick: () => this.setMarking(!this.state.marking),
    }, "Mark");
    this.clear = h("button", {type: "button", onclick: () => this.clearMarks()}, "Clear marks");
    wrapper.replaceChildren(this.viewer,
      h("div", {class: "toolbar"}, this.toggle, this.clear, this.sizeNote));
    this.attach(wrapper); // the renderer measures the laid-out viewer

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: true, preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.THREE = THREE;
    this.applyBackground();
    // The clear colour is read from the stylesheet, so follow a changed scheme.
    this.schemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
    this.onScheme = () => { this.applyBackground(); this.draw(); };
    this.schemeQuery.addEventListener("change", this.onScheme);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 1000);
    this.camera.up.set(0, 0, 1);
    this.scene.add(this.camera);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const light = new THREE.DirectionalLight(0xffffff, 2.2);
    light.position.set(0.4, 0.6, 1);
    this.camera.add(light);
    latchWheel(this.canvas);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.addEventListener("change", () => { this.saveView(); this.draw(); });

    this.setModel(group, true);
    this.watchSize();
    this.bindMarking();
    this.restoreMarks();
    this.setMarking(Boolean(this.state.marking));
    this.resize();
    this.viewer.classList.add("ready");
  }

  // Put ``group`` in the scene; fit the camera unless a view was kept.
  setModel(group, fit) {
    const THREE = this.THREE;
    if (this.group) this.scene.remove(this.group);
    this.group = group;
    this.scene.add(group);
    const box = new THREE.Box3().setFromObject(group);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    this.bounds = {min: box.min.toArray().map(round), max: box.max.toArray().map(round)};
    this.diagonal = size.length() || 1;
    const units = this._config.units ? ` ${this._config.units}` : "";
    this.sizeNote.textContent = size.toArray().map((v) => round(Number(v.toPrecision(4)))).join(" × ") + units;
    this.camera.near = this.diagonal * 0.01;
    this.camera.far = this.diagonal * 100;
    this.camera.updateProjectionMatrix();
    const view = this.state.view;
    if (fit && view) {
      this.camera.position.fromArray(view.position);
      this.controls.target.fromArray(view.target);
    } else if (fit) {
      const direction = new THREE.Vector3(...VIEW_DIRECTION).normalize();
      this.camera.position.copy(center).addScaledVector(direction, this.diagonal * 1.6);
      this.controls.target.copy(center);
    }
    this.controls.update();
    this.draw();
  }

  saveView() {
    this.state.view = {
      position: this.camera.position.toArray(), target: this.controls.target.toArray(),
    };
  }

  draw() {
    if (this.renderer) this.renderer.render(this.scene, this.camera);
  }

  resize() {
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

  dispose() {
    if (this.observer) this.observer.disconnect();
    this.observer = null;
    if (this.schemeQuery) this.schemeQuery.removeEventListener("change", this.onScheme);
    this.schemeQuery = null;
    if (this.controls) this.controls.dispose();
    if (this.renderer) {
      this.renderer.dispose();
      this.renderer.forceContextLoss();
    }
    this.renderer = this.controls = null;
    this.markSprites = [];
  }

  // ---- marks (BLK-05) ----------------------------------------------------------------

  setMarking(on) {
    this.state.marking = on;
    this.toggle.setAttribute("aria-pressed", String(on));
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

  markAt(event) {
    const THREE = this.THREE;
    const rect = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1);
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(ndc, this.camera);
    const [hit] = raycaster.intersectObject(this.group, true);
    if (!hit) return;
    const normal = hit.face.normal.clone();
    if (normal.dot(raycaster.ray.direction) > 0) normal.negate(); // face the viewer
    const marks = this.state.marks = this.state.marks || [];
    const mark = {
      point: hit.point.toArray().map(round), normal: normal.toArray().map(round),
      label: marks.length + 1,
    };
    marks.push(mark);
    this.addSprite(mark);
    this.draw();
    this.action("model-mark", mark, event);
  }

  addSprite(mark) {
    const THREE = this.THREE;
    const sprite = markSprite(THREE, mark.label, this.diagonal * 0.07);
    sprite.position.fromArray(mark.point).addScaledVector(
      new THREE.Vector3(...mark.normal), this.diagonal * 0.02);
    this.scene.add(sprite);
    this.markSprites.push(sprite);
  }

  restoreMarks() {
    for (const mark of this.state.marks || []) this.addSprite(mark);
    this.draw();
  }

  /** The one mark of a point Ask (ASK-05): it replaces every mark before it. */
  showPoint(mark) {
    this.clearMarks();
    this.state.pointed = true;
    this.state.marks = [{...mark, label: 1}];
    this.restoreMarks();
  }

  hidePoint() {
    if (!this.state.pointed) return;
    this.state.pointed = false;
    this.clearMarks();
  }

  clearMarks() {
    this.state.marks = [];
    for (const sprite of this.markSprites) this.scene.remove(sprite);
    this.markSprites = [];
    this.draw();
  }

  // ---- BLK-09 ------------------------------------------------------------------------

  // The file changed: swap the geometry, keep the camera and the marks.
  async reloadSource() {
    if (!this.renderer || !this._config || (this._wrapper && this._wrapper.isError)) {
      super.reloadSource();
      return;
    }
    try {
      const lib = await loadThree();
      this.setModel(await this.loadGroup(this._config, lib), false);
    } catch (error) {
      this.showError(error.message);
    }
  }

  // ---- BLK-06 ------------------------------------------------------------------------

  /** The viewer as an image, for screenshots (WebGL is not captured by snapdom). */
  async snapshot() {
    this.draw();
    return {image: this.canvas, rect: this.canvas.getBoundingClientRect()};
  }
}
