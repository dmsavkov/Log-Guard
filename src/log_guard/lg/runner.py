"""Subprocess execution for lg run.

Two execution modes:
- run_exec  (default): argv list, shell=False. No quoting loss, no injection.
  `list -> " ".join -> shell=True` was the original bug: quotes around
  arguments like `python -c "import a, b"` were lost in the string roundtrip.
- run_shell (opt-in via `lg run --shell`): raw string with pipes/&&/redirects.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass

from log_guard.io_config import subprocess_env

COMMAND_TIMEOUT_SEC = 300


@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def _decode(stream: str | bytes | None) -> str:
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream or ""


def run_exec(argv: list[str], *, timeout: int = COMMAND_TIMEOUT_SEC) -> RunResult:
    """Execute an argv list directly (shell=False) — the default for lg run.

    The list is passed unchanged to CreateProcess (Windows) / execvp (POSIX),
    so arguments containing spaces, commas, or quotes survive intact.
    """
    if os.name == "nt":
        from log_guard.lg.runner_windows import resolve_windows_argv

        argv = resolve_windows_argv(argv)
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=subprocess_env(),
        )
        return RunResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )
    except FileNotFoundError:
        # shell=True used to report this via the shell; with shell=False the
        # lookup fails in Python. 127 matches the POSIX "command not found" code.
        return RunResult(
            stdout="",
            stderr=(
                f"command not found: {argv[0]}"
                " (shell builtins like echo/dir need `lg run --shell \"...\"`)\n"
            ),
            exit_code=127,
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr),
            exit_code=124,
            timed_out=True,
        )


def run_shell(command: str, *, timeout: int = COMMAND_TIMEOUT_SEC) -> RunResult:
    """Execute a raw shell string (shell=True) — opt-in for pipes, &&, redirects."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=subprocess_env(),
        )
        return RunResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr),
            exit_code=124,
            timed_out=True,
        )


def format_argv(argv: list[str]) -> str:
    """Display-only command string for history/meta. Never execute this."""
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def split_command_string(command: str) -> list[str]:
    """Split a single-string command into argv (UX: `lg run "python x.py"`).

    On Windows posix=False keeps backslash paths intact but retains surrounding
    quotes on tokens, so we strip them afterwards.
    """
    if os.name == "nt":
        try:
            return [_strip_quotes(tok) for tok in shlex.split(command, posix=False)]
        except ValueError:
            return _split_python_c_fallback(command)
    return shlex.split(command)


def _split_python_c_fallback(command: str) -> list[str]:
    match = re.match(r"^(python3?|py)\s+-c\s+(.*)$", command.strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"Cannot parse command: {command!r}")
    exe = match.group(1).lower()
    code = match.group(2).strip()
    if len(code) >= 2 and code[0] == code[-1] and code[0] in ("'", '"'):
        code = code[1:-1]
    return [exe, "-c", code]


def _strip_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def merge_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout.rstrip()}\n{stderr.rstrip()}\n"
    return stdout or stderr
