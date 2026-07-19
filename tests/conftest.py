"""Pytest path setup and golden-update flag."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

collect_ignore = ["data"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--golden-update",
        action="store_true",
        default=False,
        help="Refresh tests/golden reference files from current pipeline output",
    )


@pytest.fixture
def golden_update(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--golden-update"))
