"""Lark-based dict extraction for ghost pipeline (v0.17)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from loguru import logger

_DICT_GRAMMAR = r"""
    ?value: dict
          | list
          | string
          | SIGNED_NUMBER      -> number
          | "True"             -> true
          | "False"            -> false
          | "None"             -> null

    list : "[" [value ("," value)*] "]"
    dict : "{" [pair ("," pair)*] "}"
    pair : string ":" value

    string : ESCAPED_STRING | "'" /[^']+/ "'"

    %import common.ESCAPED_STRING
    %import common.SIGNED_NUMBER
    %import common.WS
    %ignore WS
"""

_parser = None


def _get_parser():
    global _parser
    if _parser is None:
        from lark import Lark
        from lark import Transformer

        class DictTransformer(Transformer):
            def string(self, s):
                val = s[0]
                if val.startswith("'") and val.endswith("'"):
                    return val[1:-1]
                if val.startswith('"') and val.endswith('"'):
                    return val[1:-1]
                return val

            def number(self, n):
                return float(n[0]) if "." in n[0] else int(n[0])

            def true(self, _):
                return True

            def false(self, _):
                return False

            def null(self, _):
                return None

            def list(self, items):
                return list(items)

            def dict(self, items):
                return dict(items)

            def pair(self, key_value):
                return (key_value[0], key_value[1])

        _parser = Lark(
            _DICT_GRAMMAR,
            start="value",
            parser="lalr",
            lexer="contextual",
            transformer=DictTransformer(),
        )
    return _parser


@dataclass
class LarkDictRecord:
    line_no: int
    keys: list[str]
    raw: str


@dataclass
class LarkDictStats:
    lines_in: int = 0
    dicts_extracted: int = 0
    chars_before: int = 0
    chars_after: int = 0
    records: list[LarkDictRecord] = field(default_factory=list)


def _extract_balanced_dict(text: str, start: int) -> tuple[str, int] | None:
    idx = text.find("{", start)
    if idx < 0:
        return None
    depth = 0
    for i in range(idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[idx : i + 1], i + 1
    return None


def _try_lark_parse(dict_str: str) -> dict | None:
    try:
        from lark import exceptions

        return _get_parser().parse(dict_str)
    except Exception:
        return None


def mask_dicts_lark(lines: list[str]) -> tuple[list[str], LarkDictStats]:
    """Replace nested dict blocks with <MASK>; store extracted keys for OOB appendix."""
    stats = LarkDictStats(
        lines_in=len(lines),
        chars_before=sum(len(ln) for ln in lines),
    )
    out: list[str] = []

    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if "{" not in line:
            out.append(line)
            continue
        block = _extract_balanced_dict(line, 0)
        if not block or len(block[0]) < 12:
            out.append(line)
            continue
        dict_str, end = block
        parsed = _try_lark_parse(dict_str)
        keys = list(parsed.keys()) if isinstance(parsed, dict) else re.findall(
            r"['\"]?([a-zA-Z_]\w*)['\"]?\s*:", dict_str
        )
        stats.records.append(
            LarkDictRecord(line_no=i, keys=keys[:16], raw=dict_str[:2000])
        )
        stats.dicts_extracted += 1
        masked = line[: line.find("{")] + "<MASK>" + line[end:]
        out.append(masked)

    stats.chars_after = sum(len(ln) for ln in out)
    logger.info("lark_dict: {} dicts masked on {} lines", stats.dicts_extracted, stats.lines_in)
    return out, stats


def format_lark_appendix(records: list[LarkDictRecord]) -> str:
    if not records:
        return ""
    lines = ["---", "[EXTRACTED DICT PARAMS (Lark)]:"]
    for rec in records:
        keys = ", ".join(rec.keys) if rec.keys else "?"
        lines.append(f"- line {rec.line_no}: keys=[{keys}]")
    return "\n".join(lines)


def stats_dict(stats: LarkDictStats) -> dict:
    d = asdict(stats)
    d["records"] = [asdict(r) for r in stats.records]
    return d
