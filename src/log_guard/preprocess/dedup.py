"""Sliding-window Jaccard deduplication for fuzzy repeated lines."""

from __future__ import annotations

import re
from dataclasses import dataclass

_PASS_RATE = re.compile(r"pass_rate\s*=", re.IGNORECASE)
_PROTECTED = re.compile(
    r"(pass_rate\s*=|traceback|exception|Phase\s+\d+\s+Track|===\s*scripts/run\.py)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DedupStats:
    dropped: int


def _is_protected(line: str) -> bool:
    """Never dedupe lines carrying distinct metrics, faults, or experiment boundaries."""
    return bool(_PROTECTED.search(line))


def _tokens(line: str) -> set[str]:
    # Normalize punctuation so small variations (.,!,:) are treated as duplicates.
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in line.lower())
    return set(cleaned.split())


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def sliding_dedup_lines(
    lines: list[str],
    *,
    threshold: float = 0.85,
    window: int = 3,
) -> tuple[list[str], DedupStats]:
    """Drop lines highly similar to any of the previous `window` kept lines."""
    out: list[str] = []
    recent: list[set[str]] = []
    dropped = 0
    for line in lines:
        tok = _tokens(line)
        if not _is_protected(line) and any(jaccard(tok, prev) >= threshold for prev in recent):
            dropped += 1
            continue
        out.append(line)
        recent.append(tok)
        if len(recent) > window:
            recent.pop(0)
    return out, DedupStats(dropped=dropped)


def global_dedup_lines(
    lines: list[str],
    *,
    threshold: float = 0.85,
) -> tuple[list[str], DedupStats]:
    """Drop lines fuzzy-duplicated against any previously kept line (global window)."""
    out: list[str] = []
    kept: list[set[str]] = []
    dropped = 0
    for line in lines:
        if _is_protected(line):
            out.append(line)
            kept.append(_tokens(line))
            continue
        tok = _tokens(line)
        if any(jaccard(tok, prev) >= threshold for prev in kept):
            dropped += 1
            continue
        out.append(line)
        kept.append(tok)
    return out, DedupStats(dropped=dropped)
