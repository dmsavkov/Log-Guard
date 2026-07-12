"""lg CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from log_guard.lg.debug_cmd import print_debug
from log_guard.lg.history import format_history
from log_guard.lg.passthrough import is_passthrough
from log_guard.lg.pipeline import compress_for_lg
from log_guard.lg.reader import read_file
from log_guard.lg.runner import (
    format_argv,
    merge_output,
    run_exec,
    run_shell,
    split_command_string,
)
from log_guard.lg.stats import compute_stats, format_dashboard
from log_guard.lg.storage import load_raw, load_values, new_run_id, save_run
from log_guard.io_config import configure_stdio_utf8, safe_write
from log_guard.logging_config import configure_cli_logging

HEADER_PREFIX = "LogGuard"


def _print_header(run_id: str, body: str) -> None:
    safe_write(sys.stdout, f"[{HEADER_PREFIX}:{run_id}]\n{body}")
    if body and not body.endswith("\n"):
        safe_write(sys.stdout, "\n")


def _execute_and_compress(
    raw: str,
    *,
    cmd: str | None,
    exit_code: int,
    dry_run: bool,
    passthrough: bool,
) -> int:
    run_id = new_run_id()
    if passthrough:
        compressed = raw
        route = "passthrough"
        values: dict[str, Any] = {}
        distill_called = False
    else:
        result = compress_for_lg(raw, run_id, dry_run=dry_run, preliminary=False)
        compressed = result.compressed
        route = result.route
        values = result.values
        distill_called = result.distill_called

    save_run(
        run_id,
        raw=raw,
        compressed=compressed,
        values=values,
        meta={
            "cmd": cmd,
            "exit_code": exit_code,
            "route": route,
            "distill_called": distill_called,
            "passthrough": passthrough,
            "dry_run": dry_run,
        },
    )
    _print_header(run_id, compressed)
    return exit_code


def cmd_run(args: argparse.Namespace) -> int:
    argv = list(args.cmd)
    # argparse.REMAINDER keeps a literal "--" separator; drop it.
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: lg run requires a command]\n")
        return 2

    if args.shell:
        # Opt-in raw shell string: pipes, &&, redirects. Quote the whole command.
        command = argv[0] if len(argv) == 1 else " ".join(argv)
        proc = run_shell(command)
    else:
        # Default exec mode: argv list straight to the OS — no quoting loss.
        # UX nicety: `lg run "python x.py"` (one quoted arg) is split for the user.
        if len(argv) == 1 and " " in argv[0]:
            argv = split_command_string(argv[0])
        command = format_argv(argv)
        proc = run_exec(argv)

    if proc.timed_out:
        sys.stderr.write(
            f"[{HEADER_PREFIX} Error: Command timed out. Did it require interactive input?]\n"
        )
        return 124

    raw = merge_output(proc.stdout, proc.stderr)
    return _execute_and_compress(
        raw,
        cmd=command,
        exit_code=proc.exit_code,
        dry_run=args.dry_run,
        passthrough=is_passthrough(command),
    )


def cmd_read(args: argparse.Namespace) -> int:
    try:
        raw = read_file(args.filepath)
    except FileNotFoundError:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: file not found: {args.filepath}]\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: {exc}]\n")
        return 1
    return _execute_and_compress(
        raw, cmd=f"read {args.filepath}", exit_code=0, dry_run=args.dry_run, passthrough=False
    )


def cmd_raw(args: argparse.Namespace) -> int:
    try:
        safe_write(sys.stdout, load_raw(args.id))
    except FileNotFoundError:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: unknown run id {args.id!r}]\n")
        return 1
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    try:
        store = load_values(args.id)
    except FileNotFoundError:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: unknown run id {args.id!r}]\n")
        return 1
    for hash_id in args.hashes:
        key = str(hash_id)
        entry = store.get(key)
        if entry is None:
            safe_write(sys.stdout, f"[#{hash_id}] (not found)\n")
            continue
        value = entry.get("value", entry.get("summary", ""))
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        safe_write(sys.stdout, f"[#{hash_id}] {value}\n")
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    safe_write(sys.stdout, format_dashboard(compute_stats()))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    safe_write(sys.stdout, format_history(limit=args.limit))
    return 0


def cmd_debug(args: argparse.Namespace) -> int:
    return print_debug(args.id, args.file)


def main(argv: list[str] | None = None) -> None:
    configure_stdio_utf8()
    configure_cli_logging()
    parser = argparse.ArgumentParser(
        prog="lg",
        description="LogGuard — compress terminal output for coding agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Execute command and compress stdout")
    run_p.add_argument("--dry-run", action="store_true", help="Skip Gemini distill")
    run_p.add_argument(
        "--shell",
        action="store_true",
        help="Interpret command as raw shell string (pipes, &&, redirects)",
    )
    run_p.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to execute (use -- before commands with their own flags)",
    )
    run_p.set_defaults(handler=cmd_run)

    read_p = sub.add_parser("read", help="Read file and compress contents")
    read_p.add_argument("filepath", help="Path to log file")
    read_p.add_argument("--dry-run", action="store_true", help="Skip Gemini distill")
    read_p.set_defaults(handler=cmd_read)

    raw_p = sub.add_parser("raw", help="Dump uncompressed output for a run id")
    raw_p.add_argument("id", help="4-char run id")
    raw_p.set_defaults(handler=cmd_raw)

    get_p = sub.add_parser("get", help="Extract [#N] values from a prior run")
    get_p.add_argument("id", help="4-char run id")
    get_p.add_argument("hashes", nargs="+", type=int, help="Hash indices")
    get_p.set_defaults(handler=cmd_get)

    stats_p = sub.add_parser("stats", help="Session compression dashboard")
    stats_p.set_defaults(handler=cmd_stats)

    hist_p = sub.add_parser("history", help="List recent runs with compression metrics")
    hist_p.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Show last N runs (default: 10)",
    )
    hist_p.set_defaults(handler=cmd_history)

    dbg_p = sub.add_parser("debug", help="List or print per-stage debug files")
    dbg_p.add_argument("id", help="4-char run id")
    dbg_p.add_argument("file", nargs="?", help="Intermediate filename to print")
    dbg_p.set_defaults(handler=cmd_debug)

    args = parser.parse_args(argv)
    if args.command == "run" and not args.cmd:
        parser.error("lg run requires a command")

    exit_code = args.handler(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
