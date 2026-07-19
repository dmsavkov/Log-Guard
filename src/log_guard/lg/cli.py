"""lg CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from log_guard.lg.debug_cmd import print_debug
from log_guard.lg.executor import execute_read, execute_run
from log_guard.lg.history import format_history
from log_guard.lg.reader import read_file
from log_guard.lg.runner import format_argv, split_command_string
from log_guard.lg.stats import compute_stats, format_dashboard
from log_guard.lg.storage import load_raw, load_values
from log_guard.lg.telemetry import InvocationTimer, log_invocation, resolve_experimental
from log_guard.io_config import configure_stdio_utf8, safe_write
from log_guard.logging_config import configure_cli_logging

HEADER_PREFIX = "LogGuard"


def _exp(args: argparse.Namespace) -> bool:
    return resolve_experimental(bool(getattr(args, "experimental", False)))


def _print_output(run_id: str, body: str, *, show_header: bool) -> None:
    if show_header:
        safe_write(sys.stdout, f"[{HEADER_PREFIX}:{run_id}]\n{body}")
    else:
        safe_write(sys.stdout, body)
    if body and not body.endswith("\n"):
        safe_write(sys.stdout, "\n")


def cmd_run(args: argparse.Namespace) -> int:
    argv = list(args.cmd)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: lg run requires a command]\n")
        return 2

    if args.shell:
        command = argv[0] if len(argv) == 1 else " ".join(argv)
    else:
        if len(argv) == 1 and " " in argv[0]:
            argv = split_command_string(argv[0])
        command = format_argv(argv)

    result = execute_run(
        command=command,
        argv=argv,
        shell_mode=args.shell,
        dry_run=args.dry_run,
        experimental=_exp(args),
    )
    if result.timed_out:
        sys.stderr.write(
            f"[{HEADER_PREFIX} Error: Command timed out. Did it require interactive input?]\n"
        )
        return 124
    _print_output(result.run_id, result.body, show_header=result.show_header)
    return result.exit_code


def cmd_read(args: argparse.Namespace) -> int:
    try:
        raw = read_file(args.filepath)
    except FileNotFoundError:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: file not found: {args.filepath}]\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: {exc}]\n")
        return 1
    result = execute_read(
        raw,
        filepath=args.filepath,
        dry_run=args.dry_run,
        experimental=_exp(args),
    )
    _print_output(result.run_id, result.body, show_header=result.show_header)
    return 0


def cmd_raw(args: argparse.Namespace) -> int:
    timer = InvocationTimer()
    try:
        text = load_raw(args.id)
    except FileNotFoundError:
        sys.stderr.write(f"[{HEADER_PREFIX} Error: unknown run id {args.id!r}]\n")
        return 1
    safe_write(sys.stdout, text)
    log_invocation(
        subcommand="raw",
        run_id=args.id,
        raw_chars=len(text),
        latency_ms=timer.elapsed_ms,
        experimental=_exp(args),
    )
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    timer = InvocationTimer()
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
    log_invocation(
        subcommand="get",
        run_id=args.id,
        latency_ms=timer.elapsed_ms,
        experimental=_exp(args),
        extra={"hashes": args.hashes},
    )
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    timer = InvocationTimer()
    safe_write(sys.stdout, format_dashboard(compute_stats()))
    log_invocation(
        subcommand="stats",
        latency_ms=timer.elapsed_ms,
        experimental=_exp(_args),
    )
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    timer = InvocationTimer()
    safe_write(sys.stdout, format_history(limit=args.limit))
    log_invocation(
        subcommand="history",
        latency_ms=timer.elapsed_ms,
        experimental=_exp(args),
    )
    return 0


def cmd_debug(args: argparse.Namespace) -> int:
    timer = InvocationTimer()
    code = print_debug(args.id, args.file)
    log_invocation(
        subcommand="debug",
        run_id=args.id,
        latency_ms=timer.elapsed_ms,
        experimental=_exp(args),
    )
    return code


def main(argv: list[str] | None = None) -> None:
    configure_stdio_utf8()
    configure_cli_logging()
    parser = argparse.ArgumentParser(
        prog="lg",
        description="LogGuard — compress terminal output for coding agents",
    )
    # Hidden from --help / agent docs. Prefer LOGGUARD_EXPERIMENTAL=1 for probes.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--experimental", action="store_true", help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", parents=[common], help="Execute command and compress stdout")
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

    read_p = sub.add_parser("read", parents=[common], help="Read file and compress contents")
    read_p.add_argument("filepath", help="Path to log file")
    read_p.add_argument("--dry-run", action="store_true", help="Skip Gemini distill")
    read_p.set_defaults(handler=cmd_read)

    raw_p = sub.add_parser("raw", parents=[common], help="Dump uncompressed output for a run id")
    raw_p.add_argument("id", help="4-char run id")
    raw_p.set_defaults(handler=cmd_raw)

    get_p = sub.add_parser("get", parents=[common], help="Extract [#N] values from a prior run")
    get_p.add_argument("id", help="4-char run id")
    get_p.add_argument("hashes", nargs="+", type=int, help="Hash indices")
    get_p.set_defaults(handler=cmd_get)

    stats_p = sub.add_parser("stats", parents=[common], help="Session compression dashboard")
    stats_p.set_defaults(handler=cmd_stats)

    hist_p = sub.add_parser("history", parents=[common], help="List recent runs with compression metrics")
    hist_p.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Show last N runs (default: 10)",
    )
    hist_p.set_defaults(handler=cmd_history)

    dbg_p = sub.add_parser("debug", parents=[common], help="List or print per-stage debug files")
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
