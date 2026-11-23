"""A malformed ``session.json`` of one session harms no other (LIFE-08, LIFE-09)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_canvas.hub import clock
from agent_canvas.hub import purge as purge_module
from agent_canvas.hub.lifetime import DAY_SECONDS

pytestmark = pytest.mark.integration


def make_session(hub, sid: str) -> Path:  # noqa: ANN001
    answer = httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/path",
        json={"project": str(hub.project_dir), "agent": "t"},
        headers=hub.key_headers,
    )
    folder = Path(answer.json()["folder"])
    (folder / "one.html").write_text("<title>one</title><p>one</p>")
    httpx.post(
        f"{hub.base_url}/api/sessions/{sid}/show",
        json={"name": "one.html", "audit": False},
        headers=hub.key_headers,
        timeout=30,
    ).raise_for_status()
    return folder


def tamper(folder: Path, change) -> None:  # noqa: ANN001
    path = folder / "session.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


SHAPES = {
    "entry-is-a-list": lambda m: m["page_meta"].update({"one.html": []}),
    "entry-is-a-string": lambda m: m["page_meta"].update({"one.html": "x"}),
    "entry-without-set-by": lambda m: m["page_meta"]["one.html"].pop("set_by"),
    "pages-is-an-integer": lambda m: m.update({"pages": 7}),
    "page-meta-is-a-list": lambda m: m.update({"page_meta": [1]}),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_life_08_f2_one_bad_session_json_leaves_the_others_alone(
    hub,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    shape: str,
) -> None:
    bad = make_session(hub, "a")
    good = make_session(hub, "b")
    httpx.post(
        f"{hub.base_url}/api/sessions/b/pages",
        json={"action": "archive", "name": "one.html"},
        headers=hub.key_headers,
    )
    tamper(bad, SHAPES[shape])
    listed = httpx.get(f"{hub.base_url}/api/sessions", headers=hub.key_headers)
    assert listed.status_code == 200
    assert "b" in {s["id"] for s in listed.json()}
    monkeypatch.setenv(clock.TEST_MODE, "1")
    monkeypatch.setenv(clock.TEST_CLOCK_OFFSET, str(31 * DAY_SECONDS))
    services = hub.app.state.services
    removed = hub.on_loop(
        lambda: purge_module.purge(services.registry)
    )
    assert "b/one.html" in removed
    assert not (good / "one.html").exists()


def test_life_08_f2_a_bad_shape_is_logged_once_and_counts_as_nothing(
    hub,  # noqa: ANN001
    caplog,  # noqa: ANN001
) -> None:
    tamper(make_session(hub, "a"), SHAPES["pages-is-an-integer"])
    registry = hub.app.state.services.registry
    for _ in range(3):
        assert registry.get("a").pages == ()
    logged = [r for r in caplog.records if "malformed" in r.getMessage()]
    assert len(logged) == 1


def test_life_08_f2_missing_keys_take_the_defaults_and_a_non_dict_entry_is_missing(
    hub,  # noqa: ANN001
) -> None:
    folder = make_session(hub, "a")
    registry = hub.app.state.services.registry
    tamper(folder, lambda m: m["page_meta"].update({"one.html": {"kind": "long-term"}}))
    entry = registry.get("a").page_meta["one.html"]
    assert entry["kind"] == "long-term" and entry["set_by"] == "default"
    assert entry["archived"] is None and entry["counted_from"]
    tamper(folder, lambda m: m["page_meta"].update({"one.html": "x"}))
    assert "one.html" not in registry.get("a").page_meta
