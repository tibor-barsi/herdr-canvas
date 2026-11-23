"""CLI output and exit-code helpers (requirements 5.5)."""

from __future__ import annotations

import json

import pytest

from agent_canvas import output

pytestmark = pytest.mark.unit


def test_cli_exit_codes_match_table_5_5() -> None:
    assert (output.EXIT_OK, output.EXIT_FAILED, output.EXIT_USAGE) == (0, 1, 2)
    assert (output.EXIT_HUB, output.EXIT_KEY, output.EXIT_SESSION) == (3, 4, 5)


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [
        ("failed", 1),
        ("usage", 2),
        ("hub-unreachable", 3),
        ("unauthorised", 4),
        ("no-session", 5),
    ],
)
def test_cli_error_code_maps_to_exit_code(code: str, exit_code: int) -> None:
    assert output.CliError(code, "m").exit_code == exit_code


def test_cli_unknown_error_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        output.CliError("bogus", "m")


def test_cli_success_writes_one_json_object_to_stdout_only(capsys) -> None:
    assert output.emit_result({"a": 1}) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"a": 1}
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_cli_error_writes_json_to_stderr_only(capsys) -> None:
    code = output.emit_error(output.CliError("no-session", "No session id."))
    captured = capsys.readouterr()
    assert code == 5
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": "no-session",
        "message": "No session id.",
    }
