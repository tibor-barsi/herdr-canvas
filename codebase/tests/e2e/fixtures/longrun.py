"""Fixture for the end-to-end scenarios: a long run that reports progress.

Writes ``pid`` first, then one ``PROGRESS <step>/<steps>`` line per step to
``progress.log`` (and stdout), and ``finished`` only when it ran to the end. A
run that was stopped early (SIGTERM) leaves no ``finished`` marker, which is how
the tests tell a stop from a natural end.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path


def main() -> int:
    """Run for ``--seconds`` in ``--steps`` steps inside ``--dir``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=75)
    parser.add_argument("--steps", type=int, default=10)
    args = parser.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    (args.dir / "pid").write_text(str(os.getpid()))
    with (args.dir / "progress.log").open("a", buffering=1) as log:
        for step in range(1, args.steps + 1):
            time.sleep(args.seconds / args.steps)
            line = f"PROGRESS {step}/{args.steps}"
            log.write(line + "\n")
            print(line, flush=True)
    (args.dir / "finished").write_text("done")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
