"""UTF-8 stdio defaults and lg runtime toggles."""

from __future__ import annotations

import os
import sys

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def configure_stdio_utf8() -> None:
    """Force UTF-8 on stdout/stderr so ghost RLE (x) and pytest output never crash."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


def subprocess_env() -> dict[str, str]:
    """Child-process env with UTF-8 IO defaults."""
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _env_flag(name: str, *, default: bool) -> bool:
    """Parse a boolean env var (truthy/falsy tokens); load .env when present."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    raw = os.environ.get(name)
    if raw is None:
        return default
    token = raw.strip().lower()
    if token in _TRUTHY:
        return True
    if token in _FALSY:
        return False
    return default


def llm_summarization_enabled() -> bool:
    """When False, skip Gemini distill (same effect as ``lg run --dry-run`` on FULL route)."""
    return _env_flag("USE_LLM_SUMMARIZATION", default=True)


def safe_write(stream, text: str) -> None:
    """Write text; on legacy encodings fall back to replace via buffer."""
    if not text:
        return
    try:
        stream.write(text)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "utf-8"
        if hasattr(stream, "buffer"):
            stream.buffer.write(text.encode(enc, errors="replace"))
        else:
            stream.write(text.encode("utf-8", errors="replace").decode(enc, errors="replace"))
