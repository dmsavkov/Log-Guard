"""v3 pipeline configuration (production)."""

from __future__ import annotations

from log_guard.preprocess.chars_v22_config import CharsV22Config, baseline_v2_exp_cfg

DEFAULT_DISTILL_MODEL = "gemini-3.1-flash-lite"


def build_v3_config() -> dict:
    """Canonical v3 full pipeline config for lg CLI."""
    return {
        "model": DEFAULT_DISTILL_MODEL,
        "temperature": 0.2,
        "skip_filter": True,
        "length_route_v23": True,
        **CharsV22Config.baseline().to_exp_cfg(),
        "stacktrace_mode": "schema_det_telegraphic",
        "stacktrace_extended_patterns": True,
        "preserve_trace_markers": True,
        "value_extract": True,
        "extract_mode": "exhaustive_total",
        "extract_dict": True,
        "extract_list": True,
        "extract_tuple": True,
        "extract_kv": True,
        "extract_tensor": True,
        "extract_entropy": True,
        # Line-safe char budgets for LLM context windows (chunk_line_boundaries).
        "block_size": 0,
        "block_mode": "chars",
        "block_char_budget": 15000,
        "group_hash_buffer": 10,
        "short_hash": True,
        "pointer_format": "bracket",
        "extract_line_remove": True,
        "ignore_hash_prompt": True,
        "paste_strategy": "block_heading_params",
        "payload_mode": "ghost_projection",
        "frequent_only_rle": True,
        "drain_slug_masks": True,
        "drain_max_children": 10,
        **baseline_v2_exp_cfg(),
        "entropy_delete": True,
        "truncate_warnings": False,
        "warning_extract": True,
        "skip_warning_extract": False,
    }
