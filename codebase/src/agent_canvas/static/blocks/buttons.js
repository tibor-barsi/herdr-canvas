// canvas-buttons: each press sends a `button` event and shows "Sent" for 1 s.
import { CanvasBlock, h } from "./base.js";

const SENT_MS = 1000;

export class CanvasButtons extends CanvasBlock {
  static schema = {buttons: "array!"};

  validate(config) {
    const styles = ["default", "primary", "danger"];
    for (const spec of config.buttons) {
      if (!spec || typeof spec.id !== "string" || typeof spec.label !== "string") {
        return "every button needs a string id and label";
      }
      if (spec.style !== undefined && !styles.includes(spec.style)) {
        return `button style must be one of ${styles.join(", ")}`;
      }
    }
    return null;
  }

  render(config, wrapper) {
    wrapper.replaceChildren(h("div", {class: "actions"}, ...config.buttons.map((spec) => {
      const button = h("button", {
        type: "button", class: spec.style && spec.style !== "default" ? spec.style : "",
      }, spec.label);
      button.addEventListener("click", () => {
        this.event("button", spec.id);
        button.textContent = "Sent";
        clearTimeout(button.timer);
        button.timer = setTimeout(() => { button.textContent = spec.label; }, SENT_MS);
      });
      return button;
    })));
  }
}
