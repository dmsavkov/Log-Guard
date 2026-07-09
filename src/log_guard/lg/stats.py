"""Session-level compression savings dashboard."""

from __future__ import annotations

from log_guard.lg.storage import list_run_metas


def compute_stats() -> dict[str, float | int]:
    metas = list_run_metas()
    total_runs = len(metas)
    raw_chars = sum(int(m.get("raw_chars", 0)) for m in metas)
    compressed_chars = sum(int(m.get("compressed_chars", 0)) for m in metas)
    ratio = (compressed_chars / raw_chars) if raw_chars else 1.0
    saved = max(0, raw_chars - compressed_chars)
    return {
        "total_runs": total_runs,
        "raw_chars": raw_chars,
        "compressed_chars": compressed_chars,
        "chars_saved": saved,
        "compression_ratio": ratio,
        "estimated_tokens_saved": saved // 4,
    }


def format_dashboard(stats: dict[str, float | int]) -> str:
    return (
        f"LogGuard session stats\n"
        f"  Runs:           {stats['total_runs']}\n"
        f"  Raw chars:      {stats['raw_chars']:,}\n"
        f"  Compressed:     {stats['compressed_chars']:,}\n"
        f"  Chars saved:    {stats['chars_saved']:,}\n"
        f"  Ratio:          {stats['compression_ratio']:.2%}\n"
        f"  Tokens saved:   ~{stats['estimated_tokens_saved']:,} (chars/4)\n"
    )
