// canvas-markdown: text, `src` file or a text/markdown child, rendered with
// marked; $...$ and $$...$$ with KaTeX. Both libraries load only when used.
import { CanvasBlock, h } from "./base.js";
import { renderMarkdown } from "../markdown-render.js";

const KATEX_CSS = "/static/vendor/katex/katex.min.css";

export class CanvasMarkdown extends CanvasBlock {
  static markdownChild = true;
  static schema = {text: "string", src: "string"};

  validate(config) {
    return config.text === undefined && config.src === undefined
      ? "needs text, src or a text/markdown child" : null;
  }

  async render(config, wrapper) {
    let text = config.text;
    if (text === undefined) {
      const response = await fetch(config.src, {cache: "no-store"});
      if (!response.ok) throw new Error(`could not read ${config.src} (${response.status})`);
      text = await response.text();
    }
    const body = h("div", {class: "markdown"});
    body.append(await renderMarkdown(text));
    // The shadow tree needs the KaTeX rules too; they come from the cached file.
    const parts = [body];
    if (body.querySelector(".katex")) {
      parts.unshift(h("link", {rel: "stylesheet", href: KATEX_CSS}));
    }
    wrapper.replaceChildren(...parts);
  }
}
