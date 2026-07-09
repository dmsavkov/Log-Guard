"""Golden dry-run snapshots for lg v3 pipeline on synth fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from log_guard.lg.pipeline import compress_for_lg
from tests.fixtures.lg import full_route_synth_text, medium_cicd_text, tiny_trace_text

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "lg"

CASES = [
    ("tiny_trace", tiny_trace_text),
    ("medium_cicd", medium_cicd_text),
    ("full_route", full_route_synth_text),
]


def _assert_or_update(golden: Path, actual: str, golden_update: bool) -> None:
    if golden_update:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8")
        return
    if not golden.is_file():
        pytest.fail(f"Missing golden {golden}; run pytest --golden-update")
    expected = golden.read_text(encoding="utf-8")
    if actual != expected:
        pytest.fail(
            f"Golden mismatch for {golden.name}: "
            f"expected {len(expected)} bytes, got {len(actual)} bytes"
        )


@pytest.mark.parametrize("name,fixture_fn", CASES)
def test_lg_v3_golden_dry(name: str, fixture_fn, golden_update: bool, tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    result = compress_for_lg(fixture_fn(), f"g{name[:2]}", dry_run=True)
    actual = result.compressed
    assert actual.strip(), name
    _assert_or_update(GOLDEN_DIR / f"{name}.txt", actual, golden_update)
