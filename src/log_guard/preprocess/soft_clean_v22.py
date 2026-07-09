"""v0.22 Phase-1 soft cleaning with per-step toggles."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from loguru import logger

from log_guard.preprocess.char_clean import (
    char_clean_lines,
    collapse_progress_blocks,
    stats_dict as char_stats_dict,
)
from log_guard.preprocess.path_prune import prune_paths
from log_guard.preprocess.temporal_strip import temporal_strip_lines
from log_guard.preprocess.value_extract import _scrub_entropy_tokens

_LONG_ALNUM = re.compile(r"[A-Za-z0-9+/=_-]{200,}")


@dataclass
class SoftCleanV22Stats:
    input_lines: int = 0
    output_lines: int = 0
    chars_before: int = 0
    chars_after: int = 0
    paths_changed: int = 0
    base64_truncated: int = 0
    entropy_tokens: int = 0
    blank_lines_collapsed: int = 0


def _truncate_long_alnum(line: str) -> tuple[str, int]:
    count = 0

    def _repl(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[LONG_BLOB]"

    out = _LONG_ALNUM.sub(_repl, line)
    return out, count


_BARE_HEX = re.compile(r"\b(0x)?[a-fA-F]{8,16}\b")
_HEAVY_BOX = re.compile(r"[━─]+")
_MOJIBAKE = re.compile(r"\ufffd")
# Collapse 3+ decorative runs to a single char (preserve single - for flags).
_DECORATIVE_RUN = re.compile(r"([=*_~#\-])\1{2,}")
# ASCII art banners (Unsloth-style decorative lines).
_ASCII_ART = re.compile(
    r"^[=\s*\\/Oo_\.\(\)\[\]\-]{8,}$|==\(\(={3,}\)\)==|^[Oo]\s+[Oo]/|\"-_{3,}-\""
)
_BOX_DRAWING = re.compile(r"[\u2500-\u257f\u2580-\u259f]")
_JAVA_GC_NUM = re.compile(r"\b\d+K->\d+K\(\d+K\)")


def _scrub_line_entropy(line: str, *, delete_tokens: bool = False) -> tuple[str, int]:
    out, n = _scrub_entropy_tokens(line, delete_tokens=delete_tokens)
    return out, n


def _strip_bare_hex(line: str) -> tuple[str, int]:
    new, n = _BARE_HEX.subn("[HEX]", line)
    return new, n


def _collapse_decorative(line: str) -> tuple[str, int]:
    if re.match(r"^--- [ab]/", line) or re.match(r"^\+\+\+ [ab]/", line):
        return line, 0
    count = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return m.group(1)

    out = _DECORATIVE_RUN.sub(_repl, line)
    return out, count


def _strip_ascii_art_line(line: str) -> tuple[str | None, int]:
    stripped = line.strip()
    if not stripped:
        return line, 0
    if _ASCII_ART.match(stripped):
        return None, 1
    if stripped.count("=") >= 6 and sum(c.isalpha() for c in stripped) <= 4:
        return None, 1
    return line, 0


def _mask_java_gc(line: str) -> tuple[str, int]:
    new, n = _JAVA_GC_NUM.subn("<NUM>K-><NUM>K(<NUM>K)", line)
    return new, n


def _strip_box_chars(line: str) -> tuple[str, int]:
    count = 0
    new, n = _HEAVY_BOX.subn("", line)
    count += n
    new, n = _BOX_DRAWING.subn("", new)
    count += n
    new, n = _MOJIBAKE.subn("", new)
    count += n
    return new, count


def _collapse_blank_lines(lines: list[str]) -> tuple[list[str], int]:
    out: list[str] = []
    collapsed = 0
    prev_blank = False
    for ln in lines:
        blank = not ln.strip()
        if blank and prev_blank:
            collapsed += 1
            continue
        out.append(ln.rstrip())
        prev_blank = blank
    return out, collapsed


def _flags_from_exp(exp_cfg: dict) -> dict[str, bool]:
    return {
        "ansi": bool(exp_cfg.get("v22_clean_ansi", True)),
        "progress": bool(exp_cfg.get("v22_clean_progress", True)),
        "prefix": bool(exp_cfg.get("v22_clean_prefix", True)),
        "paths": bool(exp_cfg.get("v22_clean_paths", True)),
        "base64": bool(exp_cfg.get("v22_clean_base64", True)),
        "whitespace": bool(exp_cfg.get("v22_clean_whitespace", True)),
        "entropy": bool(exp_cfg.get("v22_clean_entropy", True)),
    }


def apply_soft_clean_v22(lines: list[str], exp_cfg: dict) -> tuple[list[str], dict]:
    """Run v0.22 soft clean; returns (lines, stats_dict)."""
    flags = _flags_from_exp(exp_cfg)
    stats = SoftCleanV22Stats(
        input_lines=len(lines),
        chars_before=sum(len(ln) for ln in lines),
    )
    out = list(lines)

    if flags["ansi"] or flags["progress"]:
        progress_mode = "collapse" if flags["progress"] else None
        out, cc = char_clean_lines(
            out,
            ansi_control=flags["ansi"],
            progress_mode=progress_mode,
            mask_arrays=False,
        )
        logger.debug("v22 soft char_clean: {}", char_stats_dict(cc))
        if flags["progress"]:
            out, _ = collapse_progress_blocks(out)

    if flags["prefix"]:
        out, _ts = temporal_strip_lines(out)

    if flags["paths"]:
        out, ps = prune_paths(out)
        stats.paths_changed = ps.lines_changed

    if flags["base64"]:
        truncated: list[str] = []
        for ln in out:
            new_ln, n = _truncate_long_alnum(ln)
            stats.base64_truncated += n
            truncated.append(new_ln)
        out = truncated

    if flags["entropy"]:
        delete_ent = bool(exp_cfg.get("entropy_delete", False))
        ent_out: list[str] = []
        for ln in out:
            new_ln, n = _scrub_line_entropy(ln, delete_tokens=delete_ent)
            stats.entropy_tokens += n
            ent_out.append(new_ln)
        out = ent_out

    cleaned: list[str] = []
    for ln in out:
        art_ln, _ = _strip_ascii_art_line(ln)
        if art_ln is None:
            continue
        new_ln, _ = _collapse_decorative(art_ln)
        new_ln, _ = _mask_java_gc(new_ln)
        cleaned.append(new_ln)
    out = cleaned

    hex_out: list[str] = []
    for ln in out:
        new_ln, _ = _strip_bare_hex(ln)
        new_ln, _ = _strip_box_chars(new_ln)
        hex_out.append(new_ln)
    out = hex_out

    if flags["whitespace"]:
        out, stats.blank_lines_collapsed = _collapse_blank_lines(out)

    stats.output_lines = len(out)
    stats.chars_after = sum(len(ln) for ln in out)
    logger.info(
        "soft_clean_v22: {} → {} lines, {} → {} chars",
        stats.input_lines,
        stats.output_lines,
        stats.chars_before,
        stats.chars_after,
    )
    return out, asdict(stats)
