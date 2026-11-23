## The loop, worked through

The owner has to choose the infill for a bracket.

**Draft.** `agent-canvas session path` (MCP: `session_path`) prints
`{"session": ..., "folder": ...}`, the folder being
`<project>/.agent-canvas/<session>/`. Write `infill.draft.html` there with your
own file-writing tool (Claude Code: Write/Edit), not with shell commands such as
`cat > file` or heredocs. The owner never sees a draft.

```html
<title>Infill for the bracket</title>
<canvas-ask data-canvas-id="q-infill"><script type="application/json">
{"question": "Which infill do we print the bracket with?",
 "context": "Gyroid is stiffer in all directions; lines prints 20 % faster.",
 "options": ["gyroid", "lines"], "recommended": "gyroid"}
</script></canvas-ask>
```

**Look.** `agent-canvas look infill --draft` renders it as the owner's window
will and prints `{"png": ".../history/looks/0001.png", ..., "errors": [],
"audit": {"findings": [], "counts": {"error": 0, "warn": 0, "info": 0}}}`. Read
the PNG (MCP `look` returns it inline), fix, look again. `--section ID` shows one
element, `--full` a long page.

**Publish.** `agent-canvas show infill --publish` (MCP: `show` with `publish`)
copies the draft to `infill.html` and shows it: `{"page": "infill.html", ...,
"audit": {"summary": "no problems found", ...}, "next": "Tell the owner the page
\"Infill for the bracket\" is on the canvas. ..."}`. Do what `next` says; exit
code 1 means nothing was shown.

**The answer.** Under Monitor, `agent-canvas watch --timeout 540` prints it as
one line: `{"type": "event", "kind": "answer", "page": "infill.html", "target":
{"canvas_id": "q-infill", ...}, "value": {"question": "Which infill ...",
"form": "one", "answer": ["gyroid"], "other": null, "note": "fine, go on",
"replaces": null}, ...}`. Without a watch it comes with the owner's next
message:

```text
Feedback from the owner in the agent-canvas window:
answer q-infill (infill.html): gyroid · note: fine, go on
Act on the answers, todos and changes above, say so in your reply, and record decisions in the project's decision log.
```

## Which card for which need

1. A card is one of five kinds; choose by what you need from the owner.
   `canvas-ask`: an answer. `canvas-do`: steps the owner runs by hand (answered
   Done, Problem or Later: a `todo` event). `canvas-report`: news (plan, result,
   finding). `canvas-decision`: what you decided; the owner may change it.
   `canvas-alert`: something wrong.
   `canvas-live`: a part that updates, with its age. Plots, tables and the other
   content elements go inside a card or stand alone; only an Ask or Do may go
   inside a Report, Alert or Live card. One Ask is one question, never one
   shared answer field. An Ask or Do without `default` (what you go on with)
   waits as needs you: watch for it, or tell the owner to reply when done.
   `agent-canvas answers [--open]` lists answers; `agent-canvas answers --wait
   [ID...] --timeout N` blocks until each is answered (exit 6 at the timeout).
   Use the terminal question tool for one quick pick while the owner is at the
   keyboard, a `canvas-ask` when it needs a picture, there are several
   questions, or it can wait. The `ask` command is not the `canvas-ask` card: it
   puts one question in the window and waits. Do not make answer buttons by
   hand, write a Do `run` without `where`, or put secrets in fields (`secret:
   true` tells the owner to type it); record decisions in the project's
   decision log too.
2. Write each Ask so the owner can answer it without asking you anything: it
   states what it is about in plain words, shows or links what to look at by the
   page title the owner sees, gives a recommendation, and never refers to
   anything not on the screen.
3. Before handing the owner a checklist of Do steps to run by hand, rehearse it
   in a fresh terminal: each `run` works on its own, every file it names comes
   from a setup step, each Ask follows the step that shows what it asks about,
   in the names the owner sees. Do not change the page while the owner works.

## Writing and showing pages

A page that other sessions of the project will update (a dashboard) is a project
page: read `agent-canvas guide project-pages` before writing it.

4. Give named sections an `id`, prefer blocks to hand-written JavaScript, and
   never load anything from the internet (no CDN, no web fonts). Rewriting the
   file updates the window in place. If a write into `.agent-canvas/` is
   refused, tell the owner to add the allow rule `Edit(**/.agent-canvas/**)` to
   `~/.claude/settings.json`, then retry; do not write the page elsewhere.
5. Pass your session id as `session` to every MCP tool. Claude Code: it is in
   the SessionStart context and `AGENT_CANVAS_SESSION` is set for Bash. Others:
   `agent-canvas session start --agent <name>` (MCP: `session_start`) once.

For a PDF, Markdown file or picture `show` gives `viewer_error`: null, or
`pdf-corrupt`, `pdf-password`, `image-undecodable` or `image-too-large`.

`look` and `show` also report `audit`, an object, not a list: `findings` and
`counts`, plus a one-line `summary` in `show`; null with `--no-audit` or for a
PDF, Markdown file or picture, and `pending` or `unavailable` when the checks
did not run. Each finding has `rule`, `severity`, `message`, `where`, sometimes
a `crop` PNG; rule `interaction` flags hand-made answer controls, prose
questions, two questions in one Ask, `canvas-choices` with submit and a missing
`<title>`; its message says when it does not apply (sliders, filters and
mock-ups that only change the page are fine). Fix every `error` and `warn`
before you tell the owner the page is ready; `info` items are judgement calls.

## Design kit and page templates

`agent-canvas new NAME --template compare|results|run|geometry|cards` (MCP:
`new_page`) writes `NAME.draft.html`; replace its `(replace)` placeholders;
`new --list` describes the templates. The kit stylesheet `/static/kit/kit.css`
and its classes (`.page`, `.cards`, `.panels`, `.badge`, ...) are in
`agent-canvas guide blocks`.

## Getting feedback: ask, watch or pending

`ask` puts one question to the owner and waits (`agent-canvas ask "Which one?"
--choice A --choice B --timeout 300`; `ask --block ID` waits for a block). `result` leaves a
result card at the end of a job. `watch` streams every feedback event as a JSON
line. `pending` returns what is queued and marks it delivered.

6. With Monitor (Claude Code): load it with ToolSearch `select:Monitor`; start
   `agent-canvas watch --timeout 540` under Monitor with `timeout_ms` 600000
   (Monitor ends a watch after 10 minutes at the latest). On
   `{"type": "watch-ended", ..., "renew": true}` or when Monitor reports it
   expired, start it again; with `renew: false` do not. Act on each event line,
   say nothing otherwise. Exit code 3: start it again (it starts the hub).
   Ending a turn with a waiting question or to-do and nothing listening
   brings a one-time reminder.
7. Without Monitor (opencode and others): listen with a blocking `ask`, a
   foreground `agent-canvas watch --count 1 --timeout N`, or the
   `wait_for_feedback` tool. Run `pending` at the start of every turn.
8. Give a foreground `ask` or `watch` a Bash timeout above its own `--timeout`
   (`ask` defaults to 540 s; use `--timeout 300`, Bash 330000 ms).
9. An action that carries an `event` id was already delivered as an event. Do
   not act on it a second time.

An event has `kind` (`send`, `button`, `choice`, `text`, `answer`, `custom`),
`target`, `value`; a `send` adds `message`, `actions`, `comments` and
`screenshot` (a PNG path, look at it; null on failure, see `screenshot_error`).

## Comments, approvals and page kinds

10. Comments arrive with a send, through `watch`, `wait_for_feedback`, the prompt
   hook or `pending`, numbered, with the quote and for a marked area a picture.
   Answer each with `agent-canvas comment reply PAGE N "text"` (MCP
   `comment_reply`), `--done` once dealt with; then wait again.
   `agent-canvas comment list [PAGE]` shows what is open. A comment marked lost
   points at changed content: look again first.
   Before a large or risky change send an approval card (`ask "Use plan B?"
   --approval --details-file plan.txt`, the plan in a few numbered lines); go on
   after "approved"; after "sent-back" change the plan and ask again. At the end
   of a job leave a result card. Give a page for a question, a choice or a plan
   `--kind single-use`.
   Page kinds (`agent-canvas show NAME --kind KIND` or `page kind NAME KIND`; the
   owner wins): `single-use` (3 days after answered): questions, selections,
   options, interviews, plans; `transitional` (30 days unchanged, default): work
   in progress; `long-term`: dashboards. A line "N pages past their lifetime"
   (opencode: in `pending`, called at the start of a task) archives nothing:
   `agent-canvas page archive NAME` what is finished, `agent-canvas page extend
   NAME` or `page kind` long-term what is needed. `agent-canvas page list` shows
   expiry and `starred` (a starred page never expires and you cannot archive it); `page restore NAME` undoes an archive.
