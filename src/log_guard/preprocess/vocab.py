"""Canonical compression tag vocabulary for v0.4 payloads."""

from __future__ import annotations


def rle_block(*, cluster_id: int, count: int, template: str, first: str = "", last: str = "") -> str:
    parts = [f"RLE id={cluster_id} count={count}", f'tpl="{template}"']
    if first:
        parts.append(f"first={first}")
    if last and last != first:
        parts.append(f"last={last}")
    return " ".join(parts)


def metric_line(key: str, value: str, **extra: str) -> str:
    extras = " ".join(f"{k}={v}" for k, v in extra.items())
    return f"METRIC {key}={value}" + (f" {extras}" if extras else "")


def trace_graph(path: str) -> str:
    return f"TRACE {path}"


def tensor_meta(shape: str, dtype: str = "", device: str = "") -> str:
    parts = [f"TENSOR shape={shape}"]
    if dtype:
        parts.append(f"dtype={dtype}")
    if device:
        parts.append(f"device={device}")
    return " ".join(parts)


def entropy_stripped(size_kb: float) -> str:
    return f"ENTROPY size={size_kb:.1f}KB stripped"


def json_ref(ref_id: str, size_kb: float, keys: str = "") -> str:
    base = f"JSON id={ref_id} size={size_kb:.1f}KB"
    return f"{base} keys={keys}" if keys else base


def path_ref(location: str) -> str:
    return f"PATH {location}"


def warn_compact(message: str) -> str:
    return f"WARN {message}"


def err_compact(message: str) -> str:
    return f"ERR {message}"
