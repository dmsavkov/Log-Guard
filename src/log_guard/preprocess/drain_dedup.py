"""Tri-phasic deduplication: DRAIN RLE → template Jaccard → template semantic merge."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from log_guard.preprocess.dedup import _tokens, jaccard
from log_guard.preprocess.ghost_cluster_mask import normalize_cluster_line
from log_guard.preprocess.inline_drain import assign_line_clusters

_DRAIN_MASK = re.compile(r"<\:[^:]*\:")
_DRAIN_ID = re.compile(r"<\s*DRAIN:\d+\s*>")
_SEQ_ID = re.compile(r"<\s*SEQ:[^>]+>")


def _strip_drain_markup(text: str) -> str:
    """Remove internal Drain/SEQ cluster ids; preserve [×N] RLE multipliers."""
    out = _DRAIN_ID.sub("", text)
    out = _SEQ_ID.sub("", out)
    return re.sub(r"  +", " ", out).strip()


@dataclass(frozen=True)
class TemplateMergeStats:
    input_templates: int
    output_templates: int
    merged_pairs: int
    method: str


@dataclass(frozen=True)
class SequenceCollapseStats:
    input_blocks: int
    output_blocks: int
    patterns_collapsed: int


@dataclass(frozen=True)
class DrainDedupStats:
    input_lines: int
    output_lines: int
    templates_used: int
    run_length_merged: int
    template_merge: TemplateMergeStats | None
    sequence_collapse: SequenceCollapseStats | None


def _normalize_template(tpl: str) -> str:
    return _DRAIN_MASK.sub("<MASK>", tpl)


def _union_find_merge(n: int, pairs: list[tuple[int, int]]) -> dict[int, int]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unite(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in pairs:
        unite(a, b)
    return {i: find(i) for i in range(n)}


def merge_templates_jaccard(
    clusters: dict[int, dict],
    *,
    threshold: float = 0.85,
) -> tuple[dict[int, int], TemplateMergeStats]:
    """Merge DRAIN cluster IDs whose templates are lexically similar (phase 2)."""
    cids = sorted(clusters.keys())
    if len(cids) < 2:
        return {cid: cid for cid in cids}, TemplateMergeStats(len(cids), len(cids), 0, "jaccard")

    tpl_tokens = [_tokens(_normalize_template(clusters[cid]["template"])) for cid in cids]
    pairs: list[tuple[int, int]] = []
    for i in range(len(cids)):
        for j in range(i + 1, len(cids)):
            if jaccard(tpl_tokens[i], tpl_tokens[j]) >= threshold:
                pairs.append((i, j))

    remap_idx = _union_find_merge(len(cids), pairs)
    cid_remap = {cids[idx]: cids[remap_idx[idx]] for idx in range(len(cids))}
    merged_roots = len({cid_remap[c] for c in cids})
    return cid_remap, TemplateMergeStats(
        input_templates=len(cids),
        output_templates=merged_roots,
        merged_pairs=len(pairs),
        method="jaccard",
    )


def merge_templates_semantic(
    clusters: dict[int, dict],
    *,
    threshold: float = 0.85,
) -> tuple[dict[int, int], TemplateMergeStats]:
    """Merge DRAIN templates by TF-IDF cosine similarity (phase 3, local embeddings)."""
    cids = sorted(clusters.keys())
    if len(cids) < 2:
        return {cid: cid for cid in cids}, TemplateMergeStats(len(cids), len(cids), 0, "semantic")

    texts = [_normalize_template(clusters[cid]["template"]) for cid in cids]
    vec = TfidfVectorizer(lowercase=True, token_pattern=r"(?u)\b\w+\b")
    matrix = vec.fit_transform(texts)
    sim = cosine_similarity(matrix)

    pairs: list[tuple[int, int]] = []
    for i in range(len(cids)):
        for j in range(i + 1, len(cids)):
            if sim[i, j] >= threshold:
                pairs.append((i, j))

    remap_idx = _union_find_merge(len(cids), pairs)
    cid_remap = {cids[idx]: cids[remap_idx[idx]] for idx in range(len(cids))}
    merged_roots = len({cid_remap[c] for c in cids})
    return cid_remap, TemplateMergeStats(
        input_templates=len(cids),
        output_templates=merged_roots,
        merged_pairs=len(pairs),
        method="semantic",
    )


def _remap_cids(cids: list[int], cid_remap: dict[int, int]) -> list[int]:
    return [cid_remap.get(c, c) if c >= 0 else c for c in cids]


def build_drain_rle_timeline(
    lines: list[str],
    cids: list[int],
    clusters: dict[int, dict],
    *,
    frequent_only_rle: bool = True,
) -> tuple[list[str], int, int, int]:
    """Chronological RLE. frequent_only: raw line unless consecutive run > 1."""
    out: list[str] = []
    merged = 0
    rle_blocks = 0
    raw_kept = 0
    i = 0
    n = len(cids)

    while i < n:
        if cids[i] < 0 or not lines[i].strip():
            i += 1
            continue
        cid = cids[i]
        run = 1
        j = i + 1
        while j < n and cids[j] == cid:
            run += 1
            j += 1

        if frequent_only_rle and run == 1:
            out.append(lines[i])
            raw_kept += 1
        else:
            tpl = _normalize_template(clusters[cid]["template"])
            out.append(f"[×{run}] {tpl}")
            rle_blocks += 1
            if run > 1:
                merged += run - 1
        i = j

    return out, merged, rle_blocks, raw_kept


def collapse_consecutive_cid_patterns(
    lines: list[str],
    cids: list[int],
    clusters: dict[int, dict],
    *,
    max_pattern_len: int = 3,
) -> tuple[list[str], SequenceCollapseStats]:
    """Single-line RLE first, then shortest multi-line sequence patterns (pairs→triples→…)."""
    n = len(cids)
    out: list[str] = []
    patterns_collapsed = 0
    i = 0
    input_blocks = 0

    while i < n:
        if cids[i] < 0:
            i += 1
            continue
        input_blocks += 1

        # Phase 1: consecutive verbatim duplicates → [×N] one raw line.
        line_key = normalize_cluster_line(lines[i])
        dup_run = 1
        j = i + 1
        while j < n and cids[j] >= 0 and normalize_cluster_line(lines[j]) == line_key:
            dup_run += 1
            j += 1
        if dup_run > 1:
            out.append(f"[×{dup_run}] {lines[i].strip()}")
            patterns_collapsed += 1
            i = j
            continue

        # Phase 2: multi-line sequences only (plen ≥ 2); shortest pattern first.
        best_run = 1
        best_len = 0
        for plen in range(2, min(max_pattern_len, n - i) + 1):
            pattern = cids[i : i + plen]
            if any(c < 0 for c in pattern):
                continue
            run = 1
            k = i + plen
            while k + plen <= n and cids[k : k + plen] == pattern:
                run += 1
                k += plen
            if run > 1:
                best_run = run
                best_len = plen
                break

        if best_run > 1 and best_len >= 2:
            pattern_lines = [lines[i + k].strip() for k in range(best_len)]
            seq_header = f"[×{best_run}] Sequence:"
            body = "\n".join(f"  {ln}" for ln in pattern_lines)
            out.append(f"{seq_header}\n{body}")
            patterns_collapsed += 1
            i += best_len * best_run
            continue

        out.append(lines[i])
        i += 1

    return out, SequenceCollapseStats(
        input_blocks=input_blocks,
        output_blocks=len(out),
        patterns_collapsed=patterns_collapsed,
    )


def build_drain_dedup_payload(
    lines: list[str],
    exp_cfg: dict | None,
    *,
    temporal_stripped: bool = True,
    template_jaccard: float | None = None,
    template_semantic: float | None = None,
    sequence_collapse: bool = False,
    max_pattern_len: int = 3,
    frequent_only_rle: bool = True,
) -> tuple[str, DrainDedupStats]:
    """DRAIN-as-replacer: frequent-only RLE by default (no [×1] structural tax)."""
    cfg = exp_cfg or {}
    frequent_only = bool(cfg.get("frequent_only_rle", frequent_only_rle))
    cids, clusters = assign_line_clusters(lines, exp_cfg)

    tpl_stats: TemplateMergeStats | None = None
    if template_jaccard is not None:
        cid_remap, tpl_stats = merge_templates_jaccard(clusters, threshold=template_jaccard)
        cids = _remap_cids(cids, cid_remap)
    elif template_semantic is not None:
        cid_remap, tpl_stats = merge_templates_semantic(clusters, threshold=template_semantic)
        cids = _remap_cids(cids, cid_remap)

    seq_stats: SequenceCollapseStats | None = None
    if sequence_collapse:
        timeline, seq_stats = collapse_consecutive_cid_patterns(
            lines, cids, clusters, max_pattern_len=max_pattern_len
        )
        merged = len(lines) - len(timeline)
    else:
        timeline, merged, _, _ = build_drain_rle_timeline(
            lines, cids, clusters, frequent_only_rle=frequent_only
        )

    header = "## DRAIN dedup timeline (RLE, no deletion)\n"
    if temporal_stripped:
        header += "(temporal/structural strip applied before clustering)\n"
    if frequent_only and not sequence_collapse:
        header += "(frequent-only RLE: unique lines emitted verbatim)\n"
    payload = header + "\n".join(timeline)

    templates_used = len({c for c in cids if c >= 0})
    stats = DrainDedupStats(
        input_lines=len(lines),
        output_lines=len(timeline),
        templates_used=templates_used,
        run_length_merged=merged,
        template_merge=tpl_stats,
        sequence_collapse=seq_stats,
    )
    return payload, stats


def stats_dict(stats: DrainDedupStats) -> dict:
    return asdict(stats)
