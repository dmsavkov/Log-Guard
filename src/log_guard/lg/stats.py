"""Session-level compression savings dashboard."""

from __future__ import annotations

from collections import Counter

from log_guard.lg.storage import list_run_metas
from log_guard.lg.telemetry import read_telemetry


def _is_experimental(row: dict) -> bool:
    return bool(row.get("experimental"))


def compute_stats(*, include_experimental: bool = False) -> dict[str, float | int | dict[str, int]]:
    metas = list_run_metas()
    if not include_experimental:
        metas = [m for m in metas if not _is_experimental(m)]
    total_runs = len(metas)
    raw_chars = sum(int(m.get("raw_chars", 0)) for m in metas)
    compressed_chars = sum(int(m.get("compressed_chars", 0)) for m in metas)
    ratio = (compressed_chars / raw_chars) if raw_chars else 1.0
    saved = max(0, raw_chars - compressed_chars)
    track_counts: Counter[str] = Counter()
    for m in metas:
        track_counts[str(m.get("track", "unknown"))] += 1
    telemetry = read_telemetry()
    if not include_experimental:
        telemetry = [t for t in telemetry if not _is_experimental(t)]
    subcommand_counts: Counter[str] = Counter(
        str(t.get("subcommand", "?")) for t in telemetry
    )
    return {
        "total_runs": total_runs,
        "raw_chars": raw_chars,
        "compressed_chars": compressed_chars,
        "chars_saved": saved,
        "compression_ratio": ratio,
        "estimated_tokens_saved": saved // 4,
        "tracks": dict(track_counts),
        "subcommands": dict(subcommand_counts),
    }


def format_dashboard(stats: dict[str, float | int | dict[str, int]]) -> str:
    lines = [
        "LogGuard session stats",
        f"  Runs:           {stats['total_runs']}",
        f"  Raw chars:      {stats['raw_chars']:,}",
        f"  Compressed:     {stats['compressed_chars']:,}",
        f"  Chars saved:    {stats['chars_saved']:,}",
        f"  Ratio:          {stats['compression_ratio']:.2%}",
        f"  Tokens saved:   ~{stats['estimated_tokens_saved']:,} (chars/4)",
    ]
    tracks = stats.get("tracks") or {}
    if tracks:
        lines.append("  Tracks:")
        for name, count in sorted(tracks.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"    {name}: {count}")
    subs = stats.get("subcommands") or {}
    if subs:
        lines.append("  Subcommands:")
        for name, count in sorted(subs.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"    {name}: {count}")
    return "\n".join(lines) + "\n"
