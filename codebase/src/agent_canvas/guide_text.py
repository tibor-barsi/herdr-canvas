"""The agent guideline text shared by ``agent-canvas guide`` and the plugin skill.

The text is ``guide/core.md`` (the always-on core, also given by the SessionStart
hook and the MCP server instructions) followed by ``guide/guideline.md``; the
block reference ``guide/blocks.md`` is printed by ``agent-canvas guide blocks``.
``scripts/build_plugin.py`` wraps the guide in the skill front matter, and a test
checks that the generated skill has not drifted (CLI-13, AGI-09, AGI-12).
"""

from __future__ import annotations

from importlib import resources

SKILL_NAME = "agent-canvas"
SKILL_DESCRIPTION = (
    "Put questions, decisions, approvals and hand-run checklists to the owner on "
    "the agent-canvas window, and show plots, options, geometry, run status and "
    "documents to comment on; the owner answers by clicking, commenting and "
    "typing, and it comes back to you as feedback. Use it when the owner says "
    '"on the canvas", "let me pick", "let me choose", "so I can comment" or "ask '
    'me", when something should be seen to be judged (a picture, a comparison, '
    "a document), when there are several questions, or when a question can wait "
    "for the owner to answer later; not for one-sentence answers, which stay in "
    "the terminal."
)


def _read(name: str) -> str:
    """Return a guide source file as text."""
    return (resources.files("agent_canvas") / "guide" / name).read_text("utf-8")


def core_text() -> str:
    """
    Return the always-on core (AGI-09).

    Returns
    -------
    str
        Markdown without a trailing newline.
    """
    return _read("core.md").strip()


def guide_text() -> str:
    """
    Return the guideline: the core followed by the instructions.

    Returns
    -------
    str
        Markdown ending with one newline.
    """
    return core_text() + "\n\n" + _read("guideline.md").strip() + "\n"


def blocks_text() -> str:
    """
    Return the block reference printed by ``agent-canvas guide blocks`` (AGI-12).

    Returns
    -------
    str
        Markdown ending with one newline.
    """
    return _read("blocks.md").strip() + "\n"


def project_pages_text() -> str:
    """
    Return the topic printed by ``agent-canvas guide project-pages`` (PROJ-14).

    Returns
    -------
    str
        Markdown ending with one newline.
    """
    return _read("project-pages.md").strip() + "\n"


def skill_text() -> str:
    """
    Return the content of ``plugin/skills/agent-canvas/SKILL.md``.

    Returns
    -------
    str
        The skill front matter followed by :func:`guide_text`.
    """
    front = f"---\nname: {SKILL_NAME}\ndescription: {SKILL_DESCRIPTION}\n---\n\n"
    return front + guide_text()
