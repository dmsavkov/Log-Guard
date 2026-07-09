"""Tests for lg passthrough detection."""

from log_guard.lg.passthrough import is_passthrough


def test_cat_passthrough():
    assert is_passthrough("cat foo.txt")


def test_grep_passthrough():
    assert is_passthrough("  grep pattern log.txt")


def test_pytest_not_passthrough():
    assert not is_passthrough("pytest -q")


def test_echo_not_passthrough():
    assert not is_passthrough("echo hello")
