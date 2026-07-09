"""Chronological timeline with inline Drain template run-length encoding."""

from __future__ import annotations

import re
from dataclasses import dataclass

from log_guard.preprocess.drain_config import (
    DEFAULT_DRAIN_SIM_TH,
    make_drain_miner,
)

_DRAIN_MASK = re.compile(r"<\:[^:]*\:")


@dataclass(frozen=True)
class InlineDrainStats:
    input_lines: int
    output_lines: int
    templates_used: int
    run_length_merged: int


def _normalize_template(tpl: str) -> str:
    return _DRAIN_MASK.sub("<MASK>", tpl)


def _cluster_lines_with_miner(
    lines: list[str],
    miner,
) -> tuple[list[int], dict[int, dict]]:
    cids: list[int] = []
    clusters: dict[int, dict] = {}
    for line in lines:
        if not line.strip():
            cids.append(-1)
            continue
        result = miner.add_log_message(line)
        cid = int(result["cluster_id"])
        cids.append(cid)
        if cid not in clusters:
            clusters[cid] = {
                "template": result["template_mined"],
                "count": 0,
                "samples": [],
            }
        clusters[cid]["count"] += 1
        if len(clusters[cid]["samples"]) < 2:
            clusters[cid]["samples"].append(line)
    return cids, clusters


def assign_line_clusters_with_miner(
    lines: list[str],
    exp_cfg: dict | None,
) -> tuple[list[int], dict[int, dict], object]:
    """Cluster lines and return the TemplateMiner (for extract_parameters / drain KV merge)."""
    cfg = exp_cfg or {}
    miner = make_drain_miner(
        sim_th=cfg.get("drain_sim_th", DEFAULT_DRAIN_SIM_TH),
        extra_delimiters=cfg.get("drain_extra_delimiters"),
        extended_masks=cfg.get("drain_extended_masks", True),
        drain_depth=cfg.get("drain_depth"),
        drain_max_children=cfg.get("drain_max_children"),
        slug_masks=bool(cfg.get("drain_slug_masks", False)),
    )
    cids, clusters = _cluster_lines_with_miner(lines, miner)
    return cids, clusters, miner


def assign_line_clusters(lines: list[str], exp_cfg: dict | None) -> tuple[list[int], dict[int, dict]]:
    cids, clusters, _ = assign_line_clusters_with_miner(lines, exp_cfg)
    return cids, clusters


def build_inline_drain_timeline(
    lines: list[str],
    exp_cfg: dict | None,
    *,
    rare_max_count: int = 2,
    always_emit_rare: bool = True,
) -> tuple[list[str], InlineDrainStats]:
    """Walk lines in order; collapse repeated drain templates as [×N] <DRAIN:id> tpl."""
    cids, clusters = assign_line_clusters(lines, exp_cfg)
    out: list[str] = []
    merged = 0
    templates_used: set[int] = set()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if not line.strip() or cids[i] < 0:
            i += 1
            continue
        if line.startswith(("[TRACEBACK]", "CTX ", "WARN:", "ERR:", "METRIC")):
            out.append(line)
            i += 1
            continue

        cid = cids[i]
        cnt = clusters[cid]["count"]
        is_rare = cnt <= rare_max_count

        if is_rare and always_emit_rare:
            tpl = _normalize_template(clusters[cid]["template"])
            out.append(tpl)
            if clusters[cid]["samples"]:
                out.append(f"  sample: {clusters[cid]['samples'][0]}")
            templates_used.add(cid)
            i += 1
            continue

        run = 1
        j = i + 1
        while j < n and cids[j] == cid:
            run += 1
            j += 1
        tpl = _normalize_template(clusters[cid]["template"])
        out.append(f"[×{run}] <DRAIN:{cid}> {tpl}")
        templates_used.add(cid)
        if run > 1:
            merged += run - 1
        i = j

    return out, InlineDrainStats(
        input_lines=len(lines),
        output_lines=len(out),
        templates_used=len(templates_used),
        run_length_merged=merged,
    )
