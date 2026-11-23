# agent-canvas plugin for Claude Code

Lets Claude show you HTML pages (plots, option comparisons, geometry, run
status) in a local window and get your clicks, drawings and answers back.

The plugin ships: the MCP server (`agent-canvas mcp`), the guideline skill,
and hooks on four events (SessionStart, UserPromptSubmit, Stop, SessionEnd):
they give each session its canvas session id and hand queued feedback to
Claude with your next prompt. They are quiet: if the
canvas hub is not running they do nothing and never start it, and they never
block a prompt.

## 1. Install the `agent-canvas` command

The plugin calls the `agent-canvas` command, so it has to be on `PATH`:

```sh
uv tool install <repo>/codebase      # from this repository's codebase/ folder
agent-canvas --help                  # check
```

Without the command, the MCP server reports "agent-canvas: command not found"
with this instruction, and the hooks stay silent (SessionStart tells Claude
that the canvas is not installed).

## 2. Install the plugin

```text
/plugin marketplace add <repo>/plugin
/plugin install agent-canvas@agent-canvas-local
```

To try it for one run without installing: `claude --plugin-dir <repo>/plugin`.
Check it with `claude plugin validate <repo>/plugin --strict`.

## 3. Allow page writes (once)

Pages live in `<project>/.agent-canvas/<session>/`. Claude writes them with its
Edit/Write tools, which prompt for every file unless you allow the folder. Add
this one rule to your user settings, `~/.claude/settings.json`:

```json
{ "permissions": { "allow": ["Edit(**/.agent-canvas/**)"] } }
```

Notes:

- The rule is `Edit(...)`: it covers all of Claude's file-editing tools. A
  `Write(...)` path rule does not cover the Write tool.
- In a user settings file a leading `/` is relative to the settings file's
  directory, so the project-anchored form `Edit(/.agent-canvas/**)` only works
  in project settings (`<project>/.claude/settings.local.json`). `**/` works
  everywhere.
- Pages cannot live in `<project>/.claude/`: Claude Code refuses writes there
  in every mode except `bypassPermissions`. That is why the folder is
  `.agent-canvas/` (config key `project_dir_name`).

If a write is refused, Claude is told to ask you to add this rule.

## What Claude gets

- Tools: `session_start`, `session_path`, `session_set_title`, `session_end`, `show`, `page`, `new_page`, `look`, `ask`, `result`, `wait_for_feedback`, `pending`, `comments`, `answers`, `reply_to_comment`, `comment_reply`, `comment_done`, `cleanup`.
- The `agent-canvas` skill (the same text as `agent-canvas guide`): when to use
  the canvas, a worked example, which card for which need, how to listen for
  your feedback with Monitor. The block reference is `agent-canvas guide blocks`.
- Hooks: SessionStart (session id into the Bash environment, and the session id
  and a short core of the guide into the context, also after compaction),
  UserPromptSubmit (queued feedback with screenshot paths, and a line when
  questions or to-dos are still waiting), Stop (a reminder while questions wait
  and nothing listens), SessionEnd.

The skill file is generated; edit `codebase/src/agent_canvas/guide/` and run
`uv run python scripts/build_plugin.py` in `codebase/`.

Using opencode instead of Claude Code: see `docs/opencode.md`.
