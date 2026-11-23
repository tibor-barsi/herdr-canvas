// canvas-textbox: a field; a change -> `input` action, submit -> `text` event.
import { CanvasBlock, h } from "./base.js";

const SENT_MS = 1000;

export class CanvasTextbox extends CanvasBlock {
  static schema = {
    label: "string", placeholder: "string", multiline: "boolean", submit: "string",
  };

  render(config, wrapper) {
    const label = config.submit || "Send";
    const field = h(config.multiline ? "textarea" : "input", {
      id: "field", placeholder: config.placeholder,
      type: config.multiline ? null : "text",
    });
    field.value = this.state.text || "";
    const send = h("button", {type: "button", class: "submit"}, label);
    const sync = () => { send.disabled = field.value.trim() === ""; };
    const submit = () => {
      if (field.value.trim() === "") return;
      this.event("text", field.value);
      send.textContent = "Sent";
      clearTimeout(send.timer);
      send.timer = setTimeout(() => { send.textContent = label; }, SENT_MS);
    };
    field.addEventListener("input", () => { this.state.text = field.value; sync(); });
    field.addEventListener("change", () => this.action("input", field.value));
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !config.multiline) { event.preventDefault(); submit(); }
    });
    send.addEventListener("click", submit);
    sync();
    wrapper.replaceChildren(
      config.label ? h("label", {class: "label", for: "field"}, config.label) : null,
      field, h("div", {class: "actions"}, send),
    );
  }
}
