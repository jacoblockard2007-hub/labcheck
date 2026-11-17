"""Command-line interface for labcheck."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
import time
import traceback
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .checks import CHECKS, is_enabled, select, split_names
from .config import Config, ConfigError, load_config
from .context import Context
from .formatters import format_json, format_prometheus, format_text
from .model import CheckResult, Report, Status
from .runner import Runner

EXIT_ERROR = 3


class _Parser(argparse.ArgumentParser):
    """Argument parser that reserves exit code 2 for critical findings."""

    def error(self, message: str) -> None:  # pragma: no cover - argparse glue
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="labcheck",
        description="Audit the health of a Linux homelab and report problems.",
        epilog="Exit codes: 0 ok, 1 warning, 2 critical, 3 error. "
        "Skipped checks do not affect the exit code.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="configuration file (default: /etc/labcheck.toml or ~/.config/labcheck/config.toml)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="emit JSON")
    output.add_argument(
        "--prometheus",
        action="store_true",
        help="emit Prometheus text exposition format",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="write the report to PATH instead of stdout ('-' means stdout)",
    )
    parser.add_argument(
        "--only",
        metavar="CHECKS",
        action="append",
        default=[],
        help="run only these checks, comma-separated (may include disabled checks)",
    )
    parser.add_argument(
        "--skip",
        metavar="CHECKS",
        action="append",
        default=[],
        help="skip these checks, comma-separated",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show details for every check"
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    parser.add_argument(
        "--list-checks", action="store_true", help="list available checks and exit"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)

    try:
        config, config_path = load_config(args.config)
    except ConfigError as exc:
        print(f"labcheck: {exc}", file=sys.stderr)
        return EXIT_ERROR

    for warning in config.warnings:
        print(f"labcheck: warning: {warning}", file=sys.stderr)

    if args.list_checks:
        _print_checks(config)
        return 0

    only = split_names(args.only)
    skip = split_names(args.skip)
    try:
        specs = select(config, only=only or None, skip=skip or None)
    except KeyError as exc:
        print(f"labcheck: unknown check(s): {exc.args[0]}", file=sys.stderr)
        print(
            "labcheck: valid checks: " + ", ".join(spec.name for spec in CHECKS),
            file=sys.stderr,
        )
        return EXIT_ERROR

    if not specs:
        print(
            "labcheck: no checks selected; see --list-checks",
            file=sys.stderr,
        )
        return EXIT_ERROR

    now = datetime.now(UTC)
    context = Context(config=config, runner=Runner(), now=now)
    started = time.perf_counter()
    results: list[CheckResult] = []
    for spec in specs:
        try:
            result = spec.func(context)
        except Exception as exc:  # noqa: BLE001 - a broken check must not abort the audit
            details = [f"{type(exc).__name__}: {exc}"]
            if args.verbose:
                details.append(traceback.format_exc())
            result = CheckResult(
                name=spec.name,
                title=spec.title,
                status=Status.ERROR,
                summary=f"check crashed: {type(exc).__name__}",
                details=details,
            )
        results.append(result)
    duration_ms = (time.perf_counter() - started) * 1000.0

    report = Report(
        version=__version__,
        hostname=socket.gethostname(),
        generated_at=now,
        results=results,
        duration_ms=duration_ms,
        config_path=str(config_path) if config_path else None,
    )

    color = _use_color(args)
    if args.json:
        rendered = format_json(report)
    elif args.prometheus:
        rendered = format_prometheus(report)
    else:
        rendered = format_text(report, verbose=args.verbose, color=color)

    if args.output and args.output != "-":
        try:
            _atomic_write(Path(args.output).expanduser(), rendered)
        except OSError as exc:
            print(f"labcheck: cannot write {args.output}: {exc}", file=sys.stderr)
            return EXIT_ERROR
    else:
        try:
            sys.stdout.write(rendered)
            sys.stdout.flush()
        except BrokenPipeError:
            try:
                sys.stdout.close()
            except OSError:
                pass
            return 0

    return report.exit_code


def _use_color(args: argparse.Namespace) -> bool:
    if args.no_color or os.environ.get("NO_COLOR"):
        return False
    if args.output and args.output != "-":
        return False
    try:
        return sys.stdout.isatty()
    except AttributeError:
        return False


def _print_checks(config: Config) -> None:
    lines = [f"labcheck {__version__} checks", ""]
    for spec in CHECKS:
        state = "enabled" if is_enabled(spec, config) else "disabled"
        lines.append(f"  {spec.name:<14} {state:<10} {spec.description}")
    lines.append("")
    lines.append("Run one check explicitly with --only NAME, even if disabled.")
    sys.stdout.write("\n".join(lines) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    directory = path.parent
    fd, temporary = tempfile.mkstemp(
        dir=str(directory), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates 0600 files.  Reports are meant to be readable by a
        # textfile collector running as another user; keep an existing mode if
        # there is one, otherwise use the usual 0644.
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o644
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _configure_stdout() -> None:
    """Do not crash when stdout cannot encode decorative characters."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
