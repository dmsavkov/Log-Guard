"""Pytest failure block extraction — names, file:line, soft-cleaned headers."""

from __future__ import annotations

from log_guard.preprocess.pytest_block_extract import extract_pytest_blocks


def _failures_block(*parts: str) -> list[str]:
    lines = [
        "============================= test session starts =============================",
        "collected 1 item",
        "tests/test_foo.py F",
        "",
        "================================== FAILURES ===================================",
    ]
    lines.extend(parts)
    lines.extend(
        [
            "",
            "=========================== short test summary info ===========================",
            "FAILED tests/test_foo.py::TestCliIntegration.test_shell_loop - AssertionError",
            "============================== 1 failed in 0.01s ==============================",
        ]
    )
    return lines


def test_extracts_class_method_after_soft_clean_header():
    """Soft clean reduces '___ TestClass.test ___' to '_ TestClass.test _'."""
    lines = _failures_block(
        "_ TestCliIntegration.test_shell_loop _",
        "",
        "tmp_path = ...",
        "",
        "    def test_shell_loop():",
        "tests/test_foo.py:42:",
        ">       assert False",
        "E       AssertionError: assert False",
    )
    cleaned, blocks = extract_pytest_blocks(lines)
    assert len(blocks) == 1
    _line_no, name, tele = blocks[0]
    assert name == "TestCliIntegration.test_shell_loop"
    assert "pytest_failure: TestCliIntegration.test_shell_loop" in tele
    assert "@tests/test_foo.py:42" in tele
    assert ">       assert False" in tele
    assert any("[T1]" in ln for ln in cleaned)


def test_extracts_function_name_and_line():
    lines = _failures_block(
        "_ test_run_cmd_shell_loop _",
        "",
        "tests/lg/test_cli_integration.py:190:",
        ">       assert proc.returncode == 0",
        "E       AssertionError: assert 1 == 0",
    )
    _, name, tele = extract_pytest_blocks(lines)[1][0]
    assert name == "test_run_cmd_shell_loop"
    assert "@tests/lg/test_cli_integration.py:190" in tele


def test_fallback_from_short_summary_when_header_missing():
    lines = _failures_block(
        "some traceback without underscore header",
        ">       assert 1 == 0",
        "E       AssertionError",
    )
    _, name, tele = extract_pytest_blocks(lines)[1][0]
    assert name == "TestCliIntegration.test_shell_loop"
    assert "pytest_failure:" in tele


def test_standard_long_underscore_header():
    lines = _failures_block(
        "___________________________ test_plain ___________________________",
        ">       assert 0",
        "E       assert 1 == 0",
    )
    _, name, _ = extract_pytest_blocks(lines)[1][0]
    assert name == "test_plain"


def test_pipeline_preserves_failure_identity():
    """End-to-end dry-run compression keeps test name and file:line."""
    from log_guard.lg.pipeline import compress_for_lg

    lines = _failures_block(
        "_ test_run_cmd_shell_loop _",
        "tests/lg/test_cli_integration.py:190:",
        ">       assert proc.returncode == 0",
        "E       AssertionError: assert 1 == 0",
    )
    raw = "\n".join(lines)
    result = compress_for_lg(raw, "pytest-e2e", dry_run=True)
    assert "test_run_cmd_shell_loop" in result.compressed
    assert "test_cli_integration.py:190" in result.compressed
