# RTK (Rust Token Killer) — optional binary for LogGuard

RTK is a **separate native application** (Rust), not a Python package. LogGuard does **not** bundle the binary in the PyPI/wheel install — you install RTK yourself and place it where LogGuard can find it.

## Why RTK?

For some commands (`git status`, `ls`, `grep`, …) LogGuard routes to **RTK tracks** (`rtk_lossless`, `rtk_fast`). When RTK is available, LogGuard runs:

```text
rtk <your-command-args>
```

with `RTK_TEE_DIR` pointing at the run folder so the full raw log is saved to `~/.logguard/<id>/raw.txt`. RTK applies fast structural filtering before the agent sees stdout.

If RTK is **missing**, those commands **fail open**: LogGuard runs the command natively and may use the Python `full_pipe` compressor instead (slower, but still works).

## Install RTK

1. Download the RTK binary for your OS from **[https://www.rtk-ai.app/](https://www.rtk-ai.app/)** (or your distro’s install instructions).
2. Verify it runs:

   ```bash
   rtk --version    # or: rtk --help
   ```

3. Make it discoverable using **one** of the options below.

## Where to put the binary

LogGuard searches in this order (`find_rtk_binary()` in `log_guard/lg/rtk_adapter.py`):

| Location | Use case |
| --- | --- |
| `vendor/rtk/rtk` or `vendor/rtk/rtk.exe` | **Git clone / source checkout** (this folder) |
| `vendor/rtk/bin/rtk` | Same, alternate layout |
| `vendor/rtk/nt/rtk.exe` or `vendor/rtk/posix/rtk` | Per-OS subfolders |
| `log_guard/vendor/rtk/` | Packaged copy inside the installed Python package (if present) |
| Any ancestor `vendor/rtk/` walking up from the install path | Monorepo / editable layouts |
| `rtk` on **`PATH`** | **Recommended for wheel / `pip install`** |

### Option A — system PATH (recommended for end users)

```bash
# Windows (PowerShell): add folder containing rtk.exe to user PATH
# Linux/macOS:
sudo install -m 755 rtk /usr/local/bin/rtk
```

### Option B — vendored in this repo (recommended for dev / Docker)

Copy the platform binary into **this directory**:

```text
vendor/rtk/
├── README.md          ← you are here
├── rtk.exe            ← Windows
└── bin/rtk            ← Linux/macOS (or use rtk/ directly)
```

Example after clone:

```bash
# from Log-Guard repo root
mkdir -p vendor/rtk
cp ~/Downloads/rtk vendor/rtk/rtk        # Linux/macOS
chmod +x vendor/rtk/rtk
```

Windows:

```powershell
Copy-Item .\rtk.exe .\vendor\rtk\rtk.exe
```

### Option C — containers / CI

RTK must be installed **in the image** (apt/curl/copy) and on `PATH`, or copied to `vendor/rtk/` before running `lg`. Installing only `log-guard` via pip **does not** install RTK.

```dockerfile
# illustrative — adjust to your RTK distribution
COPY rtk /usr/local/bin/rtk
RUN chmod +x /usr/local/bin/rtk
ENV PATH="/usr/local/bin:${PATH}"
```

## Which commands use RTK?

Configured in `src/log_guard/lg/tracks.toml`:

- **`rtk_lossless`** — e.g. `git status`, `cargo test`, `pip install`, `docker ps`, …
- **`rtk_fast`** — `ls`, `find`, `grep`

Other tracks (`passthrough`, `pytest_native`, `full_pipe`, `daemon_warn`) never call RTK.

## Environment variables (RTK)

| Variable | Purpose |
| --- | --- |
| `RTK_TEE_DIR` | Set automatically by LogGuard to `~/.logguard/<id>/` for raw capture |
| `RTK_TELEMETRY_DISABLED=1` | Set by LogGuard during `rtk` spawn |

## Verify LogGuard sees RTK

```bash
# should print a path, not empty
python -c "from log_guard.lg.rtk_adapter import find_rtk_binary; print(find_rtk_binary())"

# dry-run a lossless command (no API key needed for RTK path)
lg run --dry-run -- git status
```

Check run metadata: `meta.json` should include `"rtk_used": true` when RTK handled the command.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| RTK track but slow / full Python pipeline | Binary not found → fail-open to native + `full_pipe` |
| `rtk_used: false` in meta | Install binary or fix `PATH` / `vendor/rtk/` |
| Empty output, exit 127 | `rtk` missing or not executable |
| Container has no RTK | Install RTK in image; pip install alone is insufficient |

## Security note

`rtk` executes your command arguments. Only install RTK from trusted sources. LogGuard uses `shell=False` argv execution for the RTK wrapper (same as native `lg run` exec mode).
