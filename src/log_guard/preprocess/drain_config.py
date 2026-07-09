from drain3 import TemplateMiner
from drain3.masking import MaskingInstruction
from drain3.template_miner_config import TemplateMinerConfig

# Default + extended masks per Drain tuning docs.
_BASE_MASKS = [
    MaskingInstruction(r"^\d+\.?\d*s(?:\t|\s+)\d+(?:\t|\s+)", "KAGGLE_PREFIX"),
    MaskingInstruction(r"\x1b\[[0-9;]*m", "ANSI"),
]

# Full lexical masks — extended_masks=True uses these by default (v0.13+ soft config).
_FULL_LEXICAL_MASKS = [
    *_BASE_MASKS,
    MaskingInstruction(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?\b", "TIMESTAMP"),
    MaskingInstruction(r"\b\d{2}:\d{2}:\d{2}(?:\.\d{3})?\b", "TIMESTAMP"),
    MaskingInstruction(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "IP"),
    MaskingInstruction(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "UUID"),
    MaskingInstruction(r"\b0x[0-9a-fA-F]+\b", "HEX"),
    MaskingInstruction(r"https?://\S+", "URL"),
    MaskingInstruction(r"/[\w./-]{4,}", "PATH"),
    MaskingInstruction(r"\b[0-9a-fA-F]{8,}\b", "HEX_LONG"),
    MaskingInstruction(r"\[(?:Rank|GPU)[-\s]?\d+\]", "RANK"),
]

# v0.21: cluster lines that differ only by [#N] / [T#] pointer ids (Drain LogMasker, tree-building only).
# drain3 has no extra_mask tuple API — extend config.masking_instructions instead.
_SLUG_MASKS = [
    MaskingInstruction(r"\[#\d+\]", "SLUG"),
    MaskingInstruction(r"\[T\d+\]", "TRACE"),
]

_EXTENDED_MASKS = _FULL_LEXICAL_MASKS

# v0.13 soft DRAIN defaults (separate exp first; then applied to all drain_rle_* configs).
DEFAULT_DRAIN_SIM_TH = 0.20
DEFAULT_DRAIN_DEPTH = 3
DEFAULT_DRAIN_MAX_CHILDREN = 10
DEFAULT_DRAIN_EXTRA_DELIMITERS = ["_", ":", "/", ".", "-"]


def make_drain_miner(
    *,
    sim_th: float = DEFAULT_DRAIN_SIM_TH,
    extra_delimiters: list[str] | None = None,
    extended_masks: bool = True,
    drain_depth: int | None = DEFAULT_DRAIN_DEPTH,
    drain_max_children: int | None = DEFAULT_DRAIN_MAX_CHILDREN,
    profile_masks: list[MaskingInstruction] | None = None,
    slug_masks: bool = False,
) -> TemplateMiner:
    config = TemplateMinerConfig()
    config.drain_sim_th = sim_th
    config.drain_extra_delimiters = extra_delimiters if extra_delimiters is not None else list(
        DEFAULT_DRAIN_EXTRA_DELIMITERS
    )
    masks = list(_FULL_LEXICAL_MASKS if extended_masks else _BASE_MASKS)
    if slug_masks:
        masks.extend(_SLUG_MASKS)
    if profile_masks:
        masks.extend(profile_masks)
    config.masking_instructions = masks
    if drain_depth is not None:
        config.drain_max_depth = drain_depth
    if drain_max_children is not None:
        config.drain_max_children = drain_max_children
    config.mask_prefix = "<:"
    config.mask_suffix = ":>"
    return TemplateMiner(config=config)
