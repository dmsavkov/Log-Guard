"""~/.logguard/runs/ artifact storage.

Set LOGGUARD_HOME to override the root directory for all run artifacts.
Default: ~/.logguard (runs stored under LOGGUARD_HOME/runs/<id>/).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

RUNS_DIR_NAME = "runs"
DEFAULT_HOME = Path.home() / ".logguard"


def logguard_home() -> Path:
    override = os.environ.get("LOGGUARD_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_HOME


def runs_dir() -> Path:
    path = logguard_home() / RUNS_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_run_id() -> str:
    return uuid4().hex[:4]


def run_dir(run_id: str) -> Path:
    path = runs_dir() / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_raw(run_id: str) -> Path:
    return runs_dir() / f"{run_id}.raw"


def _resolve_run_dir(run_id: str) -> Path:
    nested = run_dir(run_id)
    if (nested / "raw").is_file():
        return nested
    if _legacy_raw(run_id).is_file():
        return runs_dir()
    return nested


def raw_path(run_id: str) -> Path:
    nested = run_dir(run_id) / "raw"
    if nested.is_file():
        return nested
    legacy = _legacy_raw(run_id)
    if legacy.is_file():
        return legacy
    return nested


def lg_path(run_id: str) -> Path:
    nested = run_dir(run_id) / "lg"
    if nested.is_file():
        return nested
    legacy = runs_dir() / f"{run_id}.lg"
    if legacy.is_file():
        return legacy
    return nested


def values_path(run_id: str) -> Path:
    nested = run_dir(run_id) / "values.json"
    if nested.is_file():
        return nested
    legacy = runs_dir() / f"{run_id}.values.json"
    if legacy.is_file():
        return legacy
    return nested


def meta_path(run_id: str) -> Path:
    nested = run_dir(run_id) / "meta.json"
    if nested.is_file():
        return nested
    legacy = runs_dir() / f"{run_id}.meta.json"
    if legacy.is_file():
        return legacy
    return nested


def intermediate_dir(run_id: str) -> Path:
    return run_dir(run_id) / "intermediate"


def save_run(
    run_id: str,
    *,
    raw: str,
    compressed: str,
    values: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    base = run_dir(run_id)
    (base / "raw").write_text(raw, encoding="utf-8")
    (base / "lg").write_text(compressed, encoding="utf-8")
    (base / "values.json").write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raw_chars = len(raw)
    compressed_chars = len(compressed)
    ratio = (compressed_chars / raw_chars) if raw_chars else 1.0
    meta_payload = {
        **meta,
        "id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "raw_chars": raw_chars,
        "compressed_chars": compressed_chars,
        "compression_ratio": ratio,
        "preview": _preview(compressed),
    }
    (base / "meta.json").write_text(
        json.dumps(meta_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _preview(raw: str, limit: int = 40) -> str:
    one_line = re.sub(r"\s+", " ", raw.strip())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def load_raw(run_id: str) -> str:
    path = raw_path(run_id)
    if not path.is_file():
        raise FileNotFoundError(f"No run with id {run_id!r}")
    return path.read_text(encoding="utf-8")


def load_compressed(run_id: str) -> str:
    path = lg_path(run_id)
    if not path.is_file():
        raise FileNotFoundError(f"No run with id {run_id!r}")
    return path.read_text(encoding="utf-8")


def load_values(run_id: str) -> dict[str, Any]:
    path = values_path(run_id)
    if not path.is_file():
        raise FileNotFoundError(f"No values for run {run_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_meta(run_id: str) -> dict[str, Any]:
    path = meta_path(run_id)
    if not path.is_file():
        raise FileNotFoundError(f"No meta for run {run_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_run_metas() -> list[dict[str, Any]]:
    metas: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path in runs_dir().glob("*/meta.json"):
        run_id = path.parent.name
        if run_id in seen:
            continue
        seen.add(run_id)
        metas.append(json.loads(path.read_text(encoding="utf-8")))

    for path in runs_dir().glob("*.meta.json"):
        run_id = path.stem
        if run_id in seen:
            continue
        seen.add(run_id)
        metas.append(json.loads(path.read_text(encoding="utf-8")))

    metas.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
    return metas


def list_debug_files(run_id: str) -> list[Path]:
    base = run_dir(run_id)
    files: list[Path] = []
    inter = intermediate_dir(run_id)
    if inter.is_dir():
        files.extend(sorted(inter.iterdir()))
    for name in ("values.json", "phases.json", "meta.json"):
        p = base / name
        if p.is_file():
            files.append(p)
    return files


def clear_all_runs() -> int:
    """Delete all stored runs under LOGGUARD_HOME/runs. Returns count removed."""
    root = runs_dir()
    removed = 0
    for path in list(root.iterdir()):
        if path.is_dir():
            shutil.rmtree(path)
            removed += 1
        elif path.is_file():
            path.unlink(missing_ok=True)
            removed += 1
    return removed
