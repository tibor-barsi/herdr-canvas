#!/bin/bash
# Run pytest in its own systemd scope, capped at TASKS processes plus threads.
#
# Tests then cannot use up the task limit of the terminal they run in (which
# killed herdr and every pane in it, 2026-11-08). The fixed unit name lets only
# one run exist at a time: a second call fails at once with "unit already exists".
#
# Usage (in codebase/): scripts/gate.sh [pytest args]; no args = the commit gate.
set -u
TASKS=${GATE_TASKS:-6000}
cd "$(dirname "$0")/.."
[ $# -eq 0 ] && set -- -q
# Without a -m of its own, never let e2e tests in (a bare -q once ran them, 2026-11-11).
case " $* " in *" -m "*) ;; *) set -- -m "not e2e" "$@" ;; esac
exec systemd-run --user --scope --collect --quiet --unit=agent-canvas-gate \
    -p TasksMax="$TASKS" uv run pytest "$@"
