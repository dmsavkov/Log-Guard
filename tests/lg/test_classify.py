"""Tests for lg track classification."""

from __future__ import annotations

from log_guard.lg.classify import Track, classify_base_command, is_compound_command, resolve_track
from log_guard.lg.track_config import (
    daemon_commands,
    lossless_commands,
    passthrough_prefixes,
    rtk_fast_commands,
)


def _resolve(cmd: str, *, shell: bool = False) -> Track:
    return resolve_track(
        cmd,
        shell_mode=shell,
        passthrough_prefixes=passthrough_prefixes(),
        lossless_commands=lossless_commands(),
        rtk_fast_commands=rtk_fast_commands(),
        daemon_commands=daemon_commands(),
    )


def test_compound_routes_full_pipe():
    assert is_compound_command("pytest -q && ls")
    assert _resolve("pytest -q && ls") == Track.FULL_PIPE


def test_shell_mode_full_pipe():
    assert _resolve("echo hi", shell=True) == Track.FULL_PIPE


def test_shell_mode_passthrough():
    assert _resolve("curl -I https://github.com", shell=True) == Track.PASSTHROUGH


def test_shell_mode_blocks_rtk():
    assert _resolve("ls -la", shell=True) == Track.FULL_PIPE


def test_passthrough_cat():
    assert _resolve("cat foo.txt") == Track.PASSTHROUGH


def test_passthrough_dir():
    assert _resolve("dir /b books") == Track.PASSTHROUGH


def test_pytest_native():
    assert _resolve("pytest tests/") == Track.PYTEST_NATIVE


def test_uv_run_pytest_native():
    assert classify_base_command("uv run pytest tests/") == "pytest"
    assert _resolve("uv run pytest tests/") == Track.PYTEST_NATIVE


def test_daemon_uvicorn():
    assert _resolve("uvicorn main:app") == Track.DAEMON_WARN


def test_rtk_lossless_git_status():
    assert _resolve("git status") == Track.RTK_LOSSLESS


def test_rtk_fast_ls():
    assert _resolve("ls -la") == Track.RTK_FAST
