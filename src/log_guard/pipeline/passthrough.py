"""Dry-run passthrough: assemble payload without LLM distill."""

from __future__ import annotations

from typing import Any, Protocol

from log_guard.pipeline.assembly import assemble_output


class PassthroughSession(Protocol):
    def save_intermediate(self, name: str, content: str) -> object: ...

    def save_distillation(self, text: str) -> None: ...

    def record_phase(self, phase: str, payload: dict[str, Any]) -> None: ...


def save_passthrough(
    session: PassthroughSession,
    payload: str,
    *,
    reason: str,
    cfg: dict,
    records: list | None = None,
    trace_records: list | None = None,
    extracted_lines: list[str] | None = None,
    block_boundaries: list[tuple[int, int]] | None = None,
) -> None:
    asm = assembly_kwargs(
        cfg,
        records=records or [],
        trace_records=trace_records or [],
        extracted_lines=extracted_lines or payload.splitlines(),
        block_boundaries=block_boundaries,
    )
    assembled = assemble_output(payload, **asm)
    session.save_intermediate("compressed_payload.txt", payload)
    session.save_intermediate("08_post_assembly.txt", assembled)
    session.save_distillation(assembled)
    session.record_phase(
        "distill",
        {"skipped": True, "reason": reason, "output_chars": len(assembled)},
    )


def assembly_kwargs(
    cfg: dict,
    *,
    records: list,
    trace_records: list,
    extracted_lines: list[str],
    block_boundaries: list[tuple[int, int]] | None,
) -> dict:
    block_size = int(cfg.get("block_size", 0))
    effective_block_size = block_size or (block_boundaries[0][1] if block_boundaries else 0)
    paste_strategy = str(cfg.get("paste_strategy", "pointer"))
    if cfg.get("minimal_pointer"):
        paste_strategy = "minimal_keys"
    return {
        "records": records,
        "trace_records": trace_records,
        "paste_strategy": paste_strategy,
        "total_lines": len(extracted_lines),
        "block_size": effective_block_size,
        "short_hash": bool(cfg.get("short_hash", False)),
        "pointer_format": str(cfg.get("pointer_format", "hash")),
        "block_boundaries": block_boundaries,
        "merge_block_hashes": bool(
            cfg.get("merge_block_hashes", paste_strategy == "block_heading_params")
        ),
    }


def build_user_prefix(cfg: dict) -> str:
    user_prefix = str(cfg.get("user_prefix", "Distill the following log content:"))
    if cfg.get("preserve_trace_markers"):
        user_prefix += (
            " Preserve [T#] trace markers exactly as they appear in the payload;"
            " do not expand or duplicate trace detail — only keep the [T#] tag."
        )
    if cfg.get("ignore_hash_prompt"):
        user_prefix += (
            " Ignore [HASH_...], [H#...], [Ref N], and [#N] markers in the payload;"
            " do not mention them in your summary."
        )
    elif cfg.get("value_extract"):
        user_prefix += (
            " When documenting parameters or config values, reuse [HASH_...] / [H#...] /"
            " [Ref N] / [#N] pointers from the payload."
        )
    if cfg.get("paste_strategy") == "block_heading_params":
        user_prefix += " Structure the summary using ### Block 1, ### Block 2, ... section headers."
    return user_prefix
