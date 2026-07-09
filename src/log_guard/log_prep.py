import hashlib
import re
from pathlib import Path

from loguru import logger

# Kaggle notebook runner prefix: "7.2s\t0\t" or "130.9s  103  "
_KAGGLE_LINE_PREFIX = re.compile(r"^\d+\.?\d*s(?:\t|\s+)\d+(?:\t|\s+)")
# Elapsed seconds at line start (before line number strip)
_ELAPSED_PREFIX = re.compile(r"^(\d+\.?\d*)s(?:\t|\s+)")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
# First timestamped log line in Kaggle exports
_FIRST_LOG_LINE = re.compile(r"^\d+\.?\d*s(?:\t|\s+)\d+(?:\t|\s+)")


def clean_line(line: str) -> str:
    """Strip Kaggle runner prefix, line numbers, and ANSI codes from one line."""
    line_clean = _KAGGLE_LINE_PREFIX.sub("", line)
    line_clean = re.sub(r"^\d+:\s+", "", line_clean)
    return _ANSI_ESCAPE.sub("", line_clean)


def clean_log_content(content: str) -> str:
    return "\n".join(clean_line(line) for line in content.splitlines())


def strip_kaggle_header(content: str) -> str:
    """Drop Kaggle UI chrome before the first timestamped log line."""
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if _FIRST_LOG_LINE.match(line):
            logger.debug("Stripped {} header lines before first log entry", idx)
            return "\n".join(lines[idx:])
    return content


def load_raw_log(path: Path, preliminary: bool = False, preliminary_lines: int = 150) -> tuple[str, list[str]]:
    """Load raw log, clean lines, optionally truncate for smoke runs."""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = strip_kaggle_header(raw)
    cleaned = clean_log_content(raw)
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    if preliminary:
        lines = lines[:preliminary_lines]
        logger.info("Preliminary mode: using first {} cleaned lines", len(lines))
    return "\n".join(lines), lines


def load_gold(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_elapsed_seconds(line: str) -> float | None:
    """Extract elapsed seconds from a raw (uncleaned) Kaggle log line."""
    match = _ELAPSED_PREFIX.match(line)
    if match:
        return float(match.group(1))
    return None


def extract_error_lines(lines: list[str]) -> list[str]:
    """Pull lines matching traceback/error keywords for distillation payloads."""
    keywords = (
        "traceback",
        "error:",
        "exception:",
        "failed",
        "critical",
        "pass_rate",
        "syntax error",
    )
    result: list[str] = []
    in_traceback = False
    for line in lines:
        lower = line.lower()
        if "traceback (most recent call last):" in lower:
            in_traceback = True
        if in_traceback or any(kw in lower for kw in keywords):
            result.append(line)
        if in_traceback and line.strip() and not line.startswith(" ") and "traceback" not in lower:
            in_traceback = False
    return list(dict.fromkeys(result))
