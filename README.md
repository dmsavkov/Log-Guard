# LogGuard CLI (`lg`) v1.0.0

Standalone production package for the LogGuard v3 log compression CLI.

**License:** MIT (see `LICENSE`)

## Install

From this directory (editable / source):

```bash
uv sync
uv run lg run -- python -c "print('hello')"
```

From a built wheel:

```bash
uv pip install path/to/log_guard-1.0.0-py3-none-any.whl
lg run -- python -c "print('hello')"
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

### Command classification & routing (`run` vs `read`)

* **`lg run <command...>`** — Command classifier selects a track (`passthrough`, `pytest_native`, `rtk_*`, `full_pipe`, …). If an RTK track matches and the `rtk` binary is available, LogGuard executes through RTK once.
* **`lg read <file>`** — Always uses the `full_pipe` Python pipeline (no classifier / RTK).

### `lg run` execution modes

**Default (exec mode)** — argv list, `shell=False`:

```bash
uv run lg run python -c "print('ok')"
uv run lg run -- pytest tests/ -k "not slow"
```

**Shell mode (opt-in)** — raw string with pipes, `&&`, redirects:

```bash
uv run lg run --shell "cat file.log | grep ERROR | head"
```

Use `--dry-run` to skip Gemini (deterministic stages only). Same effect: `USE_LLM_SUMMARIZATION=false` in `.env` or the environment.

## RTK (optional native binary)

Some `lg run` commands route through **[RTK](https://www.rtk-ai.app/)** — a **separate Rust application**, not installed by `pip install log-guard`.

| Without RTK | With RTK on `PATH` or in `vendor/rtk/` |
| --- | --- |
| `git status`, `ls`, `grep`, … still work | Same commands use `rtk` for faster structural filtering |
| May use Python `full_pipe` instead | `meta.json` records `"rtk_used": true` |

**First-time setup:**

1. Download `rtk` / `rtk.exe` from [rtk-ai.app](https://www.rtk-ai.app/).
2. Either add it to your **`PATH`**, or copy it to `vendor/rtk/` in this repo (see [`vendor/rtk/README.md`](vendor/rtk/README.md)).
3. Verify: `python -c "from log_guard.lg.rtk_adapter import find_rtk_binary; print(find_rtk_binary())"`

Full install paths, Docker notes, and troubleshooting: **[`vendor/rtk/README.md`](vendor/rtk/README.md)**.

## Storage

Default artifact root: `~/.logguard`

```
~/.logguard/<id>/
├── raw.txt, lg, values.json, meta.json
└── intermediate/   # per-stage debug files (lg debug)
```

Override:

```bash
export LOGGUARD_HOME=/path/to/artifacts
```

Or set `LOGGUARD_HOME` in `.env` (loaded automatically).

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `LOGGUARD_HOME` | `~/.logguard` | Root folder for saved run artifacts |
| `GOOGLE_API_KEY` | — | Live Gemini distillation on long logs |
| `USE_LLM_SUMMARIZATION` | `true` | Set `false` to skip Gemini distill (like `--dry-run`) |
| `LOGGUARD_VERBOSE` | off | Set `1` to show pipeline logs on stderr |

## Testing

```bash
uv sync --group dev
uv run pytest tests/lg/ -q
```

Golden refresh: `uv run pytest tests/lg/ --golden-update`

## Agent usage

See `.cursorrules` — prefix commands with `lg run`.

## Maintainer probes

Tag inspection runs so they do not appear in default `lg stats` / `lg history`:

```bash
uv run lg run --experimental --dry-run -- echo hello
# or: LOGGUARD_EXPERIMENTAL=1
```

Do **not** document `--experimental` in agent-facing `.cursorrules`.
