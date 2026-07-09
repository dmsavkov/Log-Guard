"""v0.22 Phase-2 mid-session cleanup after value extraction."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from loguru import logger

_PROTECTED_MARKER = re.compile(r"\[#\d+\]|\[T\d+\]|\[×\d+\]|\[PROGRESS\]")
_ORPHAN_BRACKETS = re.compile(r"[\{\}\[\]\(\)]")
_BOX_DRAWING = re.compile(r"[\u2500-\u257f\u2580-\u259f]|[━─]+")
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001f9ff"
    "\u2600-\u26ff"
    "\u2700-\u27bf"
    "]"
)
_MOJIBAKE = re.compile(r"\ufffd")


@dataclass
class MidCharCleanStats:
    input_lines: int = 0
    output_lines: int = 0
    orphan_lines_dropped: int = 0
    orphan_chars_stripped: int = 0
    hex_stripped: int = 0
    box_stripped: int = 0
    special_stripped_lines: int = 0
    chars_before: int = 0
    chars_after: int = 0


def _protect_markers(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        tokens.append(m.group(0))
        return f"__PROT{len(tokens) - 1}__"

    return _PROTECTED_MARKER.sub(_repl, text), tokens


def _unprotect_markers(text: str, tokens: list[str]) -> str:
    out = text
    for i, tok in enumerate(tokens):
        out = out.replace(f"__PROT{i}__", tok)
    return out


def mid_char_clean_lines(
    lines: list[str],
    exp_cfg: dict,
    *,
    post_extract: bool = False,
) -> tuple[list[str], dict]:
    """Post-extract: strip orphan brackets + box/emoji only; never drop lines."""
    stats = MidCharCleanStats(
        input_lines=len(lines),
        chars_before=sum(len(ln) for ln in lines),
    )
    if not post_extract or not bool(exp_cfg.get("v22_mid_enabled", True)):
        stats.output_lines = len(lines)
        stats.chars_after = stats.chars_before
        return lines, asdict(stats)

    out: list[str] = []
    for ln in lines:
        masked, tokens = _protect_markers(ln)
        new_cur, n = _ORPHAN_BRACKETS.subn(" ", masked)
        if n:
            stats.orphan_chars_stripped += n
        cur = _unprotect_markers(re.sub(r"[ \t]+", " ", new_cur).strip(), tokens)

        new_cur, n = _BOX_DRAWING.subn("", cur)
        n += len(_EMOJI.findall(cur))
        new_cur = _EMOJI.sub("", new_cur)
        new_cur = _MOJIBAKE.sub("", new_cur)
        if n:
            stats.box_stripped += n
            cur = new_cur

        out.append(cur)

    stats.output_lines = len(out)
    stats.chars_after = sum(len(ln) for ln in out)
    logger.info(
        "mid_char_clean: {} → {} lines, bracket chars stripped {}",
        stats.input_lines,
        stats.output_lines,
        stats.orphan_chars_stripped,
    )
    return out, asdict(stats)
