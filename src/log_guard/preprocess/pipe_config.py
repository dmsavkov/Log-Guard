"""Length-based routing for v0.21/v0.22 (legacy) and v0.23 four-tier pipe."""

from __future__ import annotations

from enum import Enum


class PipeRoute(str, Enum):
    """Post soft-clean routing by character count."""

    # v0.23 four-tier routes
    VERY_SHORT = "very_short"
    SHORT = "short"
    MEDIUM = "medium"
    FULL = "full"
    # v0.21/v0.22 legacy aliases
    STOP = "stop"
    GHOST_ONLY = "ghost_only"


# v0.21/v0.22 legacy thresholds (unchanged for compression_v021/v022).
GHOST_ONLY_MIN_CHARS = 3000
SUMMARIZE_MIN_CHARS = 10_000

# v0.23 thresholds (see full_pipeline.md / temp/updates.md).
V23_VERY_SHORT_MAX = 1500
V23_SHORT_MAX = 3000
V23_MEDIUM_MAX = 10_000


def route_after_soft_clean(char_count: int) -> PipeRoute:
    """Legacy v0.21/v0.22 routing — do not change without updating those orchestrators."""
    if char_count < GHOST_ONLY_MIN_CHARS:
        return PipeRoute.STOP
    if char_count < SUMMARIZE_MIN_CHARS:
        return PipeRoute.GHOST_ONLY
    return PipeRoute.FULL


def route_v23(char_count: int) -> PipeRoute:
    if char_count < V23_VERY_SHORT_MAX:
        return PipeRoute.VERY_SHORT
    if char_count < V23_SHORT_MAX:
        return PipeRoute.SHORT
    if char_count < V23_MEDIUM_MAX:
        return PipeRoute.MEDIUM
    return PipeRoute.FULL


def allows_trace(exp_cfg: dict) -> bool:
    if exp_cfg.get("skip_stacktrace_extract"):
        return False
    mode = exp_cfg.get("stacktrace_mode")
    return bool(mode)


def allows_ghost(
    route: PipeRoute,
    *,
    force_ghost: bool = False,
    force_no_ghost: bool = False,
) -> bool:
    if force_no_ghost:
        return False
    if force_ghost:
        return True
    # Ghost on all routes; severe cluster mask on short logs, inplace sanitize on long.
    return route in (
        PipeRoute.VERY_SHORT,
        PipeRoute.SHORT,
        PipeRoute.MEDIUM,
        PipeRoute.FULL,
        PipeRoute.GHOST_ONLY,
    )


def needs_inplace_sanitize(route: PipeRoute) -> bool:
    """In-place token deletion for logs >3k chars (MEDIUM+ / legacy GHOST_ONLY+)."""
    return route in (PipeRoute.MEDIUM, PipeRoute.FULL, PipeRoute.GHOST_ONLY)


def allows_value_extract(
    route: PipeRoute,
    *,
    force_kv_extract: bool = False,
) -> bool:
    if force_kv_extract:
        return True
    return route is PipeRoute.FULL


def allows_llm(
    route: PipeRoute,
    *,
    force_llm: bool = False,
) -> bool:
    if force_llm:
        return True
    return route in (PipeRoute.MEDIUM, PipeRoute.FULL)


def default_drain_sim_th(route: PipeRoute) -> float | None:
    if route is PipeRoute.MEDIUM:
        return 0.8
    if route is PipeRoute.FULL:
        return 0.5
    return None


def ghost_mask_mode(route: PipeRoute) -> str:
    """MEDIUM: masks in Drain tree only; FULL: in-place hard clean before ghost."""
    if route is PipeRoute.FULL:
        return "in_place"
    return "drain_instructions_only"


def ghost_exp_cfg_for_route(exp_cfg: dict, route: PipeRoute) -> dict:
    """Adjust drain/lexical flags per route (Risk B: no in-place NUM/IP on MEDIUM)."""
    cfg = dict(exp_cfg)
    default_sim = default_drain_sim_th(route)
    if default_sim is not None and "drain_sim_th" not in exp_cfg:
        cfg["drain_sim_th"] = default_sim
    if ghost_mask_mode(route) == "drain_instructions_only":
        cfg["lexical_remove_numbers"] = False
        cfg["lexical_mask_ip"] = False
        cfg["drain_extended_masks"] = True
    return cfg
