"""~/.logguard/<id>/ artifact storage.

Set LOGGUARD_HOME to override the root directory for all run artifacts.
Canonical layout: LOGGUARD_HOME/<id>/raw.txt, lg, values.json, meta.json, intermediate/
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

DEFAULT_HOME = Path.home() / ".logguard"
LEGACY_RUNS_DIR = "runs"


def logguard_home() -> Path:
    override = os.environ.get("LOGGUARD_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_HOME


def new_run_id() -> str:
    return uuid4().hex[:4]


def run_dir(run_id: str) -> Path:
    path = logguard_home() / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_run_dir(run_id: str) -> Path:
    return logguard_home() / LEGACY_RUNS_DIR / run_id


def raw_path(run_id: str) -> Path:
    canonical = run_dir(run_id) / "raw.txt"
    if canonical.is_file():
        return canonical
    legacy_nested = _legacy_run_dir(run_id) / "raw"
    if legacy_nested.is_file():
        return legacy_nested
    legacy_flat = logguard_home() / LEGACY_RUNS_DIR / f"{run_id}.raw"
    if legacy_flat.is_file():
        return legacy_flat
    return canonical


def lg_path(run_id: str) -> Path:
    canonical = run_dir(run_id) / "lg"
    if canonical.is_file():
        return canonical
    legacy = _legacy_run_dir(run_id) / "lg"
    if legacy.is_file():
        return legacy
    legacy_flat = logguard_home() / LEGACY_RUNS_DIR / f"{run_id}.lg"
    if legacy_flat.is_file():
        return legacy_flat
    return canonical


def values_path(run_id: str) -> Path:
    canonical = run_dir(run_id) / "values.json"
    if canonical.is_file():
        return canonical
    legacy = _legacy_run_dir(run_id) / "values.json"
    if legacy.is_file():
        return legacy
    legacy_flat = logguard_home() / LEGACY_RUNS_DIR / f"{run_id}.values.json"
    if legacy_flat.is_file():
        return legacy_flat
    return canonical


def meta_path(run_id: str) -> Path:
    canonical = run_dir(run_id) / "meta.json"
    if canonical.is_file():
        return canonical
    legacy = _legacy_run_dir(run_id) / "meta.json"
    if legacy.is_file():
        return legacy
    legacy_flat = logguard_home() / LEGACY_RUNS_DIR / f"{run_id}.meta.json"
    if legacy_flat.is_file():
        return legacy_flat
    return canonical


def intermediate_dir(run_id: str) -> Path:
    return run_dir(run_id) / "intermediate"


def format_raw_log_hint(run_id: str) -> str:
    """Tilde-prefixed path hint for agent read_file."""
    path = raw_path(run_id).resolve()
    path_str = str(path).replace("\\", "/")
    try:
        home = Path.home().resolve()
        home_str = str(home).replace("\\", "/")
        if path_str.lower().startswith(home_str.lower()):
            path_str = "~" + path_str[len(home_str) :]
    except OSError:
        pass
    return f"[full log {path_str}]"


def save_run(
    run_id: str,
    *,
    raw: str,
    compressed: str,
    values: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    base = run_dir(run_id)
    (base / "raw.txt").write_text(raw, encoding="utf-8")
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
        "raw_path": str((base / "raw.txt").resolve()),
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
    home = logguard_home()

    for path in home.glob("*/meta.json"):
        run_id = path.parent.name
        if run_id in seen or run_id == LEGACY_RUNS_DIR:
            continue
        seen.add(run_id)
        metas.append(json.loads(path.read_text(encoding="utf-8")))

    legacy_root = home / LEGACY_RUNS_DIR
    if legacy_root.is_dir():
        for path in legacy_root.glob("*/meta.json"):
            run_id = path.parent.name
            if run_id in seen:
                continue
            seen.add(run_id)
            metas.append(json.loads(path.read_text(encoding="utf-8")))
        for path in legacy_root.glob("*.meta.json"):
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
    for name in ("values.json", "phases.json", "meta.json", "raw.txt", "lg"):
        p = base / name
        if p.is_file():
            files.append(p)
    return files


def clear_all_runs() -> int:
    """Delete all stored runs under LOGGUARD_HOME. Returns count removed."""
    home = logguard_home()
    removed = 0
    for path in list(home.iterdir()):
        if path.name == LEGACY_RUNS_DIR:
            for child in list(path.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child)
                    removed += 1
                elif child.is_file():
                    child.unlink(missing_ok=True)
                    removed += 1
            continue
        if path.is_dir() and (path / "meta.json").is_file():
            shutil.rmtree(path)
            removed += 1
    return removed


# Back-compat alias used by older tests
def runs_dir() -> Path:
    return logguard_home()
