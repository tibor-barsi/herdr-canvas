// The one Markdown renderer of the Markdown viewer and the canvas-markdown
// block (VIEW-03): marked and KaTeX, then a cleaning step on an inert document
// before any node enters a live one. Both libraries load only when used.
const KATEX_CSS = "/static/vendor/katex/katex.min.css";
const KATEX_JS = "/static/vendor/katex/katex.min.js";
const MARKED_JS = "/static/vendor/marked/marked.esm.js";

// Code (left alone), then $$display$$, then $inline$. An inline formula may not
// start or end with a space or be followed by a digit, so "$5 and $6" is text.
const MATH = /(```[\s\S]*?```|`[^`\n]*`)|\$\$([\s\S]+?)\$\$|\$(?![\s$])([^$\n`]*?[^\s$`])\$(?!\d)/g;

const FORBIDDEN = "script, iframe, object, embed, meta, link, base";
const URL_ATTRIBUTES = ["href", "src", "xlink:href", "action", "formaction"];
const SAFE_PROTOCOLS = ["http:", "https:", "mailto:"];

/** True if the browser itself would read ``value`` as a safe address (VIEW-03). */
function safeUrl(element, name, value) {
  let url;
  try {
    // The URL parser drops tabs, newlines and leading blanks as the browser does.
    url = new URL(value, document.baseURI);
  } catch {
    return false;
  }
  if (SAFE_PROTOCOLS.includes(url.protocol)) return true;
  return url.protocol === "data:" && element.localName === "img" && name === "src"
    && /^data:image\/(png|gif|jpeg|webp|svg\+xml)[;,]/i.test(url.href);
}

/** Replace formulas by placeholders; return the new text and the formulas. */
export function extractMath(text) {
  const formulas = [];
  const replaced = text.replace(MATH, (match, code, display, inline) => {
    if (code) return match;
    formulas.push({tex: display === undefined ? inline : display, display: display !== undefined});
    return `ACMATH${formulas.length - 1}X`;
  });
  return {text: replaced, formulas};
}

let katexLoading = null;

function loadKatex() {
  katexLoading ||= new Promise((resolve, reject) => {
    // @font-face only works in the document scope, so the document needs the rules too.
    if (!document.head.querySelector(`link[href="${KATEX_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = KATEX_CSS;
      document.head.appendChild(link);
    }
    const tag = document.createElement("script");
    tag.src = KATEX_JS;
    tag.onload = resolve;
    tag.onerror = () => reject(new Error("could not load " + KATEX_JS));
    document.head.appendChild(tag);
  });
  return katexLoading;
}

/** Render Markdown text to an HTML string; raw HTML in it is kept as written. */
export async function markdownToHtml(text) {
  const {text: source, formulas} = extractMath(text);
  const {marked} = await import(MARKED_JS);
  const html = marked.parse(source, {async: false});
  if (!formulas.length) return html;
  await loadKatex();
  return html.replace(/ACMATH(\d+)X/g, (_, n) => window.katex.renderToString(
    formulas[n].tex, {displayMode: formulas[n].display, throwOnError: false}));
}

/** Parse ``html`` in an inert document, clean it and return its nodes as a fragment. */
export function cleanHtml(html) {
  const inert = new DOMParser().parseFromString("<!doctype html><body>" + html, "text/html");
  for (const element of inert.body.querySelectorAll(FORBIDDEN)) element.remove();
  for (const element of inert.body.querySelectorAll("*")) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const unsafe = URL_ATTRIBUTES.includes(name) && !safeUrl(element, name, attribute.value);
      if (name.startsWith("on") || unsafe) element.removeAttribute(attribute.name);
    }
  }
  const fragment = document.createDocumentFragment();
  while (inert.body.firstChild) fragment.appendChild(document.adoptNode(inert.body.firstChild));
  return fragment;
}

/** Render Markdown text to a cleaned fragment, safe to append to the document. */
export async function renderMarkdown(text) {
  return cleanHtml(await markdownToHtml(text));
}
