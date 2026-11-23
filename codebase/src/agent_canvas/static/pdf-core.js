// The one place that starts PDF.js under the frame's CSP (VIEW-05), shared by the PDF
// viewer and the document block. The worker is a classic `blob:` worker made from the
// vendored worker's text without its closing `export{...}` (a module worker does not
// start in the sandboxed frame, early check 12); if no worker starts, PDF.js runs in
// the page's thread. PDF scripts never run (`enableScripting: false`).
export const OPTIONS = {useSystemFonts: false, isEvalSupported: false, enableScripting: false};
export const LIB = new URL("/static/vendor/pdfjs-dist/", location.href).href;
const WORKER_WAIT_MS = 4000;

let pdfjs = null;
let workerText = null;
let useWorker = true;

/** A classic blob: worker from the vendored worker's text; rejects when it does not start. */
async function startWorker() {
  if (workerText === null) {
    const response = await fetch(LIB + "pdf.worker.min.mjs");
    if (!response.ok) throw new Error("worker file not found");
    workerText = (await response.text()).replace(/export\{[^}]*\};?\s*$/, "");
  }
  const blobUrl = URL.createObjectURL(new Blob([workerText], {type: "text/javascript"}));
  let worker;
  try {
    worker = new Worker(blobUrl);
    // The library's worker says "ready" as soon as its script has run.
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("worker did not start")), WORKER_WAIT_MS);
      worker.addEventListener("message", () => { clearTimeout(timer); resolve(); }, {once: true});
      worker.addEventListener("error", () => { clearTimeout(timer); reject(new Error("worker error")); }, {once: true});
    });
  } catch (error) {
    if (worker) worker.terminate();
    throw error;
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
  return worker;
}

/** The PDF.js library module, loaded once. */
export async function library() {
  if (!pdfjs) {
    pdfjs = await import(LIB + "pdf.min.mjs");
    pdfjs.GlobalWorkerOptions.workerSrc = LIB + "pdf.worker.min.mjs";
  }
  return pdfjs;
}

/** Destroy a document opened by ``openDocument`` and stop its worker. */
export function closeSession(old) {
  if (!old) return;
  old.doc.destroy();
  if (old.worker) old.worker.terminate();
}

/**
 * Open the PDF at ``url``. Resolves to ``{doc, worker, thread, lib}`` where ``thread`` is
 * "worker" or "page"; rejects with a ``pdfReason`` of "pdf-corrupt" or "pdf-password".
 */
export async function openDocument(url) {
  const lib = await library();
  const response = await fetch(url, {cache: "no-store"});
  if (!response.ok) throw Object.assign(new Error(`could not read ${url} (${response.status})`), {pdfReason: "pdf-corrupt"});
  const data = new Uint8Array(await response.arrayBuffer());
  let worker = null;
  if (useWorker) {
    try {
      worker = await startWorker();
    } catch (error) {
      useWorker = false;
    }
  }
  lib.GlobalWorkerOptions.workerPort = worker;
  const task = lib.getDocument({
    data, ...OPTIONS,
    standardFontDataUrl: LIB + "standard_fonts/",
    cMapUrl: LIB + "cmaps/", cMapPacked: true,
  });
  try {
    const doc = await task.promise;
    return {doc, worker, thread: worker ? "worker" : "page", lib};
  } catch (error) {
    if (worker) worker.terminate();
    throw Object.assign(error, {pdfReason: error && error.name === "PasswordException" ? "pdf-password" : "pdf-corrupt"});
  }
}
