"""Tests for lg stats dashboard."""

from log_guard.lg.stats import compute_stats, format_dashboard
from log_guard.lg.storage import save_run


def test_stats_math(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    save_run("ab12", raw="x" * 100, compressed="y" * 40, values={}, meta={})
    stats = compute_stats()
    assert stats["total_runs"] == 1
    assert stats["raw_chars"] == 100
    assert stats["compressed_chars"] == 40
    assert stats["chars_saved"] == 60
    assert stats["estimated_tokens_saved"] == 15
    dash = format_dashboard(stats)
    assert "LogGuard session stats" in dash
