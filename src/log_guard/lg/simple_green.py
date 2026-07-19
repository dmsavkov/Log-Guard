"""Universal safe greening — ANSI, progress, light box strip. No entropy/path deletes."""

from __future__ import annotations

import re

from log_guard.preprocess.char_clean import char_clean_lines, collapse_progress_blocks

_BOX_DRAWING = re.compile(r"[\u2500-\u257f\u2580-\u259f]")


def simple_green_lines(lines: list[str]) -> list[str]:
    """Apply minimal safe cleaning suitable for passthrough and RTK outputs."""
    collapsed, _ = collapse_progress_blocks(list(lines))
    flags = {
        "ansi_control": True,
        "progress_mode": None,
        "mask_arrays": False,
        "ws_tabs": False,
        "special_strip": False,
        "special_extra": False,
        "strip_numbers": False,
    }
    out, _ = char_clean_lines(collapsed, **flags)
    cleaned: list[str] = []
    for ln in out:
        ln = _BOX_DRAWING.sub("", ln)
        cleaned.append(ln)
    return cleaned


def simple_green(text: str) -> str:
    lines = simple_green_lines(text.splitlines())
    return "\n".join(lines)
