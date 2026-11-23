"""Generate ``plugin/skills/agent-canvas/SKILL.md`` from the package sources.

Usage: ``uv run python scripts/build_plugin.py`` (from ``codebase/``).

The skill body is exactly what ``agent-canvas guide`` prints, so the plugin and
the command cannot drift apart. A test compares the committed file with the
generated text; rerun this script after editing ``guide/guideline.md`` or
``guide/blocks.md``.
"""

from __future__ import annotations

from pathlib import Path

from agent_canvas.guide_text import skill_text

SKILL = Path(__file__).resolve().parents[2] / "plugin/skills/agent-canvas/SKILL.md"


def main() -> None:
    SKILL.parent.mkdir(parents=True, exist_ok=True)
    SKILL.write_text(skill_text(), encoding="utf-8")
    print(f"wrote {SKILL}")


if __name__ == "__main__":
    main()
