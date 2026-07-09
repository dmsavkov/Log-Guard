"""Input normalization before v23 pipeline (matches experiment load_lines)."""

from __future__ import annotations

from log_guard.log_prep import clean_log_content, strip_kaggle_header


def prepare_log_lines(raw: str) -> tuple[list[str], list[str]]:
    """Strip Kaggle chrome and runner prefixes; return (pipeline lines, raw_for_time)."""
    stripped = strip_kaggle_header(raw)
    raw_lines = [ln for ln in stripped.splitlines() if ln.strip()]
    cleaned = clean_log_content(stripped)
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    return lines, raw_lines
