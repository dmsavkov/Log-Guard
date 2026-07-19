"""In-place log sanitization: delete noisy tokens (not mask) before value extract."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from loguru import logger

# Preserve timeline markers through sanitization.
_PROTECTED = re.compile(r"(\[#\d+\]|\[T\d+\]|\[[x×]\d+\]|\[PROGRESS\])")
_HOST = re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_TIMESTAMP = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?|"
    r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b"
)
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_STANDALONE_LONG_NUM = re.compile(r"\b\d{5,}\b")
_ORPHAN_BRACKETS = re.compile(r"[\{\}\[\]\(\)]")


@dataclass
class InplaceSanitizeStats:
    input_lines: int = 0
    output_lines: int = 0
    chars_before: int = 0
    chars_after: int = 0
    tokens_deleted: int = 0


def _protect(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        tokens.append(m.group(1))
        return f"\ue002{len(tokens) - 1}\ue003"

    return _PROTECTED.sub(_repl, text), tokens


def _restore(text: str, tokens: list[str]) -> str:
    for i, tok in enumerate(tokens):
        text = text.replace(f"\ue002{i}\ue003", tok)
    return text


def _delete_matches(line: str, pattern: re.Pattern[str], stats: InplaceSanitizeStats) -> str:
    new, n = pattern.subn(" ", line)
    stats.tokens_deleted += n
    return new


def sanitize_line_inplace(line: str, stats: InplaceSanitizeStats) -> str:
    """Delete hosts, IPs, timestamps, hex, and standalone integers >= 5 digits."""
    masked, tokens = _protect(line)
    cur = masked
    for pat in (_HOST, _IPV6, _IPV4, _TIMESTAMP, _HEX, _STANDALONE_LONG_NUM):
        cur = _delete_matches(cur, pat, stats)
    cur = _ORPHAN_BRACKETS.sub(" ", cur)
    cur = re.sub(r"[ \t]+", " ", cur).strip()
    return _restore(cur, tokens)


def sanitize_lines_inplace(lines: list[str]) -> tuple[list[str], dict]:
    stats = InplaceSanitizeStats(
        input_lines=len(lines),
        chars_before=sum(len(ln) for ln in lines),
    )
    out = [sanitize_line_inplace(ln, stats) for ln in lines]
    out = [ln for ln in out if ln.strip()]
    stats.output_lines = len(out)
    stats.chars_after = sum(len(ln) for ln in out)
    logger.info(
        "inplace_sanitize: {} → {} lines, {} tokens deleted",
        stats.input_lines,
        stats.output_lines,
        stats.tokens_deleted,
    )
    return out, asdict(stats)
