"""UTF-8 stdio and safe_write tests."""

from __future__ import annotations

import io
import sys

from log_guard.io_config import configure_stdio_utf8, safe_write


def test_safe_write_unicode_on_stringio():
    buf = io.StringIO()
    safe_write(buf, "ghost RLE [×4] arrow → ok\n")
    assert "×" in buf.getvalue()


def test_configure_stdio_utf8_does_not_crash():
    configure_stdio_utf8()
    buf = io.StringIO()
    safe_write(buf, "[×2] sequence\n")
    assert "sequence" in buf.getvalue()
