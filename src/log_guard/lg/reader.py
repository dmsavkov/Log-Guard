"""File read helper for lg read."""

from __future__ import annotations

from pathlib import Path


def read_file(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")
