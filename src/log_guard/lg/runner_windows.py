"""Windows-specific argv resolution for lg run exec mode."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# Verb-Noun pattern for native PowerShell cmdlets (Get-ChildItem, New-Item, …).
_POWERSHELL_CMDLET = re.compile(r"^[A-Z][a-z]+-[A-Z][a-zA-Z0-9]+$")

_UNIX_ON_WINDOWS = frozenset({"ls", "grep", "find", "sed", "awk", "cat", "head", "tail"})


def is_powershell_cmdlet(name: str) -> bool:
    base = name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return bool(_POWERSHELL_CMDLET.match(base))


def _git_usr_bin_dirs() -> list[Path]:
    candidates: list[Path] = []
    for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_key)
        if root:
            candidates.append(Path(root) / "Git" / "usr" / "bin")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Git" / "usr" / "bin")
    return [p for p in candidates if p.is_dir()]


def _resolve_git_unix_tool(name: str) -> str | None:
    exe_name = name if name.lower().endswith(".exe") else f"{name}.exe"
    for root in _git_usr_bin_dirs():
        candidate = root / exe_name
        if candidate.is_file():
            return str(candidate)
    return None


def wrap_powershell_argv(argv: list[str]) -> list[str]:
    """Run argv through powershell.exe -Command (cmdlets are not standalone executables)."""
    inner = subprocess.list2cmdline(argv)
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        inner,
    ]


def resolve_windows_argv(argv: list[str]) -> list[str]:
    """Map PowerShell cmdlets and missing Unix tools before CreateProcess on Windows."""
    if os.name != "nt" or not argv:
        return argv

    head = argv[0]
    if is_powershell_cmdlet(head):
        return wrap_powershell_argv(argv)

    if shutil.which(head):
        return argv

    base = Path(head).name.lower()
    if base in _UNIX_ON_WINDOWS or base.endswith(".exe") and base[:-4] in _UNIX_ON_WINDOWS:
        tool = base[:-4] if base.endswith(".exe") else base
        resolved = _resolve_git_unix_tool(tool)
        if resolved:
            return [resolved, *argv[1:]]

    return argv
