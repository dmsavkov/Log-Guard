"""CLI should silence pipeline loguru noise unless LOGGUARD_VERBOSE is set."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr
from unittest.mock import patch

import pytest

from log_guard.logging_config import configure_cli_logging


def test_configure_cli_logging_default_is_error_only():
    configure_cli_logging()
    from loguru import logger

    buf = io.StringIO()
    sink_id = logger.add(buf, level="ERROR", format="{message}")
    logger.info("should not appear")
    logger.error("should appear")
    logger.remove(sink_id)
    captured = buf.getvalue()
    assert "should not appear" not in captured
    assert "should appear" in captured


def test_lg_main_configures_quiet_logging(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    monkeypatch.delenv("LOGGUARD_VERBOSE", raising=False)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        with patch("log_guard.lg.cli._execute_and_compress", return_value=0):
            with patch("log_guard.lg.cli.read_file", return_value="line\n"):
                with patch("sys.argv", ["lg", "read", "x.txt"]):
                    from log_guard.lg.cli import main

                    with pytest.raises(SystemExit) as exc:
                        main(["read", "x.txt"])
    assert exc.value.code == 0
    text = stderr.getvalue()
    assert "char_clean:" not in text
    assert "value_extract_v18:" not in text
