# Project pages

A project page outlives the session and is updated by other sessions of the
project: a project dashboard, a status board. Everything else stays a session
page, one-off questions, options and reports too: they are tied to one session
and should end with it.

- Before you create one, run `agent-canvas page list --project-page` and update the
  existing page. A second dashboard splits the owner's view of the project.
- Add `--project-page` to `agent-canvas session path` (where to write the file),
  `show`, `look`, `comment list|reply|done`, `answers` and `page kind|list`. MCP:
  `project_page: true`. Without it the command acts on your own session.
- After every change to the page or one of its data files, run `agent-canvas show
  --project-page NAME`. That records you as the last updater. The owner's comments
  and answers on the page go to the last updater while it runs, otherwise to the
  next session of the project; without the `show`, they reach the wrong session.
- Feedback marked `(project page NAME)` may be for a page you did not write.
  Handle it and reply with `agent-canvas comment reply --project-page NAME N
  "text"`; the owner is waiting on that page.
- The page is shared and holds other sessions' content: change your part and keep
  the rest. Drafts are shared too, so write the draft and publish it in one go; the
  last write wins and silently replaces what another session wrote in between.
- Use project pages from one machine per project at a time: the hub of each
  machine keeps its own state, so two machines diverge.
