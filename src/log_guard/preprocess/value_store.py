"""Save extracted value records as JSON keyed by hash id."""

from __future__ import annotations

import json
from typing import Any

from log_guard.preprocess.value_extract import ExtractedRecord


def records_to_store(records: list[ExtractedRecord]) -> dict[str, Any]:
    """Build {hash_id: {line_no, kind, keys, value}} without truncation."""
    store: dict[str, Any] = {}
    seen: set[str] = set()
    for rec in records:
        if rec.hash_id in seen:
            continue
        seen.add(rec.hash_id)
        entry: dict[str, Any] = {
            "line_no": rec.line_no,
            "kind": rec.kind,
            "keys": list(rec.top_keys),
            "summary": rec.summary,
        }
        if rec.block_no > 0:
            entry["block_no"] = rec.block_no
        try:
            entry["value"] = json.loads(rec.stored_value)
        except json.JSONDecodeError:
            entry["value"] = rec.stored_value
        store[rec.hash_id] = entry
    return store


def save_extracted_values_json(session, records: list[ExtractedRecord]) -> None:
    if not records:
        return
    payload = json.dumps(records_to_store(records), ensure_ascii=False, indent=2)
    session.save_intermediate("extracted_values.json", payload)
