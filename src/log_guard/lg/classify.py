"""Command classification for lg track routing."""

from __future__ import annotations

import json
import os
import re
import shlex
from enum import Enum

_COMPOUND_OPS = frozenset({"&&", "||", ";", "|"})
_WRAPPER_PREFIXES = frozenset({"sudo", "uv", "run", "npx", "poetry", "python", "python3", "py"})
_PYTHON_NAMES = frozenset({"python", "python3", "py"})


class Track(str, Enum):
    DAEMON_WARN = "daemon_warn"
    PASSTHROUGH = "passthrough"
    PYTEST_NATIVE = "pytest_native"
    RTK_LOSSLESS = "rtk_lossless"
    RTK_FAST = "rtk_fast"
    FULL_PIPE = "full_pipe"


def _strip_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def split_command_string(command: str) -> list[str]:
    if os.name == "nt":
        try:
            return [_strip_quotes(tok) for tok in shlex.split(command, posix=False)]
        except ValueError:
            return _split_python_c_fallback(command)
    return shlex.split(command)


def _split_python_c_fallback(command: str) -> list[str]:
    """When shlex fails (triple quotes, etc.), keep ``python -c <code>`` as one argv token."""
    match = re.match(r"^(python3?|py)\s+-c\s+(.*)$", command.strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"Cannot parse command: {command!r}")
    exe = match.group(1).lower()
    code = match.group(2).strip()
    if len(code) >= 2 and code[0] == code[-1] and code[0] in ("'", '"'):
        code = code[1:-1]
    return [exe, "-c", code]


def is_python_inline(command: str) -> bool:
    """True when command runs ``python -c`` (machine-readable stdout expected)."""
    try:
        tokens = split_command_string(command)
    except ValueError:
        return False
    for index, token in enumerate(tokens):
        base = token.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].lower()
        if base in _PYTHON_NAMES and index + 1 < len(tokens) and tokens[index + 1] == "-c":
            return True
    return False


def looks_like_machine_json(text: str) -> bool:
    """True when stdout is a single JSON object/array (downstream json.loads target)."""
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
        return True
    except json.JSONDecodeError:
        return False


def is_compound_command(command: str) -> bool:
    try:
        tokens = split_command_string(command)
    except ValueError:
        return True
    return any(op in tokens for op in _COMPOUND_OPS)


def classify_base_command(command: str) -> str:
    """Return base executable or 'compound_command' / 'unknown'."""
    try:
        tokens = split_command_string(command)
    except ValueError:
        return "unknown"
    if any(op in tokens for op in _COMPOUND_OPS):
        return "compound_command"
    for token in tokens:
        if "=" in token and not token.startswith("-"):
            continue
        base = token.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        if base in _WRAPPER_PREFIXES:
            continue
        return base.lower()
    return "unknown"


def _cmd_starts_with(command: str, prefix: str) -> bool:
    return command.lstrip().lower().startswith(prefix.lower())


def _matches_lossless(base: str, command: str, lossless: list[str]) -> bool:
    cmd_lower = command.lstrip().lower()
    for entry in lossless:
        if cmd_lower.startswith(entry.lower()):
            return True
    return base in {e.split()[0] for e in lossless}


def _matches_daemon(base: str, command: str, daemons: list[str]) -> bool:
    cmd_lower = command.lstrip().lower()
    tokens = set(split_command_string(command))
    token_lowers = {t.lower() for t in tokens}
    for d in daemons:
        dl = d.lower()
        if base == dl or dl in token_lowers:
            return True
        if cmd_lower.startswith(dl + " ") or cmd_lower == dl:
            return True
    if "npm" in token_lowers and "run dev" in cmd_lower:
        return True
    if base == "python" and "http.server" in cmd_lower:
        return True
    if base == "django-admin" and "runserver" in cmd_lower:
        return True
    if base == "next" and " dev" in cmd_lower:
        return True
    return False


def resolve_track(
    command: str,
    *,
    shell_mode: bool,
    passthrough_prefixes: tuple[str, ...],
    lossless_commands: tuple[str, ...],
    rtk_fast_commands: tuple[str, ...],
    daemon_commands: tuple[str, ...],
) -> Track:
    if is_compound_command(command):
        return Track.FULL_PIPE

    stripped = command.lstrip()
    if any(stripped.lower().startswith(p.lower()) for p in passthrough_prefixes):
        return Track.PASSTHROUGH

    if is_python_inline(stripped):
        return Track.PASSTHROUGH

    base = classify_base_command(command)
    if base == "compound_command":
        return Track.FULL_PIPE
    if _matches_daemon(base, command, list(daemon_commands)):
        return Track.DAEMON_WARN
    if base == "pytest" or stripped.lower().startswith("pytest "):
        return Track.PYTEST_NATIVE
        
    is_rtk_lossless = _matches_lossless(base, command, list(lossless_commands))
    is_rtk_fast = base in {c.lower() for c in rtk_fast_commands}
    
    if is_rtk_lossless or is_rtk_fast:
        if shell_mode:
            return Track.FULL_PIPE
        return Track.RTK_LOSSLESS if is_rtk_lossless else Track.RTK_FAST
        
    return Track.FULL_PIPE


_DAEMON_WARN_MSG = (
    "[LogGuard] Warning: This is a blocking/interactive command. "
    "Do not use 'lg run' for this. Run it natively in your terminal."
)

DAEMON_WARN_MSG = _DAEMON_WARN_MSG
