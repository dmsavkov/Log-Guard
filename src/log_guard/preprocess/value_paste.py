"""Post-distillation strategies for re-attaching extracted value hashes (v0.15)."""

from __future__ import annotations

import json
import re

from log_guard.preprocess.value_extract import ExtractedRecord

_LINE_RANGE_RE = re.compile(r"\[Lines?\s+(\d+)\s*(?:-\s*(\d+))?\]", re.IGNORECASE)
_BLOCK_RE = re.compile(r"\[Block\s+(\d+)\s*-\s*(\d+)\]", re.IGNORECASE)
_BLOCK_HEADING_RE = re.compile(r"^### Block (\d+)\s*$", re.MULTILINE)
_HASH_PTR_RE = re.compile(
    r"\[H#([A-F0-9]{3,8})\]|\[HASH_([A-F0-9]{8})\]|\[Ref (\d+)\]|\[#(\d+)\]"
)
_HASH_STRIP_RE = re.compile(
    r"\s*\[H#[A-F0-9]{3,8}\](?:\s+[^|\n]+)?"
    r"|\s*\[HASH_[A-F0-9]{8}\](?:\s+[^|\n]+)?"
    r"|\s*\[Ref \d+\](?:\s+[^|\n]+)?"
    r"|\s*\[#\d+\](?:\s+[^|\n]+)?"
)
_BLOCK_RANGE_HEAD_RE = re.compile(r"^\[Block (\d+)-\d+\]", re.MULTILINE)
_TRACE_KINDS = frozenset({"stack_trace", "trace"})


def _split_even(items: list[ExtractedRecord], n: int) -> list[list[ExtractedRecord]]:
    if not items:
        return [[] for _ in range(max(n, 0))]
    if n <= 1:
        return [items]
    chunks: list[list[ExtractedRecord]] = []
    base, extra = divmod(len(items), n)
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        chunks.append(items[start : start + size])
        start += size
    return chunks


def add_line_numbers(lines: list[str]) -> str:
    return "\n".join(f"L{i:05d} | {ln}" for i, ln in enumerate(lines, start=1))


def _ptr_token(rec: ExtractedRecord, *, short_hash: bool = False, pointer_format: str = "hash") -> str:
    if pointer_format == "ref":
        return f"[Ref {rec.hash_id}]"
    if pointer_format == "bracket":
        return f"[#{rec.hash_id}]"
    if short_hash or len(rec.hash_id) <= 3:
        return f"[H#{rec.hash_id}]"
    return f"[HASH_{rec.hash_id}]"


def _ptr_label(rec: ExtractedRecord, *, short_hash: bool = False, pointer_format: str = "hash") -> str:
    tok = _ptr_token(rec, short_hash=short_hash, pointer_format=pointer_format)
    keys = ", ".join(sorted(rec.top_keys)[:3])
    return f"{tok} {keys}" if keys else tok


def _available_params_line(
    rec: ExtractedRecord,
    *,
    short_hash: bool = False,
    pointer_format: str = "hash",
) -> str:
    tok = _ptr_token(rec, short_hash=short_hash, pointer_format=pointer_format)
    keys = _first_keys(rec, limit=5)
    more = bool(rec.top_keys and len(rec.top_keys) > 5)
    try:
        obj = json.loads(rec.stored_value)
        if isinstance(obj, dict) and len(obj) > 5:
            more = True
    except (json.JSONDecodeError, TypeError):
        pass
    preview = ", ".join(keys) if keys else ""
    if more and preview:
        preview += "..."
    return f"{tok} {preview}".strip()


def _first_keys(rec: ExtractedRecord, limit: int = 5) -> list[str]:
    if rec.top_keys:
        return sorted(rec.top_keys)[:limit]
    try:
        obj = json.loads(rec.stored_value)
        if isinstance(obj, dict):
            return sorted(str(k) for k in obj.keys())[:limit]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _merge_records(records: list[ExtractedRecord]) -> ExtractedRecord | None:
    if not records:
        return None
    if len(records) == 1:
        return records[0]
    merged: dict = {}
    for rec in records:
        try:
            obj = json.loads(rec.stored_value)
            if isinstance(obj, dict):
                merged.update(obj)
        except (json.JSONDecodeError, TypeError):
            continue
    if not merged:
        return records[0]
    keys = sorted(str(k) for k in merged.keys())
    stored = json.dumps(merged, ensure_ascii=False, indent=2)
    last = records[-1]
    return ExtractedRecord(
        hash_id=last.hash_id,
        line_no=last.line_no,
        kind="group",
        summary=f"block group ({len(records)} hashes, {len(keys)} keys)",
        stored_value=stored,
        original_len=len(stored),
        top_keys=keys[:3],
    )


def paste_line_anchor(distillation: str, records: list[ExtractedRecord], *, short_hash: bool = False) -> str:
    """Inject hash refs after [Lines X-Y] markers when reducer emitted them."""
    if not records:
        return distillation

    by_line = {r.line_no: r for r in records}

    def _inject(match: re.Match[str]) -> str:
        start = int(match.group(1))
        end = int(match.group(2) or start)
        hits = [by_line[ln] for ln in range(start, end + 1) if ln in by_line]
        if not hits:
            return match.group(0)
        seen: set[str] = set()
        refs: list[str] = []
        for h in hits:
            if h.hash_id in seen:
                continue
            seen.add(h.hash_id)
            refs.append(_ptr_label(h, short_hash=short_hash))
        return f"{match.group(0)} {' '.join(refs[:3])}"

    out = _LINE_RANGE_RE.sub(_inject, distillation)
    if out != distillation:
        return out
    return _append_hash_footer(distillation, records, short_hash=short_hash)


def paste_line_anchor_block(distillation: str, records: list[ExtractedRecord], *, short_hash: bool = False) -> str:
    """Inject block-level hash refs after [Block N-M] markers in distillation."""
    if not records:
        return distillation

    def _inject(match: re.Match[str]) -> str:
        lo, hi = int(match.group(1)), int(match.group(2))
        in_block = [r for r in records if lo <= r.line_no <= hi]
        if not in_block:
            return match.group(0)
        seen: set[str] = set()
        refs: list[str] = []
        for r in in_block:
            if r.hash_id in seen:
                continue
            seen.add(r.hash_id)
            refs.append(_ptr_label(r, short_hash=short_hash))
        if not refs:
            return match.group(0)
        return match.group(0) + "\n" + "\n".join(refs[:5])

    out = _BLOCK_RE.sub(_inject, distillation)
    if out != distillation:
        return out
    return paste_line_anchor(distillation, records, short_hash=short_hash)


def _append_hash_footer(distillation: str, records: list[ExtractedRecord], *, short_hash: bool = False) -> str:
    """Fallback: weave unique pointers into distillation (not a separate appendix file)."""
    seen: set[str] = set()
    refs: list[str] = []
    for r in records:
        if r.hash_id in seen:
            continue
        seen.add(r.hash_id)
        refs.append(_ptr_label(r, short_hash=short_hash))
    if not refs:
        return distillation
    return distillation.rstrip() + "\n\n[CONTEXT POINTERS]: " + " ".join(refs[:12])


def paste_available_params_block(
    distillation: str,
    records: list[ExtractedRecord],
    *,
    short_hash: bool = False,
    pointer_format: str = "hash",
    merge_block_hashes: bool = False,
) -> str:
    """Append 'Available params: … First 5: …' after each [Block N-M] marker."""
    if not records:
        return distillation

    def _inject(match: re.Match[str]) -> str:
        lo, hi = int(match.group(1)), int(match.group(2))
        in_block = [r for r in records if lo <= r.line_no <= hi]
        if not in_block:
            return match.group(0)
        seen: set[str] = set()
        unique: list[ExtractedRecord] = []
        for r in in_block:
            if r.hash_id in seen:
                continue
            seen.add(r.hash_id)
            unique.append(r)
        if merge_block_hashes and len(unique) > 1:
            merged = _merge_records(unique)
            unique = [merged] if merged else unique[:1]
        lines = [match.group(0)]
        if unique:
            lines.append("Extracted Values:")
            for rec in unique:
                lines.append(_available_params_line(rec, short_hash=short_hash, pointer_format=pointer_format))
        return "\n".join(lines)

    return _BLOCK_RE.sub(_inject, distillation)


def paste_block_heading_params(
    distillation: str,
    records: list[ExtractedRecord],
    *,
    block_size: int,
    total_lines: int,
    short_hash: bool = False,
    pointer_format: str = "hash",
    block_boundaries: list[tuple[int, int]] | None = None,
    merge_block_hashes: bool = True,
) -> str:
    """Append 'Extracted Values:' after ### Block N markers."""
    if not records or block_size <= 0 and not block_boundaries:
        return distillation

    bounds = list(block_boundaries or [])
    if not bounds and block_size > 0:
        for start in range(0, total_lines, block_size):
            lo = start + 1
            hi = min(start + block_size, total_lines)
            bounds.append((lo, hi))

    hash_records = sorted(
        [r for r in records if r.kind not in _TRACE_KINDS],
        key=lambda r: (r.block_no, r.line_no),
    )
    heading_count = len(_BLOCK_HEADING_RE.findall(distillation)) or 1
    heading_chunks = _split_even(hash_records, heading_count) if heading_count > 1 else []
    distinct_block_nos = {r.block_no for r in hash_records if r.block_no > 0}
    # Only trust block_no when multiple physical blocks exist (not one block with all records).
    use_block_no = len(distinct_block_nos) > 1

    def _format_records(marker: str, block_recs: list[ExtractedRecord]) -> str:
        if not block_recs:
            return marker
        seen: set[str] = set()
        unique: list[ExtractedRecord] = []
        for r in block_recs:
            if r.hash_id in seen:
                continue
            seen.add(r.hash_id)
            unique.append(r)
        if merge_block_hashes and len(unique) > 1:
            merged = _merge_records(unique)
            unique = [merged] if merged else unique[:1]
        lines = [marker]
        if unique:
            lines.append("Extracted Values:")
            for rec in unique:
                lines.append(_available_params_line(rec, short_hash=short_hash, pointer_format=pointer_format))
        return "\n".join(lines)

    def _records_for_heading(block_num: int, lo: int, hi: int) -> list[ExtractedRecord]:
        if use_block_no:
            by_block_no = [r for r in hash_records if r.block_no == block_num]
            if by_block_no:
                return by_block_no
        if heading_count > 1 and heading_chunks and 1 <= block_num <= len(heading_chunks):
            return heading_chunks[block_num - 1]
        return [r for r in hash_records if lo <= r.line_no <= hi]

    def _params_for_block_num(block_num: int, marker: str) -> str:
        if block_num <= 0 or block_num > len(bounds):
            lo = (block_num - 1) * block_size + 1
            hi = min(block_num * block_size, total_lines)
        else:
            lo, hi = bounds[block_num - 1]
        block_recs = _records_for_heading(block_num, lo, hi)
        return _format_records(marker, block_recs)

    def _inject_heading(match: re.Match[str]) -> str:
        return _params_for_block_num(int(match.group(1)), match.group(0))

    def _inject_range(match: re.Match[str]) -> str:
        lo = int(match.group(1))
        block_num = next((i + 1 for i, (blo, _) in enumerate(bounds) if blo == lo), None)
        if block_num is None and block_size > 0:
            block_num = (lo - 1) // block_size + 1
        if block_num is None:
            hi = int(match.group(0).split("-", 1)[-1].rstrip("]"))
            block_recs = [r for r in hash_records if lo <= r.line_no <= hi]
            return _format_records(match.group(0), block_recs)
        return _params_for_block_num(block_num, match.group(0))

    out = _BLOCK_HEADING_RE.sub(_inject_heading, distillation)
    if out == distillation:
        out = _BLOCK_RANGE_HEAD_RE.sub(_inject_range, distillation)
    return out


def _format_block_header(lo: int, hi: int, ptrs: list[str]) -> str:
    header = f"[Block {lo}-{hi}]"
    if ptrs:
        header += "\n" + "\n".join(ptrs)
    return header


def build_block_payload(
    lines: list[str],
    records: list[ExtractedRecord],
    *,
    block_size: int = 300,
    block_boundaries: list[tuple[int, int]] | None = None,
    short_hash: bool = False,
    pointer_format: str = "hash",
    merge_block_hashes: bool = False,
    include_pointers: bool = True,
) -> str:
    """Block headers; optional pointers on separate lines under header; body is log text."""
    by_line = {r.line_no: r for r in records}
    n = len(lines)
    bounds = block_boundaries
    if not bounds:
        bounds = []
        for start in range(0, n, max(block_size, 1)):
            lo = start + 1
            hi = min(start + block_size, n)
            bounds.append((lo, hi))

    chunks: list[str] = []
    for lo, hi in bounds:
        chunk = lines[lo - 1 : hi]
        in_block = [by_line[n] for n in range(lo, hi + 1) if n in by_line]
        ptrs: list[str] = []
        seen: set[str] = set()
        block_recs: list[ExtractedRecord] = []
        for r in in_block:
            if r.hash_id in seen:
                continue
            seen.add(r.hash_id)
            block_recs.append(r)
        if merge_block_hashes and len(block_recs) > 1:
            merged = _merge_records(block_recs)
            block_recs = [merged] if merged else block_recs[:1]
        for r in block_recs:
            ptrs.append(_ptr_label(r, short_hash=short_hash, pointer_format=pointer_format))
        header = _format_block_header(lo, hi, ptrs if include_pointers else [])
        if include_pointers:
            body_lines = [_HASH_STRIP_RE.sub("", ln).strip() for ln in chunk]
        else:
            body_lines = [ln.strip() for ln in chunk]
        body_lines = [ln for ln in body_lines if ln]
        chunks.append(f"{header}\n" + "\n".join(body_lines))
    return "\n\n".join(chunks)


def _top_keys_from_record(rec: ExtractedRecord) -> list[str]:
    if rec.top_keys:
        return sorted(rec.top_keys)[:3]
    return []


def paste_minimal_keys(distillation: str, records: list[ExtractedRecord]) -> str:
    """Inline first 3 keys immediately after each [H#...] pointer."""
    if not records:
        return distillation
    by_id = {r.hash_id: r for r in records}

    def _inline(match: re.Match[str]) -> str:
        hid = match.group(1) or match.group(2) or match.group(3) or match.group(4)
        rec = by_id.get(hid) or by_id.get(hid[:3] if hid else "")
        if not rec:
            return match.group(0)
        keys = _top_keys_from_record(rec)
        if not keys:
            return match.group(0)
        return f"{match.group(0)} ({', '.join(keys)})"

    return _HASH_PTR_RE.sub(_inline, distillation)


def apply_paste_strategy(
    distillation: str,
    records: list[ExtractedRecord],
    strategy: str,
    *,
    total_lines: int = 0,
    block_size: int = 0,
    short_hash: bool = False,
    pointer_format: str = "hash",
    merge_block_hashes: bool = False,
    block_boundaries: list[tuple[int, int]] | None = None,
) -> str:
    if strategy == "none" or not records:
        return distillation
    if strategy == "line_anchor":
        return paste_line_anchor(distillation, records, short_hash=short_hash)
    if strategy == "line_anchor_block":
        return paste_line_anchor_block(distillation, records, short_hash=short_hash)
    if strategy == "available_params_block":
        return paste_available_params_block(
            distillation,
            records,
            short_hash=short_hash,
            pointer_format=pointer_format,
            merge_block_hashes=merge_block_hashes,
        )
    if strategy == "block_heading_params":
        return paste_block_heading_params(
            distillation,
            records,
            block_size=block_size,
            total_lines=total_lines,
            short_hash=short_hash,
            pointer_format=pointer_format,
            block_boundaries=block_boundaries,
            merge_block_hashes=merge_block_hashes,
        )
    if strategy == "minimal_keys":
        return paste_minimal_keys(distillation, records)
    if strategy == "pointer":
        return _append_hash_footer(distillation, records, short_hash=short_hash)
    raise ValueError(f"Unknown paste strategy: {strategy}")
