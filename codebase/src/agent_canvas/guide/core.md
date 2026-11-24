agent-canvas is the owner's window for pages you show and answers you get back. Use it when the owner mentions the canvas, when a plot, picture or document says more than text, and for questions, decisions, approvals and checklists. One-sentence answers and a quick pick at the keyboard stay in the terminal.

Cards: one `canvas-ask` per question or decision (`recommended`; `default` if you can go on); `canvas-do` for steps the owner runs (rehearse first); `canvas-report` news; `canvas-decision` your own choice; `canvas-alert` a problem.

Pages belong to the project: run `agent-canvas page list` first; read the current page before drafting it; change a page, never copy it; use specific names.

Loop: write `NAME.TAG.draft.html` (TAG: `agent-canvas session path`) in the folder it prints; run `agent-canvas look NAME --draft`, read the PNG, fix every audit `error` and `warn`; run `agent-canvas show NAME --publish`; once shown, tell the owner the page title. Answers come with the owner's next message (no hooks: `pending`). Sooner: Monitor on `agent-canvas watch --timeout 540` (`timeout_ms` 600000); restart on `renew`.

No answer buttons, text fields or `canvas-choices` with submit; ask only about what the page shows.

Guide: `agent-canvas guide`; blocks: `agent-canvas guide blocks`.
