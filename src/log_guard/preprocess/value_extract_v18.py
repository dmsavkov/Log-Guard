"""v0.18 value extraction: JSON islands, grouping, pointer hints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

from log_guard.preprocess.value_extract import (
    ExtractedRecord,
    ValueExtractStats,
    _scrub_entropy_tokens,
    _scrub_tensor,
    _TENSOR_RE,
    _ARRAY_PREFIX_RE,
)

_KV_PAIR_RE = re.compile(r"(?<![\w.])([a-zA-Z_][\w.]*)\s*=\s*([^\s,;|]+)")
_COLON_KV_RE = re.compile(r"(?<!\d)(?<![\w.])([A-Za-z_][\w]*):\s+([^\s\n]+)")
_KV_FREQ_SKIP_DEFAULT = 25
_KV_LINE_RE = re.compile(r"=\s*[^\s,;|]+")
_PTR_HEAD_RE = re.compile(
    r"^(\[H#([A-F0-9]+)\]|\[HASH_([A-F0-9]+)\]|\[Ref (\d+)\]|\[#(\d+)\])(?:\s+(.*))?$"
)
_NON_JSON_LINE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|===|Generating |/usr|\s+warnings\.|^\d+\.?\d*s\s+\d+)",
)
_LOG_PIPE_RE = re.compile(r"\|\s*(INFO|DEBUG|WARNING|ERROR)\s*\|")

_VALUE_GRAMMAR = r"""
    ?value: dict | tuple | list | string | SIGNED_NUMBER -> number
          | "True" -> true | "False" -> false | "None" -> null
    dict  : "{" [pair ("," pair)* [","]] "}"
    list  : "[" [value ("," value)* [","]] "]"
    tuple : "(" [value ("," value)* [","]] ")"
    pair  : string ":" value
    string: ESCAPED_STRING | "'" /[^']+/ "'"
    %import common.ESCAPED_STRING
    %import common.SIGNED_NUMBER
    %import common.WS
    %ignore WS
"""

_parser = None


def _get_lark_parser():
    global _parser
    if _parser is None:
        from lark import Lark, Transformer

        class _T(Transformer):
            def string(self, s):
                v = s[0]
                if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
                    return v[1:-1]
                return v

            def number(self, n):
                return float(n[0]) if "." in n[0] else int(n[0])

            def true(self, _):
                return True

            def false(self, _):
                return False

            def null(self, _):
                return None

            def list(self, items):
                return list(items)

            def tuple(self, items):
                return tuple(items)

            def dict(self, items):
                return dict(items)

            def pair(self, kv):
                return (kv[0], kv[1])

        _parser = Lark(_VALUE_GRAMMAR, start="value", parser="lalr", lexer="contextual", transformer=_T())
    return _parser


def _hash_id(content: str, *, short: int = 8) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:short].upper()


def _balanced_span(text: str, open_ch: str, close_ch: str, start: int = 0) -> tuple[str, int] | None:
    idx = text.find(open_ch, start)
    if idx < 0:
        return None
    depth = 0
    in_str: str | None = None
    escape = False
    for i in range(idx, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[idx : i + 1], i + 1
    return None


def _collect_keys(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            _collect_keys(v, out)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_keys(item, out)


def _try_lark_value(blob: str) -> tuple[Any | None, list[str]]:
    try:
        parsed = _get_lark_parser().parse(blob)
        keys: list[str] = []
        _collect_keys(parsed, keys)
        return parsed, sorted(set(keys))
    except Exception:
        return None, []


def _try_parse_blob(blob: str) -> tuple[Any | None, list[str]]:
    """json.loads first (with auto-close), then Lark."""
    trimmed = blob.strip()
    if not trimmed:
        return None, []
    base = trimmed.rstrip().rstrip(",")
    for suffix in ("", "]", "]}", "}", "}]}"):
        try:
            obj = json.loads(base + suffix)
            keys: list[str] = []
            _collect_keys(obj, keys)
            return obj, sorted(set(keys))
        except json.JSONDecodeError:
            continue
    return _try_lark_value(base)


def _regex_keys(blob: str) -> list[str]:
    keys = re.findall(r"['\"]?([a-zA-Z_]\w*)['\"]?\s*[:=]", blob)
    return sorted(set(keys))


def _is_non_json_line(line: str) -> bool:
    if _NON_JSON_LINE.match(line.strip()):
        return True
    return _LOG_PIPE_RE.search(line) is not None


def _is_json_fragment_line(line: str) -> bool:
    if _is_non_json_line(line):
        return False
    s = line.strip()
    if not s:
        return False
    if s in ("{", "}", "[", "]", "},", "],"):
        return True
    if re.match(r'^["\{\[\]\}]', s):
        return True
    if re.match(r"^-?\d+,?$", s):
        return True
    if re.match(r'^"[^"]+"\s*:', s):
        return True
    return bool(re.match(r"^[\s\"\'\{\}\[\]\d,.\-truefalsenull:]+$", s, re.IGNORECASE))


@dataclass
class _SpanHit:
    line_indices: list[int]
    kind: str
    blob: str
    parsed: Any | None
    keys: list[str]


def _find_json_islands(lines: list[str], cfg: "V18ExtractConfig") -> list[_SpanHit]:
    if not (cfg.enable_dict or cfg.enable_list or cfg.enable_tuple):
        return []

    hits: list[_SpanHit] = []
    occupied: set[int] = set()
    i = 0
    while i < len(lines):
        if i in occupied or not _is_json_fragment_line(lines[i]):
            i += 1
            continue
        stripped = lines[i].strip()
        if stripped not in ("{", "[") and not stripped.startswith("{"):
            i += 1
            continue
        if cfg.mode == "lark_basic" and stripped == "[":
            i += 1
            continue

        frags: list[str] = []
        indices: list[int] = []
        j = i
        while j < len(lines):
            if _is_json_fragment_line(lines[j]):
                frags.append(lines[j])
                indices.append(j)
                j += 1
            elif frags:
                break
            else:
                j += 1
        if not frags:
            i += 1
            continue

        blob = "\n".join(frags)
        parsed, keys = _try_parse_blob(blob)
        kind = "dict"
        if parsed is not None:
            kind = "dict" if isinstance(parsed, dict) else "list" if isinstance(parsed, list) else "tuple"
        else:
            keys = _regex_keys(blob)
            if not keys:
                i = j
                continue

        if kind == "dict" and not cfg.enable_dict:
            i = j
            continue
        if kind == "list" and not cfg.enable_list:
            i = j
            continue
        if kind == "tuple" and not cfg.enable_tuple:
            i = j
            continue
        if any(idx in occupied for idx in indices):
            i = j
            continue

        hits.append(_SpanHit(indices, kind, blob, parsed, keys))
        occupied.update(indices)
        i = j
    return hits


def _format_stored_value(
    *,
    parsed: Any | None,
    stored_blob: str,
    kv_pairs: list[tuple[str, str]],
) -> str:
    if parsed is not None:
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    if kv_pairs:
        return json.dumps({k: v for k, v in kv_pairs}, ensure_ascii=False)
    return stored_blob


def _is_kv_line(line: str) -> bool:
    if "pip install" in line or "==" in line or "http://" in line:
        return False
    pairs = _KV_PAIR_RE.findall(line)
    return len(pairs) >= 1 and _KV_LINE_RE.search(line) is not None


def merge_consecutive_kv_lines(lines: list[str]) -> list[str]:
    if not lines:
        return lines
    out: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if _is_kv_line(ln):
            buf.append(ln.strip())
        else:
            if buf:
                out.append(" | ".join(buf))
                buf = []
            out.append(ln)
    if buf:
        out.append(" | ".join(buf))
    return out


def _find_extractable_blobs(line: str, *, lark_dict_only: bool = False) -> list[tuple[str, str, list[str], Any | None]]:
    found: list[tuple[str, str, list[str], Any | None]] = []
    for open_ch, close_ch, kind in (("{", "}", "dict"), ("[", "]", "list"), ("(", ")", "tuple")):
        if lark_dict_only and kind != "dict":
            continue
        pos = 0
        while pos < len(line):
            span = _balanced_span(line, open_ch, close_ch, pos)
            if not span:
                break
            blob, end = span
            if len(blob) >= 8:
                parsed, keys = _try_parse_blob(blob)
                if parsed is not None:
                    found.append((kind, blob, keys, parsed))
                elif not lark_dict_only and kind == "dict":
                    rk = _regex_keys(blob)
                    if rk:
                        found.append((kind, blob, rk, None))
            pos = end if end > pos else pos + 1
    return found


def _eq_kv_pairs(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in _KV_PAIR_RE.findall(line):
        if re.fullmatch(r"-?\d+(?:\.\d+)?", v) or re.fullmatch(r"[A-Za-z_]\w*", v):
            out.append((k, v))
    return out


def _colon_kv_pairs(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in _COLON_KV_RE.findall(line):
        if (
            re.fullmatch(r"-?\d+(?:\.\d+)?", v)
            or re.fullmatch(r"[A-Za-z_]\w*", v)
            or v.startswith("/")
            or v.startswith("./")
            or v.startswith("http://")
            or v.startswith("https://")
        ):
            out.append((k, v))
    return out


def _all_kv_pairs_from_line(
    line: str,
    *,
    brackets_only: bool = False,
    extract_eq_kv: bool = True,
    extract_colon_kv: bool = True,
) -> list[tuple[str, str]]:
    if brackets_only:
        pairs: list[tuple[str, str]] = []
        for open_ch, close_ch in (("(", ")"), ("[", "]"), ("{", "}")):
            pos = 0
            while pos < len(line):
                span = _balanced_span(line, open_ch, close_ch, pos)
                if not span:
                    break
                blob, end = span
                pairs.extend(
                    _all_kv_pairs_from_line(
                        blob,
                        brackets_only=False,
                        extract_eq_kv=extract_eq_kv,
                        extract_colon_kv=extract_colon_kv,
                    )
                )
                pos = end if end > pos else pos + 1
        return pairs
    pairs = _eq_kv_pairs(line) if extract_eq_kv else []
    seen = set(pairs)
    if extract_colon_kv:
        for p in _colon_kv_pairs(line):
            if p not in seen:
                pairs.append(p)
                seen.add(p)
    return pairs


def _frequent_kv_pairs(lines: list[str], *, threshold: int = _KV_FREQ_SKIP_DEFAULT) -> set[tuple[str, str]]:
    counts: dict[tuple[str, str], int] = {}
    for ln in lines:
        for pair in _all_kv_pairs_from_line(ln):
            counts[pair] = counts.get(pair, 0) + 1
    return {pair for pair, n in counts.items() if n > threshold}


def _manual_kv_pairs(
    line: str,
    *,
    brackets_only: bool = False,
    skip_pairs: set[tuple[str, str]] | None = None,
    extract_eq_kv: bool = True,
    extract_colon_kv: bool = True,
) -> list[tuple[str, str]]:
    if brackets_only:
        pairs: list[tuple[str, str]] = []
        for open_ch, close_ch in (("(", ")"), ("[", "]"), ("{", "}")):
            pos = 0
            while pos < len(line):
                span = _balanced_span(line, open_ch, close_ch, pos)
                if not span:
                    break
                blob, end = span
                pairs.extend(
                    _manual_kv_pairs(
                        blob,
                        brackets_only=False,
                        skip_pairs=skip_pairs,
                        extract_eq_kv=extract_eq_kv,
                        extract_colon_kv=extract_colon_kv,
                    )
                )
                pos = end if end > pos else pos + 1
        return pairs
    if "pip install" in line or "==" in line:
        return []
    if "Kernel command line:" in line:
        return []
    out: list[tuple[str, str]] = []
    for pair in _all_kv_pairs_from_line(
        line,
        extract_eq_kv=extract_eq_kv,
        extract_colon_kv=extract_colon_kv,
    ):
        if skip_pairs and pair in skip_pairs:
            continue
        out.append(pair)
    return out


def _merge_value_into_dict(target: dict[str, Any], stored: str) -> None:
    try:
        val = json.loads(stored)
        if isinstance(val, dict):
            for k, v in val.items():
                target[str(k)] = v
            return
        elif isinstance(val, list):
            target[f"list_{len(target)}"] = val
            return
        else:
            target[f"value_{len(target)}"] = val
            return
    except json.JSONDecodeError:
        pass
    
    pairs = _manual_kv_pairs(stored)
    if pairs:
        for k, v in pairs:
            target[k] = v
    else:
        target[f"text_{len(target)}"] = stored


def _consolidate_group_records(records: list[ExtractedRecord]) -> list[ExtractedRecord]:
    groups = [r for r in records if r.kind == "group"]
    if len(groups) <= 1:
        return records
    merged: dict[str, Any] = {}
    for g in groups:
        _merge_value_into_dict(merged, g.stored_value)
    if not merged:
        return records
    keys = sorted(merged.keys())
    stored = json.dumps(merged, ensure_ascii=False, indent=2)
    short = len(groups[0].hash_id) <= 3
    hid = _hash_id(stored, short=3 if short else 8)
    last = groups[-1]
    consolidated = ExtractedRecord(
        hash_id=hid,
        line_no=last.line_no,
        kind="group",
        summary=f"group merged ({len(groups)} buffers, {len(keys)} keys)",
        stored_value=stored,
        original_len=len(stored),
        top_keys=keys[:3],
    )
    return [r for r in records if r.kind != "group"] + [consolidated]


def _parse_pointer_line(line: str) -> str | None:
    """Return record id from a hash-only payload line, else None."""
    m = _PTR_HEAD_RE.match(line.strip())
    if not m:
        return None
    tail = (m.group(5) or "").strip()
    if tail and ("|" in tail or len(tail) > 120 or "=" in tail):
        return None
    return m.group(2) or m.group(3) or m.group(4) or m.group(5)


def _serial_pointer_format(cfg: "V18ExtractConfig") -> bool:
    return cfg.pointer_format in ("ref", "bracket")


def _merged_hash_id(stored: str, cfg: "V18ExtractConfig", ref_counter: int) -> tuple[str, int]:
    if _serial_pointer_format(cfg):
        nxt = ref_counter + 1
        return str(nxt), nxt
    return _hash_id(stored, short=3 if cfg.short_hash else 8), ref_counter


def _record_lookup(records: list[ExtractedRecord]) -> dict[str, ExtractedRecord]:
    idx: dict[str, ExtractedRecord] = {}
    for rec in records:
        idx[rec.hash_id] = rec
        if len(rec.hash_id) <= 3:
            idx[rec.hash_id.upper()] = rec
    return idx


def _record_key_count(rec: ExtractedRecord) -> int:
    """Count keys in stored value (used for cumulative merge threshold)."""
    try:
        obj = json.loads(rec.stored_value)
        if isinstance(obj, dict):
            return len(obj)
    except (json.JSONDecodeError, TypeError):
        pass
    return max(len(rec.top_keys), 1)


def _apply_hash_stack_merge(
    lines: list[str],
    records: list[ExtractedRecord],
    threshold: int,
    cfg: "V18ExtractConfig",
) -> tuple[list[str], list[ExtractedRecord]]:
    """Merge hash lines when cumulative key count in stack reaches threshold.

    Hash lines may be interleaved with log text. On merge, earlier hash lines are
    removed; one merged pointer replaces the last hash in the stack.
    """
    if threshold <= 0:
        return lines, records

    lookup = _record_lookup(records)
    hash_slots: list[tuple[int, ExtractedRecord]] = []
    for i, ln in enumerate(lines):
        rid = _parse_pointer_line(ln)
        if rid and rid in lookup:
            hash_slots.append((i, lookup[rid]))
    if not hash_slots:
        return lines, records

    result = list(lines)
    kept: list[ExtractedRecord] = list(records)
    removed: set[str] = set()
    ref_counter = max(
        (int(r.hash_id) for r in records if _serial_pointer_format(cfg) and r.hash_id.isdigit()),
        default=0,
    )
    stack: list[tuple[int, ExtractedRecord]] = []
    key_sum = 0

    def _emit_merged(*, force: bool) -> None:
        nonlocal stack, key_sum, kept, ref_counter
        if not stack:
            return
        if len(stack) == 1:
            stack.clear()
            key_sum = 0
            return
        if not force and key_sum < threshold:
            return

        merged: dict[str, Any] = {}
        for _, rec in stack:
            _merge_value_into_dict(merged, rec.stored_value)
            removed.add(rec.hash_id)
        keys = sorted(str(k) for k in merged.keys())
        stored = json.dumps(merged, ensure_ascii=False, indent=2)
        hid, ref_counter = _merged_hash_id(stored, cfg, ref_counter)
        last_idx = stack[-1][0]
        merged_rec = ExtractedRecord(
            hash_id=hid,
            line_no=last_idx + 1,
            kind="group",
            summary=f"group ({len(stack)} hashes, {len(keys)} keys)",
            stored_value=stored,
            original_len=len(stored),
            top_keys=keys[:3],
        )
        for idx, _ in stack[:-1]:
            result[idx] = ""
        result[last_idx] = _pointer_with_keys(hid, keys, cfg)
        kept = [r for r in kept if r.hash_id not in removed]
        kept.append(merged_rec)
        lookup[hid] = merged_rec
        stack.clear()
        key_sum = 0

    for idx, rec in hash_slots:
        stack.append((idx, rec))
        key_sum += _record_key_count(rec)
        if key_sum >= threshold:
            _emit_merged(force=True)

    _emit_merged(force=True)

    ordered = [ln for ln in result if ln != ""]
    return ordered, kept


def _apply_record_key_stack_merge(
    records: list[ExtractedRecord],
    threshold: int,
    cfg: "V18ExtractConfig",
) -> list[ExtractedRecord]:
    """Merge records by line_no order when cumulative key count reaches threshold.

    Used when block_header_only keeps hash pointers out of the payload (anchor_merge).
    """
    if threshold <= 0 or not records:
        return records

    sorted_recs = sorted(records, key=lambda r: r.line_no)
    kept: list[ExtractedRecord] = []
    removed: set[str] = set()
    ref_counter = max(
        (int(r.hash_id) for r in records if _serial_pointer_format(cfg) and r.hash_id.isdigit()),
        default=0,
    )
    stack: list[ExtractedRecord] = []
    key_sum = 0

    def _emit_merged(*, force: bool) -> None:
        nonlocal stack, key_sum, kept, ref_counter
        if not stack:
            return
        if len(stack) == 1:
            kept.append(stack[0])
            stack.clear()
            key_sum = 0
            return
        if not force and key_sum < threshold:
            return

        merged: dict[str, Any] = {}
        for rec in stack:
            _merge_value_into_dict(merged, rec.stored_value)
            removed.add(rec.hash_id)
        keys = sorted(str(k) for k in merged.keys())
        stored = json.dumps(merged, ensure_ascii=False, indent=2)
        hid, ref_counter = _merged_hash_id(stored, cfg, ref_counter)
        last = stack[-1]
        kept.append(
            ExtractedRecord(
                hash_id=hid,
                line_no=last.line_no,
                kind="group",
                summary=f"group ({len(stack)} hashes, {len(keys)} keys)",
                stored_value=stored,
                original_len=len(stored),
                top_keys=keys[:3],
                block_no=stack[0].block_no,
            )
        )
        stack.clear()
        key_sum = 0

    for rec in sorted_recs:
        stack.append(rec)
        key_sum += _record_key_count(rec)
        if key_sum >= threshold:
            _emit_merged(force=True)

    _emit_merged(force=True)
    return kept


def _cap_hash_groups(
    records: list[ExtractedRecord],
    max_groups: int,
    cfg: "V18ExtractConfig",
) -> list[ExtractedRecord]:
    """Merge value records until at most max_groups non-trace hash groups remain."""
    if max_groups <= 0:
        return records
    trace_recs = [r for r in records if r.kind in ("stack_trace", "trace")]
    hash_recs = [r for r in records if r.kind not in ("stack_trace", "trace")]
    if len(hash_recs) <= max_groups:
        return records
    threshold = max(10, cfg.group_hash_buffer or 10)
    merged = _apply_record_key_stack_merge(hash_recs, threshold, cfg)
    while len(merged) > max_groups and threshold <= 1000:
        threshold += 10
        merged = _apply_record_key_stack_merge(merged, threshold, cfg)
    if len(merged) > max_groups:
        chunk = max(1, len(merged) // max_groups)
        squashed: list[ExtractedRecord] = []
        for i in range(0, len(merged), chunk):
            sub = merged[i : i + chunk]
            if len(sub) == 1:
                squashed.append(sub[0])
            else:
                squashed.extend(_apply_record_key_stack_merge(sub, 10, cfg))
        merged = squashed
    while len(merged) > max_groups:
        merged = _apply_record_key_stack_merge(merged, 1, cfg)
    return trace_recs + merged[:max_groups]


def cap_hash_groups_for_exp(
    records: list[ExtractedRecord],
    exp_cfg: dict,
) -> list[ExtractedRecord]:
    """Re-apply hash group cap after drain-KV merge appends records."""
    cfg = config_from_exp(exp_cfg)
    if cfg.max_hash_groups <= 0:
        return records
    trace_recs = [r for r in records if r.kind in ("stack_trace", "trace")]
    hash_recs = [r for r in records if r.kind not in ("stack_trace", "trace")]
    block_ids = sorted({r.block_no for r in hash_recs if r.block_no > 0})
    if len(block_ids) > 1:
        capped: list[ExtractedRecord] = list(trace_recs)
        for block_id in block_ids:
            block_recs = [r for r in hash_recs if r.block_no == block_id]
            capped.extend(_cap_hash_groups(block_recs, cfg.max_hash_groups, cfg))
        uncapped = [r for r in hash_recs if r.block_no <= 0]
        capped.extend(uncapped)
        return capped
    return _cap_hash_groups(records, cfg.max_hash_groups, cfg)


def _remap_records_after_compaction(
    records: list[ExtractedRecord],
    out: list[str],
) -> None:
    """Map record line_no from pre-compaction indices to compacted output lines.

    When extract_line_remove drops hashed lines, pointers are absent from the payload
    and the pointer-based remap cannot run; this keeps block boundaries aligned.
    """
    compact_map: dict[int, int] = {}
    compact = 0
    for i, ln in enumerate(out):
        if ln != "":
            compact += 1
        compact_map[i + 1] = compact or 1
    for rec in records:
        mapped = compact_map.get(rec.line_no)
        if mapped is not None:
            rec.line_no = mapped


def _block_index(line_no: int, bounds: list[tuple[int, int]]) -> int:
    for i, (lo, hi) in enumerate(bounds):
        if lo <= line_no <= hi:
            return i
    return max(0, len(bounds) - 1)


def _merge_record_list(records: list[ExtractedRecord]) -> ExtractedRecord | None:
    if not records:
        return None
    if len(records) == 1:
        return records[0]
    merged: dict[str, Any] = {}
    for rec in records:
        _merge_value_into_dict(merged, rec.stored_value)
    if not merged:
        return records[0]
    keys = sorted(str(k) for k in merged.keys())
    stored = json.dumps(merged, ensure_ascii=False, indent=2)
    first = min(records, key=lambda r: r.line_no)
    return ExtractedRecord(
        hash_id=first.hash_id,
        line_no=first.line_no,
        kind="group",
        summary=f"block group ({len(records)} hashes, {len(keys)} keys)",
        stored_value=stored,
        original_len=len(stored),
        top_keys=keys[:3],
        block_no=first.block_no,
    )


def finalize_records_for_blocks(
    records: list[ExtractedRecord],
    *,
    block_boundaries: list[tuple[int, int]] | None,
    block_size: int,
    total_lines: int,
    exp_cfg: dict,
) -> list[ExtractedRecord]:
    """Merge hash groups within each line block; keep multiple groups when under cap."""
    trace_recs = [r for r in records if r.kind in ("stack_trace", "trace")]
    hash_recs = [r for r in records if r.kind not in ("stack_trace", "trace")]
    if not hash_recs:
        return records

    bounds = list(block_boundaries or [])
    if not bounds and block_size > 0 and total_lines > 0:
        for start in range(0, total_lines, block_size):
            lo = start + 1
            hi = min(start + block_size, total_lines)
            bounds.append((lo, hi))
    if not bounds:
        bounds = [(1, total_lines or max(r.line_no for r in hash_recs))]

    cfg = config_from_exp(exp_cfg)
    threshold = max(10, cfg.group_hash_buffer or 10)

    by_block: dict[int, list[ExtractedRecord]] = {}
    for rec in hash_recs:
        bi = _block_index(rec.line_no, bounds)
        by_block.setdefault(bi, []).append(rec)

    per_block: list[ExtractedRecord] = []
    for bi in sorted(by_block):
        block_recs = sorted(by_block[bi], key=lambda r: r.line_no)
        merged = _apply_record_key_stack_merge(block_recs, threshold, cfg)
        if cfg.max_hash_groups > 0 and len(merged) > cfg.max_hash_groups:
            merged = _cap_hash_groups(merged, cfg.max_hash_groups, cfg)
            merged = [r for r in merged if r.kind not in ("stack_trace", "trace")]
        for rec in merged:
            rec.block_no = bi + 1
            per_block.append(rec)

    return trace_recs + per_block


@dataclass
class V18ExtractConfig:
    mode: str = "manual"
    hash_mode: str = "pointer"
    short_hash: bool = False
    minimal_pointer: bool = False
    line_replace: bool = False
    line_remove: bool = False
    kv_keep_inline: bool = False
    group_kv_close: bool = False
    group_kv_buffer: int = 0
    group_hash_buffer: int = 0
    max_hash_groups: int = 0
    min_line_len: int = 40
    pointer_format: str = "hash"
    block_header_only: bool = False
    enable_kv: bool = False
    enable_dict: bool = False
    enable_list: bool = False
    enable_tuple: bool = False
    enable_tensor: bool = False
    enable_entropy: bool = False
    kv_brackets_only: bool = False
    extract_eq_kv: bool = True
    extract_colon_kv: bool = True
    extract_pip_heuristic: bool = True


def config_from_exp(exp_cfg: dict) -> V18ExtractConfig:
    mode = str(exp_cfg.get("extract_mode", "manual"))
    return V18ExtractConfig(
        mode=mode,
        hash_mode=str(exp_cfg.get("hash_mode", "pointer")),
        short_hash=bool(exp_cfg.get("short_hash", False)),
        minimal_pointer=bool(exp_cfg.get("minimal_pointer", False)),
        line_replace=bool(exp_cfg.get("line_replace", False)),
        line_remove=bool(exp_cfg.get("extract_line_remove", False)),
        kv_keep_inline=bool(exp_cfg.get("extract_kv_keep_inline", False)),
        group_kv_close=bool(exp_cfg.get("group_kv_close", False)),
        group_kv_buffer=int(exp_cfg.get("group_kv_buffer", 0)),
        group_hash_buffer=int(exp_cfg.get("group_hash_buffer", 0)),
        max_hash_groups=int(exp_cfg.get("max_hash_groups", 0)),
        min_line_len=int(exp_cfg.get("min_hash_line_len", 40)),
        pointer_format=str(exp_cfg.get("pointer_format", "hash")),
        block_header_only=bool(exp_cfg.get("extract_block_header_only", False)),
        enable_kv=bool(exp_cfg.get("extract_kv")),
        enable_dict=bool(exp_cfg.get("extract_dict")),
        enable_list=bool(exp_cfg.get("extract_list")),
        enable_tuple=bool(exp_cfg.get("extract_tuple")),
        enable_tensor=bool(exp_cfg.get("extract_tensor")),
        enable_entropy=bool(exp_cfg.get("extract_entropy")),
        kv_brackets_only=bool(exp_cfg.get("extract_kv_brackets_only", False)),
        extract_eq_kv=bool(exp_cfg.get("extract_eq_kv", True)),
        extract_colon_kv=bool(exp_cfg.get("extract_colon_kv", True)),
        extract_pip_heuristic=bool(exp_cfg.get("extract_pip_heuristic", True)),
    )


def _pointer_token(hid: str, cfg: V18ExtractConfig) -> str:
    if cfg.pointer_format == "ref":
        return f"[Ref {hid}]"
    if cfg.pointer_format == "bracket":
        return f"[#{hid}]"
    if cfg.minimal_pointer or cfg.short_hash:
        return f"[H#{hid}]"
    return f"[HASH_{hid}]"


def _pointer_with_keys(hid: str, keys: list[str], cfg: V18ExtractConfig) -> str:
    ptr = _pointer_token(hid, cfg)
    if cfg.minimal_pointer:
        return ptr
    hint = ", ".join(sorted(keys)[:3])
    return f"{ptr} {hint}" if hint else ptr


def _keep_line_inline(cfg: V18ExtractConfig, kind: str) -> bool:
    if cfg.kv_keep_inline and kind == "kv":
        return True
    return cfg.block_header_only


def _emit_extracted_line(
    cfg: V18ExtractConfig,
    *,
    line: str,
    kind: str,
    hid: str,
    keys: list[str],
) -> str:
    if _keep_line_inline(cfg, kind):
        return line
    if cfg.line_remove:
        return ""
    if cfg.line_replace:
        return _pointer_token(hid, cfg) if cfg.minimal_pointer else _pointer_with_keys(hid, keys, cfg)
    if cfg.hash_mode == "strip":
        return "[event line]"
    return _pointer_with_keys(hid, keys, cfg)


def _use_record_merge(cfg: V18ExtractConfig) -> bool:
    return cfg.block_header_only or cfg.line_remove or cfg.kv_keep_inline


def _analyze_line(
    line: str,
    cfg: V18ExtractConfig,
    *,
    multiline_masked: bool = False,
    skip_kv_pairs: set[tuple[str, str]] | None = None,
) -> tuple[bool, str, list[str], str, str, Any | None, list[tuple[str, str]]]:
    if multiline_masked:
        return False, line, [], "", "", None, []

    original = line
    kinds: list[str] = []
    keys: list[str] = []
    stored_parts: list[str] = []
    parsed_obj: Any | None = None
    kv_pairs: list[tuple[str, str]] = []
    scrubbed = line
    lark_dict_only = cfg.mode == "lark_basic"

    if cfg.enable_tensor and (_TENSOR_RE.search(scrubbed) or _ARRAY_PREFIX_RE.search(scrubbed)):
        scrubbed, t_summaries = _scrub_tensor(scrubbed)
        if t_summaries:
            kinds.append("tensor")
            stored_parts.append(original)

    if cfg.enable_entropy:
        scrubbed, n_ent = _scrub_entropy_tokens(scrubbed)
        if n_ent:
            kinds.append("entropy")
            stored_parts.append(original)

    if cfg.enable_dict or cfg.enable_list or cfg.enable_tuple:
        for kind, blob, klist, parsed in _find_extractable_blobs(scrubbed, lark_dict_only=lark_dict_only):
            if kind == "dict" and not cfg.enable_dict:
                continue
            if kind == "list" and not cfg.enable_list:
                continue
            if kind == "tuple" and not cfg.enable_tuple:
                continue
            kinds.append(kind)
            keys.extend(klist)
            stored_parts.append(blob)
            if parsed is not None:
                parsed_obj = parsed
            scrubbed = scrubbed.replace(blob, "<MASK>", 1)

    if cfg.enable_kv:
        if cfg.extract_pip_heuristic and "pip install" in scrubbed.lower():
            pkg_blob = scrubbed.split("pip install", 1)[-1].strip()
            if pkg_blob:
                kinds.append("pip")
                keys.append("packages")
                kv_pairs = [("packages", pkg_blob)]
                stored_parts.append(pkg_blob)
        else:
            pairs = _manual_kv_pairs(
                scrubbed,
                brackets_only=cfg.kv_brackets_only,
                skip_pairs=skip_kv_pairs,
                extract_eq_kv=cfg.extract_eq_kv,
                extract_colon_kv=cfg.extract_colon_kv,
            )
            if pairs:
                kinds.append("kv")
                keys.extend(k for k, _ in pairs)
                kv_pairs = pairs
                stored_parts.append(original)

    keys = sorted(set(keys))
    if not kinds:
        return False, original, [], "", "", None, []

    stored_blob = "\n---\n".join(stored_parts) if stored_parts else original
    kind = "+".join(sorted(set(kinds)))
    return True, scrubbed, keys, kind, stored_blob, parsed_obj, kv_pairs


def extract_values_v18(
    lines: list[str],
    exp_cfg: dict,
) -> tuple[list[str], ValueExtractStats]:
    cfg = config_from_exp(exp_cfg)
    working = merge_consecutive_kv_lines(lines) if cfg.group_kv_close else list(lines)
    kv_skip_threshold = int(exp_cfg.get("kv_freq_skip_threshold", _KV_FREQ_SKIP_DEFAULT))
    skip_kv_pairs = _frequent_kv_pairs(working, threshold=kv_skip_threshold)

    stats = ValueExtractStats(lines_in=len(working), chars_before=sum(len(ln) for ln in working))
    out: list[str | None] = [None] * len(working)
    records: list[ExtractedRecord] = []
    hash_index: dict[str, ExtractedRecord] = {}
    multiline_lines: set[int] = set()
    ref_counter = 0
    hash_buffer = cfg.group_hash_buffer or cfg.group_kv_buffer

    def _new_hash_id(stored: str) -> str:
        nonlocal ref_counter
        if cfg.pointer_format == "ref":
            ref_counter += 1
            return str(ref_counter)
        if cfg.pointer_format == "bracket":
            ref_counter += 1
            return str(ref_counter)
        return _hash_id(stored, short=3 if cfg.short_hash else 8)

    for hit in _find_json_islands(working, cfg):
        for li in hit.line_indices:
            multiline_lines.add(li)
        stored = _format_stored_value(parsed=hit.parsed, stored_blob=hit.blob, kv_pairs=[])
        content_hid = _hash_id(stored, short=3 if cfg.short_hash else 8)
        if cfg.pointer_format != "ref" and cfg.pointer_format != "bracket" and content_hid in hash_index:
            hid = content_hid
        else:
            hid = _new_hash_id(stored)
            key_hint = ", ".join(hit.keys[:8]) + ("…" if len(hit.keys) > 8 else "")
            summary = f"{hit.kind}: {key_hint}" if key_hint else hit.kind
            rec = ExtractedRecord(
                hash_id=hid,
                line_no=hit.line_indices[0] + 1,
                kind=hit.kind,
                summary=summary,
                stored_value=stored,
                original_len=len(hit.blob),
                top_keys=sorted(hit.keys)[:3],
            )
            records.append(rec)
            hash_index[hid] = rec
        ptr = _pointer_with_keys(hid, hit.keys, cfg)
        last = hit.line_indices[-1]
        if _keep_line_inline(cfg, hit.kind):
            for li in hit.line_indices:
                out[li] = working[li].rstrip("\n")
        elif cfg.line_remove:
            for li in hit.line_indices:
                out[li] = ""
        else:
            for li in hit.line_indices:
                out[li] = "" if li != last else ptr
        stats.lines_hashed += len(hit.line_indices)

    group_buf: list[tuple[int, list[str], str, dict[str, Any]]] = []

    def _flush_group_buffer() -> None:
        if not group_buf:
            return
        merged: dict[str, Any] = {}
        for _, _, stored, kv in group_buf:
            if kv:
                merged.update(kv)
            else:
                _merge_value_into_dict(merged, stored)
        keys = sorted(str(k) for k in merged.keys())
        stored = json.dumps(merged, ensure_ascii=False, indent=2)
        last_idx = group_buf[-1][0]
        hid = _new_hash_id(stored)
        rec = ExtractedRecord(
            hash_id=hid,
            line_no=last_idx + 1,
            kind="group",
            summary=f"group ({len(group_buf)} items, {len(keys)} keys)",
            stored_value=stored,
            original_len=len(stored),
            top_keys=keys[:3],
        )
        records.append(rec)
        hash_index[hid] = rec
        stats.lines_hashed += len(group_buf)
        ptr = _pointer_with_keys(hid, keys, cfg)
        for j, (idx, _, _, _) in enumerate(group_buf):
            out[idx] = ptr if j == len(group_buf) - 1 else ""
        group_buf.clear()

    for i, raw in enumerate(working):
        if out[i] is not None:
            continue
        line = raw.rstrip("\n")
        possible, scrubbed, keys, kind, stored_blob, parsed, kv_pairs = _analyze_line(
            line,
            cfg,
            multiline_masked=i in multiline_lines,
            skip_kv_pairs=skip_kv_pairs,
        )
        if not possible:
            if group_buf:
                _flush_group_buffer()
            out[i] = line
            continue

        heavy = cfg.line_replace or len(line) >= cfg.min_line_len or len(scrubbed) < len(line) * 0.85
        if not heavy:
            out[i] = line
            continue

        kv_dict = {k: v for k, v in kv_pairs} if kv_pairs else {}
        stored = _format_stored_value(parsed=parsed, stored_blob=stored_blob, kv_pairs=kv_pairs)

        # Inline buffer only for manual KV-only (exhaustive uses post-pass hash stack merge).
        inline_buffer = hash_buffer > 0 and cfg.mode == "manual" and cfg.enable_kv and not cfg.enable_dict
        if inline_buffer:
            group_buf.append((i, keys, stored, kv_dict))
            if len(group_buf) >= hash_buffer:
                _flush_group_buffer()
            continue

        hid = _new_hash_id(stored)
        if hid in hash_index:
            out[i] = _emit_extracted_line(
                cfg, line=line, kind=kind, hid=hid, keys=hash_index[hid].top_keys or keys
            )
            continue

        key_hint = ", ".join(keys[:3]) + ("…" if len(keys) > 3 else "")
        summary = f"{kind}: {key_hint}" if key_hint else kind
        rec = ExtractedRecord(
            hash_id=hid,
            line_no=i + 1,
            kind=kind,
            summary=summary,
            stored_value=stored,
            original_len=len(line),
            top_keys=keys[:3],
        )
        records.append(rec)
        hash_index[hid] = rec
        stats.lines_hashed += 1
        out[i] = _emit_extracted_line(cfg, line=line, kind=kind, hid=hid, keys=keys)

    if group_buf:
        _flush_group_buffer()

    ordered: list[str] = []
    for i, ln in enumerate(out):
        if ln == "":
            continue
        if ln is None:
            ordered.append(working[i].rstrip("\n"))
        else:
            ordered.append(ln)

    # Post-pass: merge consecutive hash-only lines (exhaustive + buffer experiments).
    manual_inline_buffer = (
        hash_buffer > 0 and cfg.mode == "manual" and cfg.enable_kv and not cfg.enable_dict
    )
    if hash_buffer > 0 and not manual_inline_buffer:
        if _use_record_merge(cfg):
            records = _apply_record_key_stack_merge(records, hash_buffer, cfg)
        else:
            ordered, records = _apply_hash_stack_merge(ordered, records, hash_buffer, cfg)

    if cfg.max_hash_groups > 0:
        records = _cap_hash_groups(records, cfg.max_hash_groups, cfg)

    _remap_records_after_compaction(records, out)
    lookup = _record_lookup(records)
    for line_no, ln in enumerate(ordered, start=1):
        rid = _parse_pointer_line(ln)
        if rid and rid in lookup:
            lookup[rid].line_no = line_no

    stats.records = records
    stats.chars_after = sum(len(x) for x in ordered)
    logger.info("value_extract_v18: {} hashed / {} lines, {} records", stats.lines_hashed, stats.lines_in, len(records))
    return ordered, stats


def stats_dict(stats: ValueExtractStats) -> dict:
    d = asdict(stats)
    d.pop("records", None)
    d["record_count"] = len(stats.records)
    return d
