"""CLI integration tests via subprocess."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _lg(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {**dict(**__import__("os").environ), **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "log_guard.lg.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=full_env,
    )


def _parse_run_id(stdout: str) -> str:
    marker = "[LogGuard:"
    start = stdout.index(marker) + len(marker)
    return stdout[start : start + 4]


def test_run_echo(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "echo", "hello")
    assert proc.returncode == 0
    assert "[LogGuard:" in proc.stdout
    assert "hello" in proc.stdout
    assert list((tmp_path / "runs").iterdir())


def test_run_false_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "python", "-c", "import sys; sys.exit(1)")
    assert proc.returncode == 1


def test_passthrough_skips_compression(tmp_path, monkeypatch):
    from log_guard.lg import cli as lg_cli

    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))

    def _fake_run(command: str, **kwargs):
        from log_guard.lg.runner import RunResult

        return RunResult(stdout="file contents\n", stderr="", exit_code=0)

    monkeypatch.setattr("log_guard.lg.cli.run_shell", _fake_run)
    exit_code = lg_cli.cmd_run(
        type("Args", (), {"cmd": ["cat", "foo.txt"], "dry_run": True})()
    )
    assert exit_code == 0
    run_dirs = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "lg").read_text(encoding="utf-8") == "file contents\n"


def test_raw_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    run = _lg("run", "echo", "roundtrip")
    run_id = _parse_run_id(run.stdout)
    raw = _lg("raw", run_id)
    assert raw.returncode == 0
    assert "roundtrip" in raw.stdout


def test_stats_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    _lg("run", "echo", "a")
    stats = _lg("stats")
    assert stats.returncode == 0
    assert "LogGuard session stats" in stats.stdout


def test_history_after_run(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    _lg("run", "echo", "hist")
    hist = _lg("history")
    assert hist.returncode == 0
    assert "hist" in hist.stdout or "LogGuard run history" in hist.stdout


def test_read_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("read", "/no/such/file.log")
    assert proc.returncode == 1


def test_get_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    run = _lg("run", "--dry-run", "echo", "x")
    run_id = _parse_run_id(run.stdout)
    got = _lg("get", run_id, "99")
    assert got.returncode == 0
    assert "(not found)" in got.stdout
