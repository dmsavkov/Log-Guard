"""lg debug command — list or print per-stage intermediate files."""

from __future__ import annotations

import sys
from pathlib import Path

from log_guard.lg.storage import intermediate_dir, list_debug_files, run_dir


def format_debug_list(run_id: str) -> str:
    base = run_dir(run_id)
    if not base.is_dir() and not list_debug_files(run_id):
        raise FileNotFoundError(f"No run with id {run_id!r}")

    lines = [f"Debug artifacts for run {run_id}:", ""]
    for path in list_debug_files(run_id):
        rel = path.relative_to(base) if path.is_relative_to(base) else path.name
        size = path.stat().st_size if path.is_file() else 0
        lines.append(f"  {rel}  ({size:,} bytes)")
    if len(lines) == 2:
        lines.append("  (no intermediate files)")
    return "\n".join(lines) + "\n"


def read_debug_file(run_id: str, filename: str) -> str:
    inter = intermediate_dir(run_id)
    candidates = [
        inter / filename,
        run_dir(run_id) / filename,
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"No debug file {filename!r} for run {run_id!r}")


def print_debug(run_id: str, filename: str | None) -> int:
    try:
        if filename is None:
            sys.stdout.write(format_debug_list(run_id))
        else:
            sys.stdout.write(read_debug_file(run_id, filename))
    except FileNotFoundError as exc:
        sys.stderr.write(f"[LogGuard Error: {exc}]\n")
        return 1
    return 0
