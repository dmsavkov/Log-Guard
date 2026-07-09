"""RTK state-machine stack trace extraction for v0.19 experiments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from loguru import logger

from log_guard.preprocess.value_extract import ExtractedRecord

_SECTION_RE = re.compile(r"^={1,3}\s*Stack Trace (\d+)\s*={1,3}\s*$", re.IGNORECASE)
_TB_START = re.compile(r"Traceback\s*\(most recent call last\)", re.IGNORECASE)
_TB_INLINE_TYPE = re.compile(
    r"^(\w+(?:Error|Exception|Warning))\s+Traceback\s*\(most recent call last\)",
    re.IGNORECASE,
)
_FRAME = re.compile(
    r'File\s+["\']([^"\']+)["\'],\s*line\s+(\d+)(?:,\s*in\s+(\w+))?',
    re.IGNORECASE,
)
_FRAME_COMPACT = re.compile(
    r'File\s+["\']([^"\']+)["\'],\s*line\s+(\d+)(?:,\s*in\s+(\w+))?',
    re.IGNORECASE,
)
_ERROR_LINE = re.compile(
    r"^(\*{0,2})?(\w+(?:Error|Exception|Warning))(?::\s*(.*))?$",
)
_ERROR_TAIL = re.compile(
    r"(\w+(?:Error|Exception|Warning))(?::\s*|\()([^\n)]*)",
)
_CHAIN_MARKER = re.compile(
    r"(?:During handling of the above exception|"
    r"The above exception was the direct cause|"
    r"While handling the above exception)",
    re.IGNORECASE,
)
_TIMESTAMP = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|\[\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\]|"
    r"\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})",
)
_WARN = re.compile(r"\b(WARNING|WARN|UserWarning|FutureWarning)\b", re.IGNORECASE)
_UNITTEST_ERR = re.compile(r"^ERROR:\s+", re.IGNORECASE)
_FAIL_LINE = re.compile(r"^FAILED\s+", re.IGNORECASE)
_PATTERNS_PATH = Path(__file__).resolve().parents[3] / "helpers" / "patterns.txt"


@lru_cache(maxsize=1)
def _load_extended_patterns() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Error-type names and message fragments from helpers/patterns.txt."""
    if not _PATTERNS_PATH.is_file():
        return (), ()
    raw = _PATTERNS_PATH.read_text(encoding="utf-8")
    items = re.findall(r'"([^"]+)"', raw)
    errors = tuple(
        p for p in items
        if p.endswith(("Error", "Exception", "Warning")) or "." in p and p[0].isupper()
    )
    msgs = tuple(p for p in items if p not in errors and not p.startswith("Traceback"))
    return errors, msgs


def _match_extended_patterns(text: str) -> tuple[str, str]:
    """Fill missing error_type/message using patterns.txt (longest match wins)."""
    error_type = ""
    message = ""
    errors, msgs = _load_extended_patterns()
    for pat in sorted(errors, key=len, reverse=True):
        if pat in text:
            error_type = pat.rsplit(".", 1)[-1] if "." in pat and pat.endswith("Error") else pat
            break
    if not error_type:
        m = re.search(r"\b(\w+(?:Error|Exception|Warning))\b", text)
        if m:
            error_type = m.group(1)
    for pat in sorted(msgs, key=len, reverse=True):
        if pat in text:
            message = pat
            break
    return error_type, message


@dataclass(frozen=True)
class ParsedFrame:
    file: str
    line: int | None
    func: str


@dataclass
class ParsedException:
    error_type: str
    message: str
    frames: list[ParsedFrame] = field(default_factory=list)


@dataclass
class ParsedTraceBlock:
    trace_no: int | None
    exceptions: list[ParsedException]
    raw: str
    start_line: int = 0


@dataclass
class StackExtractStats:
    sections_in: int = 0
    traces_parsed: int = 0
    traces_failed: int = 0
    warnings_truncated: int = 0
    chars_before: int = 0
    chars_after: int = 0
    records: list[ExtractedRecord] = field(default_factory=list)


def _hash_id(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:8].upper()


def truncate_warning_lines(lines: list[str], *, max_len: int = 60) -> tuple[list[str], int]:
    """Truncate WARNING lines to a short pure message."""
    out: list[str] = []
    count = 0
    for ln in lines:
        if _WARN.search(ln):
            # Strip log prefixes like [INFO] module - WARNING -
            msg = re.sub(r"^.*?\b(WARNING|WARN)\b[:\s-]*", "", ln, flags=re.IGNORECASE).strip()
            if not msg:
                msg = ln.strip()
            if len(msg) > max_len:
                msg = msg[: max_len - 3] + "..."
                count += 1
            out.append(msg)
        else:
            out.append(ln)
    return out, count


def _normalize_blob(blob: str) -> str:
    """Expand single-line tracebacks into pseudo-multiline for parsing."""
    t = blob.replace("\r\n", "\n").replace("\r", "\n")
    if _TB_START.search(t) and t.count("\n") < 2:
        t = re.sub(
            r"(Traceback\s*\(most recent call last\):)\s*",
            r"\1\n  ",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(r"\s+(File\s+)", r"\n  \1", t)
    return t


def _parse_frames(text: str) -> list[ParsedFrame]:
    frames: list[ParsedFrame] = []
    for m in _FRAME.finditer(text):
        func = m.group(3) or ""
        try:
            line_no = int(m.group(2))
        except ValueError:
            line_no = None
        frames.append(ParsedFrame(file=m.group(1), line=line_no, func=func))
    return frames


def _split_exception_segments(text: str) -> list[str]:
    """Split chained tracebacks on secondary Traceback headers."""
    parts = re.split(
        r"(?=(?:\n|^)\s*Traceback\s*\(most recent call last\))",
        text,
        flags=re.IGNORECASE,
    )
    return [p.strip() for p in parts if p.strip()]


def _parse_exception_segment(seg: str, *, extended_patterns: bool = False) -> ParsedException | None:
    frames = _parse_frames(seg)
    error_type = ""
    message = ""

    # Inline type before Traceback (Jupyter style)
    m_inline = _TB_INLINE_TYPE.search(seg)
    if m_inline:
        error_type = m_inline.group(1)
        seg = seg[m_inline.end() :]

    # Last matching error tail in segment
    for m in _ERROR_TAIL.finditer(seg):
        error_type = m.group(1)
        message = m.group(2).strip()

    # Line-based error at end
    for line in reversed(seg.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("File "):
            continue
        em = _ERROR_LINE.match(stripped)
        if em:
            error_type = em.group(2)
            message = (em.group(3) or "").strip()
            break
        if not error_type and ":" in stripped and not stripped.startswith("Traceback"):
            head, _, tail = stripped.partition(":")
            if head.endswith("Error") or head.endswith("Exception"):
                error_type = head.strip()
                message = tail.strip()
                break

    if not error_type and not message and not frames:
        return None
    if not error_type:
        error_type = "Exception"
    if extended_patterns and (not message or error_type == "Exception"):
        ext_type, ext_msg = _match_extended_patterns(seg)
        if ext_type and error_type == "Exception":
            error_type = ext_type
        if ext_msg and not message:
            message = ext_msg
    return ParsedException(error_type=error_type, message=message, frames=frames)


def parse_trace_block(
    blob: str,
    *,
    trace_no: int | None = None,
    extended_patterns: bool = False,
) -> ParsedTraceBlock:
    """Parse one traceback blob (possibly chained) into structured exceptions."""
    normalized = _normalize_blob(blob)
    segments = _split_exception_segments(normalized)
    exceptions: list[ParsedException] = []
    for seg in segments:
        exc = _parse_exception_segment(seg, extended_patterns=extended_patterns)
        if exc:
            exceptions.append(exc)
    return ParsedTraceBlock(trace_no=trace_no, exceptions=exceptions, raw=blob.strip())


def _frame_label(frame: ParsedFrame) -> str:
    if frame.func:
        return f"{frame.func}()"
    name = frame.file.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name or frame.file


def _format_type_message(block: ParsedTraceBlock) -> str:
    lines: list[str] = []
    prefix = f"Trace {block.trace_no}: " if block.trace_no else ""
    if not block.exceptions:
        return f"{prefix}ERR extraction_failed"
    for exc in block.exceptions:
        msg = exc.message[:120] + ("…" if len(exc.message) > 120 else "")
        lines.append(f"{prefix}ERR {exc.error_type}: {msg}".strip())
        prefix = ""
    return "\n".join(lines)


def _format_frames(block: ParsedTraceBlock) -> str:
    lines: list[str] = []
    prefix = f"Trace {block.trace_no}: " if block.trace_no else ""
    for exc in block.exceptions:
        parts = [_frame_label(f) for f in exc.frames]
        if exc.error_type:
            tail = f"{exc.error_type}: {exc.message[:80]}"
            parts.append(tail)
        path = " → ".join(parts) if parts else f"{exc.error_type}: {exc.message}"
        lines.append(f"{prefix}{path}".strip())
        prefix = ""
    return "\n".join(lines)


def _format_close_lines(block: ParsedTraceBlock, *, context: int = 2) -> str:
    if not block.exceptions:
        return _format_type_message(block)
    exc = block.exceptions[-1]
    lines: list[str] = []
    prefix = f"Trace {block.trace_no}: " if block.trace_no else ""
    for fr in exc.frames[-context:]:
        lines.append(f'{prefix}  File "{fr.file}", line {fr.line or "?"}, in {fr.func or "?"}')
        prefix = ""
    lines.append(f"ERR {exc.error_type}: {exc.message[:120]}")
    return "\n".join(lines)


def _format_last_only(block: ParsedTraceBlock) -> str:
    if not block.exceptions:
        return _format_type_message(block)
    exc = block.exceptions[-1]
    prefix = f"Trace {block.trace_no}: " if block.trace_no else ""
    msg = exc.message[:120] + ("…" if len(exc.message) > 120 else "")
    return f"{prefix}ERR {exc.error_type}: {msg}".strip()


def _format_first_last(block: ParsedTraceBlock) -> str:
    if not block.exceptions:
        return _format_type_message(block)
    exc = block.exceptions[-1]
    prefix = f"Trace {block.trace_no}: " if block.trace_no else ""
    first = _frame_label(exc.frames[0]) if exc.frames else "?"
    last = _frame_label(exc.frames[-1]) if exc.frames else "?"
    msg = exc.message[:100] + ("…" if len(exc.message) > 100 else "")
    return f"{prefix}first={first} last={last} ERR {exc.error_type}: {msg}".strip()


def _format_sentry(block: ParsedTraceBlock) -> str:
    if not block.exceptions:
        return _format_type_message(block)
    exc = block.exceptions[-1]
    prefix = f"Trace {block.trace_no}: " if block.trace_no else ""
    first = _frame_label(exc.frames[0]) if exc.frames else "?"
    last = _frame_label(exc.frames[-1]) if exc.frames else "?"
    hidden = max(0, len(exc.frames) - 2)
    mid = f" [... {hidden} framework frames hidden ...] " if hidden > 0 else " → "
    msg = exc.message[:100] + ("…" if len(exc.message) > 100 else "")
    return (
        f"{prefix}{first}{mid}{last} → {exc.error_type}: {msg}".strip()
    )


def _schema_from_block(block: ParsedTraceBlock) -> dict:
    if not block.exceptions:
        return {"trace_no": block.trace_no, "extraction": "failed"}
    exc = block.exceptions[-1]
    crashing = exc.frames[-1] if exc.frames else None
    schema: dict = {"trace_no": block.trace_no}
    if exc.error_type:
        schema["error_type"] = exc.error_type
    if exc.message:
        schema["message"] = exc.message[:500]
    if crashing:
        schema["crashing_file"] = crashing.file.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if crashing.line is not None:
            schema["crashing_line"] = crashing.line
        if crashing.func:
            schema["crashing_function"] = crashing.func
    return schema


def _short_file(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def _format_telegraphic(block: ParsedTraceBlock, *, trace_id: str) -> str:
    if not block.exceptions:
        return f"[T{trace_id}] extraction_failed"
    exc = block.exceptions[-1]
    crashing = exc.frames[-1] if exc.frames else None
    msg = exc.message.replace("'", "\\'")[:120]
    if crashing and crashing.line is not None:
        loc = f"{_short_file(crashing.file)}:{crashing.line}"
    elif crashing:
        loc = _short_file(crashing.file)
    else:
        loc = "?"
    func = f" (**{crashing.func}**)" if crashing and crashing.func else ""
    return f"[T{trace_id}] {exc.error_type}: '{msg}' @ {loc}{func}"


def _next_trace_id(records: list[ExtractedRecord]) -> str:
  numeric = [int(r.hash_id) for r in records if r.hash_id.isdigit()]
  return str(max(numeric, default=0) + 1)


def _emit_telegraphic_trace(
    block: ParsedTraceBlock,
    records: list[ExtractedRecord],
    *,
    line_no: int,
) -> str:
    """Payload line is short [TN] Type; full telegraphic stored for reinjection."""
    tid = _next_trace_id(records)
    full = _format_telegraphic(block, trace_id=tid)
    exc_type = block.exceptions[-1].error_type if block.exceptions else "unknown"
    records.append(
        ExtractedRecord(
            hash_id=tid,
            line_no=line_no,
            kind="stack_trace",
            summary=exc_type,
            stored_value=full,
            original_len=len(full),
            top_keys=["trace"],
        )
    )
    return f"[T{tid}] {exc_type}"


def _skip_unittest_tail(lines: list[str], i: int, n: int) -> int:
    while i < n:
        s = lines[i].strip()
        if _UNITTEST_ERR.match(s) or _FAIL_LINE.match(s):
            i += 1
            continue
        break
    return i


def _format_tuple_line(block: ParsedTraceBlock) -> str:
    if not block.exceptions:
        return f"T{block.trace_no or '?'}(extraction_failed)"
    exc = block.exceptions[-1]
    crashing = exc.frames[-1] if exc.frames else None
    tid = block.trace_no or "?"
    msg = exc.message.replace('"', '\\"')[:120]
    if crashing and crashing.line is not None:
        loc = f"{_short_file(crashing.file)}:{crashing.line}"
    elif crashing:
        loc = _short_file(crashing.file)
    else:
        loc = "?"
    parts = [exc.error_type, f'"{msg}"', loc]
    if crashing and crashing.func:
        parts.append(crashing.func)
    return f"T{tid}({', '.join(parts)})"


def _format_schema_table(schemas: list[dict]) -> str:
    header = "| ID | Type | Message | File:Line | Func |"
    sep = "|---|---|---|---|---|"
    rows: list[str] = [header, sep]
    for sch in schemas:
        tid = sch.get("trace_no", "?")
        etype = sch.get("error_type", sch.get("extraction", "?"))
        msg = str(sch.get("message", ""))[:80]
        file = sch.get("crashing_file", "")
        line = sch.get("crashing_line")
        loc = f"{file}:{line}" if file and line is not None else (file or "-")
        func = sch.get("crashing_function", "-") or "-"
        rows.append(f"| {tid} | {etype} | {msg} | {loc} | {func} |")
    return "\n".join(rows)


def _format_block(
    block: ParsedTraceBlock,
    mode: str,
    *,
    close_context: int = 2,
    hash_pointer: bool = False,
    records: list[ExtractedRecord],
    line_no: int,
) -> str:
    if mode == "type_message":
        text = _format_type_message(block)
    elif mode == "frames":
        text = _format_frames(block)
    elif mode == "close_lines":
        text = _format_close_lines(block, context=close_context)
    elif mode == "last_only":
        text = _format_last_only(block)
    elif mode == "first_last":
        text = _format_first_last(block)
    elif mode == "sentry":
        text = _format_sentry(block)
    elif mode == "schema_det":
        schema = _schema_from_block(block)
        text = json.dumps(schema, ensure_ascii=False)
    elif mode == "schema_det_telegraphic":
        return _emit_telegraphic_trace(block, records, line_no=line_no)
    elif mode == "schema_det_tuple":
        text = _format_tuple_line(block)
    elif mode in ("hash_trace", "rtk_hash"):
        text = _format_type_message(block)
        if hash_pointer and block.raw:
            hid = _hash_id(block.raw)
            records.append(
                ExtractedRecord(
                    hash_id=hid,
                    line_no=line_no,
                    kind="stack_trace",
                    summary=f"trace {block.trace_no or '?'}",
                    stored_value=block.raw,
                    original_len=len(block.raw),
                    top_keys=["trace"],
                )
            )
            text = f"{text} [HASH_{hid}]"
    else:
        text = _format_type_message(block)

    return text


def _rtk_capture_block(lines: list[str], start: int) -> tuple[int, list[str]]:
    """Capture traceback block from *start* until boundary break."""
    block = [lines[start]]
    i = start + 1
    n = len(lines)
    base_indent = len(lines[start]) - len(lines[start].lstrip())

    while i < n:
        ln = lines[i]
        if _SECTION_RE.match(ln):
            break
        if _TIMESTAMP.match(ln.strip()) and i > start + 1:
            break
        stripped = ln.strip()
        if not stripped:
            block.append(ln)
            i += 1
            continue
        indent = len(ln) - len(ln.lstrip())
        # Unindented non-frame line after we've started → likely error tail / end
        if (
            indent <= base_indent
            and i > start
            and not _FRAME.match(stripped)
            and not stripped.lower().startswith("traceback")
            and not stripped.startswith("File ")
            and _ERROR_TAIL.search(stripped)
        ):
            block.append(ln)
            i += 1
            break
        if (
            indent <= base_indent
            and i > start + 2
            and not stripped.startswith(("File ", "Traceback", " ", "\t"))
            and not _FRAME.search(ln)
            and _ERROR_TAIL.search(stripped)
        ):
            block.append(ln)
            i += 1
            break
        block.append(ln)
        i += 1
    return i, block


def extract_stacktraces(
    lines: list[str],
    *,
    mode: str = "type_message",
    close_context: int = 2,
    hash_pointer: bool = False,
    truncate_warnings: bool = True,
    warn_max_len: int = 60,
    extended_patterns: bool = False,
) -> tuple[list[str], StackExtractStats]:
    """Replace traceback blocks with compact representations."""
    from log_guard.preprocess.pytest_block_extract import extract_pytest_blocks

    stats = StackExtractStats(
        chars_before=sum(len(ln) for ln in lines),
        records=[],
    )
    working, pytest_blocks = extract_pytest_blocks(list(lines))
    trace_counter = 0
    for line_no, test_name, telegraphic in pytest_blocks:
        trace_counter += 1
        hid = str(trace_counter)
        stats.records.append(
            ExtractedRecord(
                hash_id=hid,
                line_no=line_no,
                kind="stack_trace",
                summary=f"pytest: {test_name}" if test_name else "pytest failure",
                stored_value=telegraphic,
                original_len=len(telegraphic),
                top_keys=[test_name] if test_name else [],
            )
        )
    if truncate_warnings:
        working, stats.warnings_truncated = truncate_warning_lines(
            working, max_len=warn_max_len
        )

    out: list[str] = []
    batch_schemas: list[dict] = []
    i = 0
    n = len(working)

    while i < n:
        ln = working[i]
        sec = _SECTION_RE.match(ln)
        if sec:
            stats.sections_in += 1
            trace_no = int(sec.group(1))
            i += 1
            block_lines: list[str] = []
            while i < n and not _SECTION_RE.match(working[i]):
                block_lines.append(working[i])
                i += 1
            blob = "\n".join(block_lines).strip()
            if not blob:
                stats.traces_failed += 1
                if mode != "schema_det_table":
                    out.append("ERR extraction_failed: empty section")
                continue
            parsed = parse_trace_block(blob, trace_no=trace_no, extended_patterns=extended_patterns)
            if parsed.exceptions:
                stats.traces_parsed += 1
            else:
                stats.traces_failed += 1
            if mode == "schema_det_table":
                batch_schemas.append(_schema_from_block(parsed))
            else:
                compact = _format_block(
                    parsed,
                    mode,
                    close_context=close_context,
                    hash_pointer=hash_pointer,
                    records=stats.records,
                    line_no=i,
                )
                out.extend(compact.splitlines())
                if mode == "schema_det_telegraphic":
                    i = _skip_unittest_tail(working, i, n)
            continue

        if _TB_START.search(ln) or _TB_INLINE_TYPE.search(ln):
            end, block_lines = _rtk_capture_block(working, i)
            blob = "\n".join(block_lines).strip()
            parsed = parse_trace_block(blob, extended_patterns=extended_patterns)
            if parsed.exceptions:
                stats.traces_parsed += 1
            else:
                stats.traces_failed += 1
            if mode == "schema_det_table":
                batch_schemas.append(_schema_from_block(parsed))
            else:
                compact = _format_block(
                    parsed,
                    mode,
                    close_context=close_context,
                    hash_pointer=hash_pointer or mode == "rtk_hash",
                    records=stats.records,
                    line_no=i + 1,
                )
                out.extend(compact.splitlines())
            if mode == "schema_det_telegraphic":
                i = _skip_unittest_tail(working, end, n)
            else:
                i = end
            continue

        out.append(ln)
        i += 1

    if batch_schemas:
        out.extend(_format_schema_table(batch_schemas).splitlines())

    stats.chars_after = sum(len(ln) for ln in out)
    logger.info(
        "stacktrace_extract mode={}: {} sections, {} parsed, {} failed, {}→{} chars",
        mode,
        stats.sections_in,
        stats.traces_parsed,
        stats.traces_failed,
        stats.chars_before,
        stats.chars_after,
    )
    return out, stats


def stats_dict(stats: StackExtractStats) -> dict:
    d = asdict(stats)
    d["record_count"] = len(stats.records)
    d.pop("records", None)
    return d
