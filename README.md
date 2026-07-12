# LogGuard CLI (`lg`) v1.0.0

Standalone production package for the LogGuard v3 log compression CLI.

## Install

```bash
uv sync
uv run lg run python -c "print('hello')"
```

Expected: `[LogGuard:abcd]` then command output.

## Commands

| Command | Description |
| --- | --- |
| `lg run [--dry-run] [--shell] [--] <cmd...>` | Run command, compress stdout |
| `lg read <file>` | Compress a log file |
| `lg raw <id>` | Full uncompressed output |
| `lg get <id> <hashes...>` | Extract `[#N]` values |
| `lg stats` | Compression dashboard |
| `lg history [-n N]` | Recent runs (default last 10) |
| `lg debug <id> [file]` | Per-stage debug files |

### `lg run` execution modes

**Default (exec mode)** — argv list, `shell=False`. Preserves quoting, spaces, commas:

```bash
uv run lg run python -c "import fastapi, bleach; print('ok')"
uv run lg run -- pytest tests/ -k "not slow"
```

Use `--` before commands with their own flags.

**Shell mode (opt-in)** — raw string with pipes, `&&`, redirects:

```bash
uv run lg run --shell "cat file.log | grep ERROR | head"
```

Use `--dry-run` to skip Gemini (deterministic stages only).

## Storage

Default artifact root: `~/.logguard`

```
~/.logguard/runs/<id>/
├── raw, lg, values.json, meta.json
└── intermediate/   # per-stage debug files (lg debug)
```

Override the root directory:

```bash
export LOGGUARD_HOME=/path/to/artifacts
```

Or set `LOGGUARD_HOME` in `.env` (loaded automatically).

## Environment

| Variable         | Default       | Purpose                                 |
| ---------------- | ------------- | --------------------------------------- |
| `LOGGUARD_HOME`  | `~/.logguard` | Root folder for all saved run artifacts |
| `GOOGLE_API_KEY` | —             | Live Gemini distillation on long logs   |
| `LOGGUARD_VERBOSE` | off         | Set `1` to show pipeline logs on stderr |
| `PYTHONIOENCODING` | `utf-8` (set by lg) | Override child-process stdout encoding |

LogGuard forces UTF-8 on stdout/stderr at startup (`×` RLE markers, unicode logs). Child commands inherit `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`.

## Testing

```bash
uv sync --group dev
uv run pytest tests/lg/ -q
```

Quality smoke tests validate output against bundled references in `tests/fixtures/expected/`.

Golden refresh: `uv run pytest tests/lg/ --golden-update`

## Agent usage

See `.cursorrules` — prefix commands with `lg run`.
