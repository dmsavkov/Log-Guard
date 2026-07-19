"""v3 pipeline stage orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from log_guard.pipeline.snapshots import save_phase_lines
from log_guard.pipeline.stages import (
    apply_mid_clean,
    apply_soft_clean,
    apply_stacktrace,
    apply_value_extract,
    build_extract_payload,
)
from log_guard.preprocess.block_chunk import chunk_line_boundaries
from log_guard.preprocess.ghost_projection import build_ghost_projection_payload
from log_guard.preprocess.inplace_sanitize import sanitize_lines_inplace
from log_guard.preprocess.pipe_config import (
    PipeRoute,
    allows_ghost,
    allows_llm,
    allows_trace,
    allows_value_extract,
    ghost_exp_cfg_for_route,
    needs_inplace_sanitize,
    route_v23,
)
from log_guard.preprocess.value_extract_v18 import finalize_records_for_blocks


class PipelineSession(Protocol):
    def record_phase(self, phase: str, payload: dict[str, Any]) -> None: ...

    def save_intermediate(self, name: str, content: str) -> Any: ...

    def save_distillation(self, text: str) -> None: ...


@dataclass
class V23StagesResult:
    payload: str
    pipe_route: PipeRoute
    records: list = field(default_factory=list)
    trace_records: list = field(default_factory=list)
    extracted_lines: list[str] = field(default_factory=list)
    block_boundaries: list[tuple[int, int]] | None = None
    early_exit: bool = False
    early_reason: str = ""


def run_v23_stages(
    session: PipelineSession,
    lines: list[str],
    cfg: dict,
    *,
    raw_for_time: list[str] | None = None,
    preliminary: bool = False,
    dry_run: bool = False,
) -> V23StagesResult:
    _ = preliminary, dry_run
    raw_for_time = list(raw_for_time if raw_for_time is not None else lines)

    if cfg.get("skip_soft_clean"):
        save_phase_lines(session, "01_soft_clean.txt", lines)
    else:
        lines = apply_soft_clean(lines, cfg, session)  # type: ignore[arg-type]
        if cfg.get("chars_v22") and cfg.get("v22_clean_prefix", True):
            save_phase_lines(session, "02_temporal.txt", lines)

    trace_records: list = []
    if allows_trace(cfg):
        lines, trace_records = apply_stacktrace(lines, cfg, session)  # type: ignore[arg-type]
    save_phase_lines(session, "03_stacktrace.txt", lines)

    if cfg.get("warning_extract", True) and not cfg.get("skip_warning_extract"):
        from log_guard.lg.warning_handling import extract_warnings, stats_dict as warn_stats

        lines, wstats = extract_warnings(lines)
        session.record_phase("warning_extract", warn_stats(wstats))
        save_phase_lines(session, "03c_warnings.txt", lines)

    route_char_count = sum(len(ln) for ln in lines)
    pipe_route = route_v23(route_char_count)
    force_ghost = bool(cfg.get("force_ghost") or cfg.get("force_ghost_all"))
    force_no_ghost = bool(cfg.get("force_no_ghost"))
    force_kv = bool(cfg.get("force_kv_extract"))
    force_llm = bool(cfg.get("force_llm"))

    session.record_phase(
        "length_route",
        {
            "chars_after_trace": route_char_count,
            "route": pipe_route.value,
            "force_ghost": force_ghost,
            "force_no_ghost": force_no_ghost,
            "force_kv_extract": force_kv,
            "force_llm": force_llm,
        },
    )

    run_extract = bool(cfg.get("value_extract")) and allows_value_extract(
        pipe_route, force_kv_extract=force_kv
    )
    records: list = []
    extracted_lines = lines
    block_boundaries = None
    block_size = int(cfg.get("block_size", 0))

    if run_extract:
        extracted_lines, records = apply_value_extract(lines, cfg, session)  # type: ignore[arg-type]
        save_phase_lines(session, "04_value_extract.txt", extracted_lines)
        extracted_lines = apply_mid_clean(extracted_lines, cfg, session, post_extract=True)  # type: ignore[arg-type]
        block_mode = str(cfg.get("block_mode", "lines"))
        if block_size > 0 or block_mode in ("time", "chars"):
            block_boundaries = chunk_line_boundaries(
                len(extracted_lines),
                mode=block_mode,
                block_size=block_size or 300,
                block_time_sec=int(cfg.get("block_time_sec", 3000)),
                block_char_budget=int(cfg.get("block_char_budget", 20000)),
                lines=extracted_lines,
                raw_lines=raw_for_time if block_mode == "time" else None,
            )
        records = finalize_records_for_blocks(
            records,
            block_boundaries=block_boundaries,
            block_size=block_size or 300,
            total_lines=len(extracted_lines),
            exp_cfg=cfg,
        )

    if needs_inplace_sanitize(pipe_route):
        target = extracted_lines if run_extract else lines
        sanitized, san_stats = sanitize_lines_inplace(target)
        session.record_phase("inplace_sanitize", san_stats)
        save_phase_lines(session, "03b_inplace_sanitize.txt", sanitized)
        if run_extract:
            extracted_lines = sanitized
        else:
            lines = sanitized
            extracted_lines = sanitized

    ghost_cfg = ghost_exp_cfg_for_route(cfg, pipe_route)
    use_ghost = allows_ghost(pipe_route, force_ghost=force_ghost, force_no_ghost=force_no_ghost)

    if use_ghost:
        from dataclasses import asdict

        from log_guard.preprocess.drain_kv_merge import merge_drain_records
        from log_guard.preprocess.value_extract_v18 import cap_hash_groups_for_exp
        from log_guard.preprocess.value_store import save_extracted_values_json

        ghost_cfg = {
            **ghost_cfg,
            "drain_kv_merge": bool(cfg.get("drain_kv_merge", True)) and run_extract,
        }
        payload, gs, drain_records = build_ghost_projection_payload(
            extracted_lines,
            ghost_cfg,
            temporal_stripped=bool(cfg.get("temporal_strip", True)),
            frequent_only_rle=bool(cfg.get("frequent_only_rle", True)),
        )
        if drain_records:
            records = merge_drain_records(records, drain_records)
            records = cap_hash_groups_for_exp(records, cfg)
            save_extracted_values_json(session, records)  # type: ignore[arg-type]
            session.record_phase("drain_kv_merge", {"records": len(drain_records)})
        session.record_phase("ghost_projection", asdict(gs))
        save_phase_lines(session, "06_ghost_timeline.txt", payload.splitlines())
        save_phase_lines(session, "07_compressed_payload.txt", payload.splitlines())
        if not allows_llm(pipe_route, force_llm=force_llm):
            return V23StagesResult(
                payload=payload,
                pipe_route=pipe_route,
                records=records,
                trace_records=trace_records,
                extracted_lines=extracted_lines,
                block_boundaries=block_boundaries,
                early_exit=True,
                early_reason=f"length_route_{pipe_route.value}",
            )
    elif records:
        payload = build_extract_payload(
            extracted_lines, records, cfg, session, raw_for_time=raw_for_time  # type: ignore[arg-type]
        )
    else:
        payload = "\n".join(extracted_lines)

    save_phase_lines(session, "07_compressed_payload.txt", payload.splitlines())

    return V23StagesResult(
        payload=payload,
        pipe_route=pipe_route,
        records=records,
        trace_records=trace_records,
        extracted_lines=extracted_lines,
        block_boundaries=block_boundaries,
    )
