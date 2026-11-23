#!/bin/bash
# Run the herdr-canvas hub in the foreground, beside an agent-canvas hub if one runs.
#
# Own port, config and state; the session list (sessions.json) is copied from the
# agent-canvas state (when it exists) at every start, so the same canvases show, and while the fork runs
# it follows the daily list read-only (sessions added later appear; no purge). Session folders are read
# where the list says, and are shared with the daily hub.
# Overrides: HERDR_CANVAS_PORT, HERDR_CANVAS_STATE_DIR, HERDR_CANVAS_CONFIG_DIR,
# HERDR_CANVAS_DAILY_STATE (where the session list is copied from).
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
port=${HERDR_CANVAS_PORT:-27464}
state=${HERDR_CANVAS_STATE_DIR:-$HOME/.local/state/herdr-canvas}
config=${HERDR_CANVAS_CONFIG_DIR:-$HOME/.config/herdr-canvas}
daily=${HERDR_CANVAS_DAILY_STATE:-$HOME/.local/state/agent-canvas}

if [ "$port" = 27463 ] || [ "$state" = "$daily" ] || [ "$state" = "$HOME/.local/state/agent-canvas" ]; then
    echo "refusing: port or state folder is the daily hub's" >&2
    exit 1
fi

mkdir -p -m 700 "$state"
[ ! -e "$daily/sessions.json" ] || install -m 600 "$daily/sessions.json" "$state/sessions.json"
for name in projects.json removed.json; do
    [ -e "$state/$name" ] || [ ! -e "$daily/$name" ] || install -m 600 "$daily/$name" "$state/$name"
done

export AGENT_CANVAS_FOLLOW_STATE=$daily
export AGENT_CANVAS_PORT=$port
export AGENT_CANVAS_STATE_DIR=$state
export AGENT_CANVAS_CONFIG_DIR=$config
# The daily hub already notifies; the fork must not repeat each notification.
export AGENT_CANVAS_NOTIFY_COMMAND=true

echo "herdr-canvas hub: http://127.0.0.1:$port/  (state $state)"
exec uv run --project "$here" agent-canvas hub
