"""Tests for lg debug command."""

from log_guard.lg.debug_cmd import format_debug_list, read_debug_file
from log_guard.lg.session import LgRunSession


def test_debug_list_and_cat(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    session = LgRunSession("cd34")
    session.save_intermediate("01_soft_clean.txt", "line1\nline2\n")
    session.save_intermediate("extracted_values.json", "{}")

    listing = format_debug_list("cd34")
    assert "01_soft_clean.txt" in listing
    assert read_debug_file("cd34", "01_soft_clean.txt") == "line1\nline2\n"
