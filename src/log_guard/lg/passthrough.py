"""Passthrough prefixes — skip compression (agent native read tools)."""

from __future__ import annotations

PASSTHROUGH_PREFIXES = ("cat ", "head ", "tail ", "grep ", "sed ", "awk ")


def is_passthrough(command: str) -> bool:
    stripped = command.lstrip()
    return stripped.startswith(PASSTHROUGH_PREFIXES)
