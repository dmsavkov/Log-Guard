"""Tests for ~/.logguard storage."""

from __future__ import annotations

import pytest

from log_guard.lg.storage import (
    format_raw_log_hint,
    load_compressed,
    load_raw,
    load_values,
    logguard_home,
    new_run_id,
    run_dir,
    save_run,
)


@pytest.fixture
def lg_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    return tmp_path


def test_save_and_load_roundtrip(lg_home):
    run_id = new_run_id()
    assert len(run_id) == 4
    save_run(
        run_id,
        raw="raw\n",
        compressed="lg\n",
        values={"1": {"value": "x"}},
        meta={"cmd": "echo hi", "exit_code": 0},
    )
    assert load_raw(run_id) == "raw\n"
    assert load_compressed(run_id) == "lg\n"
    assert load_values(run_id)["1"]["value"] == "x"
    assert logguard_home() == lg_home
    assert (run_dir(run_id) / "raw.txt").is_file()
    assert (run_dir(run_id) / "lg").is_file()


def test_load_raw_missing_raises(lg_home):
    with pytest.raises(FileNotFoundError):
        load_raw("dead")


def test_hint_uses_tilde_home(lg_home):
    run_id = "abcd"
    save_run(
        run_id,
        raw="x",
        compressed="y",
        values={},
        meta={"cmd": "test"},
    )
    hint = format_raw_log_hint(run_id)
    assert hint.startswith("[full log ~/")
    assert "abcd/raw.txt" in hint.replace("\\", "/")
    assert "Users" not in hint
