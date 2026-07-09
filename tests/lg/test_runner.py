"""Tests for subprocess runner exit codes."""

from log_guard.lg.runner import merge_output, run_shell


def test_true_exit_zero():
    result = run_shell("python -c \"import sys; sys.exit(0)\"")
    assert result.exit_code == 0


def test_false_exit_one():
    result = run_shell("python -c \"import sys; sys.exit(1)\"")
    assert result.exit_code == 1


def test_merge_both_streams():
    merged = merge_output("out\n", "err\n")
    assert "out" in merged and "err" in merged
