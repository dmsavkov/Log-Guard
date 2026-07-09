"""Character-level log cleaning for v0.16 (ANSI, control codes, arrays, whitespace)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from loguru import logger

# Broader than log_prep._ANSI_ESCAPE — CSI sequences, OSC, cursor controls.
_ANSI = re.compile(
    r"\x1b(?:\[[0-?9;]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])"
    r"|\[\?2026[hl]|\[\?25[hl]"
)
# Non-printable ASCII except tab/newline (applied per line).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_PROGRESS = re.compile(
    r"(sandbox:\s*\d+%|\|\s*\d+/\d+\s*\[|\d+/\d+\s*\[.*(?:it/s|s/it|examples/s)\]|"
    r"Generating \w+ split:|Map:\s*\d+%|\d+/\d+\s*\[|"
    r"\d+%\|[█▏▎▍▌▋▊▉\s]+\||"
    r"\[progress\]|examples\s*\[|^\s*\d+\s+examples\s*\[)",
    re.IGNORECASE,
)
_DOWNLOAD_SPEED = re.compile(
    r"\d+\.?\d*/\d+\.?\d*\s*(?:kB|MB|GB|KiB|MiB|GiB).*(?:eta|s/it|MB/s)",
    re.IGNORECASE,
)
_PROGRESS_TAG = "[PROGRESS]"


def is_progress_line(line: str) -> bool:
    if _DOWNLOAD_SPEED.search(line):
        return True
    if _PROGRESS.search(line):
        return True
    if re.search(r"\d+/\d+\s*kB", line, re.IGNORECASE):
        return True
    return False


def _collapse_progress_line(line: str) -> str:
    if not is_progress_line(line):
        return line
    return _PROGRESS_TAG


def collapse_progress_blocks(lines: list[str]) -> tuple[list[str], int]:
    """Replace consecutive progress/download lines with a single [PROGRESS] line."""
    out: list[str] = []
    merged = 0
    i = 0
    n = len(lines)
    while i < n:
        if is_progress_line(lines[i]):
            j = i + 1
            while j < n and is_progress_line(lines[j]):
                j += 1
            if out and out[-1] == _PROGRESS_TAG:
                merged += j - i
            else:
                out.append(_PROGRESS_TAG)
                merged += max(0, j - i - 1)
            i = j
            continue
        out.append(lines[i])
        i += 1
    return out, merged

# Bracketed or bare comma-separated runs of 5+ numeric literals.
_BRACKET_NUM_ARRAY = re.compile(
    r"\[(?:\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\s*,\s*){4,}"
    r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\s*\]"
)
_COMMA_NUM_RUN = re.compile(
    r"(?<![\w/\:])(?:[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\s*,\s*){4,}"
    r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?(?![\w/\:])"
)

# Mask tokens produced by upstream stages — preserved through special-char strip.
_PROTECTED = re.compile(
    r"\[(?:HASH_[A-F0-9]{8}|FLOAT_ARRAY_MASKED|ENTROPY:[A-F0-9]{8}|"
    r"DICT_EXTRACTED|PROGRESS|Matrix:[^\]]+)\]"
    r"|<TS>|<ADDR>|\[PID\]"
)

_SPECIAL_STRIP = re.compile(r"[\[\]\{\}\^~`@#$%&*+=\\|<>]")
# v0.16 special_extra: strip punctuation used as delimiters (not alnum).
_SPECIAL_EXTRA = re.compile(r"[.,_/\\:;\-]+")
_ALL_NUMBERS = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


@dataclass
class CharCleanStats:
    input_lines: int = 0
    output_lines: int = 0
    ansi_lines: int = 0
    control_lines: int = 0
    progress_dropped: int = 0
    progress_collapsed: int = 0
    arrays_masked: int = 0
    ws_tab_lines: int = 0
    special_stripped_lines: int = 0
    special_extra_lines: int = 0
    numbers_stripped_lines: int = 0
    chars_before: int = 0
    chars_after: int = 0


def _mask_protected(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        tokens.append(m.group(0))
        return f"__PROT{len(tokens) - 1}__"

    return _PROTECTED.sub(_repl, text), tokens


def _unmask_protected(text: str, tokens: list[str]) -> str:
    out = text
    for i, tok in enumerate(tokens):
        out = out.replace(f"__PROT{i}__", tok)
    return out


def _annihilate_ansi_control(line: str) -> tuple[str, bool, bool]:
    had_ansi = bool(_ANSI.search(line))
    had_ctrl = bool(_CONTROL.search(line) or "\r" in line)
    # Carriage returns (tqdm overwrites): keep final segment only.
    if "\r" in line:
        line = line.split("\r")[-1]
    line = _ANSI.sub("", line)
    line = _CONTROL.sub("", line)
    return line, had_ansi, had_ctrl


def _mask_numeric_arrays(line: str) -> tuple[str, int]:
    count = 0

    def _bracket_repl(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[FLOAT_ARRAY_MASKED]"

    def _comma_repl(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[FLOAT_ARRAY_MASKED]"

    out = _BRACKET_NUM_ARRAY.sub(_bracket_repl, line)
    out = _COMMA_NUM_RUN.sub(_comma_repl, out)
    return out, count


def _normalize_whitespace_tabs(line: str) -> tuple[str, bool]:
    original = line
    # Collapse horizontal whitespace runs to a single tab (preserve newlines at line level).
    out = re.sub(r"[ \t]{2,}", "\t", line)
    out = re.sub(r" ?\t ?", "\t", out)
    return out, out != original


def _strip_special_extra(line: str) -> tuple[str, bool]:
    masked, tokens = _mask_protected(line)
    stripped = _SPECIAL_EXTRA.sub(" ", masked)
    stripped = re.sub(r"[ \t]+", " ", stripped).strip()
    out = _unmask_protected(stripped, tokens)
    return out, out != line


def _strip_all_numbers(line: str) -> tuple[str, bool]:
    masked, tokens = _mask_protected(line)
    stripped = _ALL_NUMBERS.sub(" ", masked)
    stripped = re.sub(r"[ \t]+", " ", stripped).strip()
    out = _unmask_protected(stripped, tokens)
    return out, out != line


def _strip_special_chars(line: str) -> tuple[str, bool]:
    masked, tokens = _mask_protected(line)
    stripped = _SPECIAL_STRIP.sub(" ", masked)
    stripped = re.sub(r"[ \t]+", " ", stripped).strip()
    out = _unmask_protected(stripped, tokens)
    return out, out != line


def clean_line_chars(
    line: str,
    *,
    ansi_control: bool = False,
    progress_mode: str | None = None,
    mask_arrays: bool = False,
    ws_tabs: bool = False,
    special_strip: bool = False,
    special_extra: bool = False,
    strip_numbers: bool = False,
) -> tuple[str | None, dict[str, int]]:
    """Clean one line. Returns (line_or_none_if_dropped, delta stats)."""
    delta = {
        "ansi": 0,
        "control": 0,
        "progress_drop": 0,
        "progress_collapse": 0,
        "arrays": 0,
        "ws": 0,
        "special": 0,
        "special_extra": 0,
        "numbers": 0,
    }
    out = line

    if ansi_control:
        out, had_ansi, had_ctrl = _annihilate_ansi_control(out)
        delta["ansi"] += int(had_ansi)
        delta["control"] += int(had_ctrl)

    if progress_mode and _PROGRESS.search(out):
        if progress_mode == "drop":
            delta["progress_drop"] += 1
            return None, delta
        if progress_mode == "collapse":
            out = _collapse_progress_line(out)
            delta["progress_collapse"] += 1

    if mask_arrays:
        out, n = _mask_numeric_arrays(out)
        delta["arrays"] += n

    if ws_tabs:
        out, changed = _normalize_whitespace_tabs(out)
        delta["ws"] += int(changed)

    if special_extra:
        out, changed = _strip_special_extra(out)
        delta["special_extra"] += int(changed)

    if strip_numbers:
        out, changed = _strip_all_numbers(out)
        delta["numbers"] += int(changed)

    if special_strip:
        out, changed = _strip_special_chars(out)
        delta["special"] += int(changed)

    out = out.strip()
    if not out:
        return None, delta
    return out, delta


def char_clean_lines(
    lines: list[str],
    *,
    ansi_control: bool = False,
    progress_mode: str | None = None,
    mask_arrays: bool = False,
    ws_tabs: bool = False,
    special_strip: bool = False,
    special_extra: bool = False,
    strip_numbers: bool = False,
) -> tuple[list[str], CharCleanStats]:
    """Apply character cleaning. Never lowercases — casing preserved for LLM payload."""
    stats = CharCleanStats(
        input_lines=len(lines),
        chars_before=sum(len(ln) for ln in lines),
    )
    out: list[str] = []

    for ln in lines:
        cleaned, delta = clean_line_chars(
            ln,
            ansi_control=ansi_control,
            progress_mode=progress_mode,
            mask_arrays=mask_arrays,
            ws_tabs=ws_tabs,
            special_strip=special_strip,
            special_extra=special_extra,
            strip_numbers=strip_numbers,
        )
        stats.ansi_lines += delta["ansi"]
        stats.control_lines += delta["control"]
        stats.progress_dropped += delta["progress_drop"]
        stats.progress_collapsed += delta["progress_collapse"]
        stats.arrays_masked += delta["arrays"]
        stats.ws_tab_lines += delta["ws"]
        stats.special_stripped_lines += delta["special"]
        stats.special_extra_lines += delta.get("special_extra", 0)
        stats.numbers_stripped_lines += delta.get("numbers", 0)
        if cleaned is not None:
            out.append(cleaned)

    stats.output_lines = len(out)
    stats.chars_after = sum(len(ln) for ln in out)
    logger.info(
        "char_clean: {} → {} lines, {} → {} chars",
        stats.input_lines,
        stats.output_lines,
        stats.chars_before,
        stats.chars_after,
    )
    return out, stats


def stats_dict(stats: CharCleanStats) -> dict:
    return asdict(stats)
