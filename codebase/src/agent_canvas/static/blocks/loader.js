// Defines every block element; the hub injects this module next to the helper.
import { CanvasAlert } from "./alert.js";
import { CanvasAnimation } from "./animation.js";
import { CanvasAsk } from "./ask.js";
import { CanvasButtons } from "./buttons.js";
import { CanvasChoices } from "./choices.js";
import { CanvasCompare } from "./compare.js";
import { CanvasDecision } from "./decision.js";
import { CanvasDo } from "./do.js";
import { CanvasDocument } from "./document.js";
import { CanvasFile } from "./file.js";
import { CanvasImage } from "./image.js";
import { CanvasLive } from "./live.js";
import { CanvasMarkdown } from "./markdown.js";
import { CanvasMetrics } from "./metrics.js";
import { CanvasModel } from "./model.js";
import { CanvasPlot } from "./plot.js";
import { CanvasProgress } from "./progress.js";
import { CanvasReport } from "./report.js";
import { CanvasScene } from "./scene.js";
import { CanvasSource } from "./source.js";
import { CanvasTable } from "./table.js";
import { CanvasTextbox } from "./textbox.js";

const BLOCKS = {
  "canvas-choices": CanvasChoices,
  "canvas-buttons": CanvasButtons,
  "canvas-textbox": CanvasTextbox,
  "canvas-table": CanvasTable,
  "canvas-progress": CanvasProgress,
  "canvas-markdown": CanvasMarkdown,
  "canvas-plot": CanvasPlot,
  "canvas-image": CanvasImage,
  "canvas-model": CanvasModel,
  "canvas-scene": CanvasScene,
  "canvas-ask": CanvasAsk,
  "canvas-do": CanvasDo,
  "canvas-report": CanvasReport,
  "canvas-decision": CanvasDecision,
  "canvas-alert": CanvasAlert,
  "canvas-live": CanvasLive,
  "canvas-animation": CanvasAnimation,
  "canvas-document": CanvasDocument,
  "canvas-file": CanvasFile,
  "canvas-source": CanvasSource,
  "canvas-metrics": CanvasMetrics,
  "canvas-compare": CanvasCompare,
};

for (const [tag, block] of Object.entries(BLOCKS)) {
  if (!customElements.get(tag)) customElements.define(tag, block);
}
