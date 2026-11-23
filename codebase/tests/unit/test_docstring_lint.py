"""Docstring lint over the package (NFR-05)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from helpers import PACKAGE_DIR

pytestmark = pytest.mark.unit


def test_nfr_05_numpy_docstrings_pass_ruff_d_rules() -> None:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--select",
        "D",
        "--config",
        'lint.pydocstyle.convention = "numpy"',
        str(PACKAGE_DIR),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
