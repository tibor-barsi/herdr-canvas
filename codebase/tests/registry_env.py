"""A real registry in temp folders (P15.4 tests)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_canvas.hub.answers import AnswerStore
from agent_canvas.hub.registry import SessionMeta, SessionRegistry
from agent_canvas.hub.state import HubState
from agent_canvas.hub.watcher import PageHistory


@dataclass
class Env:
    """A registry with its answer store."""

    registry: SessionRegistry
    project: Path
    state_dir: Path
    answers: AnswerStore

    def add_page(
        self, session_id: str, name: str = "page.html", **fields  # noqa: ANN003
    ) -> SessionMeta | None:
        """Create the session if needed, write a page with one version and show it."""
        project, agent = str(self.project), fields.pop("agent", "opencode")
        meta, _ = self.registry.ensure(session_id, project, agent)
        folder = self.registry.folder_of(meta)
        html = fields.pop("html", f"<title>{name} title</title><p>{name}</p>")
        content = html.encode()
        (folder / name).write_bytes(content)
        PageHistory(folder).save(name, content)
        self.registry.show(session_id, name, fields.get("title"), None)
        return self.registry.get(session_id)


def make_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """Build the registry in ``tmp_path``."""
    home = tmp_path / "home"
    project = home / "proj"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    registry = SessionRegistry(state_dir, HubState(1, "k", lambda: 0.0))
    registry.load()

    def pages(sid: str) -> list[str]:
        meta = registry.get(sid)
        return list(meta.pages) if meta else []

    answers = AnswerStore(
        lambda sid: registry.folder_of(registry.get(sid)),
        pages,
        lambda sid, page: None,
    )
    return Env(registry, project.resolve(), state_dir, answers)
