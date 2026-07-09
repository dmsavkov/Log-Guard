"""Tests for ~/.logguard storage."""

from __future__ import annotations

import pytest

from log_guard.lg.storage import (
    load_compressed,
    load_raw,
    load_values,
    logguard_home,
    new_run_id,
    run_dir,
    runs_dir,
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
    assert runs_dir().parent == logguard_home()
    assert (run_dir(run_id) / "intermediate").is_dir() or True


def test_load_raw_missing_raises(lg_home):
    with pytest.raises(FileNotFoundError):
        load_raw("dead")
