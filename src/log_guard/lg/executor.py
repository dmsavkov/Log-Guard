"""lg run orchestration — track routing, compression, artifact save."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from log_guard.lg.classify import Track, resolve_track, DAEMON_WARN_MSG, is_python_inline, looks_like_machine_json
from log_guard.lg.pipeline import compress_for_lg
from log_guard.lg.pytest_summary import format_pytest_success
from log_guard.lg.rtk_adapter import find_rtk_binary, run_via_rtk
from log_guard.lg.runner import RunResult, merge_output, run_exec, run_shell
from log_guard.lg.simple_green import simple_green
from log_guard.lg.storage import format_raw_log_hint, new_run_id, run_dir, save_run
from log_guard.lg.telemetry import InvocationTimer, log_invocation
from log_guard.lg.track_config import (
    daemon_commands,
    lossless_commands,
    passthrough_prefixes,
    rtk_fast_commands,
)


@dataclass
class ExecuteResult:
    run_id: str
    body: str
    exit_code: int
    track: str
    show_header: bool = True
    timed_out: bool = False


def _should_append_raw_hint(
    *,
    track: str,
    raw: str,
    compressed: str,
    meta: dict[str, Any],
) -> bool:
    if track == Track.PASSTHROUGH.value or track == Track.DAEMON_WARN.value:
        return False
    if meta.get("pytest_success"):
        return False
    if bool(meta.get("distill_called")):
        return True
    return len(raw) > len(compressed) + 150


def _save_and_finish(
    run_id: str,
    *,
    raw: str,
    compressed: str,
    values: dict[str, Any],
    meta: dict[str, Any],
    exit_code: int,
    track: str,
    show_header: bool,
    timer: InvocationTimer,
    subcommand: str = "run",
    experimental: bool = False,
) -> ExecuteResult:
    save_run(
        run_id,
        raw=raw,
        compressed=compressed,
        values=values,
        meta={**meta, "track": track, "experimental": experimental},
    )
    body = compressed.rstrip("\n")
    if _should_append_raw_hint(track=track, raw=raw, compressed=compressed, meta=meta):
        hint = format_raw_log_hint(run_id)
        if hint not in body:
            body = f"{body}\n{hint}" if body else hint
    extra = {k: meta[k] for k in ("distill_called", "rtk_used") if k in meta}
    log_invocation(
        subcommand=subcommand,
        run_id=run_id,
        track=track,
        cmd=meta.get("cmd"),
        exit_code=exit_code,
        raw_chars=len(raw),
        compressed_chars=len(compressed),
        latency_ms=timer.elapsed_ms,
        experimental=experimental,
        extra=extra,
    )
    return ExecuteResult(
        run_id=run_id,
        body=body,
        exit_code=exit_code,
        track=track,
        show_header=show_header,
    )


def _rtk_argv_from_command(command: str, argv: list[str]) -> list[str]:
    if argv:
        return argv
    from log_guard.lg.classify import split_command_string

    return split_command_string(command)


def _rtk_result_usable(result) -> bool:
    """False when RTK ran but failed to spawn the target (fall back to native exec)."""
    if not result.used_rtk:
        return False
    if result.exit_code == 127:
        return False
    blob = f"{result.stdout}\n{result.stderr}".lower()
    markers = (
        "failed to resolve",
        "not found on path",
        "program not found",
        "failed to spawn",
    )
    return not any(m in blob for m in markers)


def _should_passthrough_output(*, command: str, raw: str, track: str) -> bool:
    if track == Track.PASSTHROUGH.value:
        return True
    if is_python_inline(command):
        return True
    return looks_like_machine_json(raw)


def _run_subprocess(
    *,
    command: str,
    argv: list[str],
    shell_mode: bool,
) -> RunResult:
    if shell_mode:
        return run_shell(command)
    return run_exec(argv)


def execute_run(
    *,
    command: str,
    argv: list[str],
    shell_mode: bool,
    dry_run: bool,
    experimental: bool = False,
) -> ExecuteResult:
    """Resolve track first, then spawn exactly once (RTK or native)."""
    timer = InvocationTimer()
    run_id = new_run_id()
    track = resolve_track(
        command,
        shell_mode=shell_mode,
        passthrough_prefixes=passthrough_prefixes(),
        lossless_commands=lossless_commands(),
        rtk_fast_commands=rtk_fast_commands(),
        daemon_commands=daemon_commands(),
    )

    if track == Track.DAEMON_WARN:
        return _save_and_finish(
            run_id,
            raw="",
            compressed=DAEMON_WARN_MSG,
            values={},
            meta={"cmd": command, "exit_code": 2, "distill_called": False},
            exit_code=2,
            track=track.value,
            show_header=True,
            timer=timer,
            experimental=experimental,
        )

    use_rtk = track in (Track.RTK_LOSSLESS, Track.RTK_FAST) and find_rtk_binary() is not None

    if use_rtk:
        rtk_argv = _rtk_argv_from_command(command, argv)
        rtk_result = run_via_rtk(rtk_argv, run_dir=run_dir(run_id))
        if _rtk_result_usable(rtk_result):
            filtered = simple_green(rtk_result.stdout)
            if rtk_result.raw_path and rtk_result.raw_path.is_file():
                tee_raw = rtk_result.raw_path.read_text(encoding="utf-8")
            else:
                tee_raw = filtered
            return _save_and_finish(
                run_id,
                raw=tee_raw,
                compressed=filtered,
                values={},
                meta={
                    "cmd": command,
                    "exit_code": rtk_result.exit_code,
                    "distill_called": False,
                    "dry_run": dry_run,
                    "shell_mode": shell_mode,
                    "rtk_used": True,
                },
                exit_code=rtk_result.exit_code,
                track=track.value,
                show_header=True,
                timer=timer,
                experimental=experimental,
            )

    proc = _run_subprocess(command=command, argv=argv, shell_mode=shell_mode)
    if proc.timed_out:
        return ExecuteResult(
            run_id=run_id,
            body="",
            exit_code=124,
            track=track.value,
            show_header=True,
            timed_out=True,
        )

    raw = merge_output(proc.stdout, proc.stderr)
    base_meta: dict[str, Any] = {
        "cmd": command,
        "exit_code": proc.exit_code,
        "distill_called": False,
        "dry_run": dry_run,
        "shell_mode": shell_mode,
    }

    if _should_passthrough_output(command=command, raw=raw, track=track.value):
        compressed = simple_green(raw)
        return _save_and_finish(
            run_id,
            raw=raw,
            compressed=compressed,
            values={},
            meta={**base_meta, "passthrough": True},
            exit_code=proc.exit_code,
            track=Track.PASSTHROUGH.value,
            show_header=True,
            timer=timer,
            experimental=experimental,
        )

    if track == Track.PYTEST_NATIVE:
        (run_dir(run_id) / "raw.txt").write_text(raw, encoding="utf-8")
        if proc.exit_code == 0:
            msg = format_pytest_success(raw)
            return _save_and_finish(
                run_id,
                raw=raw,
                compressed=msg,
                values={},
                meta={**base_meta, "pytest_success": True},
                exit_code=0,
                track=track.value,
                show_header=False,
                timer=timer,
                experimental=experimental,
            )
        result = compress_for_lg(raw, run_id, dry_run=dry_run, preliminary=False)
        compressed = result.compressed if result.distill_called else simple_green(result.compressed)
        return _save_and_finish(
            run_id,
            raw=raw,
            compressed=compressed,
            values=result.values,
            meta={
                **base_meta,
                "route": result.route,
                "distill_called": result.distill_called,
            },
            exit_code=proc.exit_code,
            track=track.value,
            show_header=True,
            timer=timer,
            experimental=experimental,
        )

    if not raw.strip():
        return _save_and_finish(
            run_id,
            raw=raw,
            compressed=raw,
            values={},
            meta=base_meta,
            exit_code=proc.exit_code,
            track=Track.FULL_PIPE.value,
            show_header=True,
            timer=timer,
            experimental=experimental,
        )

    result = compress_for_lg(raw, run_id, dry_run=dry_run, preliminary=False)
    return _save_and_finish(
        run_id,
        raw=raw,
        compressed=result.compressed,
        values=result.values,
        meta={
            **base_meta,
            "route": result.route,
            "distill_called": result.distill_called,
            "rtk_used": False,
        },
        exit_code=proc.exit_code,
        track=Track.FULL_PIPE.value,
        show_header=True,
        timer=timer,
        experimental=experimental,
    )


def execute_read(
    raw: str,
    *,
    filepath: str,
    dry_run: bool,
    experimental: bool = False,
) -> ExecuteResult:
    timer = InvocationTimer()
    run_id = new_run_id()
    result = compress_for_lg(raw, run_id, dry_run=dry_run, preliminary=False)
    return _save_and_finish(
        run_id,
        raw=raw,
        compressed=result.compressed,
        values=result.values,
        meta={
            "cmd": f"read {filepath}",
            "exit_code": 0,
            "route": result.route,
            "distill_called": result.distill_called,
            "dry_run": dry_run,
        },
        exit_code=0,
        track=Track.FULL_PIPE.value,
        show_header=True,
        timer=timer,
        subcommand="read",
        experimental=experimental,
    )
