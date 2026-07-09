"""Strip timestamps, PIDs, and volatile addresses before dedup/clustering."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Module path uses dot (not literal asterisk).
_LOGURU_PREFIX = re.compile(r"^[a-zA-Z0-9_.]+:[a-zA-Z0-9_]+:\d+\s+-\s")
_LOGURU_TS = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*\|\s*\w+\s*\|\s*"
    r"[a-zA-Z0-9_.]+:[a-zA-Z0-9_]+:\d+\s+-\s"
)
_KAGGLE_PREFIX = re.compile(r"^\d+\.?\d*s(?:\t|\s+)\d+(?:\t|\s+)")
_SYSLOG = re.compile(
    r"^(?:[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}|"
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r"(?:\S+\s+){0,2}",
)
_APACHE = re.compile(r"^\[[^\]]+\]\s\[(?:error|warn|notice|info|debug)\]\s", re.IGNORECASE)
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_PID = re.compile(r"\[\d{4,}\]")
_THREAD = re.compile(r"\b\d{4,}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\b")


@dataclass(frozen=True)
class TemporalStripStats:
    input_lines: int
    changed_lines: int


def strip_temporal_line(line: str) -> str:
    s = _LOGURU_TS.sub("", line)
    s = _LOGURU_PREFIX.sub("", s)
    s = _KAGGLE_PREFIX.sub("", s)
    s = _SYSLOG.sub("", s)
    s = _APACHE.sub("", s)
    s = _THREAD.sub("<TS>", s)
    s = _HEX.sub("<ADDR>", s)
    s = _PID.sub("[PID]", s)
    return s.strip()


def temporal_strip_lines(lines: list[str]) -> tuple[list[str], TemporalStripStats]:
    out: list[str] = []
    changed = 0
    for ln in lines:
        stripped = strip_temporal_line(ln)
        if stripped != ln.strip():
            changed += 1
        if stripped:
            out.append(stripped)
    return out, TemporalStripStats(input_lines=len(lines), changed_lines=changed)
