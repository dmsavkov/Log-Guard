"""Parse pytest summary for compact success messages."""

from __future__ import annotations

import re

_PASSED_RE = re.compile(
    r"=+\s*(\d+)\s+passed(?:\s+in\s+[\d.]+s)?\s*=+",
    re.IGNORECASE,
)
_COLLECTED_RE = re.compile(r"collected\s+(\d+)\s+item", re.IGNORECASE)


def parse_pytest_pass_count(output: str) -> int | None:
    m = _PASSED_RE.search(output)
    if m:
        return int(m.group(1))
    m = _COLLECTED_RE.search(output)
    if m:
        return int(m.group(1))
    return None


def format_pytest_success(output: str) -> str:
    n = parse_pytest_pass_count(output)
    if n is not None:
        return f"all {n} tests passed"
    return "all tests passed"
