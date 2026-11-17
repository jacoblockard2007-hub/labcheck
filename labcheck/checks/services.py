"""systemd unit health and required services."""

from __future__ import annotations

import fnmatch

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import truncate

NAME = "services"
TITLE = "Services"
DESCRIPTION = "Failed systemd units and required services"


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.systemd
    if ctx.runner.which("systemctl") is None:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="systemd not available",
            details=["systemctl was not found on PATH"],
        )

    failed = ctx.runner.run(
        ["systemctl", "--failed", "--no-legend", "--plain", "--no-pager"], timeout=10
    )
    if failed.returncode != 0 and not failed.stdout.strip():
        if _systemd_unavailable(failed.stderr):
            return CheckResult(
                name=NAME,
                title=TITLE,
                status=Status.SKIP,
                summary="systemd not reachable",
                details=[truncate(failed.message, 200)],
            )
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.ERROR,
            summary="systemctl --failed failed",
            details=[truncate(failed.message, 200)],
        )

    units = _parse_failed(failed.stdout)
    ignored = [unit for unit in units if _matches_any(unit[0], cfg.allow_failed)]
    units = [unit for unit in units if not _matches_any(unit[0], cfg.allow_failed)]

    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = [
        Metric("failed_units", len(units), {}, "Failed systemd units")
    ]

    for unit, description in units:
        status = worse(status, Status.CRIT)
        line = f"{unit}: failed"
        if description:
            line += f" ({description})"
        details.append(line)
        metrics.append(Metric("unit_failed", 1, {"unit": unit}, "Unit failure state"))
    for unit, _ in ignored:
        details.append(f"{unit}: failed, allowed by configuration")

    required = _unique(cfg.required_services)
    missing: list[str] = []
    for service in required:
        result = ctx.runner.run(["systemctl", "is-active", service], timeout=10)
        state = (
            result.stdout.strip().splitlines()[0]
            if result.stdout.strip()
            else "unknown"
        )
        active = result.returncode == 0 and state == "active"
        metrics.append(
            Metric(
                "service_active",
                1 if active else 0,
                {"service": service},
                "Required service is active",
            )
        )
        details.append(f"{service}: {state}")
        if not active:
            status = worse(status, Status.CRIT)
            missing.append(f"{service} ({state})")

    if units:
        summary = f"{len(units)} failed unit" + ("" if len(units) == 1 else "s")
        summary += ": " + ", ".join(unit for unit, _ in units[:3])
        if len(units) > 3:
            summary += ", \u2026"
    elif missing:
        summary = "required service not running: " + ", ".join(missing[:3])
    elif required:
        summary = f"{len(required)} required service" + (
            "" if len(required) == 1 else "s"
        )
        summary += " active, no failed units"
    else:
        summary = "no failed units"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _parse_failed(output: str) -> list[tuple[str, str]]:
    units: list[tuple[str, str]] = []
    for line in output.splitlines():
        fields = line.split(None, 4)
        if not fields or fields[0] == "UNIT":
            continue
        unit = fields[0]
        description = fields[4] if len(fields) > 4 else ""
        units.append((unit, description.strip()))
    return units


def _systemd_unavailable(stderr: str) -> bool:
    lowered = stderr.lower()
    markers = (
        "not been booted with systemd",
        "failed to connect to bus",
        "system has not been booted",
        "no such file or directory",
        "connection refused",
    )
    return any(marker in lowered for marker in markers)


def _matches_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
