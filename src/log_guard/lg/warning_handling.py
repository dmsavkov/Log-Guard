"""Structured warning extraction — runs after trace, before mid clean."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERN_FILE_LINE = re.compile(
    r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*(?P<type>\w*Warning):\s*(?P<msg>.*)$"
)
_PATTERN_LOGGING = re.compile(
    r"^(?:\[)?(?P<level>WARNING|WARN|WARNI?NG)(?:\])?[:\s-]*"
    r"(?:\[[^\]]+\]\s*)?(?P<msg>.*)$",
    re.IGNORECASE,
)
_PATTERN_INLINE = re.compile(
    r"\b(?P<type>UserWarning|FutureWarning|DeprecationWarning|"
    r"PendingDeprecationWarning|SyntaxWarning|ResourceWarning|ImportWarning|"
    r"XMLParsedAsHTMLWarning)\b[:\s]*(?P<msg>.{0,300})",
    re.IGNORECASE,
)
_WARN_TYPES = frozenset(
    {
        "warning",
        "warn",
        "userwarning",
        "futurewarning",
        "deprecationwarning",
        "pendingdeprecationwarning",
        "syntaxwarning",
        "resourcewarning",
        "importwarning",
        "xmlparsedashtmlwarning",
    }
)


@dataclass
class WarningRecord:
    warn_type: str
    message: str
    file: str = ""
    line: int | None = None
    count: int = 1

    @property
    def key(self) -> tuple:
        return (self.warn_type, self.file, self.line, self.message[:80])


@dataclass
class WarningExtractStats:
    warnings_found: int = 0
    warnings_grouped: int = 0
    lines_removed: int = 0
    records: list[WarningRecord] = field(default_factory=list)


def _truncate(msg: str, *, has_file: bool) -> str:
    limit = 200 if has_file else 120
    if len(msg) <= limit:
        return msg
    return msg[: limit - 3] + "..."


def _parse_line(ln: str) -> WarningRecord | None:
    m = _PATTERN_FILE_LINE.match(ln.strip())
    if m:
        msg = _truncate(m.group("msg").strip(), has_file=True)
        return WarningRecord(
            warn_type=m.group("type"),
            message=msg,
            file=m.group("file"),
            line=int(m.group("line")),
        )
    m = _PATTERN_LOGGING.match(ln.strip())
    if m:
        msg = _truncate(m.group("msg").strip(), has_file=False)
        if msg:
            return WarningRecord(warn_type="WARNING", message=msg)
    m = _PATTERN_INLINE.search(ln)
    if m:
        msg = _truncate(m.group("msg").strip(), has_file=False)
        return WarningRecord(warn_type=m.group("type"), message=msg)
    return None


def _is_warning_line(ln: str) -> bool:
    if _PATTERN_FILE_LINE.match(ln.strip()):
        return True
    if _PATTERN_LOGGING.match(ln.strip()):
        return True
    if _PATTERN_INLINE.search(ln):
        return True
    low = ln.lower()
    return any(w in low for w in _WARN_TYPES)


def extract_warnings(lines: list[str]) -> tuple[list[str], WarningExtractStats]:
    """Remove warning lines; emit grouped compact replacements."""
    stats = WarningExtractStats()
    grouped: dict[tuple, WarningRecord] = {}
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if not _is_warning_line(ln):
            out.append(ln)
            i += 1
            continue
        rec = _parse_line(ln)
        if rec is None:
            out.append(ln)
            i += 1
            continue
        stats.warnings_found += 1
        stats.lines_removed += 1
        key = rec.key
        if key in grouped:
            grouped[key].count += 1
        else:
            grouped[key] = rec
        i += 1
    stats.records = list(grouped.values())
    stats.warnings_grouped = len(stats.records)
    for rec in stats.records:
        if rec.count > 1:
            prefix = f"[x{rec.count}]"
        else:
            prefix = ""
        if rec.file and rec.line is not None:
            line = f"{prefix} {rec.warn_type} @ {rec.file}:{rec.line} : {rec.message}".strip()
        else:
            line = f"{prefix} {rec.warn_type}: {rec.message}".strip()
        out.append(line)
    return out, stats


def stats_dict(stats: WarningExtractStats) -> dict:
    return {
        "warnings_found": stats.warnings_found,
        "warnings_grouped": stats.warnings_grouped,
        "lines_removed": stats.lines_removed,
        "record_count": len(stats.records),
    }
