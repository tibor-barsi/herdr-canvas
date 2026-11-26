"""The guide teaches the pooled model, not project pages (POOL-08, POOL-10)."""

from __future__ import annotations

import argparse
import asyncio
import io
from contextlib import redirect_stdout

import pytest
from mcp import Client

from agent_canvas.cli import build_parser, main
from agent_canvas.guide_text import core_text, guide_text
from agent_canvas.mcp_server import INSTRUCTIONS, create_server
from helpers import PLUGIN_DIR

pytestmark = pytest.mark.unit

SKILL = PLUGIN_DIR / "skills" / "agent-canvas" / "SKILL.md"
SPELLINGS = ("project page", "project-page", "project_page", "--project-page")


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_pool_08_core_names_the_pool_rules_within_1300_characters() -> None:
    core = core_text()
    assert len(core) <= 1300, len(core)
    text = " ".join(core.split())
    for phrase in (
        "belong to the project", "page list", "NAME.TAG.draft.html",
        "read the current page", "never copy", "specific names",
    ):  # fmt: skip
        assert phrase in text, phrase


def mcp_texts() -> list[str]:
    async def listed() -> list[str]:
        async with Client(create_server()) as client:
            tools = (await client.list_tools()).tools
            return [INSTRUCTIONS] + [
                f"{t.name} {t.description} {t.input_schema}" for t in tools
            ]

    return asyncio.run(listed())


def help_texts() -> list[str]:
    """The help of every command and subcommand of the command line."""
    texts: list[str] = []
    pending = [build_parser()]
    while pending:
        parser = pending.pop()
        texts.append(parser.format_help())
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())
    return texts


def test_pool_10_guide_skill_cli_and_mcp_never_mention_project_pages() -> None:
    guide_out = io.StringIO()
    with redirect_stdout(guide_out):
        assert main(["guide"]) == 0
        assert main(["guide", "blocks"]) == 0
    sources = {
        "guide": guide_text(),
        "guide output": guide_out.getvalue(),
        "skill": SKILL.read_text(),
        "cli help": "\n".join(help_texts()),
        "mcp": "\n".join(mcp_texts()),
    }
    # Positive controls: each source was read, and the guide names `page list`.
    assert all(len(text) > 500 for text in sources.values()), sources.keys()
    assert "page list" in flat(sources["guide"])
    assert "page list" in flat(sources["skill"])
    assert "--archived" in sources["cli help"]
    assert "session_path" in sources["mcp"]
    for name, text in sources.items():
        for spelling in SPELLINGS:
            assert spelling not in flat(text), (name, spelling)
