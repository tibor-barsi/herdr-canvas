# agent-canvas with opencode

opencode has no Monitor tool and no hooks, so it uses the MCP tools (or the
CLI through Bash) and listens in a blocking way. Claude Code users: see
`plugin/README.md` instead.

## 1. Install the command

```sh
uv tool install <repo>/codebase
agent-canvas --help
```

## 2. Configure the MCP server

Add this to `opencode.json` (project) or `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "agent-canvas": {
      "type": "local",
      "command": ["agent-canvas", "mcp"],
      "enabled": true
    }
  }
}
```

The server starts the hub on demand. Its tools: `session_start`, `session_path`, `session_set_title`, `session_end`, `show`, `page`, `new_page`, `look`, `ask`, `result`, `wait_for_feedback`, `pending`, `comments`, `answers`, `reply_to_comment`, `comment_reply`, `comment_done`, `cleanup`. opencode does not tell the server a
session id, so the agent creates one and passes it as `session` to every tool.
`ask` and `wait_for_feedback` wait up to 300 s by default (at most 1500 s).
Measured with opencode v2.0.32 and no `timeout` in the config (its documented
default is 5000 ms): `wait_for_feedback` calls of 12 s, 75 s and 330 s all
returned normally, so the default of 300 s needs no change. If a later opencode
version cuts calls short, pass a smaller `timeout_s`, or set `"timeout"` (ms) on
the MCP entry.

## 3. Tell the agent how to use it

Put this in the project's `AGENTS.md` (or the opencode `instructions`):

```markdown
## agent-canvas
Use the agent-canvas window when a visual answer beats text (plots, comparing
options, geometry, the status of a long run).

1. At the start of the conversation run
   `agent-canvas session start --agent opencode --title "<short title>"` and
   keep the printed session id (pass it as `session` to the agent-canvas MCP
   tools, or as `--session` to the command).
2. Run `agent-canvas guide` once and follow it: where pages go, how to listen
   for feedback; `agent-canvas guide blocks` is the block reference.
3. At the start of every turn, call the `pending` tool (or
   `agent-canvas pending --session <id>`) to pick up queued feedback.
4. Call `pending` at the start of every task too, and call `answers` (tool or
   `agent-canvas answers --open`) after a `todo` event or when a Do card was open:
   the user may have ticked or answered while nothing was listening.
```

## 4. Listening for feedback without Monitor

Choose one, depending on what the agent has to do next:

- `ask` (tool, or `agent-canvas ask "Which one?" --choice A --choice B`) when
  the agent cannot go on without a decision. It blocks until the user answers.
- `agent-canvas watch --count 1 --timeout N` in the foreground: returns after
  the first feedback event or after N seconds (`watch-ended` line,
  `renew: true` means nothing came, call it again if still waiting). Give the
  Bash call a timeout above N.
- the `wait_for_feedback` tool when there is nothing else to do: returns the
  events (with screenshots as images) or `{"events": [], "ended_reason":
  "timeout"}`.

## 5. What reaches opencode and when

Feedback the user sends with "send now" reaches a waiting `ask`, `watch` or
`wait_for_feedback` at once. Feedback sent as `next-message` (or while nothing
is listening) stays queued: opencode has no prompt hook, so it reaches the
agent only through `pending`, which is why the instruction above runs it at the
start of every turn.
