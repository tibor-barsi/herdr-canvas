"""Fixtures for end-to-end runs: the hub, the owner's browser, model retry.

The Playwright fixtures live with the browser tests; they are re-used here so
that a real agent talks to a real hub while a headless Chromium plays the owner.

A test marked ``fixed_model("name")`` (the opencode runs) uses that model on
every attempt and is recorded under it; the retry is the same model.

Claude Code scenarios start with ``haiku``. If the first attempt fails, the
whole test (fresh hub, fresh browser) runs once more with ``sonnet`` and both
attempts are recorded (TST-03). Set ``AGENT_CANVAS_E2E_MODEL`` to change the
first model and ``AGENT_CANVAS_E2E_LOG`` to a file to collect one JSON line
per attempt for ``docs/acceptance-report.md``.
"""

from __future__ import annotations

import json
import os
import time

import pytest
from _pytest.runner import runtestprotocol

from browser.conftest import browser, owner  # noqa: F401

MODEL_KEY = pytest.StashKey[str]()
FIRST_MODEL = os.environ.get("AGENT_CANVAS_E2E_MODEL", "haiku")
RETRY_MODEL = "sonnet"


@pytest.fixture
def claude_model(request: pytest.FixtureRequest) -> str:
    """Model alias for this attempt (``haiku``, or ``sonnet`` on the retry)."""
    return request.node.stash.get(MODEL_KEY, FIRST_MODEL)


def _record(item: pytest.Item, model: str, reports: list, seconds: float) -> None:
    failed = [r for r in reports if r.failed]
    line = {
        "test": item.name,
        "model": model,
        "result": "fail" if failed else "pass",
        "seconds": round(seconds),
        "reason": failed[0].longreprtext[-600:] if failed else "",
    }
    print(f"\nE2E-ATTEMPT {json.dumps(line)}")
    if path := os.environ.get("AGENT_CANVAS_E2E_LOG"):
        with open(path, "a") as handle:
            handle.write(json.dumps(line) + "\n")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):  # noqa: ANN201
    """Run ``retry_once`` tests once more after a failure (Claude: sonnet)."""
    if item.get_closest_marker("retry_once") is None:
        return None
    ihook = item.ihook
    ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    fixed = item.get_closest_marker("fixed_model")
    first = fixed.args[0] if fixed else FIRST_MODEL
    retry = fixed.args[0] if fixed else RETRY_MODEL
    item.stash[MODEL_KEY] = first
    started = time.monotonic()
    reports = runtestprotocol(item, nextitem=None, log=False)  # tear down fully
    _record(item, first, reports, time.monotonic() - started)
    if any(r.failed for r in reports) and (fixed or first != retry):
        item._initrequest()  # fresh fixtures for the second attempt
        item.stash[MODEL_KEY] = retry
        started = time.monotonic()
        reports = runtestprotocol(item, nextitem=nextitem, log=False)
        _record(item, retry, reports, time.monotonic() - started)
    for report in reports:
        ihook.pytest_runtest_logreport(report=report)
    ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
