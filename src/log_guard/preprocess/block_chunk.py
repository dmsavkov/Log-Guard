"""Block boundary strategies for v0.18 payload chunking."""

from __future__ import annotations

import re
from datetime import datetime

_KAGGLE_ELAPSED = re.compile(r"^(\d+(?:\.\d+)?)s(?:\t|\s+)")
_SYSLOG_TS = re.compile(
    r"^(?:([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})|"
    r"(\d{4}-\d{2}-\d{2}[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)))"
)


def _parse_line_epoch(line: str, *, year: int = 2026) -> float | None:
    m = _KAGGLE_ELAPSED.match(line)
    if m:
        return float(m.group(1))
    m = _SYSLOG_TS.match(line)
    if not m:
        return None
    if m.group(1):
        try:
            dt = datetime.strptime(f"{m.group(1)} {year}", "%b %d %H:%M:%S %Y")
            return dt.timestamp()
        except ValueError:
            return None
    if m.group(2):
        try:
            dt = datetime.fromisoformat(m.group(2).replace(" ", "T"))
            return dt.timestamp()
        except ValueError:
            return None
    return None


def chunk_line_boundaries(
    n_lines: int,
    *,
    mode: str = "lines",
    block_size: int = 300,
    block_time_sec: int = 3000,
    block_char_budget: int = 20000,
    lines: list[str] | None = None,
    raw_lines: list[str] | None = None,
) -> list[tuple[int, int]]:
    """Return 1-based inclusive (lo, hi) line ranges covering all lines."""
    if n_lines <= 0:
        return []

    if mode == "lines" or mode == "":
        out: list[tuple[int, int]] = []
        for start in range(0, n_lines, max(block_size, 1)):
            lo = start + 1
            hi = min(start + block_size, n_lines)
            out.append((lo, hi))
        return out

    if mode == "time":
        src = raw_lines if raw_lines is not None else (lines or [])
        if len(src) != n_lines:
            src = (lines or [])[:n_lines]
        epochs: list[float | None] = [_parse_line_epoch(ln) for ln in src]
        anchor: float | None = None
        rel: list[float] = []
        for ep in epochs:
            if ep is None:
                rel.append(rel[-1] if rel else 0.0)
                continue
            if anchor is None:
                anchor = ep
            rel.append(ep - anchor)

        boundaries: list[tuple[int, int]] = []
        lo = 1
        chunk_start = rel[0] if rel else 0.0
        for i, t in enumerate(rel, start=1):
            if i == n_lines:
                boundaries.append((lo, n_lines))
                break
            if t - chunk_start >= block_time_sec and i >= lo:
                boundaries.append((lo, i))
                lo = i + 1
                chunk_start = t
        if not boundaries:
            boundaries.append((1, n_lines))
        elif boundaries[-1][1] < n_lines:
            boundaries.append((lo, n_lines))
        return boundaries

    if mode == "chars":
        text_lines = lines or []
        if len(text_lines) != n_lines:
            text_lines = text_lines[:n_lines]
        boundaries = []
        lo = 1
        pos = 0
        while pos < n_lines:
            budget = block_char_budget
            used = 0
            hi = pos
            while hi < n_lines:
                ln_len = len(text_lines[hi]) + (1 if hi > pos else 0)
                if used + ln_len > budget and hi > pos:
                    break
                used += ln_len
                hi += 1
            if hi == pos:
                hi = pos + 1
            else:
                # roll back to last newline within chunk if we exceeded budget mid-line
                if hi < n_lines and used > block_char_budget:
                    hi = max(pos + 1, hi - 1)
            boundaries.append((lo, hi))
            pos = hi
            lo = hi + 1
        return boundaries or [(1, n_lines)]

    raise ValueError(f"Unknown block mode: {mode}")
