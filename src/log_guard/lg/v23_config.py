"""Compatibility aliases for pipeline config (standalone release — no genai/judge)."""

from __future__ import annotations

from log_guard.pipeline.config import DEFAULT_DISTILL_MODEL, build_v3_config

# Kept for older test imports; production code uses build_v3_config().
build_v23_full_pipe_baseline_v3_cfg = build_v3_config
build_v23_base_cfg = build_v3_config

__all__ = [
    "DEFAULT_DISTILL_MODEL",
    "build_v3_config",
    "build_v23_base_cfg",
    "build_v23_full_pipe_baseline_v3_cfg",
]
