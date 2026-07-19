"""Vendored RTK binary wrapper — single spawn, tee-owned raw capture."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from log_guard.io_config import subprocess_env

_RTK_HINT_RE = re.compile(
    r"\[full output[^\]]*\][^\n]*|\[see remaining[^\]]*\][^\n]*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RtkRunResult:
    stdout: str
    stderr: str
    exit_code: int
    used_rtk: bool
    raw_path: Path | None = None


def _vendor_roots() -> list[Path]:
    repo = Path(__file__).resolve().parents[3]
    return [
        repo / "vendor" / "rtk",
        Path(__file__).resolve().parent / "vendor",
    ]


def find_rtk_binary() -> Path | None:
    name = "rtk.exe" if os.name == "nt" else "rtk"
    for root in _vendor_roots():
        if not root.is_dir():
            continue
        for sub in (root, root / "bin", root / os.name):
            candidate = sub / name
            if candidate.is_file():
                return candidate
    return shutil.which("rtk")


def strip_rtk_hints(text: str) -> str:
    lines = [ln for ln in text.splitlines() if not _RTK_HINT_RE.search(ln)]
    return "\n".join(lines).rstrip("\n") + ("\n" if text.endswith("\n") else "")


def _rename_tee_file(run_dir: Path, filtered_stdout: str) -> Path:
    logs = sorted(run_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    raw_txt = run_dir / "raw.txt"
    if logs:
        logs[0].replace(raw_txt)
        return raw_txt
    raw_txt.write_text(filtered_stdout, encoding="utf-8")
    return raw_txt


def run_via_rtk(
    argv: list[str],
    *,
    run_dir: Path,
    shell_command: str | None = None,
    timeout: int = 300,
) -> RtkRunResult:
    """Execute `rtk <argv...>` once; tee raw into run_dir/raw.txt."""
    binary = find_rtk_binary()
    run_dir.mkdir(parents=True, exist_ok=True)
    env = {**subprocess_env(), "RTK_TEE_DIR": str(run_dir.resolve())}
    env.setdefault("RTK_TELEMETRY_DISABLED", "1")

    if binary is None:
        return RtkRunResult(stdout="", stderr="", exit_code=127, used_rtk=False)

    cmd = [str(binary), *argv]
    try:
        proc = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=None,
        )
    except subprocess.TimeoutExpired:
        return RtkRunResult(stdout="", stderr="timeout", exit_code=124, used_rtk=True)
    except OSError as exc:
        return RtkRunResult(stdout="", stderr=str(exc), exit_code=127, used_rtk=False)

    merged = proc.stdout or ""
    if proc.stderr:
        merged = f"{merged.rstrip()}\n{proc.stderr.rstrip()}\n" if merged else proc.stderr
    cleaned = strip_rtk_hints(merged)
    raw_path = _rename_tee_file(run_dir, merged)
    return RtkRunResult(
        stdout=cleaned,
        stderr="",
        exit_code=proc.returncode,
        used_rtk=True,
        raw_path=raw_path,
    )
