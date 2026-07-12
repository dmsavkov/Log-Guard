"""Tests for subprocess runners: exec mode (list, shell=False) and shell mode."""

from __future__ import annotations

import sys

from log_guard.lg.runner import (
    format_argv,
    merge_output,
    run_exec,
    run_shell,
    split_command_string,
)

PY = sys.executable


# --- run_exec: the default, quoting-safe path ---


def test_exec_exit_zero():
    result = run_exec([PY, "-c", "import sys; sys.exit(0)"])
    assert result.exit_code == 0


def test_exec_exit_one():
    result = run_exec([PY, "-c", "import sys; sys.exit(1)"])
    assert result.exit_code == 1


def test_exec_preserves_commas_and_quotes():
    """The original bug: `python -c "import a, b; print('ok')"` broke via ' '.join."""
    result = run_exec([PY, "-c", "import os, sys, json; print('ok')"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"


def test_exec_arg_with_spaces_survives():
    result = run_exec([PY, "-c", "import sys; print(sys.argv[1])", "hello world  spaced"])
    assert result.stdout.strip() == "hello world  spaced"


def test_exec_arg_with_nested_quotes():
    payload = 'he said "hi" and \'bye\''
    result = run_exec([PY, "-c", "import sys; print(sys.argv[1])", payload])
    assert result.stdout.strip() == payload


def test_exec_no_shell_interpretation():
    """Shell metacharacters must be passed literally, not interpreted."""
    result = run_exec([PY, "-c", "import sys; print(sys.argv[1])", "a && echo pwned | rm"])
    assert result.stdout.strip() == "a && echo pwned | rm"
    assert "pwned" not in result.stderr


def test_exec_command_not_found():
    result = run_exec(["definitely-not-a-real-binary-xyz"])
    assert result.exit_code == 127
    assert "command not found" in result.stderr


def test_exec_timeout():
    result = run_exec([PY, "-c", "import time; time.sleep(30)"], timeout=1)
    assert result.timed_out
    assert result.exit_code == 124


def test_exec_captures_stderr():
    result = run_exec([PY, "-c", "import sys; sys.stderr.write('boom\\n')"])
    assert "boom" in result.stderr


def test_exec_unicode_output():
    result = run_exec([PY, "-X", "utf8", "-c", "print('\u00d7 \u2192 \u258f')"])
    assert "\u00d7" in result.stdout


# --- run_shell: opt-in raw string mode ---


def test_shell_pipe_works():
    quoted_py = f'"{PY}"' if " " in PY else PY
    result = run_shell(f"{quoted_py} -c \"print('needle')\"")
    assert result.exit_code == 0
    assert "needle" in result.stdout


def test_shell_exit_code():
    quoted_py = f'"{PY}"' if " " in PY else PY
    result = run_shell(f'{quoted_py} -c "import sys; sys.exit(3)"')
    assert result.exit_code == 3


def test_shell_timeout():
    quoted_py = f'"{PY}"' if " " in PY else PY
    result = run_shell(f'{quoted_py} -c "import time; time.sleep(30)"', timeout=1)
    assert result.timed_out
    assert result.exit_code == 124


# --- helpers ---


def test_format_argv_roundtrip_display():
    display = format_argv(["python", "-c", "import a, b; print('ok')"])
    assert "import a, b" in display
    # Display string must be quoted (not the lossy bare join)
    assert display != "python -c import a, b; print('ok')"


def test_split_command_string_basic():
    assert split_command_string("python script.py --flag") == [
        "python",
        "script.py",
        "--flag",
    ]


def test_split_command_string_quoted_arg():
    argv = split_command_string('python -c "print(1)"')
    assert argv[0] == "python"
    assert argv[1] == "-c"
    assert argv[2] == "print(1)"


def test_merge_both_streams():
    merged = merge_output("out\n", "err\n")
    assert "out" in merged and "err" in merged
