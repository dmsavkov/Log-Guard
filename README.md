# LogGuard CLI (`lg`) v1.0.0

Standalone production package for the LogGuard v3 log compression CLI.

## Install

```bash
uv sync
uv run lg run echo hello
```

Expected: `[LogGuard:abcd]` then command output.

## Commands

| Command                   | Description                   |
| ------------------------- | ----------------------------- |
| `lg run <cmd...>`         | Run command, compress stdout  |
| `lg read <file>`          | Compress a log file           |
| `lg raw <id>`             | Full uncompressed output      |
| `lg get <id> <hashes...>` | Extract `[#N]` values         |
| `lg stats`                | Compression dashboard         |
| `lg history [-n N]`       | Recent runs (default last 10) |
| `lg debug <id> [file]`    | Per-stage debug files         |

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

## Testing

```bash
uv sync --group dev
uv run pytest tests/lg/ -q
```

Quality smoke tests validate output against bundled references in `tests/fixtures/expected/`.

Golden refresh: `uv run pytest tests/lg/ --golden-update`

## Agent usage

See `.cursorrules` — prefix commands with `lg run`.
