"""The guideline points to the project-pages topic, which teaches them (PROJ-14)."""

from __future__ import annotations

import pytest

from agent_canvas.cli import main
from agent_canvas.guide_text import _read, project_pages_text
from helpers import PLUGIN_DIR

pytestmark = pytest.mark.unit

POINTER = "read `agent-canvas guide project-pages` before writing it"


def flat(text: str) -> str:
    return " ".join(text.split())


def test_proj_14_the_guideline_and_the_skill_point_to_the_topic() -> None:
    skill = (PLUGIN_DIR / "skills" / "agent-canvas" / "SKILL.md").read_text()
    for text in (_read("guideline.md"), skill):
        assert POINTER in flat(text)


def test_proj_14_guide_project_pages_prints_the_topic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["guide", "project-pages"]) == 0
    assert capsys.readouterr().out == project_pages_text()


def test_proj_14_the_topic_names_the_flag_the_show_rule_and_the_shared_page() -> None:
    text = flat(project_pages_text())
    for phrase in (
        "--project-page", "project_page: true", "page list --project-page",
        "outlives the session", "agent-canvas show --project-page NAME",
        "last updater", "(project page NAME)", "comment reply --project-page",
        "change your part and keep the rest", "last write wins",
        "one machine per project",
    ):  # fmt: skip
        assert phrase in text, phrase
