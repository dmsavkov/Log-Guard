"""Shorten absolute paths in log lines."""

from __future__ import annotations

import os
import re
import site
from dataclasses import dataclass

from log_guard.preprocess.vocab import path_ref

_SITE_PACKAGES = re.compile(
    r"(?:[A-Za-z]:)?[/\\][\w./\\-]*site-packages[/\\]",
    re.IGNORECASE,
)
_UNIX_LIB = re.compile(r"/usr/local/lib/python[\d.]+/dist-packages/")
_DEEP_ABS_PATH = re.compile(
    r"(?<![\w.])((?:/[A-Za-z0-9_.\-]+){3,}/)([A-Za-z0-9_.\-]+(?:\.[A-Za-z0-9]+)?)"
)


def _ellipsis_deep_paths(line: str) -> tuple[str, int]:
    changed = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal changed
        changed += 1
        return f".../{m.group(2)}"

    out = _DEEP_ABS_PATH.sub(_repl, line)
    return out, changed


@dataclass(frozen=True)
class PathPruneStats:
    lines_changed: int


def _workspace_root() -> str:
    return os.getcwd().replace("\\", "/")


def prune_line(line: str) -> tuple[str, bool]:
    original = line
    line, _ = _ellipsis_deep_paths(line)
    line = _SITE_PACKAGES.sub("[SITE-PACKAGES]/", line)
    line = _UNIX_LIB.sub("[SITE-PACKAGES]/", line)
    ws = _workspace_root()
    if ws and len(ws) > 3:
        line = line.replace(ws, "[WORKSPACE]")
        line = line.replace(ws.replace("/", "\\"), "[WORKSPACE]")
    for pkg in site.getsitepackages():
        norm = pkg.replace("\\", "/")
        if norm in line:
            line = line.replace(norm, "[SITE-PACKAGES]")
            line = line.replace(pkg, "[SITE-PACKAGES]")
    if line != original:
        return line, True
    return line, False


def prune_paths(lines: list[str]) -> tuple[list[str], PathPruneStats]:
    out: list[str] = []
    changed = 0
    for line in lines:
        pruned, did = prune_line(line)
        out.append(pruned)
        if did:
            changed += 1
    return out, PathPruneStats(lines_changed=changed)
