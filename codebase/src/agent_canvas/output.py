"""CLI output and exit codes (requirements 5.5).

Exit 0, 6 and 7 write one JSON object to stdout; exits 1 to 5 write one
``{"error", "message"}`` object to stderr and nothing to stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_HUB = 3
EXIT_KEY = 4
EXIT_SESSION = 5

ERROR_EXIT_CODES = {
    "failed": EXIT_FAILED,
    "usage": EXIT_USAGE,
    "hub-unreachable": EXIT_HUB,
    "unauthorised": EXIT_KEY,
    "no-session": EXIT_SESSION,
}


class CliError(Exception):
    """
    A failure that ends the command with exit code 1 to 5.

    Parameters
    ----------
    code : str
        One of ``failed``, ``usage``, ``hub-unreachable``, ``unauthorised``,
        ``no-session``.
    message : str
        Human-readable text.

    Raises
    ------
    ValueError
        If ``code`` is not one of the known error codes.
    """

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_EXIT_CODES:
            raise ValueError(f"Unknown error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def exit_code(self) -> int:
        """Process exit code belonging to ``code``."""
        return ERROR_EXIT_CODES[self.code]


def emit_result(result: dict[str, Any], exit_code: int = EXIT_OK) -> int:
    """
    Write ``result`` as one JSON line to stdout.

    Parameters
    ----------
    result : dict[str, Any]
        The result object.
    exit_code : int, optional
        Exit code to return (0, 6 or 7). Default is 0.

    Returns
    -------
    int
        ``exit_code``.
    """
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return exit_code


def emit_error(error: CliError) -> int:
    """
    Write the error object to stderr.

    Parameters
    ----------
    error : CliError
        The failure to report.

    Returns
    -------
    int
        The exit code for the error.
    """
    body = {"error": error.code, "message": error.message}
    sys.stderr.write(json.dumps(body) + "\n")
    sys.stderr.flush()
    return error.exit_code
