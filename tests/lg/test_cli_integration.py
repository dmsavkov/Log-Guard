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
    proc = _lg("run", "python", "-c", "print('hello')")
    assert proc.returncode == 0
    assert "[LogGuard:" in proc.stdout
    assert "hello" in proc.stdout
    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir() and (p / "raw.txt").is_file()]
    assert len(run_dirs) >= 1


def test_run_false_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "python", "-c", "import sys; sys.exit(1)")
    assert proc.returncode == 1


def test_run_python_c_with_commas(tmp_path, monkeypatch):
    """Regression: `lg run python -c "import a, b; print('ok')"` used to lose
    quoting via ' '.join + shell=True and die with SyntaxError."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "--dry-run", "python", "-c", "import os, sys, json; print('ok')")
    assert proc.returncode == 0
    assert "ok" in proc.stdout
    assert "SyntaxError" not in proc.stdout


def test_run_with_dashdash_separator(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "--dry-run", "--", "python", "-c", "print('sep-ok')")
    assert proc.returncode == 0
    assert "sep-ok" in proc.stdout


def test_run_single_quoted_string_split(tmp_path, monkeypatch):
    """UX: entire command passed as one quoted argument gets split."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "--dry-run", "python --version")
    assert proc.returncode == 0
    assert "Python" in proc.stdout


def test_run_arg_with_spaces(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg(
        "run",
        "--dry-run",
        "python",
        "-c",
        "import sys; print(sys.argv[1])",
        "hello world with spaces",
    )
    assert proc.returncode == 0
    assert "hello world with spaces" in proc.stdout


def test_run_no_shell_injection(tmp_path, monkeypatch):
    """Metacharacters in args must not spawn extra shell commands."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    canary = tmp_path / "injected.txt"
    proc = _lg(
        "run",
        "--dry-run",
        "python",
        "-c",
        "import sys; print(sys.argv[1])",
        f"x && python -c \"open(r'{canary}','w')\"",
    )
    assert proc.returncode == 0
    assert not canary.exists()


def test_run_shell_mode_pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "--dry-run", "--shell", "echo alpha && echo beta")
    assert proc.returncode == 0
    assert "alpha" in proc.stdout
    assert "beta" in proc.stdout


def test_run_command_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "--dry-run", "no-such-binary-qqq")
    assert proc.returncode == 127


def test_run_empty_command_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "--dry-run", "--")
    assert proc.returncode == 2


def test_passthrough_skips_compression(tmp_path, monkeypatch):
    from log_guard.lg import cli as lg_cli

    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))

    def _fake_run(argv, **kwargs):
        from log_guard.lg.runner import RunResult

        return RunResult(stdout="file contents\n", stderr="", exit_code=0)

    monkeypatch.setattr("log_guard.lg.executor.run_exec", _fake_run)
    exit_code = lg_cli.cmd_run(
        type("Args", (), {"cmd": ["cat", "foo.txt"], "dry_run": True, "shell": False})()
    )
    assert exit_code == 0
    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir() and (p / "lg").is_file()]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "lg").read_text(encoding="utf-8")


def test_raw_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    run = _lg("run", "python", "-c", "print('roundtrip')")
    run_id = _parse_run_id(run.stdout)
    raw = _lg("raw", run_id)
    assert raw.returncode == 0
    assert "roundtrip" in raw.stdout


def test_stats_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    _lg("run", "python", "-c", "print('a')")
    stats = _lg("stats")
    assert stats.returncode == 0
    assert "LogGuard session stats" in stats.stdout


def test_history_after_run(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    _lg("run", "python", "-c", "print('hist')")
    hist = _lg("history")
    assert hist.returncode == 0
    assert "hist" in hist.stdout or "LogGuard run history" in hist.stdout


def test_read_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("read", "/no/such/file.log")
    assert proc.returncode == 1


def test_get_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    run = _lg("run", "--dry-run", "python", "-c", "print('x')")
    run_id = _parse_run_id(run.stdout)
    got = _lg("get", run_id, "99")
    assert got.returncode == 0
    assert "(not found)" in got.stdout


# === Additional cross-platform/OS command tests ===

import platform

def test_run_cmd_shell_loop(tmp_path, monkeypatch):
    """Windows cmd shell loop — output includes all lines; lg must not crash on × RLE."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    if platform.system() != "Windows":
        import pytest
        pytest.skip("Windows cmd shell only")
    proc = _lg("run", "--dry-run", "--shell", 'cmd /c "for /l %i in (1,1,10) do @echo Stress Testing Line %i"')
    assert proc.returncode == 0, proc.stderr
    assert "[LogGuard:" in proc.stdout
    assert "Stress Testing Line" in proc.stdout
    # Ghost RLE may collapse repeated lines into [xN] Seq — first lines still present.
    assert "Line 1" in proc.stdout or "[x" in proc.stdout or "Seq" in proc.stdout

def test_run_command_not_found_randomfile(tmp_path, monkeypatch):
    """Test a random command/file that does not exist at all."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    proc = _lg("run", "--dry-run", "thisisnotarealcommandfile123")
    assert proc.returncode == 127 or proc.returncode == 1  # Allow fallback for systems with different not found exit codes

def test_run_git_help_all(tmp_path, monkeypatch):
    """Test a common multi-part command (semi-colon, with shell split)."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    if platform.system() == "Windows":
        # On Windows, use shell and PowerShell/command
        proc = _lg("run", "--dry-run", "--shell", "git help --all & git rev-parse --is-inside-work-tree")
    else:
        # On POSIX, use shell and ;
        proc = _lg("run", "--dry-run", "--shell", "git help --all; git rev-parse --is-inside-work-tree")
    assert proc.returncode in (0, 1, 128)  # git rev-parse can fail if not in repo, but should not crash parser
    assert ("config" in proc.stdout or "usage:" in proc.stdout or "not a git repository" in proc.stdout or "command-line" in proc.stdout or "OPTIONS" in proc.stdout)

def test_run_abbreviation_l(tmp_path, monkeypatch):
    """A single letter or shorthand command."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    # 'l' often means nothing, just verify its handled as not-found or shell-abbreviation (should fail gracefully)
    proc = _lg("run", "--dry-run", "l")
    assert proc.returncode == 127 or proc.returncode == 1

def test_run_powershell_env_vars(tmp_path, monkeypatch):
    """Test running a PowerShell command with $env vars (Windows-only)."""
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    if platform.system() != "Windows":
        import pytest
        pytest.skip("PowerShell syntax test: Windows only")
    # This should print out environmental info
    proc = _lg("run", "--dry-run", "--shell", 'powershell -Command "Write-Output \'OS: $($env:OS) | User: $($env:USERNAME) | SystemRoot: $($env:SystemRoot)\'"')
    assert proc.returncode == 0
    assert "OS:" in proc.stdout and "SystemRoot:" in proc.stdout