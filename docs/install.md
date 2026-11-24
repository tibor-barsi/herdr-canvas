# Installing agent-canvas

Tested on Linux (Arch with Hyprland, Chromium). Commands assume the
repository is cloned to `~/agent-canvas`; adjust `REPO`.

```sh
REPO=~/agent-canvas
```

## 1. Install the command

```sh
uv tool install --managed-python --python 3.12 "$REPO/codebase"
agent-canvas --help          # check; the command is in ~/.local/bin
```

`--managed-python` makes uv use its own Python, never the Arch system one.
`uv tool install` ignores `uv.lock` and takes the newest versions the
`pyproject.toml` ranges allow; reinstall to pick up newer ones.

After changing the code, reinstall with
`uv tool install --reinstall --managed-python --python 3.12 "$REPO/codebase"`
(or install editable with `--editable`) and, once the service exists (step 4),
restart it so that it runs the new code: `systemctl --user restart agent-canvas`.

`agent-canvas status` starts a hub on demand (a detached process, or the
service when it is installed and enabled) and prints its state. Stop it with
`agent-canvas stop`.

## Upgrading

After pulling a newer version (#57):

1. Stop the hub with the old command (`agent-canvas stop`), or, if the service
   runs it, `systemctl --user stop agent-canvas`.
2. Reinstall the tool: `uv tool install --reinstall "$REPO/codebase"`.
3. Start new Claude Code sessions only after step 2. A plugin that is ahead of
   the installed command is harmless: its hook lines exit 0 on an unknown hook
   name, but the canvas hooks do nothing until the tool is reinstalled.

The first start of a version with pooled pages (#2) moves the pages of the old
session folders into each project's pool once, with their comments, answers and
versions; the old folders stay as they are. `agent-canvas pages migrate --project
DIR` shows what it would move, and `--yes` runs it again by hand.

If you reinstalled first, the new command refuses the old hub ("did not prove
that it holds the access key"), also for `stop`. Find the old hub with
`pgrep -af 'agent_canvas.cli hub'` and end that process by id (or
`systemctl --user stop agent-canvas`), then start the new one.

## 2. Install the Claude Code plugin

The plugin directory is its own local marketplace (`agent-canvas-local`).
These two commands were run against a scratch Claude config and worked
(Claude Code 2.1.302):

```sh
claude plugin marketplace add "$REPO/plugin"
claude plugin install agent-canvas@agent-canvas-local
```

Inside a running Claude Code session the same is
`/plugin marketplace add <REPO>/plugin` and
`/plugin install agent-canvas@agent-canvas-local`. Restart Claude Code
afterwards. Check with `claude plugin list` and
`claude plugin validate "$REPO/plugin" --strict`. To try it for one run only:
`claude --plugin-dir "$REPO/plugin"`.

## 3. Permission rules (`~/.claude/settings.json`)

Required (PLG-03a): one rule so that Claude's page writes into
`<project>/.agent-canvas/` do not prompt for every file:

```json
{ "permissions": { "allow": ["Edit(**/.agent-canvas/**)"] } }
```

`Edit(...)` covers the Write tool as well; a `Write(...)` path rule does not.
In a user settings file a leading `/` is relative to the settings file's
directory, so `Edit(/.agent-canvas/**)` works only in project settings; `**/`
works everywhere. Pages cannot live in `.claude/` (Claude Code refuses writes
there), which is why the folder is `.agent-canvas/`.

Optional, to avoid prompts for the tool calls themselves:

```json
{
  "permissions": {
    "allow": [
      "Edit(**/.agent-canvas/**)",
      "Bash(agent-canvas:*)",
      "mcp__plugin_agent-canvas_agent-canvas"
    ]
  }
}
```

The last entry allows every tool of the plugin's MCP server. The name follows
Claude Code's pattern `mcp__plugin_<plugin>_<server>`; with Claude Code 2.1.302
the tools are called `mcp__plugin_agent-canvas_agent-canvas__show` and so on
(seen in the stream-json output of the acceptance runs), and this entry, without
a tool suffix, allowed all of them in default permission mode.

## 4. Run the hub as a service

```sh
agent-canvas install-service --print      # show the unit, change nothing
agent-canvas install-service              # write it, enable and start it
agent-canvas install-service --no-enable  # write it only
```

`install-service` writes `~/.config/systemd/user/agent-canvas.service`, then
runs `systemctl --user daemon-reload` and `systemctl --user enable --now
agent-canvas`. A hub you started by hand (or that `status` started) would hold
the port, so `install-service` stops it first; `agent-canvas stop` does the same
by hand. If the service already runs, it is restarted to pick up the new unit.
Run it from the installed tool, not with `uv run` inside `codebase/`: it warns
when the command it found is in a `.venv`.

The unit:

- `After=` / `PartOf=` / `WantedBy=graphical-session.target`. Omarchy starts
  Hyprland through uwsm, which imports the session environment
  (`WAYLAND_DISPLAY`) into the systemd user manager and then activates
  `graphical-session.target`. A hub started by `default.target` at login could
  run before that and never see `WAYLAND_DISPLAY`, so Chromium would not open.
- `Restart=always`, `RestartSec=1`. uvicorn exits cleanly on SIGTERM, which
  `on-failure` would not restart.
- `KillMode=process`: stopping or restarting the hub does not kill other
  processes in its group.

**The window must not die with the hub.** A Chromium started by the hub inside
the service's group would be the main process of all your Chromium windows and
would be killed by every `systemctl --user restart agent-canvas`. So the hub
starts the window outside its group: through `systemd-run --user --collect --`
if that exists (the window then also gets the session's current environment),
else `uwsm app --`, else as a plain detached process. If the wrapped start fails
the plain command is tried. `window_command` stays the command that is wrapped
(default `chromium --app={url}`). Change the choice in `config.toml` with
`window_wrapper = "auto" | "systemd-run" | "uwsm" | "none"`; a `window_command`
that already begins with `systemd-run` or `uwsm` is used as written.
Limitation: with `systemd-run` the hub only learns that the unit was created, not
that Chromium started, so a missing Chromium shows as `launched`.

When the unit is installed and enabled, the CLI starts a missing hub with
`systemctl --user start agent-canvas`; otherwise it starts a detached process.

Logs: `journalctl --user -u agent-canvas` and `hub.log` in the state directory.
Checks (not verified here):

```sh
# does the running hub itself see the display? (the check that matters)
tr '\0' '\n' < /proc/$(systemctl --user show -p MainPID --value agent-canvas)/environ | grep -i wayland
# is the browser outside the hub's group? after the first `show`:
systemd-cgls --user-unit agent-canvas.service    # only the hub should be listed
```

`systemctl --user show-environment` is not that check: it shows the user
manager's environment now, which can have the variable although the hub, which
got its environment when it started, does not.

## 5. Hyprland window rule

The canvas window should open without taking keyboard focus from the terminal
or editor where you are typing, and sit where you want it.

**Check first.** The Hyprland version and its rule syntax could not
be verified here; the versions below come from reading the Hyprland wiki
("Window Rules"), not from your machine. Omarchy ships its own
`~/.config/hypr/hyprland.conf` that sources Omarchy defaults, so:

```sh
hyprctl version                  # which Hyprland you run
ls ~/.config/hypr                # which config files exist (.conf, or .lua?)
grep -rn windowrule ~/.config/hypr ~/.local/share/omarchy/default/hypr 2>/dev/null | head
```

The last line shows rules already in use, in the syntax your installation
accepts; copy their style. Put your rule in the file Omarchy tells you to use for
your own changes (normally `~/.config/hypr/hyprland.conf` or a file it sources),
not in Omarchy's defaults.

Then find the window's class: open the canvas (`agent-canvas open`), then

```sh
hyprctl clients | grep -B2 -A12 "127.0.0.1"
# or, only class and title of every window:
hyprctl clients -j | jq -r '.[] | "\(.class)\t\(.title)"'
```

Chromium's `--app` windows get a class made from the start URL, often
`chrome-127.0.0.1__login-Default` (`chrome-<host>__<path>-<profile>`); the exact
text depends on the Chromium version, so use what `hyprctl clients` shows. A
regex that starts with `chrome-127\.0\.0\.1` separates it from ordinary
Chromium windows. Replace it below if your class differs.

**Classic hyprlang syntax** (`windowrulev2`, Hyprland before 0.53; unverified):

```ini
windowrulev2 = noinitialfocus, class:^(chrome-127\.0\.0\.1.*)$
windowrulev2 = float, class:^(chrome-127\.0\.0\.1.*)$
```

**Newer hyprlang syntax** (`windowrule` with `match:`, reported for 0.53 and 0.54;
unverified):

```ini
windowrule = no_initial_focus on, match:class ^chrome-127\.0\.0\.1.*
windowrule = float on, match:class ^chrome-127\.0\.0\.1.*
```

**Lua configuration** (reported for Hyprland 0.55 and newer; unverified, and only
if `ls ~/.config/hypr` shows a `.lua` config; a Lua file is silently ignored by a
Hyprland that reads hyprlang):

```lua
hl.window_rule({
    name = "agent-canvas",
    match = { class = "^chrome-127\\.0\\.0\\.1.*" },
    no_initial_focus = true,
    float = true,
})
```

If a rule does nothing, the syntax does not match your version: `hyprctl reload`
prints config errors, and the wiki page for your version is the authority. Drop
`float` if you prefer the canvas tiled; keep the no-initial-focus rule. Static
rules apply when a window opens, so close and reopen the canvas to test.

## 6. opencode

See `docs/opencode.md`: install the command (step 1 above), add the MCP server
to `opencode.json`, and paste the instruction block into `AGENTS.md`.

## 7. Cleaning up history

History is kept until you remove it (the hub deletes nothing by itself):

```sh
agent-canvas cleanup --older-than 30d          # dry run: lists what would go
agent-canvas cleanup --older-than 30d --yes    # delete
agent-canvas cleanup --session <id> --yes      # one session
```

Pages are never removed by `--older-than`. `--session` removes the session's
own folder and its drafts only when the session has ended; the project's pages
in the pool stay. Feedback that has not
yet reached an agent is kept unless you add `--force`; such events are listed
as `kept_queued`. `--project DIR` limits the scope.

### Pictures of pages (`agent-canvas look`)

Agents render their own page with `agent-canvas look` before they publish it.
The pictures are `history/looks/NNNN.png` in the project's pool folder; `cleanup`
removes them like sends. The open canvas window renders them (hidden, with your
fonts and colour scheme); nothing shows on screen and your tab, scroll and
draft are untouched. Without a window, or for the other colour scheme, the hub
starts a headless Chromium through Playwright: it uses `AGENT_CANVAS_BROWSER`
(path of an executable) if set, else `chromium`, `chromium-browser`,
`google-chrome` or `google-chrome-stable` on `PATH`, else the browser that
`playwright install chromium` fetches. With none of them, `look` asks the agent
to open the canvas window.

## 8. The home page: agents, hook forwarder, herdr

The home page lists your Claude Code sessions and their state (working, needs
you, done). Clicking a session opens it: in herdr (a terminal program that
splits a window into panes) if the session runs in a herdr pane, else on its
canvas tab. Two things feed the page.

- **The session list.** At start the hub reads the `*.json` files in Claude
  Code's session folder to learn which sessions already run. It never opens the
  `.key` files beside them.
- **The hook forwarder.** A hook is a command Claude Code runs on an event
  (session start, prompt, question, stop). The plugin's hooks call
  `agent-canvas hook forward`, which posts each event to the hub, so the page
  changes within a second. The forwarder also sends the `HERDR_PANE_ID`,
  `HERDR_TAB_ID`, `HERDR_WORKSPACE_ID` and `HERDR_SOCKET_PATH` variables when
  they are set, so Claude Code must run inside the herdr pane for the click to
  find the pane. Without the forwarder the page shows only what the session list
  gave at hub start.

### What the hub needs

1. **The installed `agent-canvas` must be new enough** to have `hook forward`
   (section 1; reinstall after pulling). The plugin's hook line runs
   `command -v agent-canvas >/dev/null 2>&1 || exit 0; agent-canvas hook forward`,
   so with an old command the hook fails silently and no event reaches the hub.
   Check:

   ```sh
   agent-canvas hook forward --help; echo "exit $?"
   ```

   A new command prints the usage of `hook` (listing `forward`) and `exit 0`
   (seen with this checkout's command). An old one should refuse `forward` as an
   invalid choice and exit 2 (not tried on an old command).
2. **The plugin must be enabled in Claude Code** (section 2), and Claude Code
   restarted after enabling it: the plugin's `hooks/hooks.json` carries the
   forwarder lines. Check with `claude plugin list`:
   `agent-canvas@agent-canvas-local` must be listed as enabled. Sessions started
   before the plugin was enabled probably send no events; restart them
   (not checked).

### Config keys (`config.toml`)

| Key | Default | Meaning |
|---|---|---|
| `claude_sessions_dir` | `~/.claude/sessions` | Claude Code's session list, read at hub start |
| `herdr_command` | `herdr` | the herdr executable: one program name or path, not split into words |
| `notify_hidden_projects` | `false` | `true` also sends desktop notifications for projects you hid on the home page |
| `view` in a `[home]` table | `tiles` | the home page layout, `tiles` or `lanes` (today's layout); write it as `[home]` then `view = "lanes"` (a top-level `view` or any other value is refused) |

Restart the hub after changing any of them (`systemctl --user restart agent-canvas`).

### Keyboard keys (`keys.toml`)

All shortcuts of the window are defined in one place, `src/agent_canvas/static/keymap.js`
(action name, default keys, and the text shown by `?`). To change them without editing code,
write `keys.toml` in the folder of `config.toml` (`~/.config/agent-canvas/`). Reload the window
afterwards; the hub does not need a restart. `?` always shows the keys now in force.

```toml
profile = "vim"          # optional; leave out for the default keys

[keys]
"tab.next" = "n"                      # one key
"home.up" = ["k", "ArrowUp"]          # several keys for one action
"send.next" = "Ctrl+Shift+Enter"      # modifiers in front
```

A key is the browser's key name (`a`, `[`, `?`, `ArrowUp`, `Escape`, `Enter`, `F10`). Letters are
case-sensitive: the defaults list both `h` and `H`. Action names are the left column of
`keymap.js` (`window.home`, `tab.prev`, `tab.next`, `update.next`, `comment.toggle`, `comment.text`,
`home.up`, `menu.open`, ...). An entry with an unknown action or a bad key is skipped and named in
a notice and at the bottom of `?`; a file that is not valid TOML is skipped as a whole. Two actions
on the same key are not checked.

The vim profile (`profile = "vim"`) changes: `H` and `L` previous and next tab, `0` Home, and on the
home view `j` `k` `h` `l` for Down, Up, Left, Right (the arrows keep working). In comment mode `L`
is the lasso. Everything else keeps its default key. Enter, Space, Tab, Esc in text fields and the
resizer arrows are not shortcuts and cannot be changed.

### herdr and Hyprland

On a click the hub runs `herdr agent get <pane>` (is the pane a Claude Code
agent?), then `herdr agent focus <pane>`, then raises the terminal window that
holds herdr with `hyprctl dispatch`. `herdr agent focus` alone switches the pane
but leaves the window behind (seen
on Hyprland 0.56.2). Notes:

- **Start the hub from the desktop session.** `hyprctl` finds Hyprland through
  the variable `HYPRLAND_INSTANCE_SIGNATURE`, which the hub inherits from
  whatever started it. A hub without it still focuses the pane but raises no
  window. Check what the running service sees (this prints only 1 or 0, not a
  value):

  ```sh
  tr '\0' '\n' < /proc/$(systemctl --user show -p MainPID --value agent-canvas)/environ | cut -d= -f1 | grep -c '^HYPRLAND_INSTANCE_SIGNATURE$'
  ```

  `1`: the hub has it. `0`: restart the service from a terminal of the desktop
  session.
- **One herdr client only.** The window is found from the single running
  `herdr` client process. With two such processes (two terminals running
  herdr, or a herdr command you run at that moment) the pane is focused and no
  window is raised (by design).
- **After `/clear` or a restart in the same pane**, the first click can fall
  back to the canvas tab until the session sends its next event, because the
  hub gives the pane to the newest event.
- **Do not start the hub from inside a herdr pane.** It would inherit that
  pane's `HERDR_SOCKET_PATH` and use it for events that carry none.
- The window raise uses the Hyprland 0.56 syntax
  `hl.dsp.focus({ window = "pid:<pid>" })`; the old `focuswindow` form failed on
  that version.

## 9. The interaction kinds and `answers`

A page can hold cards of five kinds: Needs you (`canvas-ask`, a question with
one answer, and `canvas-do`, a task only you can do), Report (`canvas-report`),
Decision (`canvas-decision`), Alert (`canvas-alert`) and Live (`canvas-live`).
An agent writes them into its page; the canvas draws them with one look in
pages and in the shell's question, approval and result cards. Nothing to install:
the kinds ship with the command and the plugin (sections 1 and 2).

- **Only open Asks and Dos pulse**, with a soft glow; with the system setting
  "reduce motion" nothing animates and a static mark shows instead.
- **Answers stay.** What you answer, tick or put off is stored by the hub per
  page element, so the answered line is drawn again after a reload and after a
  hub restart. Changing an answer replaces the earlier one.
- **Copy** on a Do step puts exactly the step's command on the clipboard, through
  the canvas shell. The canvas never runs a command; there is no Run button.
- **`agent-canvas answers`** is how an agent reads the answers. It lists the
  answers to the cards in the shown pages and does not consume them; listing
  them marks them "read by the agent" in your window. `--page P` limits it to
  one page, `--open` to open Asks and Dos, and `--wait [ID ...]` waits until each
  ID (none: each item that waits for you) is answered, exit 6 at `--timeout`
  seconds. An Ask with a `default` goes on with it and does not count as waiting.
- **The "For you N" button** on the home page lists the open Asks and Dos of all
  sessions; a click opens the page at the element.

## 10. Comments, files and page kinds

Nothing to install: the comment layer, the Markdown, PDF and picture viewers and
the page kinds ship with the command and the plugin (sections 1 and 2).

- **PDF viewer.** The PDF library `pdfjs-dist` 4.10.38 (Apache-2.0) is vendored in
  the package, with its licence and SHA-256 in
  `src/agent_canvas/static/vendor/MANIFEST.json`. No network or CDN is used. Do
  not edit or update it by hand: new versions only through
  `scripts/vendor.py` (the pinned version stays 4.10.38 because 5.x needs
  `import.meta` in the worker, which the sandboxed frame does not allow).
  No PDF script ever runs.
- **Comment keys.** `C` turns comment mode on and off; in comment mode `T` text,
  `P` point, `R` rectangle, `L` lasso, `X` marks the selected comment done or
  reopens it, `Esc` closes the box, then leaves the mode. In the box `Enter`
  saves and `Shift+Enter` makes a new line. `Ctrl+Enter` sends ("Send now"),
  `Ctrl+Shift+Enter` is "Add to next message". The keys are ignored while a text
  field has focus. The panel shrinks to a thin strip when comment mode is off and
  the page has nothing open.
- **Opening files.** Besides pages an agent shows (`agent-canvas show NAME`,
  `show --copy SRC`), you can open a file yourself: "+ Open file…" under a
  session's files in the tab column, or drop a file on the window. Dropped on a
  session in the tab column it goes to that session; dropped elsewhere a dialog
  lists the sessions that have not ended and `Enter` confirms. Allowed types:
  Markdown (`.md`, `.markdown`), PDF, pictures (`.png`, `.jpg`, `.jpeg`, `.gif`,
  `.webp`, `.svg`) and HTML; the limit is 64 MB. A name already in use gets `-2`,
  `-3` before its extension.
- **Page kinds.** Every page is `single-use` (expires 3 days after it was
  answered or changed), `transitional` (30 days after the last change; the
  default) or `long-term` (never). Set it with `show --kind KIND`, `page kind
  NAME KIND`, or a right click on the page's tile on the home page (your choice
  wins over the agent's). An expired page is never archived by itself: its agent
  is told at its next prompt (once in 24 h), `page extend NAME` restarts the
  clock, `page archive NAME` and `page restore NAME` (or the tile menu and the
  "Archive" button on the home page) archive and restore; 30 days after archiving
  a page is deleted.
