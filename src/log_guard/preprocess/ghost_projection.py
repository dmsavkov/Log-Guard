"""Ghost projection: cluster on masked copy, RLE-compress originals (v0.17)."""

from __future__ import annotations

from log_guard.preprocess.drain_dedup import (
    DrainDedupStats,
    TemplateMergeStats,
    _remap_cids,
    build_drain_rle_timeline,
    collapse_consecutive_cid_patterns,
    merge_templates_jaccard,
    merge_templates_semantic,
)
from log_guard.preprocess.drain_kv_merge import (
    collect_drain_kv_records,
    pointerize_rle_timeline,
)
from log_guard.preprocess.ghost_cluster_mask import mask_line_ghost_cluster, normalize_cluster_line
from log_guard.preprocess.inline_drain import assign_line_clusters_with_miner
from log_guard.preprocess.value_extract import ExtractedRecord


def build_ghost_projection_payload(
    original_lines: list[str],
    exp_cfg: dict | None,
    *,
    temporal_stripped: bool = True,
    template_jaccard: float | None = None,
    template_semantic: float | None = None,
    frequent_only_rle: bool = True,
    case_fold: bool = False,
) -> tuple[str, DrainDedupStats, list[ExtractedRecord]]:
    """DRAIN on ghost-cluster copy; emit RLE on originals, keep unique lines raw."""
    cfg = exp_cfg or {}
    cluster_cfg = dict(cfg)
    if not bool(cfg.get("drain_split_words", True)):
        cluster_cfg = {**cluster_cfg, "drain_extra_delimiters": []}

    cluster_input: list[str] = []
    for ln in original_lines:
        masked = mask_line_ghost_cluster(ln)
        cluster_input.append(normalize_cluster_line(masked))

    cids, clusters, miner = assign_line_clusters_with_miner(cluster_input, cluster_cfg)
    drain_kv_merge = bool(cfg.get("drain_kv_merge", True))

    tpl_stats: TemplateMergeStats | None = None
    if template_jaccard is not None:
        cid_remap, tpl_stats = merge_templates_jaccard(clusters, threshold=template_jaccard)
        cids = _remap_cids(cids, cid_remap)
    elif template_semantic is not None:
        cid_remap, tpl_stats = merge_templates_semantic(clusters, threshold=template_semantic)
        cids = _remap_cids(cids, cid_remap)

    frequent_only = bool(cfg.get("frequent_only_rle", frequent_only_rle))
    sequence_collapse = bool(cfg.get("sequence_collapse", True))
    max_pattern_len = int(cfg.get("sequence_max_pattern_len", 4))
    seq_stats = None
    merged = 0

    if sequence_collapse:
        timeline, seq_stats = collapse_consecutive_cid_patterns(
            original_lines,
            cids,
            clusters,
            max_pattern_len=max_pattern_len,
        )
        merged = len(original_lines) - len(timeline)
    else:
        timeline, merged, _, _ = build_drain_rle_timeline(
            original_lines,
            cids,
            clusters,
            frequent_only_rle=frequent_only,
        )

    drain_records: list[ExtractedRecord] = []
    if drain_kv_merge:
        pointer_format = str(cfg.get("pointer_format", "bracket"))
        short_hash = bool(cfg.get("short_hash", False))
        drain_records, stored_to_hid, cid_to_hid = collect_drain_kv_records(
            miner,
            cluster_input,
            cids,
            clusters,
            source_lines=original_lines,
            short_hash=short_hash,
            pointer_format=pointer_format,
        )
        timeline = pointerize_rle_timeline(
            timeline,
            miner=miner,
            masked_lines=cluster_input,
            cids=cids,
            clusters=clusters,
            stored_to_hid=stored_to_hid,
            cid_to_hid=cid_to_hid,
            source_lines=original_lines,
            pointer_format=pointer_format,
            short_hash=short_hash,
        )

    payload = "\n".join(timeline)

    templates_used = len({c for c in cids if c >= 0})
    stats = DrainDedupStats(
        input_lines=len(original_lines),
        output_lines=len(timeline),
        templates_used=templates_used,
        run_length_merged=merged,
        template_merge=tpl_stats,
        sequence_collapse=seq_stats,
    )
    return payload, stats, drain_records
