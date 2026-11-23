"""The drawing helper's short ``show`` wait must not outlive its call (TST speed)."""

from __future__ import annotations

import pytest

from agent_canvas.hub.routes import sessions

from .support import SCROLL_PAGE

pytestmark = pytest.mark.browser


def test_tst_studio_make_restores_the_hubs_render_wait(studio) -> None:  # noqa: ANN001
    before = sessions.RENDER_WAIT_SECONDS
    assert before == 2.0
    studio.make(SCROLL_PAGE)
    assert sessions.RENDER_WAIT_SECONDS == before
