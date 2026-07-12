"""Deterministic post-distill assembly: trace reinjection + value paste."""

from __future__ import annotations

import re

from log_guard.preprocess.value_extract import ExtractedRecord
from log_guard.preprocess.value_paste import apply_paste_strategy


def apply_trace_reinjection(text: str, trace_records: list[ExtractedRecord]) -> str:
    if not trace_records:
        return text
    by_id = {r.hash_id: r for r in trace_records}
    for r in trace_records:
        if r.hash_id.isdigit():
            by_id[r.hash_id.upper()] = r

    placeholder_only = re.compile(r"^\[T(\d+)\]\s+(.+)$")
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        m = placeholder_only.match(stripped)
        if m:
            tid = m.group(1)
            rec = by_id.get(tid) or by_id.get(tid.upper())
            if rec and rec.stored_value.strip():
                out.append(rec.stored_value.splitlines()[0].strip())
                continue
        out.append(line)
    return "\n".join(out)


def assemble_output(
    text: str,
    *,
    records: list[ExtractedRecord],
    trace_records: list[ExtractedRecord],
    paste_strategy: str,
    total_lines: int,
    block_size: int,
    short_hash: bool,
    pointer_format: str,
    block_boundaries: list[tuple[int, int]] | None = None,
    merge_block_hashes: bool = False,
) -> str:
    out = apply_trace_reinjection(text, trace_records)
    if records and paste_strategy not in ("none",):
        out = apply_paste_strategy(
            out,
            records,
            paste_strategy,
            total_lines=total_lines,
            block_size=block_size,
            short_hash=short_hash,
            pointer_format=pointer_format,
            block_boundaries=block_boundaries,
            merge_block_hashes=merge_block_hashes,
        )
    return out
