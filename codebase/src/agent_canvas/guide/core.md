agent-canvas is the owner's window for pages you show and answers you get back. Use it when the owner mentions the canvas, when a plot, picture or document says more than text, and for questions, decisions, approvals and hand-run checklists. One-sentence answers, and one quick pick while the owner is at the keyboard, stay in the terminal.

Cards by need: a question or decision is one `canvas-ask` per question (context, `recommended`, and `default` if you can go on without it); steps the owner runs are `canvas-do` (rehearse them first); news is `canvas-report`; your own choice is `canvas-decision`; a problem is `canvas-alert`.

Loop: write `NAME.draft.html` in the folder `agent-canvas session path` prints; run `agent-canvas look NAME --draft`, read the PNG, fix every audit `error` and `warn`; run `agent-canvas show NAME --publish`; once it succeeds, tell the owner the page title. Answers come with the owner's next message (no hooks: `pending`). To get them sooner, run Monitor on `agent-canvas watch --timeout 540` (`timeout_ms` 600000); restart it on `renew`.

Don't build answer buttons, text fields or `canvas-choices` with submit for decisions, or ask about anything not visible on that page.

Full guide: `agent-canvas guide` (the skill); blocks: `agent-canvas guide blocks`.
