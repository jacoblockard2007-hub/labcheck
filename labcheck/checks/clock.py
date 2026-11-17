"""NTP clock synchronisation via systemd-timedated."""

from __future__ import annotations

from ..context import Context
from ..model import CheckResult, Metric, Status
from ..util import truncate

NAME = "clock"
TITLE = "Clock"
DESCRIPTION = "NTP clock synchronisation"


def run(ctx: Context) -> CheckResult:
    if ctx.runner.which("timedatectl") is None:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="timedatectl not available",
            details=["install systemd to check NTP synchronisation"],
        )

    result = ctx.runner.run(
        ["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=10
    )
    if result.returncode != 0:
        if _unavailable(result.stderr):
            return CheckResult(
                name=NAME,
                title=TITLE,
                status=Status.SKIP,
                summary="systemd not reachable",
                details=[truncate(result.message, 200)],
            )
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.ERROR,
            summary="timedatectl failed",
            details=[truncate(result.message, 200)],
        )

    value = result.stdout.strip().lower()
    if value == "yes":
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.OK,
            summary="NTP synchronized",
            details=["systemd reports NTPSynchronized=yes"],
            metrics=[Metric("ntp_synchronized", 1, {}, "NTP clock is synchronized")],
        )
    if value == "no":
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.WARN,
            summary="clock not synchronized",
            details=[
                "systemd reports NTPSynchronized=no; check chrony or systemd-timesyncd"
            ],
            metrics=[Metric("ntp_synchronized", 0, {}, "NTP clock is synchronized")],
        )

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=Status.ERROR,
        summary="unexpected timedatectl output",
        details=[f"expected yes/no, got {value!r}"],
    )


def _unavailable(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        marker in lowered
        for marker in (
            "failed to connect to bus",
            "not been booted with systemd",
            "connection refused",
            "no such file or directory",
        )
    )
