"""v3 deterministic pipeline stages (soft clean through payload)."""

from __future__ import annotations

from typing import Any, Protocol

from log_guard.pipeline.snapshots import save_phase_lines
from log_guard.preprocess.block_chunk import chunk_line_boundaries
from log_guard.preprocess.mid_char_clean import mid_char_clean_lines
from log_guard.preprocess.soft_clean_v22 import apply_soft_clean_v22
from log_guard.preprocess.stacktrace_extract import extract_stacktraces, stats_dict as st_stats_dict
from log_guard.preprocess.value_extract_v18 import extract_values_v18, stats_dict as ve_stats_dict
from log_guard.preprocess.value_paste import build_block_payload
from log_guard.preprocess.value_store import save_extracted_values_json


class StageSession(Protocol):
    def record_phase(self, phase: str, payload: dict[str, Any]) -> None: ...

    def save_intermediate(self, name: str, content: str) -> object: ...


def apply_soft_clean(lines: list[str], cfg: dict, session: StageSession) -> list[str]:
    out, stats = apply_soft_clean_v22(lines, cfg)
    session.record_phase("soft_clean_v22", stats)
    save_phase_lines(session, "01_soft_clean.txt", out)
    return out


def apply_mid_clean(
    lines: list[str], cfg: dict, session: StageSession, *, post_extract: bool = True
) -> list[str]:
    out, stats = mid_char_clean_lines(lines, cfg, post_extract=post_extract)
    if post_extract:
        session.record_phase("mid_char_clean", stats)
        save_phase_lines(session, "05_mid_clean.txt", out)
    return out


def apply_stacktrace(
    lines: list[str], cfg: dict, session: StageSession
) -> tuple[list[str], list]:
    mode = cfg.get("stacktrace_mode")
    if not mode:
        return lines, []
    out, stats = extract_stacktraces(
        lines,
        mode=str(mode),
        close_context=int(cfg.get("stacktrace_close_context", 2)),
        hash_pointer=bool(cfg.get("stacktrace_hash", False)),
        truncate_warnings=bool(cfg.get("truncate_warnings", True)),
        warn_max_len=int(cfg.get("warn_max_len", 60)),
        extended_patterns=bool(cfg.get("stacktrace_extended_patterns", True)),
    )
    session.record_phase("stacktrace_extract", st_stats_dict(stats))
    if stats.records:
        save_extracted_values_json(session, stats.records)  # type: ignore[arg-type]
    return out, list(stats.records)


def apply_value_extract(
    lines: list[str], cfg: dict, session: StageSession
) -> tuple[list[str], list]:
    if not cfg.get("value_extract"):
        return lines, []
    out, stats = extract_values_v18(lines, cfg)
    session.record_phase("value_extract", ve_stats_dict(stats))
    if stats.records:
        save_extracted_values_json(session, stats.records)  # type: ignore[arg-type]
    return out, stats.records


def build_extract_payload(
    lines: list[str],
    records: list,
    cfg: dict,
    session: StageSession,
    *,
    raw_for_time: list[str],
) -> str:
    block_size = int(cfg.get("block_size", 0))
    block_mode = str(cfg.get("block_mode", "lines"))
    pointer_format = str(cfg.get("pointer_format", "hash"))
    merge_block_hashes = bool(cfg.get("merge_block_hashes", False))

    block_boundaries: list[tuple[int, int]] | None = None
    if block_size > 0 or block_mode in ("time", "chars"):
        block_boundaries = chunk_line_boundaries(
            len(lines),
            mode=block_mode,
            block_size=block_size or 300,
            block_time_sec=int(cfg.get("block_time_sec", 3000)),
            block_char_budget=int(cfg.get("block_char_budget", 20000)),
            lines=lines,
            raw_lines=raw_for_time if block_mode == "time" else None,
        )
        session.record_phase("block_boundaries", {"mode": block_mode, "chunks": block_boundaries})

    if block_size > 0 or block_boundaries:
        return build_block_payload(
            lines,
            records,
            block_size=block_size or 300,
            block_boundaries=block_boundaries,
            short_hash=bool(cfg.get("short_hash", False)),
            pointer_format=pointer_format,
            merge_block_hashes=merge_block_hashes,
            include_pointers=bool(cfg.get("include_block_pointers", False)),
        )
    return "\n".join(lines)
