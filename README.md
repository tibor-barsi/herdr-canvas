# herdr-canvas

Unofficial; not affiliated with or endorsed by the Herdr project.

herdr-canvas shows the HTML pages that coding agents (Claude Code, opencode)
produce, such as plots, option comparisons and run status, in a window beside the
[Herdr](https://github.com/herdrdev/herdr) desktop app, and sends your answers
back to the agent: clicks, drawings, comments and question cards.

- The sidebar and the tabs mirror Herdr's spaces, tabs and split panes, so each
  agent's canvas page sits next to the pane it belongs to.
- Everything can be done from the keyboard, including commenting on a page. The
  `?` overview lists the keys.
- Key profiles choose the shortcuts. Two ship with the package (`herdr`, `vim`,
  in `codebase/src/agent_canvas/keyprofiles/`); your own are files
  `<config dir>/keys/<name>.toml` (config dir: `~/.config/herdr-canvas` when
  started with `scripts/run-beside.sh`, else `~/.config/agent-canvas`), and the
  chosen profile is stored in `<config dir>/keys.toml`.

Status: a prototype. It is derived from agent-canvas, a local canvas for coding
agents, and still uses its `agent-canvas` command, plugin and file names.
Expect rough edges.

## Install and run

Needs Python 3.12 or newer and [uv](https://docs.astral.sh/uv/); the Herdr
desktop app is optional (without it the herdr views stay empty).

```sh
cd codebase
uv sync
scripts/run-beside.sh   # a hub on port 27464 with its own state
# or, without the script: uv run agent-canvas hub   (port 27463)
```

`scripts/run-beside.sh` keeps its own state and configuration
(`~/.local/state/herdr-canvas`, `~/.config/herdr-canvas`) and, if an
agent-canvas state folder exists, copies its session list so the same canvases
show. `HERDR_CANVAS_PORT` and the other `HERDR_CANVAS_*` variables at the top of
the script change the defaults.

To let agents use it, install the `agent-canvas` command and the Claude Code
plugin or the opencode setup: [docs/install.md](docs/install.md),
[docs/opencode.md](docs/opencode.md).

## Layout

- `codebase/` the Python package (uv project, src layout) and its tests
- `plugin/` the Claude Code plugin
- `docs/` installation and opencode notes
- `NOTICE` third-party attributions

Tests: `cd codebase && scripts/gate.sh` (see `AGENTS.md`).

## Licence

See `LICENSE`; third-party material is listed in `NOTICE`.
