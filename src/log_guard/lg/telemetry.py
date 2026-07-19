"""Telemetry for all lg subcommands."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from log_guard.lg.storage import logguard_home

# Marks probe/manual runs for exclusion from default agent-facing stats.
# Not documented in agent .cursorrules; CLI help is suppressed.
EXPERIMENTAL_ENV = "LOGGUARD_EXPERIMENTAL"


def resolve_experimental(cli_flag: bool = False) -> bool:
    """True if CLI --experimental or LOGGUARD_EXPERIMENTAL is set."""
    if cli_flag:
        return True
    val = os.environ.get(EXPERIMENTAL_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _telemetry_path() -> Path:
    path = logguard_home() / "telemetry.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_invocation(
    *,
    subcommand: str,
    run_id: str | None = None,
    track: str | None = None,
    cmd: str | None = None,
    exit_code: int | None = None,
    raw_chars: int = 0,
    compressed_chars: int = 0,
    latency_ms: float = 0.0,
    experimental: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "subcommand": subcommand,
        "run_id": run_id,
        "track": track,
        "cmd": cmd,
        "exit_code": exit_code,
        "raw_chars": raw_chars,
        "compressed_chars": compressed_chars,
        "latency_ms": round(latency_ms, 2),
        "experimental": experimental,
        **(extra or {}),
    }
    with _telemetry_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_telemetry() -> list[dict[str, Any]]:
    path = _telemetry_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


class InvocationTimer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000
