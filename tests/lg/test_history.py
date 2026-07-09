"""Tests for lg history command."""

from log_guard.lg.history import format_history
from log_guard.lg.storage import save_run


def test_history_lists_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    save_run(
        "ab12",
        raw="hello world from pytest",
        compressed="compressed output preview text",
        values={},
        meta={"cmd": "echo test"},
    )
    out = format_history()
    assert "ab12" in out
    assert "SAVED" in out
    assert "COMMAND" in out
    assert "CONTENT" in out
    assert "echo test" in out
    assert "compressed output" in out


def test_history_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    for i in range(5):
        save_run(f"id{i:02d}", raw="x", compressed="y", values={}, meta={"cmd": f"cmd{i}"})
    lines = [ln for ln in format_history(limit=2).splitlines() if ln and not ln.startswith("LogGuard")]
    data_lines = [ln for ln in lines if not ln.startswith("ID")]
    assert len(data_lines) == 2
