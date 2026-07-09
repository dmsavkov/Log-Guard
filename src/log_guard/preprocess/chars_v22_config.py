"""v0.22 character-cleaning ablation config — baseline + single-flag overrides."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

# v0.22 default Drain for character pipeline (0.7/8 outperforms 0.5/6 on Kaggle).
DEFAULT_CHARS_DRAIN_SIM_TH = 0.7
DEFAULT_CHARS_DRAIN_DEPTH = 8


@dataclass(frozen=True)
class CharsV22Config:
    """Boolean toggles for soft / mid / hard char phases (baseline = all ON where applicable)."""

    # Phase 1 — soft cleaning
    clean_ansi: bool = True
    clean_progress: bool = True
    clean_prefix: bool = True
    clean_paths: bool = True
    clean_base64: bool = True
    clean_whitespace: bool = True
    clean_entropy: bool = True

    # Phase 2 — mid-session (post-extract shrapnel)
    mid_enabled: bool = True
    mid_orphan_lines: bool = False
    mid_shrapnel_orphans: bool = True
    mid_orphan_chars_only: bool = False
    mid_hex: bool = True
    mid_box: bool = True
    mid_special: bool = True

    # Phase 3 — hard lexical / drain
    hard_mask_num: bool = True
    hard_mask_ip: bool = True
    hard_strip_punct: bool = True
    hard_split_words: bool = True
    hard_extended_masks: bool = True
    drain_sim_th: float = DEFAULT_CHARS_DRAIN_SIM_TH
    drain_depth: int = DEFAULT_CHARS_DRAIN_DEPTH

    # Quirky overrides
    extract_kv_brackets_only: bool = False
    force_ghost_all: bool = False

    @classmethod
    def baseline(cls) -> CharsV22Config:
        return cls()

    def to_exp_cfg(self) -> dict:
        """Flatten into experiment registry keys consumed by compression_v022."""
        return {
            "chars_v22": True,
            "char_clean": False,
            "temporal_strip": self.clean_prefix,
            "v22_clean_ansi": self.clean_ansi,
            "v22_clean_progress": self.clean_progress,
            "v22_clean_prefix": self.clean_prefix,
            "v22_clean_paths": self.clean_paths,
            "v22_clean_base64": self.clean_base64,
            "v22_clean_whitespace": self.clean_whitespace,
            "v22_clean_entropy": self.clean_entropy,
            "v22_mid_enabled": self.mid_enabled,
            "v22_mid_orphan_lines": self.mid_orphan_lines,
            "v22_mid_shrapnel_orphans": self.mid_shrapnel_orphans,
            "v22_mid_orphan_chars_only": self.mid_orphan_chars_only,
            "v22_mid_hex": self.mid_hex,
            "v22_mid_box": self.mid_box,
            "v22_mid_special": self.mid_special,
            "lexical_remove_numbers": self.hard_mask_num,
            "lexical_mask_ip": self.hard_mask_ip,
            "lexical_strip_punct": self.hard_strip_punct,
            "drain_split_words": self.hard_split_words,
            "drain_extended_masks": self.hard_extended_masks,
            "drain_sim_th": self.drain_sim_th,
            "drain_depth": self.drain_depth,
            "extract_kv_brackets_only": self.extract_kv_brackets_only,
            "force_ghost_all": self.force_ghost_all,
            "drain_kv_merge": True,
        }

    def asdict(self) -> dict:
        return asdict(self)


def _abl(**kwargs: object) -> dict:
    """Merge a single ablation override onto baseline exp_cfg."""
    cfg = replace(CharsV22Config.baseline(), **kwargs)
    return cfg.to_exp_cfg()


# Single-flag (or small) overrides keyed by experiment id.
CHARS_V22_ABLATIONS: dict[str, dict] = {
    # Group A — soft
    "chars_v22_soft_no_ansi": _abl(clean_ansi=False),
    "chars_v22_soft_no_progress": _abl(clean_progress=False),
    "chars_v22_soft_no_prefix": _abl(clean_prefix=False),
    "chars_v22_soft_no_paths": _abl(clean_paths=False),
    "chars_v22_soft_no_base64": _abl(clean_base64=False),
    "chars_v22_soft_no_whitespace": _abl(clean_whitespace=False),
    "chars_v22_soft_no_entropy": _abl(clean_entropy=False),
    # Group B — mid
    "chars_v22_mid_no_orphan_lines": _abl(mid_orphan_lines=True),
    "chars_v22_mid_orphan_chars_only": _abl(mid_orphan_lines=False, mid_orphan_chars_only=True),
    "chars_v22_mid_no_hex": _abl(mid_hex=False),
    "chars_v22_mid_no_box": _abl(mid_box=False),
    "chars_v22_mid_no_special": _abl(mid_special=False),
    # Group C — hard lexical
    "chars_v22_hard_no_num": _abl(hard_mask_num=False),
    "chars_v22_hard_no_ip": _abl(hard_mask_ip=False),
    "chars_v22_hard_no_punct": _abl(hard_strip_punct=False),
    "chars_v22_hard_no_split": _abl(hard_split_words=False),
    "chars_v22_hard_no_extended_masks": _abl(hard_extended_masks=False),
    # Group D — drain tuning
    "chars_v22_drain_tune_06_3": _abl(drain_sim_th=0.6, drain_depth=3),
    "chars_v22_drain_tune_02_3": _abl(drain_sim_th=0.2, drain_depth=3),
    "chars_v22_drain_tune_04_4": _abl(drain_sim_th=0.4, drain_depth=4),
    # Group D — quirky
    "chars_v22_quirky_strict_kv_delimiters": _abl(extract_kv_brackets_only=True),
    "chars_v22_quirky_drain_on_ml": _abl(force_ghost_all=True, drain_sim_th=0.6, drain_depth=3),
    "chars_v22_quirky_no_mid_cleaning": _abl(mid_enabled=False),
    "chars_v22_quirky_entropy_delete": {**_abl(), "entropy_delete": True},
    # Group D — quirky extract / drain masks (medium-risk ablations)
    "chars_v22_quirky_extract_colon_kv": {
        **_abl(),
        "extract_dict": False,
        "extract_list": False,
        "extract_tuple": False,
        "extract_tensor": False,
        "extract_entropy": False,
        "extract_eq_kv": False,
        "extract_colon_kv": True,
    },
    "chars_v22_quirky_extract_pip_install": {
        **_abl(),
        "extract_dict": False,
        "extract_list": False,
        "extract_tuple": False,
        "extract_tensor": False,
        "extract_entropy": False,
        "extract_eq_kv": False,
        "extract_colon_kv": False,
        "extract_pip_heuristic": True,
    },
    "chars_v22_quirky_drain_extra_masks": _abl(hard_mask_num=False, hard_mask_ip=False),
    "chars_v22_quirky_no_drain_kv": {**_abl(), "drain_kv_merge": False},
}

CHARS_V22_EXPERIMENT_IDS = ["chars_v22_baseline", "chars_baseline_v2", *CHARS_V22_ABLATIONS.keys()]


def baseline_v2_exp_cfg() -> dict:
    """Canonical v2 char + extract defaults (Group C registry keys)."""
    return {
        **CharsV22Config.baseline().to_exp_cfg(),
        "min_hash_line_len": 0,
        "max_hash_groups": 10,
        "kv_freq_skip_threshold": 25,
        "extract_colon_kv": True,
        "extract_pip_heuristic": True,
        "drain_kv_merge": False,
        "merge_block_hashes": True,
        "v22_mid_shrapnel_orphans": True,
        "v22_mid_orphan_lines": False,
    }
