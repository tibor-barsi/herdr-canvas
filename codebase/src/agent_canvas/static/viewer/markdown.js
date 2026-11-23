// Markdown viewer (VIEW-03): the file is rendered into this document's light
// DOM, so its text can be selected and commented like a page's.
//
// window.acViewer is the one interface of all viewers (4.2): kind, space,
// mount(root, url) -> the text root, update(message, morph), mounted. Markdown
// lives in page-px, so it has no coordinate conversion or crop of its own.
(() => {
  for (const href of ["/static/kit/kit.css", "/static/viewer/markdown.css"]) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }
  // A classic script of an opaque origin cannot import() a path, only a full URL.
  const rendering = import(new URL("/static/markdown-render.js", location.href).href);
  let text = null;
  let mounted = false;

  async function render(source) {
    const {renderMarkdown} = await rendering;
    const main = document.createElement("main");
    main.className = "page markdown";
    main.append(await renderMarkdown(source));
    return main;
  }

  async function mount(root, url) {
    const response = await fetch(url, {cache: "no-store"});
    if (!response.ok) throw new Error(`could not read ${url} (${response.status})`);
    text = await render(await response.text());
    root.append(text);
    mounted = true;
    document.dispatchEvent(new CustomEvent("agentcanvas:updated"));
    return text;
  }

  // A new version is morphed into the shown one, so scroll and selection stay (VIEW-08).
  async function update(message, morph) {
    await ready;
    morph.morph(text, await render(message.html));
  }

  const query = new URLSearchParams(location.search);
  query.delete("ac-view");
  const own = location.pathname + (query.size ? "?" + query : "");
  window.acViewer = {
    kind: "markdown",
    space: "page-px",
    mount,
    update,
    get mounted() { return mounted; },
    get ready() { return ready; },
  };
  const ready = mount(document.body, own);
})();
