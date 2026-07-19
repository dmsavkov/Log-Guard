"""Run history listing for lg history."""

from __future__ import annotations

from datetime import datetime

from log_guard.lg.storage import list_run_metas

_W_ID = 4
_W_SAVED = 10
_W_CHARS = 13
_W_DATE = 6
_W_CMD = 32
_W_CONTENT = 24


def _short_date(iso_ts: str) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return f"{dt.strftime('%b')} {dt.day:>2}"
    except ValueError:
        return iso_ts[:6]


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 3] + "..."


def format_history(limit: int = 10, *, include_experimental: bool = False) -> str:
    metas = list_run_metas()
    if not include_experimental:
        metas = [m for m in metas if not m.get("experimental")]
    metas = metas[:limit]
    if not metas:
        return "No LogGuard runs yet.\n"

    header = (
        f"{'ID':<{_W_ID}} "
        f"{'SAVED':<{_W_SAVED}} "
        f"{'CHARS':<{_W_CHARS}} "
        f"{'DATE':<{_W_DATE}} "
        f"{'COMMAND':<{_W_CMD}} "
        f"{'CONTENT':<{_W_CONTENT}}"
    )
    lines = ["LogGuard run history", "", header]
    for meta in metas:
        run_id = meta.get("id", "????")
        raw_c = int(meta.get("raw_chars", 0))
        comp_c = int(meta.get("compressed_chars", 0))
        saved = max(raw_c - comp_c, 0)
        pct = (saved / raw_c * 100) if raw_c else 0.0
        cmd = (meta.get("cmd") or "").strip()
        ts = _short_date(str(meta.get("timestamp", "")))
        inner = str(meta.get("preview", ""))
        lines.append(
            f"{run_id:<{_W_ID}} "
            f"{f'{pct:.0f}% saved':<{_W_SAVED}} "
            f"{f'{raw_c}->{comp_c}':<{_W_CHARS}} "
            f"{ts:<{_W_DATE}} "
            f"{_clip(cmd, _W_CMD)} "
            f"{_clip(inner, _W_CONTENT)}"
        )
    return "\n".join(lines) + "\n"
