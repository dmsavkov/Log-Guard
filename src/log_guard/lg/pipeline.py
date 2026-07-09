"""v3 pipeline wrapper with mandatory raw fallback."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from log_guard.distill import distill_with_retries
from log_guard.lg.preprocess_input import prepare_log_lines
from log_guard.lg.session import LgRunSession
from log_guard.pipeline.assembly import assemble_output
from log_guard.pipeline.config import build_v3_config
from log_guard.pipeline.passthrough import assembly_kwargs, build_user_prefix, save_passthrough
from log_guard.pipeline.v23_runner import run_v23_stages
from log_guard.preprocess.pipe_config import allows_llm
from log_guard.prompt import DISTILL_SYSTEM


@dataclass
class LgCompressResult:
    compressed: str
    route: str
    distill_called: bool
    raw_chars: int
    compressed_chars: int
    latency_ms: float
    phases: dict[str, Any] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)


def compress_for_lg(
    raw: str,
    run_id: str,
    *,
    dry_run: bool = False,
    preliminary: bool = False,
) -> LgCompressResult:
    """Run v3 pipeline; on failure return raw unchanged."""
    t0 = time.perf_counter()
    raw_chars = len(raw)
    cfg = build_v3_config()

    if not raw.strip():
        return LgCompressResult(
            compressed=raw,
            route="passthrough",
            distill_called=False,
            raw_chars=raw_chars,
            compressed_chars=raw_chars,
            latency_ms=0.0,
        )

    session = LgRunSession(run_id)
    try:
        lines, raw_for_time = prepare_log_lines(raw)
        stages = run_v23_stages(
            session,
            lines,
            cfg,
            raw_for_time=raw_for_time,
            preliminary=preliminary,
            dry_run=dry_run,
        )

        if stages.early_exit:
            save_passthrough(
                session,
                stages.payload,
                reason=stages.early_reason,
                cfg=cfg,
                records=stages.records,
                trace_records=stages.trace_records,
                extracted_lines=stages.extracted_lines,
                block_boundaries=stages.block_boundaries,
            )
            out = session.distillation or assemble_output(
                stages.payload,
                **assembly_kwargs(
                    cfg,
                    records=stages.records,
                    trace_records=stages.trace_records,
                    extracted_lines=stages.extracted_lines,
                    block_boundaries=stages.block_boundaries,
                ),
            )
            session.save_phases_json()
            return _result(session, out, raw_chars, t0, distill_called=False)

        if dry_run:
            save_passthrough(
                session,
                stages.payload,
                reason="dry_run_full_route",
                cfg=cfg,
                records=stages.records,
                trace_records=stages.trace_records,
                extracted_lines=stages.extracted_lines,
                block_boundaries=stages.block_boundaries,
            )
            out = session.distillation
            session.save_phases_json()
            return _result(session, out, raw_chars, t0, distill_called=False)

        force_llm = bool(cfg.get("force_llm"))
        if not allows_llm(stages.pipe_route, force_llm=force_llm):
            save_passthrough(
                session,
                stages.payload,
                reason=f"length_route_{stages.pipe_route.value}",
                cfg=cfg,
                records=stages.records,
                trace_records=stages.trace_records,
                extracted_lines=stages.extracted_lines,
                block_boundaries=stages.block_boundaries,
            )
            out = session.distillation
            session.save_phases_json()
            return _result(session, out, raw_chars, t0, distill_called=False)

        asm = assembly_kwargs(
            cfg,
            records=stages.records,
            trace_records=stages.trace_records,
            extracted_lines=stages.extracted_lines,
            block_boundaries=stages.block_boundaries,
        )
        max_retries = 3 if preliminary else 10
        user_prefix = build_user_prefix(cfg)
        distilled, tokens, _ms = distill_with_retries(
            model=cfg["model"],
            system=DISTILL_SYSTEM,
            user=f"{user_prefix}\n\n{stages.payload}",
            temperature=float(cfg.get("temperature", 0.2)),
            max_retries=max_retries,
        )
        out = assemble_output(distilled, **asm)
        session.save_distillation(out)
        session.record_phase(
            "distill",
            {"model": cfg["model"], "tokens": tokens, "output_chars": len(out)},
        )
        session.save_phases_json()
        return _result(session, out, raw_chars, t0, distill_called=True)

    except Exception as exc:
        logger.warning("Pipeline failed, falling back to raw: {}", exc)
        return LgCompressResult(
            compressed=raw,
            route="fallback",
            distill_called=False,
            raw_chars=raw_chars,
            compressed_chars=raw_chars,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


def _result(
    session: LgRunSession,
    out: str,
    raw_chars: int,
    t0: float,
    *,
    distill_called: bool,
) -> LgCompressResult:
    route_phase = session.phases.get("length_route", {})
    values: dict[str, Any] = {}
    values_path = session.intermediate_dir / "extracted_values.json"
    if values_path.is_file():
        import json

        values = json.loads(values_path.read_text(encoding="utf-8"))
    return LgCompressResult(
        compressed=out,
        route=str(route_phase.get("route", "unknown")),
        distill_called=distill_called,
        raw_chars=raw_chars,
        compressed_chars=len(out),
        latency_ms=(time.perf_counter() - t0) * 1000,
        phases=session.phases,
        values=values,
    )
