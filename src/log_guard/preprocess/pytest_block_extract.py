"""Simplified pytest failure block extractor (FAILURES → short test summary)."""

from __future__ import annotations

import re

_FAILURES_START = re.compile(r"^=+\s*FAILURES\s*=+\s*$", re.MULTILINE)
_SHORT_SUMMARY = re.compile(r"^=+\s*short test summary info\s*=+\s*$", re.MULTILINE | re.IGNORECASE)
_TEST_HEADER = re.compile(r"^_{3,}\s+(.+?)\s+_{3,}$", re.MULTILINE)
_CAPTURED_STDOUT = re.compile(r"^--- Captured stdout ---\s*$", re.MULTILINE)


def _extract_block_body(block: str) -> tuple[str, str, str]:
    """Return (test_name, telegraphic, raw_body_before_captured)."""
    test_name = ""
    m = _TEST_HEADER.search(block)
    if m:
        test_name = m.group(1).strip()

    body = block
    cap = _CAPTURED_STDOUT.search(body)
    if cap:
        body = body[: cap.start()]

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

    parts = [f"pytest_failure: {test_name}" if test_name else "pytest_failure"]
    if gt_line:
        parts.append(gt_line)
    parts.extend(e_lines)
    telegraphic = " | ".join(parts) if len(parts) > 1 else parts[0]
    return test_name, telegraphic, body.strip()


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
        line_no = text[: m.start()].count("\n") + 1
        test_name, telegraphic, _ = _extract_block_body(block)
        trace_idx += 1
        placeholder = f"[T{trace_idx}] pytest: {test_name}" if test_name else f"[T{trace_idx}] pytest_failure"
        extracted.append((line_no, test_name, telegraphic))
        insert_at = len("\n".join(out_parts).splitlines()) if out_parts else 0
        markers.append((insert_at, placeholder))
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
