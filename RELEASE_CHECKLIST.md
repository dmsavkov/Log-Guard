# Release v1.0.0 — publish checklist (2026-07-20)

## Done gates

- [x] MIT `LICENSE` in release + repo root
- [x] Softened deps (dropped unused numpy/pydantic direct pins; upper caps on majors)
- [x] `tracks.toml` force-included in wheel; verified present
- [x] `v23_config` no longer imports missing `genai` (aliases `build_v3_config`)
- [x] Char-block defaults + warning extract in release pipeline config
- [x] README storage layout: `~/.logguard/<id>/raw.txt`
- [x] Release tests: `84 passed`
- [x] `uv build` → sdist + wheel
- [x] Clean-room: `temp/test-download/` wheel install → `lg run` / daemon refuse / tracks.toml importable

## Rebuild / retest

```bash
cd releases/log-guard-v1.0.0
uv sync --group dev
uv run pytest tests/lg -q
uv build
```

Clean-room:

```bash
# from repo root
mkdir -p temp/test-download/dist
cp releases/log-guard-v1.0.0/dist/log_guard-1.0.0-py3-none-any.whl temp/test-download/dist/
cd temp/test-download
uv venv .venv
uv pip install --python .venv/Scripts/python.exe dist/log_guard-1.0.0-py3-none-any.whl
.venv/Scripts/lg.exe run --dry-run -- python -c "print('ok')"
```

## Known soft limits

- RTK binary is optional (fallback to native / full_pipe)
- Live Gemini distill requires `GOOGLE_API_KEY` (dry-run does not)
- Quality smoke fixtures are regenerated from current dry-run pipeline
