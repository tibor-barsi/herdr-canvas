# Blocks (ready-made page elements)

Prefer a block to hand-written JavaScript. Write the tag with a required
`data-canvas-id` (a short unique name; it becomes the event target) and one
`<script type="application/json">` child holding the config. Blocks follow the
owner's light or dark mode and need no CSS. A wrong config shows a red error box
and is listed in the `errors` of `show`. Rewriting the file updates a block in
place: unchanged blocks keep their state (selection, sort, typed text).

```html
<canvas-ask data-canvas-id="q-design">
  <script type="application/json">
  {"question": "Which design do we print first?",
   "context": "Ribbed is lighter; lattice is stiffer.",
   "options": ["ribbed", "lattice"], "recommended": "lattice"}
  </script>
</canvas-ask>
```

A question or decision for the owner is a `canvas-ask` (see its section); the
`ask` command is the same question put in the window without writing a page.

Events (`choice`, `button`, `text`) reach you through `watch` or `ask --block ID`
(the id is the `data-canvas-id`). Actions (`select`, `input`) are context that
travels with the owner's next send; do not act on them alone.

## `canvas-choices`

Example: `<canvas-choices data-canvas-id="design"><script type="application/json">{"options": [{"id": "a", "title": "Ribbed"}, {"id": "b", "title": "Lattice"}]}</script></canvas-choices>`

This is live selection: the owner picks on the page and the pick travels with
their next send. Its submit button is not for decisions: it is not an answer
card (`answers` does not list it); use `canvas-ask` for a decision.

Config: `mode` (`single` or `multi`, default `single`), `options` (list of
`{id, title, description?, image?}`; `image` is a file in the page folder),
`submit?` (button label; without it there is no button).
Produces: owner selects -> `select` action (value: list of option ids);
presses submit -> `choice` event, `value` = list of option ids.

Use it for a live selection without `submit` (which plot to show). For a
decision you need from the owner use `canvas-ask` (form `one` or `several`);
with `submit` this block only shows "Sent", a receipt and Change.

## `canvas-buttons`

Example: `<canvas-buttons data-canvas-id="ctl"><script type="application/json">{"buttons": [{"id": "stop", "label": "Stop", "style": "danger"}]}</script></canvas-buttons>`

Config: `buttons` (list of `{id, label, style?}`; `style` is `default`,
`primary` or `danger`).
Produces: press -> `button` event, `value` = the button id (the button shows
"Sent" for one second).

## `canvas-textbox`

Example: `<canvas-textbox data-canvas-id="note"><script type="application/json">{"label": "Why?", "multiline": true}</script></canvas-textbox>`

Config: `label?`, `placeholder?`, `multiline?` (bool), `submit?` (default
"Send").
Produces: field change -> `input` action (value: the text); submit -> `text`
event, `value` = the text.

## `canvas-table`

Example: `<canvas-table data-canvas-id="runs"><script type="application/json">{"columns": ["run", "error"], "rows": [["r1", 0.2]], "key": "run", "select": "single"}</script></canvas-table>`

Config: `columns` (list of names), `rows` (list of lists), `key?` (a column name
whose value identifies a row), `select` (`none`, `single` or `multi`, default
`none`). The owner can sort by clicking a header.
Produces: row click -> `select` action, value = list of selected row keys (the
`key` column value, or the row index without `key`).

## `canvas-progress`

Example: `<canvas-progress data-canvas-id="job"><script type="application/json">{"value": 3, "max": 10, "label": "Solving", "status": "running"}</script></canvas-progress>`

Config: `value` (number), `max?` (default 1), `label?`, `status` (`running`,
`done` or `failed`, default `running`), `detail?` (small text below).
Rewrite the file to update it; the bar moves without flicker.
Long jobs: `started?`, `eta?` (ISO times), `log?` (a file in the page folder,
never elsewhere; its last 5 lines show folded and refresh when it changes) and
`stop?` (true: a Stop button while running; after "Stop the run?" and "Yes, stop"
a `button` event `stop` arrives; stop the job and rewrite `status`).

## `canvas-markdown`

Example: `<canvas-markdown data-canvas-id="notes"><script type="text/markdown">Energy $E=mc^2$ and a **list**.</script></canvas-markdown>`

Config: `text` (markdown), or `src` (a `.md` file in the page folder), or a
child `<script type="text/markdown">` with the markdown itself (no JSON needed).
`$...$` and `$$...$$` are rendered as math (KaTeX); `$5` stays text.
Display only.

## `canvas-plot`

Example: `<canvas-plot data-canvas-id="spectrum"><script type="application/json">{"data": [{"x": [1, 2, 3], "y": [2, 5, 3], "mode": "lines+markers"}], "layout": {"xaxis": {"title": {"text": "f (Hz)"}}}}</script></canvas-plot>`

Config: a Plotly figure as `data` (list of traces), `layout?`, `config?`; or
`src` (a JSON file in the page folder holding `{data, layout?, config?}`).
Axis titles are `{"text": "f (Hz)"}`: a plain string is ignored by this
Plotly version. Without `layout.width` the plot fills the block's width. Rewriting the `src`
file redraws the plot within a second, with no page reload. Plotly GL traces
(`scattergl`) appear in screenshots.
Theme: a canvas theme (fonts, colour-blind-safe colours, light grid, tight
margins, light/dark) is applied; your `layout` values win. plotly.py's default
`layout.template` (in `to_json()`) is replaced by it; `"theme": "figure"` keeps
the figure's own template. Under 2D plots an axis bar gives the owner lin/log,
min, max and autoscale per axis (`"axes": false` hides it). The owner's axis
choices and zooms survive rewrites; a new `layout.uirevision` resets them.
Produces: point click -> `plot-click` action, value `{trace, index, x, y}`;
box or lasso select (set `layout.dragmode` to `select` or `lasso`, or the owner
uses the mode bar) -> `plot-select` action, value `{points, total}` with at most
100 points. A comment on a rectangle over the plot carries `data` with the
`canvas_id` and the `x` and `y` ranges in data coordinates.

## `canvas-image`

Example: `<canvas-image data-canvas-id="photo"><script type="application/json">{"src": "photo.png", "alt": "Test part"}</script></canvas-image>`

Config: `src` (an image file in the page folder), `alt?`.
The owner zooms with the wheel, pans by dragging and resets with a double
click; the enlarge button (or Enter on the picture) opens it full-frame, Esc
closes. Rewriting the file reloads it and keeps the zoom.
Produces: click -> `image-click` action, value `{x, y}` in image pixels
(0,0 = top-left pixel of the picture, whatever the zoom).

## `canvas-model`

Example: `<canvas-model data-canvas-id="part"><script type="application/json">{"src": "bracket.step", "units": "mm", "colour": "#2a9d8f"}</script></canvas-model>`

Config: `src` (a `.stl`, `.step` or `.stp` file in the page folder),
`units?` (label shown with the size, no conversion), `colour?` (CSS hex colour;
STEP colours are used without it), `height?` (px, default 320).
The owner orbits, zooms and pans. A "Mark" toggle switches on mark mode: a
click on the surface adds a numbered marker. Rewriting the file reloads the
geometry and keeps the camera and markers. The 3D view appears in screenshots.
Produces: mark click -> `model-mark` action, value `{point, normal, label}`
(`point` in the model's own coordinates, `normal` a unit vector facing the
viewer, `label` the marker number).

## `canvas-scene`

Example: `<canvas-scene data-canvas-id="asm"><script type="application/json">{"src": "asm.json"}</script></canvas-scene>`
with `asm.json` in the page folder:
`{"units": "mm", "up": "z", "parts": [{"src": "base.stl", "group": "frame"}, {"src": "cooler.stl", "colour": "#e15759", "opacity": 0.6, "visible": false}, {"src": "asm.step", "split": true}]}`

Several parts in one view. Config: `parts` (or `src` = a manifest `.json` with
the same keys), `units?`, `height?` (px, default 480), `up?` (`"z"` default, or
`"y"`; GLB files are Y-up). Part: `src` (`.stl`, `.step`/`.stp`, `.glb`),
`name?` (default: file name), `group?`, `colour?` (CSS hex; STEP and GLB colours
are used without it), `opacity?` (0..1), `visible?` (false: not fetched until
the owner shows it), `split?` (STEP only: one part per solid, named from the
file, grouped by `group` or the file name).
The owner gets a part list (group rows and part rows with checkbox, colour and
opacity), view buttons (iso, top, front, side, reset, fit), a section plane
(X, Y or Z with slider and flip) and a Mark toggle. Parts show as they arrive;
one that fails shows its error in its row and in `errors`. Rewriting the page or
a part file keeps the owner's visibility, colours, section and camera. The 3D
view appears in screenshots.
Produces: mark click -> `scene-mark` action, value `{point, normal, label, part}`
(`part` = its name). Visibility, colour and opacity changes are not events.

## `canvas-report`

Example: `<canvas-report data-canvas-id="r1"><script type="application/json">{"type": "result", "title": "Yield at 131 MPa", "text": "Failed at 152 MPa.\n- run 7"}</script><canvas-plot ...></canvas-report>`

Config: `type?` (`plan`, `result` or `finding`, default `result`), `title`, `text?`
(shown as text, never HTML; lines starting `- ` or `1. ` become list items).
A card, display only. Child elements (plots, tables, images) go inside it.

## `canvas-alert`

Example: `<canvas-alert data-canvas-id="a1"><script type="application/json">{"title": "Bed fell to 42 C", "text": "Limit 60 C."}</script></canvas-alert>`

Config: `title`, `text?`. A card with a hazard stripe, display only; it reads
"needs action" while an Ask or Do inside it is open, else "no action needed".
No other card goes inside a card (error box); an Ask or Do may.

## `canvas-ask`

Example: `<canvas-ask data-canvas-id="q-infill"><script type="application/json">{"question": "Which infill?", "options": ["gyroid", "lines"], "recommended": "gyroid"}</script></canvas-ask>`

Config: `question` (at most 300 characters), `context?` (at most 1000), `form`
(`yesno`, `one`, `several`, `text`, `number`, `confirm` or `approve`; default
`one` with `options`, else `text`), `options` (2 to 8 strings or `{id, label,
description?, image?}`), `recommended?` (an option id, listed first), `min?`,
`max?`, `unit?`, `step?` (number), `default?` (what you go on with unless the
owner changes it: the Ask then does not count as waiting). One Ask is one
question; never put two questions in one.
Produces: `answer` event, `value` `{question, form, answer, other, note,
replaces}`; `answer` is `"yes"`/`"no"`, a list of option ids (`[]` with only an
Other), a string, a number, `"keep"` or `{"change": text}`, and for `approve`
`{"decision": "approved"}` or `{"decision": "sent-back", "reason": text}`.
The answer stays on the page (`answers`, `answers --wait`); a changed question
or options opens the Ask again. An unknown key or a `one` with one option shows
the error box.
Form `point`: put one `canvas-plot`, `canvas-image`, `canvas-model` or
`canvas-scene` inside; the owner's click there is the answer (marked, a new click
moves it): `answer` is that block's click value (`{trace, index, x, y}`, image
pixels `{x, y}`, or `{point, normal, part?}`). Form `fields` (`fields` 1 to 12 of
`{id, label, type: number|one|onoff|text, value, unit?, min?, max?, options?}`,
`submit?` label): a form with the owner's changes marked; `answer` is `{values:
{id: value}, changed: [ids]}`.

## `canvas-decision`

Example: `<canvas-decision data-canvas-id="d1"><script type="application/json">{"text": "I chose PETG", "why": "Tough enough for snap fits.", "ref": "d-mat", "date": "2026-11-09"}</script></canvas-decision>`

Config: `text`, `why?` (folded), `ref?` (id in the project's decision log), `date?`.
"Change…" takes a one-line reason (300 characters); a `change` event arrives,
`value` `{decision, reason, replaces}`, and the card shows the reason and whether
you read it. Also record the decision in the project's log.

## `canvas-live`

Example: `<canvas-live data-canvas-id="l1"><script type="application/json">{"title": "Job", "updated": "2026-11-10T12:00:00Z", "stale_after": 600}</script><canvas-progress ...></canvas-live>`

Config: `title`, `text?`, `updated?` (ISO time of the last update; rewrite it
with the content), `stale_after?` (seconds, default 600). Reads
"updated 2 min ago", counted by the page; older than `stale_after` it reads "stale since HH:MM"
and turns grey. Display only; children update in place.

## `canvas-do`

Example: `<canvas-do data-canvas-id="w1"><script type="application/json">{"title": "Re-seat the plug", "where": "work, ~/project", "steps": [{"text": "Switch off"}, {"text": "Run the check", "run": "uv run check", "expect": "exit 0"}]}</script></canvas-do>`

Config: `title`, `why?`, `where` (required when a step has `run`), `time?`, `risk?`
(list), `steps` (1 to 20: `text`, `run?`, `expect?`, `if_not?`, `secret?`) or one
`run`. Numbered steps; each `run` has a Copy button (the owner runs it in a
terminal; there is no Run button); `secret: true` tells the owner to type it
themselves. Ticks are stored, no event. Done, Problem... (a note) and Later give
a `todo` event, status `done`, `problem` or `later`, with the ticked steps.

## `canvas-animation`

Example: `<canvas-animation data-canvas-id="mode3"><script type="application/json">{"frames": ["m3-00.png", "m3-01.png", "m3-02.png"], "fps": 8, "loop": true}</script></canvas-animation>`

Config: `src` (a video in the page folder: WebM everywhere, MP4 only where the
browser has the codec) or `frames` (1 to 300 pictures, in order); `fps?` (frames
a second of a sequence, default 10; for a video only the step size, default
30), `autoplay?`, `loop?`, `speed?` (0.25, 0.5, 1, 2 or 4), `alt?`.
Starts paused on the first frame unless `autoplay: true`. Never plays sound.
Play and pause, one-frame steps, a position slider, speed and loop for the
owner. The send screenshot and `look` show the frame on screen (`look` starts
at the first). Rewriting the file reloads it and keeps the position.

## `canvas-document`

Example: `<canvas-document data-canvas-id="spec"><script type="application/json">{"src": "spec.pdf", "height": 480}</script></canvas-document>`

Config: `src` (a `.md`, `.markdown` or `.pdf` file in the page folder), `height?`
(window height in px, default 480), `title?`. The file scrolls in its own window and the
page does not grow. Markdown is cleaned as in `canvas-markdown` (no script runs); a PDF
has page-by-page drawing, zoom buttons and selectable text. "Open" shows a file of the
page folder (not a subfolder) as a page of its own. Gives no events.

## `canvas-file`

Example: `<canvas-file data-canvas-id="out"><script type="application/json">{"path": "/data/run4/result.csv", "size": "2.1 MB", "note": "Raw results"}</script></canvas-file>`

Config: `path` (absolute, required), `size?`, `date?`, `machine?`, `note?` (shown as written). Shows
a type badge, name and folder, with Copy for the path. "Open" shows only for a Markdown, PDF
or picture file directly in the page folder. Gives no events.

## `canvas-source`

Example: `<canvas-source data-canvas-id="e-mod"><script type="application/json">{"claim": "E = 70 GPa", "source": "Handbook p. 4", "status": "verified"}</script></canvas-source>`

Config: `claim`, `source` (one line, a link stays text), `status?` (`verified`, `not checked` default,
`disputed`), `quote?` (folded). The owner can Copy the source or press "Doubt this..." and
type a reason: a `text` event.

## `canvas-metrics`

Example: `<canvas-metrics data-canvas-id="kpi"><script type="application/json">{"tiles": [{"label": "Safety factor", "value": 1.8, "min": 1.5}, {"label": "Mass", "value": 412, "unit": "g", "previous": 400}]}</script></canvas-metrics>`

Config: `tiles` (1 to 12: `label`, `value`, `unit?`, `min?`, `max?`, `previous?`), `near?` (default 0.1:
fraction of a limit). The block computes the state (ok, near limit, out of limit) from value and
limits; never give a state. Shows the limit and the change from `previous` in percent.

## `canvas-compare`

Example: `<canvas-compare data-canvas-id="cmp"><script type="application/json">{"before": "a.png", "after": "b.png", "mode": "slider"}</script></canvas-compare>`

Config: `before`, `after` (pictures in the page folder), `mode?` (`side` default, or `slider`:
one over the other), `before_label?`, `after_label?`. For a verdict put it inside a `canvas-ask`.

## Design kit

For a good-looking page without writing CSS, link the shared stylesheet in
`<head>`: `<link rel="stylesheet" href="/static/kit/kit.css">` (it follows the
owner's light or dark mode). Kit classes: `.page` (wrap the body content),
`.lead`, `.muted`, `.small`, `.columns` (auto-fit), `.cols-2`, `.cols-3`
(one column below 700 px), `.stack`, `.card`, `.tiles` with `.tile` (children
`.value`, `.unit`, `.label`; add `.good`, `.warn` or `.bad`), `.callout`
(add `.info`, `.warn` or `.bad`), `figure` with `figcaption`, `details` with
`summary` for folded sections, `.scroll` around `table.data` (give number cells
`.num`), `.cards` (add `.compare` for aligned columns) of `.card` with a header
(title, `.badge` + recommended|fallback|fails|placeholder|ok|warn|bad|info),
`.tiles` and `.panels` (up to three blocks).
