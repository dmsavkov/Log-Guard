"""Simplified pytest failure block extractor (FAILURES → short test summary)."""

from __future__ import annotations

import re

_FAILURES_START = re.compile(r"^=+\s*FAILURES\s*=+\s*$", re.MULTILINE)
_SHORT_SUMMARY = re.compile(r"^=+\s*short test summary info\s*=+\s*$", re.MULTILINE | re.IGNORECASE)
# Soft clean collapses long underscore banners to "_ name _"; accept 1+ underscores.
_TEST_HEADER = re.compile(r"^_{1,}\s+(.+?)\s+_{1,}\s*$", re.MULTILINE)
_CAPTURED_STDOUT = re.compile(r"^--- Captured stdout ---\s*$", re.MULTILINE)
_FILE_LINE = re.compile(r"^(\S+\.py):(\d+)(?::|\s|$)", re.MULTILINE)
_SHORT_FAILED = re.compile(
    r"^FAILED\s+(?:(\S+\.py)::(\S+)|(\S+))\s+-",
    re.MULTILINE,
)


def _parse_test_name(raw: str) -> str:
    """Normalize pytest node id or header name to Class.test or test_fn."""
    raw = raw.strip()
    if "::" in raw:
        parts = raw.split("::")
        return parts[-1] if len(parts) == 2 else ".".join(parts[-2:])
    return raw


def _file_line_from_body(body: str) -> str:
    m = _FILE_LINE.search(body)
    if not m:
        return ""
    return f"{m.group(1)}:{m.group(2)}"


def _fallback_name_from_summary(text: str) -> str:
    m = _SHORT_FAILED.search(text)
    if not m:
        return ""
    if m.group(1) and m.group(2):
        return f"{m.group(2)}"
    if m.group(3):
        return _parse_test_name(m.group(3))
    return ""


def _extract_sub_block(body: str, header_name: str) -> tuple[str, str, str]:
    """Return (test_name, telegraphic, raw_body) for one failure sub-block."""
    test_name = _parse_test_name(header_name)
    cap = _CAPTURED_STDOUT.search(body)
    if cap:
        body = body[: cap.start()]

    file_line = _file_line_from_body(body)
    gt_line = ""
    e_lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            gt_line = stripped
        elif stripped.startswith("E "):
            e_lines.append(stripped)
        elif stripped.startswith("E") and len(stripped) > 1 and stripped[1] in " \t":
            e_lines.append(stripped)

    label = f"pytest_failure: {test_name}" if test_name else "pytest_failure"
    parts = [label]
    if file_line:
        parts.append(f"@{file_line}")
    if gt_line:
        parts.append(gt_line)
    parts.extend(e_lines[:4])
    telegraphic = " | ".join(parts)
    return test_name, telegraphic, body.strip()


def _extract_block_body(block: str, *, summary_tail: str = "") -> list[tuple[str, str, str]]:
    """Return list of (test_name, telegraphic, raw_body) per failure in block."""
    headers = list(_TEST_HEADER.finditer(block))
    if headers:
        out: list[tuple[str, str, str]] = []
        for i, hm in enumerate(headers):
            start = hm.start()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(block)
            sub = block[start:end]
            out.append(_extract_sub_block(sub, hm.group(1)))
        return out

    fallback = _fallback_name_from_summary(summary_tail) or _fallback_name_from_summary(block)
    test_name, telegraphic, raw = _extract_sub_block(block, fallback)
    if not test_name and fallback:
        test_name = fallback
        telegraphic = _extract_sub_block(block, fallback)[1]
    return [(test_name, telegraphic, raw)]


def extract_pytest_blocks(lines: list[str]) -> tuple[list[str], list[tuple[int, str, str]]]:
    """Remove pytest failure blocks; return (new_lines, [(line_no, test_name, telegraphic)])."""
    text = "\n".join(lines)
    if not _FAILURES_START.search(text):
        return lines, []

    extracted: list[tuple[int, str, str]] = []
    markers: list[tuple[int, str]] = []
    out_parts: list[str] = []
    pos = 0
    trace_idx = 0
    for m in _FAILURES_START.finditer(text):
        out_parts.append(text[pos : m.start()])
        block_start = m.end()
        sm = _SHORT_SUMMARY.search(text, block_start)
        block_end = sm.start() if sm else len(text)
        block = text[block_start:block_end]
        summary_tail = text[block_end:] if sm else ""
        line_no = text[: m.start()].count("\n") + 1
        failures = _extract_block_body(block, summary_tail=summary_tail)
        insert_at = len("\n".join(out_parts).splitlines()) if out_parts else 0
        for test_name, telegraphic, _ in failures:
            trace_idx += 1
            tag = test_name or "pytest_failure"
            placeholder = f"[T{trace_idx}] pytest: {tag}"
            extracted.append((line_no, test_name, telegraphic))
            markers.append((insert_at, placeholder))
            insert_at += 1
        pos = block_end
        if sm:
            pos = sm.end()
            nxt = _FAILURES_START.search(text, pos)
            pos = nxt.start() if nxt else len(text)

    out_parts.append(text[pos:])
    cleaned_lines = [ln for ln in "\n".join(out_parts).splitlines()]
    offset = 0
    for insert_at, placeholder in markers:
        cleaned_lines.insert(min(insert_at + offset, len(cleaned_lines)), placeholder)
        offset += 1
    return cleaned_lines, extracted
