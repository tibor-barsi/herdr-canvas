// canvas-alert: something the owner should notice (KIND-01, KIND-06). Display only; it
// reads "needs action" while an Ask or a Do inside it is open, else "no action needed".
import { CanvasCard, headLine } from "../kinds/card.js";

export class CanvasAlert extends CanvasCard {
  static kind = "alert";
  static schema = {title: "string!", text: "string"};

  constructor() {
    super();
    // An Ask or Do inside changed its state: redraw the words.
    this.addEventListener("agentcanvas:kind-state", (event) => {
      if (event.target === this) return;
      this._config = undefined;
      this.schedule();
    });
  }

  card(config) {
    const open = [...this.querySelectorAll("canvas-ask, canvas-do")]
      .some((part) => part.isOpen !== false);
    return {
      label: headLine("alert"), words: open ? "needs action" : "no action needed",
      title: config.title, text: config.text,
    };
  }
}
