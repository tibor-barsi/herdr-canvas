// canvas-scene loading: three.js and its addons on demand, fetching with progress,
// and parsing of STL, STEP and GLB files into three.js objects (SCN-05).
import { installImportMap, loadOcct, extensionOf } from "./model.js";

const THREE_URL = "/static/vendor/three/three.module.js";
const STL_URL = "/static/vendor/three/addons/STLLoader.js";
const ORBIT_URL = "/static/vendor/three/addons/OrbitControls.js";
const GLTF_URL = "/static/vendor/three/addons/GLTFLoader.js";

export { extensionOf };

let library = null;

/** Load three.js, the loaders and the orbit controls once; resolves to an object. */
export function loadSceneLibs() {
  if (!library) {
    installImportMap();
    library = Promise.all([
      import(THREE_URL), import(STL_URL), import(ORBIT_URL), import(GLTF_URL),
    ]).then(([THREE, stl, orbit, gltf]) => ({
      THREE, STLLoader: stl.STLLoader, OrbitControls: orbit.OrbitControls,
      GLTFLoader: gltf.GLTFLoader,
    }));
    library.catch(() => { library = null; });
  }
  return library;
}

/**
 * Fetch ``url`` as an ArrayBuffer and report ``onProgress(fraction)``; the
 * fraction is null while the size is unknown.
 */
export async function fetchBytes(url, onProgress) {
  const response = await fetch(url, {cache: "no-store"});
  if (!response.ok) throw new Error(`could not read ${url} (${response.status})`);
  const total = Number(response.headers.get("content-length")) || 0;
  if (!response.body) return response.arrayBuffer();
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    onProgress(total ? Math.min(received / total, 1) : null);
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return bytes.buffer;
}

// occt-import-js reads synchronously; one file at a time keeps the page responsive
// between files and avoids two big allocations at once.
let stepQueue = Promise.resolve();

function readStep(bytes) {
  const job = stepQueue.then(async () => {
    await new Promise((resolve) => setTimeout(resolve));
    const occt = await loadOcct();
    return occt.ReadStepFile(new Uint8Array(bytes), null);
  });
  stepQueue = job.catch(() => {});
  return job;
}

function newMaterial(THREE, colour) {
  return new THREE.MeshStandardMaterial({
    color: colour, roughness: 0.55, metalness: 0.1, side: THREE.DoubleSide,
  });
}

function stepGeometry(THREE, mesh) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position",
    new THREE.Float32BufferAttribute(mesh.attributes.position.array, 3));
  if (mesh.attributes.normal) {
    geometry.setAttribute("normal",
      new THREE.Float32BufferAttribute(mesh.attributes.normal.array, 3));
  }
  geometry.setIndex(Array.from(mesh.index.array));
  if (!mesh.attributes.normal) geometry.computeVertexNormals();
  return geometry;
}

// Names of the STEP tree nodes by mesh index (product or label names).
function stepNodeNames(root) {
  const names = new Map();
  const walk = (node) => {
    for (const index of node.meshes || []) {
      if (node.name && !names.has(index)) names.set(index, node.name);
    }
    (node.children || []).forEach(walk);
  };
  if (root) walk(root);
  return names;
}

async function parseStep(THREE, bytes, src, split) {
  const result = await readStep(bytes);
  if (!result.success || !result.meshes.length) {
    throw new Error(`${src} is not a STEP file this viewer can read`);
  }
  const names = stepNodeNames(result.root);
  const solids = result.meshes.map((mesh, index) => {
    const colour = mesh.color ? new THREE.Color(...mesh.color) : null;
    const object = new THREE.Group();
    const piece = new THREE.Mesh(stepGeometry(THREE, mesh), newMaterial(THREE, colour));
    piece.material.userData.native = Boolean(colour);
    object.add(piece);
    return {name: mesh.name || names.get(index) || null, object};
  });
  if (split) return solids;
  const object = new THREE.Group();
  for (const solid of solids) object.add(...solid.object.children);
  return [{name: null, object}];
}

async function parseGlb(lib, bytes) {
  const gltf = await new lib.GLTFLoader().parseAsync(bytes, "");
  gltf.scene.traverse((node) => {
    if (!node.isMesh) return;
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    for (const material of materials) {
      material.side = lib.THREE.DoubleSide;
      material.userData.native = true;
    }
  });
  return [{name: null, object: gltf.scene}];
}

function parseStl(lib, bytes) {
  const geometry = new lib.STLLoader().parse(bytes);
  const mesh = new lib.THREE.Mesh(geometry, newMaterial(lib.THREE, null));
  const object = new lib.THREE.Group();
  object.add(mesh);
  return [{name: null, object}];
}

/**
 * Parse a loaded file into solids ``[{name, object}]``: one solid for STL,
 * GLB and an unsplit STEP file, one per solid of a split STEP file. Throws a
 * readable error for empty or broken files.
 */
export async function parseFile(lib, src, bytes, split) {
  const extension = extensionOf(src);
  let solids;
  if (extension === ".stl") solids = parseStl(lib, bytes);
  else if (extension === ".glb") solids = await parseGlb(lib, bytes);
  else solids = await parseStep(lib.THREE, bytes, src, split);
  for (const solid of solids) {
    let triangles = 0;
    solid.object.traverse((node) => {
      if (node.isMesh) triangles += node.geometry.attributes.position?.count || 0;
    });
    if (!triangles) {
      disposeObject(solid.object);
      throw new Error(`${src} contains no triangles`);
    }
  }
  return solids;
}

/** Free the GPU resources (geometry, materials, textures) below ``object``. */
export function disposeObject(object) {
  object.traverse((node) => {
    if (node.geometry) node.geometry.dispose();
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    for (const material of materials) {
      if (!material) continue;
      for (const value of Object.values(material)) {
        if (value && value.isTexture) value.dispose();
      }
      material.dispose();
    }
  });
}
