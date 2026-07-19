"""Load track routing config from tracks.toml."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

_CONFIG_PATH = Path(__file__).resolve().parent / "tracks.toml"


@lru_cache(maxsize=1)
def load_track_config() -> dict:
    return tomllib.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def passthrough_prefixes() -> tuple[str, ...]:
    cfg = load_track_config()
    return tuple(cfg.get("passthrough_prefixes", {}).get("prefixes", []))


def lossless_commands() -> tuple[str, ...]:
    cfg = load_track_config()
    return tuple(cfg.get("lossless_no_truncate", {}).get("commands", []))


def rtk_fast_commands() -> tuple[str, ...]:
    cfg = load_track_config()
    return tuple(cfg.get("rtk_fast", {}).get("commands", []))


def daemon_commands() -> tuple[str, ...]:
    cfg = load_track_config()
    return tuple(cfg.get("daemon_warn", {}).get("commands", []))
