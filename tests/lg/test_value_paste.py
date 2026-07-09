"""Per-block value paste and line_no remap tests."""

from __future__ import annotations

from pathlib import Path

from log_guard.lg.preprocess_input import prepare_log_lines
from log_guard.pipeline.config import build_v3_config
from log_guard.pipeline.passthrough import assembly_kwargs
from log_guard.pipeline.v23_runner import run_v23_stages
from log_guard.lg.session import LgRunSession
from log_guard.preprocess.value_extract import ExtractedRecord
from log_guard.preprocess.value_paste import paste_block_heading_params


def _records_10_txt() -> tuple[list[ExtractedRecord], dict]:
    raw = Path("tests/fixtures/eval_raw/10.txt").read_text(encoding="utf-8")
    lines, raw_for_time = prepare_log_lines(raw)
    cfg = build_v3_config()
    session = LgRunSession("paste-test")
    stages = run_v23_stages(session, lines, cfg, raw_for_time=raw_for_time, dry_run=True)
    asm = assembly_kwargs(
        cfg,
        records=stages.records,
        trace_records=stages.trace_records,
        extracted_lines=stages.extracted_lines,
        block_boundaries=stages.block_boundaries,
    )
    return stages.records, asm


def test_line_no_remapped_into_compact_range():
    records, _ = _records_10_txt()
    hash_recs = [r for r in records if r.kind not in ("stack_trace", "trace")]
    assert hash_recs
    assert max(r.line_no for r in hash_recs) <= 132


def test_paste_distributes_across_block_headings():
    records, asm = _records_10_txt()
    distill = "\n".join(f"### Block {i}\n- summary {i}" for i in range(1, 6))
    out = paste_block_heading_params(
        distill,
        asm["records"],
        block_size=asm["block_size"],
        total_lines=asm["total_lines"],
        short_hash=asm["short_hash"],
        pointer_format=asm["pointer_format"],
        block_boundaries=asm["block_boundaries"],
        merge_block_hashes=asm["merge_block_hashes"],
    )
    for i in range(1, 6):
        section = out.split(f"### Block {i}\n", 1)[1].split("### Block", 1)[0]
        assert "Extracted Values:" in section, f"Block {i} missing Extracted Values"


def test_single_block_no_does_not_hoard_all_headings():
    """All records sharing block_no=1 must not all land under ### Block 1."""
    recs = [
        ExtractedRecord(
            hash_id=str(i),
            line_no=i,
            kind="group",
            summary="g",
            stored_value="{}",
            original_len=2,
            top_keys=["k"],
            block_no=1,
        )
        for i in range(1, 7)
    ]
    distill = "\n".join(f"### Block {i}\n- x" for i in range(1, 6))
    out = paste_block_heading_params(
        distill,
        recs,
        block_size=300,
        total_lines=132,
        block_boundaries=[(1, 132)],
    )
    block1 = out.split("### Block 1\n", 1)[1].split("### Block 2", 1)[0]
    block2 = out.split("### Block 2\n", 1)[1].split("### Block 3", 1)[0]
    assert block1.count("[#") <= 2
    assert "Extracted Values:" in block2
