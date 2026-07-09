"""Tests for [LogGuard:xxxx] header format."""

import re

from log_guard.lg.storage import new_run_id


def test_run_id_is_four_hex_chars():
    run_id = new_run_id()
    assert len(run_id) == 4
    assert re.fullmatch(r"[0-9a-f]{4}", run_id)
