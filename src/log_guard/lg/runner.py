"""Subprocess execution for lg run."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

COMMAND_TIMEOUT_SEC = 300


@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def run_shell(command: str, *, timeout: int = COMMAND_TIMEOUT_SEC) -> RunResult:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return RunResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(
            "utf-8", errors="replace"
        )
        err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(
            "utf-8", errors="replace"
        )
        return RunResult(stdout=out, stderr=err, exit_code=124, timed_out=True)


def merge_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout.rstrip()}\n{stderr.rstrip()}\n"
    return stdout or stderr
