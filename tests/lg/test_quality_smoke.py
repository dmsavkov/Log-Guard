"""Quality smoke: v3 dry-run output matches bundled reference artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from log_guard.lg.pipeline import compress_for_lg

ROOT = Path(__file__).resolve().parents[2]
EVAL_RAW = ROOT / "tests" / "fixtures" / "eval_raw"
EXPECTED = ROOT / "tests" / "fixtures" / "expected"

STAGE_FILES = [
    "01_soft_clean.txt",
    "02_temporal.txt",
    "03_stacktrace.txt",
    "04_value_extract.txt",
    "05_mid_clean.txt",
    "03b_inplace_sanitize.txt",
    "06_ghost_timeline.txt",
    "07_compressed_payload.txt",
    "08_post_assembly.txt",
]

CASES = ["10", "linux"]


@pytest.mark.parametrize("eval_id", CASES)
def test_v3_output_matches_reference(eval_id: str, tmp_path, monkeypatch):
    raw_path = EVAL_RAW / f"{eval_id}.txt"
    ref_dir = EXPECTED / eval_id
    if not raw_path.is_file() or not ref_dir.is_dir():
        pytest.skip(f"missing fixtures for {eval_id}")

    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    result = compress_for_lg(raw_path.read_text(encoding="utf-8"), eval_id, dry_run=True)
    run_inter = tmp_path / "runs" / eval_id / "intermediate"

    failures: list[str] = []
    for name in STAGE_FILES:
        ref = ref_dir / name
        ours = run_inter / name
        if not ref.is_file():
            continue
        if not ours.is_file():
            failures.append(f"{name}: missing")
            continue
        if ref.read_text(encoding="utf-8") != ours.read_text(encoding="utf-8"):
            failures.append(f"{name}: byte mismatch")

    ref_vals = ref_dir / "extracted_values.json"
    ours_vals = run_inter / "extracted_values.json"
    if ref_vals.is_file() and ours_vals.is_file():
        if json.loads(ref_vals.read_text()) != json.loads(ours_vals.read_text()):
            failures.append("extracted_values.json: mismatch")

    ref_asm = ref_dir / "08_post_assembly.txt"
    if ref_asm.is_file() and result.compressed != ref_asm.read_text(encoding="utf-8"):
        failures.append(
            f"final output: ref={len(ref_asm.read_text())} ours={len(result.compressed)}"
        )

    if failures:
        pytest.fail(f"eval {eval_id}:\n" + "\n".join(failures))
