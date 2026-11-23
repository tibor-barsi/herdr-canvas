# herdr-canvas

Local canvas where coding agents show HTML pages beside the Herdr desktop app and
receive feedback. A prototype derived from agent-canvas; the package, command and
file names are still `agent_canvas` / `agent-canvas`.

## Layout

- `codebase/` uv project (src layout, package `agent_canvas`, script `agent-canvas`)
  - `src/agent_canvas/static/vendor/` vendored browser libs, `MANIFEST.json` with
    SHA-256 per file; regenerate only via `scripts/vendor.py` (pinned versions)
  - `src/agent_canvas/static/blocks/` block elements (`base.js` runtime, `style.js`
    shared stylesheet); `src/agent_canvas/guide/blocks.md` agent reference of the blocks
  - `src/agent_canvas/files_safe.py` every file write (temporary file, rename), set-aside of damaged files and the session-folder names; no other module writes this way
  - `src/agent_canvas/keyprofiles/` shipped key profiles; `static/keymap.js` the actions
  - `tests/{unit,integration,browser,e2e}/`
- Shell scripts: `static/shell.js` (tabs, frame), `static/draw.js` (send button,
  send); `static/helper.js` runs in the page (actions, keys, snapdom capture)
  `static/comments-layer.js` (loaded by the helper: rectangle gesture, markers, picture)
  and `static/comments.js` + `comments.css` (comment box and panel in the shell; the
  comment text never goes into the frame) driven by `static/comment-feature.js`;
  the messages between page, window and hub are one table per direction (`Map`s in
  `shell.js` and `helper.js`, `hub/messages.py`, `SHELL_MESSAGES` in
  `hub/routes/sockets.py`); `static/render.js` renders a page in a hidden frame for
  `look` (shell and headless host page `static/render.html`); drafts are
  `NAME.draft.html` (`drafts.py`), looks go to `history/looks/`
  (`hub/looks.py`, `hub/headless.py`)
- `plugin/` Claude Code plugin (its `SKILL.md` is generated: edit
  `src/agent_canvas/guide/guideline.md` or `blocks.md`, then
  `uv run python scripts/build_plugin.py`); `docs/` install and opencode notes

## Commands (run in `codebase/`, uv only)

- `uv sync` install; `uv run agent-canvas --help`; `scripts/run-beside.sh` runs a hub
  beside an agent-canvas hub (own port 27464, state and config)
- `scripts/gate.sh` the commit gate (`pytest -m "not e2e"`: unit, integration, browser, lint);
  other pytest arguments go after it (`scripts/gate.sh -n 0 tests/unit`). Always run
  tests through it: it caps them at 6000 processes plus threads in their own systemd scope
  and allows one run at a time (a second plain call fails with "unit already exists";
  queue runs with `flock /tmp/ac-gate.lock scripts/gate.sh ...`). It runs on up to 20
  pytest-xdist workers (about 2 min); `-n 0` runs serially.
- Timing tests (marker `timing`, wall-clock budgets) run serially:
  `scripts/gate.sh -m timing -n 0 -q`
- `uv run pytest -m e2e -k <name>` end-to-end (needs claude or opencode), never in the gate
- `uv run ruff check .` / `uv run ruff format .`
- If headless Chromium fails on missing `.so` files, see `tests/browser/conftest.py`;
  after a Playwright upgrade run `uv run playwright install chromium-headless-shell`.

## Conventions

- Tests first; requirement IDs in test names (`test_hub_05_...`); markers
  `unit integration browser e2e`.
- NumPy-style docstrings on public code (ruff `D`, enforced by a test).
- No CDN or network use in the package or tests (browser tests guard origins).
- Do not edit vendored files by hand.
- Anything that can be clicked or done with the mouse must also be possible with the
  keyboard, and its key shows in the `?` overview. A new action goes into
  `static/keymap.js` (scope, group, text) and into
  `src/agent_canvas/keyprofiles/herdr.toml` (its key); nothing else names keys.
- Key profiles: `keyprofiles/<name>.toml` (shipped: `herdr`, `vim`) and the user's
  `<config dir>/keys/<name>.toml` are files with `description` and a `[keys]` table
  (`"action" = ["Ctrl+Alt+ArrowLeft", ...]`; an action a profile leaves out keeps the
  `herdr` key). The chosen profile (`profile = "name"`) and the user's own changes
  (`[keys]`) are `<config dir>/keys.toml`, written by the `?` overview through
  `POST /api/keys`; a shipped profile is never edited.
