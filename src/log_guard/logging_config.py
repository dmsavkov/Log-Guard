"""CLI logging defaults — silence pipeline noise on stdout/stderr."""

from __future__ import annotations

import os
import sys

from loguru import logger


def configure_cli_logging() -> None:
    """Keep only errors on stderr unless LOGGUARD_VERBOSE is set."""
    logger.remove()
    level = "DEBUG" if os.environ.get("LOGGUARD_VERBOSE", "").strip().lower() in ("1", "true", "yes") else "ERROR"
    logger.add(sys.stderr, level=level)
