"""Merge Drain extract_parameters into the shared [#N] value registry (Phase 5)."""

from __future__ import annotations

import json
import re

from drain3.template_miner import ExtractedParameter

from log_guard.preprocess.value_extract import ExtractedRecord
from log_guard.preprocess.value_extract_v18 import _hash_id

# Drain mask tokens in mined templates, e.g. <:IP:> or <:*:>
_DRAIN_MASK_TOKEN = re.compile(r"<\:([^:]*)\:")
# drain3 join tokens with spaces, splitting <:NAME:> into "<", "NAME", ">"
_SPLIT_MASK_TOKEN = re.compile(r"<\s+([^>]+?)\s+>")
_RLE_PREFIX = re.compile(r"^(\[x\d+\]\s*)")
# sequence-collapse templates use <MASK> after drain_dedup._normalize_template
_NORM_MASK = re.compile(r"<MASK>")


def _fix_drain_template(tpl: str, *, prefix: str = "<:", suffix: str = ":>") -> str:
    """Rejoin mask tokens that drain3 split across whitespace (e.g. '< IP >' → '<:IP:>')."""
    return _SPLIT_MASK_TOKEN.sub(lambda m: f"{prefix}{m.group(1).strip()}{suffix}", tpl)


def _template_has_drain_params(tpl: str, *, prefix: str = "<:", suffix: str = ":>") -> bool:
    fixed = _fix_drain_template(tpl, prefix=prefix, suffix=suffix)
    return bool(_DRAIN_MASK_TOKEN.search(fixed))


def _extract_drain_params(
    miner,
    tpl: str,
    line: str,
) -> list[ExtractedParameter] | None:
    """Extract Drain params without drain3 delimiter substitution (breaks IPs/paths)."""
    prefix = miner.config.mask_prefix
    suffix = miner.config.mask_suffix
    fixed = _fix_drain_template(tpl, prefix=prefix, suffix=suffix)
    if not _template_has_drain_params(fixed, prefix=prefix, suffix=suffix):
        return None
    template_regex, param_group_name_to_mask_name = miner._get_template_parameter_extraction_regex(
        fixed, False
    )
    parameter_match = re.match(template_regex, line)
    if not parameter_match:
        return None
    extracted: list[ExtractedParameter] = []
    for group_name, parameter in parameter_match.groupdict().items():
        if group_name in param_group_name_to_mask_name and parameter is not None:
            mask_name = param_group_name_to_mask_name[group_name]
            extracted.append(ExtractedParameter(parameter, mask_name))
    return extracted or None


def _param_dict(extracted: list[ExtractedParameter]) -> tuple[dict[str, str], list[str]]:
    """Build stored JSON + synthetic keys from Drain ExtractedParameter list."""
    obj: dict[str, str] = {}
    keys: list[str] = []
    for j, ep in enumerate(extracted):
        key = ep.mask_name.lower() if ep.mask_name and ep.mask_name != "*" else f"val_{j}"
        if key in obj:
            key = f"val_{j}"
        obj[key] = ep.value
        keys.append(key)
    return obj, keys


def _pointer(hid: str, *, pointer_format: str = "bracket") -> str:
    if pointer_format == "bracket":
        return f"[#{hid}]"
    if pointer_format == "ref":
        return f"[Ref {hid}]"
    return f"[H#{hid}]"


def _normalize_template_body(tpl: str) -> str:
    """Match drain_dedup sequence-collapse display form (<:MASK:> → <MASK>)."""
    return _DRAIN_MASK_TOKEN.sub("<MASK>", _fix_drain_template(tpl))


def collect_drain_kv_records(
    miner,
    masked_lines: list[str],
    cids: list[int],
    clusters: dict[int, dict],
    *,
    source_lines: list[str] | None = None,
    short_hash: bool = True,
    pointer_format: str = "bracket",
) -> tuple[list[ExtractedRecord], dict[str, str], dict[int, str]]:
    """Walk clustered lines; register unique Drain parameter blobs as kind=drain records."""
    values = source_lines if source_lines is not None else masked_lines
    stored_to_hid: dict[str, str] = {}
    cid_to_hid: dict[int, str] = {}
    records: list[ExtractedRecord] = []
    seen_hid: set[str] = set()

    for i, (masked, cid) in enumerate(zip(masked_lines, cids, strict=True)):
        if cid < 0 or not masked.strip():
            continue
        tpl = clusters[cid]["template"]
        if not _template_has_drain_params(tpl, prefix=miner.config.mask_prefix, suffix=miner.config.mask_suffix):
            continue
        line = values[i] if i < len(values) else masked
        extracted = _extract_drain_params(miner, tpl, line)
        if not extracted and line != masked:
            extracted = _extract_drain_params(miner, tpl, masked)
        if not extracted:
            continue
        obj, keys = _param_dict(extracted)
        if not obj:
            continue
        stored = json.dumps(obj, ensure_ascii=False, sort_keys=True)
        hid = stored_to_hid.get(stored)
        if not hid:
            hid = _hash_id(stored, short=3 if short_hash else 8)
            stored_to_hid[stored] = hid
        cid_to_hid.setdefault(cid, hid)
        if hid in seen_hid:
            continue
        seen_hid.add(hid)
        records.append(
            ExtractedRecord(
                hash_id=hid,
                line_no=i + 1,
                kind="drain",
                summary=f"drain params ({len(keys)} vals)",
                stored_value=stored,
                original_len=len(stored),
                top_keys=keys[:5],
            )
        )
    return records, stored_to_hid, cid_to_hid


def _sample_line_for_cid(
    cid: int,
    cids: list[int],
    lines: list[str],
) -> str | None:
    for i, c in enumerate(cids):
        if c == cid and lines[i].strip():
            return lines[i]
    return None


def _pointerize_template_body(
    body: str,
    *,
    miner,
    clusters: dict[int, dict],
    cid_to_hid: dict[int, str],
    source_lines: list[str],
    masked_lines: list[str],
    cids: list[int],
    stored_to_hid: dict[str, str],
    pointer_format: str,
    short_hash: bool,
) -> str:
    """Replace drain mask tokens or <MASK> placeholders with [#N] pointers."""
    if "<:" not in body and "<MASK>" not in body:
        return body

    matched_cid: int | None = None
    norm_body = body
    for cid in clusters:
        norm_tpl = _normalize_template_body(clusters[cid]["template"])
        if norm_tpl == norm_body or norm_tpl in norm_body:
            matched_cid = cid
            break
    if matched_cid is None and "<:" in body:
        for cid, cluster in clusters.items():
            fixed = _fix_drain_template(
                cluster["template"],
                prefix=miner.config.mask_prefix,
                suffix=miner.config.mask_suffix,
            )
            if fixed in body or _DRAIN_MASK_TOKEN.sub("<MASK>", fixed) in body:
                matched_cid = cid
                break

    if matched_cid is None:
        return body

    hid = cid_to_hid.get(matched_cid)
    if not hid:
        sample = _sample_line_for_cid(matched_cid, cids, source_lines)
        masked_sample = _sample_line_for_cid(matched_cid, cids, masked_lines)
        tpl = clusters[matched_cid]["template"]
        extracted = None
        if sample:
            extracted = _extract_drain_params(miner, tpl, sample)
        if not extracted and masked_sample and masked_sample != sample:
            extracted = _extract_drain_params(miner, tpl, masked_sample)
        if extracted:
            obj, _ = _param_dict(extracted)
            stored = json.dumps(obj, ensure_ascii=False, sort_keys=True)
            hid = stored_to_hid.get(stored) or _hash_id(stored, short=3 if short_hash else 8)
            stored_to_hid[stored] = hid
            cid_to_hid[matched_cid] = hid
    if not hid:
        return body

    ptr = _pointer(hid, pointer_format=pointer_format)
    new_body = body
    if "<:" in new_body:
        fixed = _fix_drain_template(
            clusters[matched_cid]["template"],
            prefix=miner.config.mask_prefix,
            suffix=miner.config.mask_suffix,
        )
        mask_count = len(_DRAIN_MASK_TOKEN.findall(fixed))
        for _ in range(mask_count):
            new_body = _DRAIN_MASK_TOKEN.sub(ptr, new_body, count=1)
    while "<MASK>" in new_body:
        new_body = _NORM_MASK.sub(ptr, new_body, count=1)
    return new_body


def pointerize_rle_timeline(
    timeline: list[str],
    *,
    miner,
    masked_lines: list[str],
    cids: list[int],
    clusters: dict[int, dict],
    stored_to_hid: dict[str, str],
    cid_to_hid: dict[int, str] | None = None,
    source_lines: list[str] | None = None,
    pointer_format: str = "bracket",
    short_hash: bool = True,
) -> list[str]:
    """Replace <:MASK:> / <MASK> tokens in [xN] RLE lines with [#N] pointers from Drain params."""
    values = source_lines if source_lines is not None else masked_lines
    cid_hids = dict(cid_to_hid or {})
    out: list[str] = []

    for line in timeline:
        if "<:" not in line and "<MASK>" not in line:
            out.append(line)
            continue
        m = _RLE_PREFIX.match(line)
        prefix = m.group(1) if m else ""
        body = line[len(prefix) :] if m else line

        if " → " in body:
            parts = body.split(" → ")
            new_parts = [
                _pointerize_template_body(
                    part,
                    miner=miner,
                    clusters=clusters,
                    cid_to_hid=cid_hids,
                    source_lines=values,
                    masked_lines=masked_lines,
                    cids=cids,
                    stored_to_hid=stored_to_hid,
                    pointer_format=pointer_format,
                    short_hash=short_hash,
                )
                for part in parts
            ]
            out.append(f"{prefix}{' → '.join(new_parts)}".rstrip())
            continue

        new_body = _pointerize_template_body(
            body,
            miner=miner,
            clusters=clusters,
            cid_to_hid=cid_hids,
            source_lines=values,
            masked_lines=masked_lines,
            cids=cids,
            stored_to_hid=stored_to_hid,
            pointer_format=pointer_format,
            short_hash=short_hash,
        )
        out.append(f"{prefix}{new_body}".rstrip())
    return out


def merge_drain_records(
    lark_records: list[ExtractedRecord],
    drain_records: list[ExtractedRecord],
) -> list[ExtractedRecord]:
    """Append drain-sourced records; skip hash_ids already present from Lark extract."""
    seen = {r.hash_id for r in lark_records}
    merged = list(lark_records)
    for rec in drain_records:
        if rec.hash_id not in seen:
            merged.append(rec)
            seen.add(rec.hash_id)
    return merged
