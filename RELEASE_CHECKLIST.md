# Release v1.0.0 — publish checklist (2026-07-20)

This directory is the **standalone GitHub repo** [`dmsavkov/Log-Guard`](https://github.com/dmsavkov/Log-Guard) (`main`).

## Done gates

- [x] `git pull` from `origin/main` (already up to date before publish commit)
- [x] MIT `LICENSE`
- [x] Softened deps (no unused numpy/pydantic directs; major upper bounds)
- [x] `tracks.toml` force-included in wheel
- [x] `v23_config` aliases `build_v3_config` (no missing `genai`)
- [x] Char-block defaults + warning extract in pipeline
- [x] README storage: `~/.logguard/<id>/raw.txt`
- [x] Release tests: **84 passed**
- [x] `uv build` → sdist + wheel
- [x] Clean-room wheel install (`temp/test-download-release/`)
- [x] Commit `49879e0` on `main` + **pushed** to `origin/main`
- [x] Clean-room install **from GitHub**:
  `uv pip install git+https://github.com/dmsavkov/Log-Guard.git@main`
  → `lg run` ok, daemon refuse exit 2, `tracks.toml` present, version `1.0.0`

## Rebuild / retest (inside this repo)

```bash
uv sync --group dev
uv run pytest tests/lg -q
uv build
```

## Install for users

```bash
uv pip install "git+https://github.com/dmsavkov/Log-Guard.git@main"
# or from a built wheel:
uv pip install path/to/log_guard-1.0.0-py3-none-any.whl
lg run --dry-run -- python -c "print('ok')"
```

## Known soft limits

- RTK binary is optional (fallback to native / full_pipe)
- Live Gemini distill requires `GOOGLE_API_KEY` (dry-run does not)
- Quality smoke fixtures match current dry-run pipeline
