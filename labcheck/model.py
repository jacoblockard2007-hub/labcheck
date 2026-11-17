"""Shared data types for labcheck checks and output formats."""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime


class Status(str, enum.Enum):
    """Result of a single check."""

    OK = "ok"
    WARN = "warn"
    CRIT = "crit"
    ERROR = "error"
    SKIP = "skip"


#: Ordering used to fold several findings into one check status.
SEVERITY = {
    Status.OK: 0,
    Status.SKIP: 0,
    Status.WARN: 1,
    Status.CRIT: 2,
    Status.ERROR: 3,
}

#: Process exit code for each status (nagios-compatible).
EXIT_CODE = {
    Status.OK: 0,
    Status.SKIP: 0,
    Status.WARN: 1,
    Status.CRIT: 2,
    Status.ERROR: 3,
}

#: Short labels for the human-readable report.
STATUS_LABEL = {
    Status.OK: "OK",
    Status.WARN: "WARN",
    Status.CRIT: "CRIT",
    Status.ERROR: "ERR",
    Status.SKIP: "SKIP",
}

#: Numeric values used in Prometheus output (skip is deliberately distinct).
PROMETHEUS_VALUE = {
    Status.OK: 0,
    Status.WARN: 1,
    Status.CRIT: 2,
    Status.ERROR: 3,
    Status.SKIP: 4,
}


def worse(a: Status, b: Status) -> Status:
    """Return the more severe of two statuses.

    ``SKIP`` ranks alongside ``OK``; when both rank equally the status that
    actually ran wins, so folding a skipped item into a healthy check does not
    turn the check into a skip.
    """
    if SEVERITY[a] != SEVERITY[b]:
        return a if SEVERITY[a] > SEVERITY[b] else b
    return b if a is Status.SKIP else a


@dataclass(frozen=True)
class Metric:
    """A single gauge exported by a check."""

    name: str
    value: float
    labels: Mapping[str, str] = field(default_factory=dict)
    help: str = ""


@dataclass
class CheckResult:
    """Everything one check learned."""

    name: str
    title: str
    status: Status
    summary: str
    details: list[str] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)


@dataclass
class Report:
    """A complete run of every selected check."""

    version: str
    hostname: str
    generated_at: datetime
    results: list[CheckResult]
    duration_ms: float
    config_path: str | None = None

    @property
    def status(self) -> Status:
        """Overall status, ignoring checks that were skipped."""
        checked = [
            result for result in self.results if result.status is not Status.SKIP
        ]
        if not checked:
            return Status.SKIP
        return max((result.status for result in checked), key=SEVERITY.__getitem__)

    @property
    def exit_code(self) -> int:
        return EXIT_CODE[self.status]

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for result in self.results:
            counts[result.status.value] += 1
        return counts


def summarize_counts(results: Iterable[CheckResult]) -> str:
    """Return a compact one-line tally, e.g. ``1 critical, 2 warnings, 6 ok``."""
    counts = {status.value: 0 for status in Status}
    for result in results:
        counts[result.status.value] += 1

    parts: list[str] = []
    if counts["error"]:
        parts.append(_plural(counts["error"], "error"))
    if counts["crit"]:
        parts.append(f"{counts['crit']} critical")
    if counts["warn"]:
        parts.append(_plural(counts["warn"], "warning"))
    if counts["ok"]:
        parts.append(f"{counts['ok']} ok")
    if counts["skip"]:
        parts.append(f"{counts['skip']} skipped")
    return ", ".join(parts) if parts else "no checks ran"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")
