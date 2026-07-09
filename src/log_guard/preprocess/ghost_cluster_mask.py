"""Ghost-only clustering mask: aggressive digit/punct strip on a Drain copy; originals untouched."""

from __future__ import annotations

import re

# Preserve timeline markers through ghost clustering (never compress away).
_GHOST_PROTECTED = re.compile(r"(\[T\d+\]|\[#\d+\]|\[PROGRESS\]|\[×\d+\]|### Block \d+)")
_HOST = re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}\b")
_ALL_DIGITS = re.compile(r"\d")
_GHOST_PUNCT = re.compile(r"[@$^&?*!;'`~<>\\|№#.,/\\:;=\-+_\[\]\(\)\{\}\"]+")


def _placeholder(i: int) -> str:
    """Digit/punct-safe sentinel (private-use chars only)."""
    return "\ue000" + chr(0xF000 + i) + "\ue001"


def _protect(line: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        tokens.append(m.group(1))
        return _placeholder(len(tokens) - 1)

    return _GHOST_PROTECTED.sub(_repl, line), tokens


def _restore(line: str, tokens: list[str]) -> str:
    for i, tok in enumerate(tokens):
        line = line.replace(_placeholder(i), tok)
    return line


def normalize_cluster_line(line: str) -> str:
    """Collapse whitespace for Drain clustering (fixes space-mismatch RLE misses)."""
    return re.sub(r"\s+", " ", line.strip())


def mask_line_ghost_cluster(line: str) -> str:
    """Ghost cluster copy: mask hostnames, strip punct, delete all digits."""
    if not line.strip():
        return line
    protected, tokens = _protect(line)
    # Hostname mask BEFORE punct strip so mail.net stays one token (<HOST>).
    masked = _HOST.sub(" HOST ", protected)
    stripped = _GHOST_PUNCT.sub(" ", masked)
    stripped = _ALL_DIGITS.sub("", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return _restore(stripped, tokens) or line
