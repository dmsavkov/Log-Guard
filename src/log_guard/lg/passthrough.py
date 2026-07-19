"""Passthrough prefixes — skip compression (agent native read tools)."""

from __future__ import annotations

from log_guard.lg.track_config import passthrough_prefixes

PASSTHROUGH_PREFIXES = passthrough_prefixes()


def is_passthrough(command: str) -> bool:
    stripped = command.lstrip()
    return any(stripped.lower().startswith(p.lower()) for p in PASSTHROUGH_PREFIXES)
