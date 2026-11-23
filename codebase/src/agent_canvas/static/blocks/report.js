// canvas-report: a plan, result or finding from the agent (KIND-01, KIND-06). Display only.
import { CanvasCard, headLine } from "../kinds/card.js";

export class CanvasReport extends CanvasCard {
  static kind = "report";
  static schema = {type: "plan|result|finding", title: "string!", text: "string"};

  card(config) {
    return {
      label: headLine("report", config.type), words: "from the agent",
      title: config.title, text: config.text,
    };
  }
}
