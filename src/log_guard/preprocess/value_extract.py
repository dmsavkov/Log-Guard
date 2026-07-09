"""Generic value extraction + in-place hashing for v0.15 experiments."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field

from loguru import logger

# ML / training terms — lines containing these may be kept verbatim when keep_ml_keywords=True.
_ML_KEYWORD_RE = re.compile(
    r"\b("
    r"loss|accuracy|epoch|batch|learning_rate|lr|memory|cuda|gpu|gradient|"
    r"pass_rate|f1|bleu|rouge|perplexity|throughput|latency|"
    r"checkpoint|tokenizer|embedding|tensor|dtype|device|optimizer"
    r")\b",
    re.IGNORECASE,
)

_KV_PAIR_RE = re.compile(
    r"(?<![\w.])([a-zA-Z_][\w.]*)=([^\s,;|]+(?:\([^\)]*\))?)",
)
_DICT_START_RE = re.compile(r"\{")
_TENSOR_RE = re.compile(
    r"(?:tensor|array|Tensor|ndarray)\((.*?)\)",
    re.DOTALL | re.IGNORECASE,
)
_ARRAY_PREFIX_RE = re.compile(
    r"(?:np\.|torch\.)?(?:array|tensor|zeros|ones|randn|empty)\(",
    re.IGNORECASE,
)


@dataclass
class ExtractedRecord:
    hash_id: str
    line_no: int
    kind: str
    summary: str
    stored_value: str
    original_len: int
    top_keys: list[str] = field(default_factory=list)
    block_no: int = 0


@dataclass
class ValueExtractStats:
    lines_in: int = 0
    lines_hashed: int = 0
    kv_lines: int = 0
    dict_lines: int = 0
    tensor_lines: int = 0
    entropy_tokens: int = 0
    kept_rare: int = 0
    kept_ml: int = 0
    chars_before: int = 0
    chars_after: int = 0
    records: list[ExtractedRecord] = field(default_factory=list)


def _hash_id(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:8].upper()


def _entropy(text: str) -> float:
    if not text:
        return 0.0
    ent = 0.0
    n = len(text)
    for ch in set(text):
        p = text.count(ch) / n
        if p > 0:
            ent -= p * math.log2(p)
    return ent


def _line_signature(line: str) -> str:
    """Normalize line for rare-line detection (strip digits and long tokens)."""
    s = re.sub(r"\d+(?:\.\d+)?", "<N>", line)
    s = re.sub(r"\S{20,}", "<BLOB>", s)
    return s.strip()


def _extract_balanced_dict(text: str, start: int) -> tuple[str, int] | None:
    """Return dict substring and end index from first `{` at/after start."""
    idx = text.find("{", start)
    if idx < 0:
        return None
    depth = 0
    for i in range(idx, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[idx : i + 1], i + 1
    return None


def _scrub_tensor(text: str) -> tuple[str, list[str]]:
    summaries: list[str] = []

    def _replacer(match: re.Match[str]) -> str:
        content = match.group(1)
        dims = 0
        for ch in content.lstrip():
            if ch == "[":
                dims += 1
            else:
                break
        elements = max(1, content.count(",") + 1)
        meta_parts: list[str] = [f"ndim={dims}", f"elements~={elements}"]
        for key in ("dtype", "device"):
            if f"{key}=" in content:
                frag = content.split(f"{key}=", 1)[1].split(",", 1)[0].strip(")'\" ")
                meta_parts.append(f"{key}={frag}")
        summary = f"[Matrix: {', '.join(meta_parts)}]"
        summaries.append(summary)
        return summary

    out = _TENSOR_RE.sub(_replacer, text)
    return out, summaries


def _scrub_entropy_tokens(
    text: str,
    *,
    min_token_len: int = 30,
    entropy_threshold: float = 4.5,
    delete_tokens: bool = False,
) -> tuple[str, int]:
    words = text.split()
    out_words: list[str] = []
    count = 0
    for w in words:
        if len(w) >= min_token_len and _entropy(w) >= entropy_threshold:
            if delete_tokens:
                count += 1
                continue
            short_hid = _hash_id(w)[:4].lower()
            out_words.append(f"[{short_hid}]")
            count += 1
        else:
            out_words.append(w)
    return " ".join(out_words), count


def _extract_kv_summary(line: str) -> tuple[str, str | None]:
    if "pip install" in line or "==" in line or "http://" in line or "https://" in line:
        return line, None
    pairs = _KV_PAIR_RE.findall(line)
    metric_pairs = []
    for key, val in pairs:
        if re.fullmatch(r"-?\d+(?:\.\d+)?", val) or re.fullmatch(r"[A-Za-z_]\w*", val):
            metric_pairs.append((key, val))
    if len(metric_pairs) < 2:
        return line, None
    keys = [k for k, _ in metric_pairs[:12]]
    summary = f"kv pairs ({len(metric_pairs)}): {', '.join(keys)}"
    scrubbed = line
    for key, val in metric_pairs:
        scrubbed = scrubbed.replace(f"{key}={val}", f"{key}=<{key}>", 1)
    return scrubbed, summary


def _extract_dict_summary(line: str) -> tuple[str, str | None, str | None]:
    if "{" not in line:
        return line, None, None
    block = _extract_balanced_dict(line, 0)
    if not block:
        return line, None, None
    dict_str, end = block
    if len(dict_str) < 20:
        return line, None, None
    keys = re.findall(r"['\"]?([a-zA-Z_]\w*)['\"]?\s*:", dict_str)
    if not keys:
        keys = re.findall(r"['\"]?([a-zA-Z_]\w*)['\"]?\s*=", dict_str)
    key_hint = ", ".join(keys[:8]) if keys else "nested"
    summary = f"dict block ({len(dict_str)} chars, keys: {key_hint})"
    scrubbed = line[: line.find("{")] + "[DICT_EXTRACTED]" + line[end:]
    return scrubbed, summary, dict_str


def _should_keep_line(
    line: str,
    sig_counts: dict[str, int],
    *,
    keep_rare: bool,
    keep_ml_keywords: bool,
) -> tuple[bool, str]:
    if keep_ml_keywords and _ML_KEYWORD_RE.search(line):
        return True, "ml_keyword"
    sig = _line_signature(line)
    if keep_rare and sig_counts.get(sig, 0) <= 1:
        return True, "rare"
    return False, ""


def _stub_without_hash(line: str, line_no: int) -> str:
    """Narrative stub for OOB mode — no hash pointer in distill payload."""
    # Keep level/module prefix if present; drop heavy tail.
    m = re.match(r"^(\d+\.?\d*s\s+\d+\s+)?(.{0,120})", line)
    if m:
        prefix = m.group(1) or ""
        tail = m.group(2).split(" - ", 1)
        if len(tail) == 2:
            return f"{prefix}{tail[0]} - {tail[1][:80]}…"
        return f"{prefix}{m.group(2)[:100]}…"
    return f"[event at line {line_no}]"


def extract_values(
    lines: list[str],
    *,
    enable_kv: bool = False,
    enable_dict: bool = False,
    enable_tensor: bool = False,
    enable_entropy: bool = False,
    hash_mode: str = "inplace",
    min_line_len: int = 80,
    keep_rare: bool = False,
    keep_ml_keywords: bool = False,
) -> tuple[list[str], ValueExtractStats]:
    """Extract bulky values; optionally replace lines with hash placeholders."""
    stats = ValueExtractStats(
        lines_in=len(lines),
        kv_lines=0,
        dict_lines=0,
        tensor_lines=0,
    )
    stats.chars_before = sum(len(ln) for ln in lines)

    sig_counts: dict[str, int] = {}
    for ln in lines:
        sig = _line_signature(ln)
        sig_counts[sig] = sig_counts.get(sig, 0) + 1

    out_lines: list[str] = []
    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        original = line
        record_value_parts: list[str] = []
        kinds: list[str] = []
        summaries: list[str] = []

        if enable_tensor and (_TENSOR_RE.search(line) or _ARRAY_PREFIX_RE.search(line)):
            scrubbed, t_summaries = _scrub_tensor(line)
            if t_summaries:
                line = scrubbed
                stats.tensor_lines += 1
                kinds.append("tensor")
                summaries.extend(t_summaries)
                record_value_parts.append(scrubbed)

        if enable_entropy:
            scrubbed, n_ent = _scrub_entropy_tokens(line)
            if n_ent:
                line = scrubbed
                stats.entropy_tokens += n_ent
                kinds.append("entropy")
                summaries.append(f"{n_ent} high-entropy token(s)")
                record_value_parts.append(original)

        if enable_dict and "{" in line:
            scrubbed, d_summary, dict_blob = _extract_dict_summary(line)
            if d_summary and dict_blob:
                line = scrubbed
                stats.dict_lines += 1
                kinds.append("dict")
                summaries.append(d_summary)
                record_value_parts.append(dict_blob)

        if enable_kv:
            scrubbed, kv_summary = _extract_kv_summary(line)
            if kv_summary:
                line = scrubbed
                stats.kv_lines += 1
                kinds.append("kv")
                summaries.append(kv_summary)
                record_value_parts.append(original)

        extracted = bool(kinds)
        if not extracted:
            out_lines.append(original)
            continue

        keep, reason = _should_keep_line(original, sig_counts, keep_rare=keep_rare, keep_ml_keywords=keep_ml_keywords)
        if keep:
            out_lines.append(original)
            if reason == "rare":
                stats.kept_rare += 1
            elif reason == "ml_keyword":
                stats.kept_ml += 1
            continue

        # Whole-line hash when line is long or heavily scrubbed.
        heavy = len(original) >= min_line_len or len(line) < len(original) * 0.6
        if not heavy:
            out_lines.append(line)
            continue

        stored = "\n---\n".join(record_value_parts) if record_value_parts else original
        hid = _hash_id(stored)
        kind = "+".join(sorted(set(kinds)))
        summary = "; ".join(summaries)[:200]

        stats.records.append(
            ExtractedRecord(
                hash_id=hid,
                line_no=i,
                kind=kind,
                summary=summary,
                stored_value=stored[:4000],
                original_len=len(original),
            )
        )
        stats.lines_hashed += 1

        if hash_mode == "strip":
            out_lines.append(_stub_without_hash(original, i))
        elif hash_mode == "pointer":
            out_lines.append(f"[HASH_{hid}] {summary}")
        else:
            out_lines.append(f"[HASH_{hid}] {summary}")

    stats.chars_after = sum(len(ln) for ln in out_lines)
    logger.info(
        "value_extract: {} lines → {} hashed, {} chars → {}",
        stats.lines_in,
        stats.lines_hashed,
        stats.chars_before,
        stats.chars_after,
    )
    return out_lines, stats


def stats_dict(stats: ValueExtractStats) -> dict:
    d = asdict(stats)
    d["records"] = [asdict(r) for r in stats.records]
    return d


def format_appendix(records: list[ExtractedRecord]) -> str:
    if not records:
        return ""
    lines = ["---", "[AVAILABLE CONTEXT HASHES]:"]
    seen: set[str] = set()
    for rec in records:
        if rec.hash_id in seen:
            continue
        seen.add(rec.hash_id)
        tok = f"[H#{rec.hash_id}]" if len(rec.hash_id) <= 3 else f"[HASH_{rec.hash_id}]"
        lines.append(f"- {tok} ({rec.kind}, line {rec.line_no})")
        if rec.top_keys:
            lines.append(f"  keys: {', '.join(rec.top_keys)}")
        preview = rec.stored_value.replace("\n", " ")[:240]
        if preview:
            lines.append(f"  data: {preview}")
    return "\n".join(lines)
