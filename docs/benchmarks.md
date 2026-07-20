# Benchmarks

**Source of truth** for numbers cited in the product README. When you re-measure, update **this file first**, then sync the README table / proof bullets. Do not invent “debugging quality %” — figures here are **character-size** reductions unless stated otherwise.

## Showcase examples (size reduction)

From curated real `lg` runs (agent / eval logs):

| Workload | Raw → compressed | Reduction |
| --- | ---: | ---: |
| pytest failure (`pytest_native`) | 5,202 → 123 | 98% |
| pytest success (`pytest_native`) | 4,432 → 20 | ~100% |
| Large pytest failure run | 35,878 → 6,375 | 82% |
| CI/CD + Docker + pytest (synth file) | 10,958 → 685 | 94% |
| Kaggle notebook log (`lg read`) | 83,211 → 1,702 | 98% |
| `apt-get install` (Terminal-Bench) | 31,475 → 2,690 | 91% |

These are **character/token-size** reductions, not a measured “debugging quality” score. Agents recovered full output via `lg raw` rarely (see below).

## Dogfooding / active-cli slice

On a Terminal-Bench active-cli corpus (July 2026):

- Overall retention ≈ **31%** of raw characters (≈ **69%** reduction across the slice).
- Per-run median reduction is much lower (~6–7%) — many steps are already short; big wins concentrate on noisy tracks.
- Telemetry share of `lg raw` follow-ups ≈ **0.6–1.9%** in those windows (agents rarely needed the full log).

## Terminal-Bench (easy subset, post-fix boards)

Illustrative board (not a guarantee on other days/quotas):

| Setup | Tasks with ≥1 pass (easy subset) | Notes |
| --- | ---: | --- |
| Flash-Lite active-cli | ~4/5 | Strongest of the compared boards |
| Gemma passive | ~4/5 | Compression on; agent does not invoke `lg` |
| Gemma active-cli | lower | Wrapper + model errors; not “compression failed” |
| Gemma baseline | ~3/5 | No LogGuard compression |

**Limitations of this evidence**

- Free-tier API throttling / TPM caps disrupted some runs.
- Sandbox network / `apt-get` failures blocked install-heavy tasks independently of LogGuard.
- Container images often lacked the RTK binary (`rtk_used=0%`); Python `full_pipe` still ran.
- Pass rates vary with model, quota, and image health — treat as directional.

## Related tools (not a bake-off)

- **Headroom** — general text compression; weak / uneven on agent execution logs in our experiments.
- **RTK** — fast structural filtering for some commands; can be aggressive (lossy). LogGuard may route through RTK when the binary is present, otherwise uses its Python pipeline.
