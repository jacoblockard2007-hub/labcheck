"""Rendering a :class:`~labcheck.model.Report` as text, JSON or Prometheus."""

from __future__ import annotations

import json
import math
from datetime import UTC

from .model import (
    PROMETHEUS_VALUE,
    STATUS_LABEL,
    Metric,
    Report,
    Status,
    summarize_counts,
)

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"

STATUS_COLOR = {
    Status.OK: "\x1b[32m",
    Status.WARN: "\x1b[33m",
    Status.CRIT: "\x1b[1;31m",
    Status.ERROR: "\x1b[1;35m",
    Status.SKIP: "\x1b[2m",
}

TITLE_WIDTH = 12
LABEL_WIDTH = 4


def format_text(report: Report, *, verbose: bool = False, color: bool = False) -> str:
    """Human-readable report, optionally with ANSI colours and details."""
    lines: list[str] = []
    header = f"labcheck {report.version}"
    if report.hostname:
        header += f"  \u00b7  {report.hostname}"
    header += f"  \u00b7  {_timestamp(report)}"
    lines.append(_paint(header, BOLD, color))
    lines.append("")

    for result in report.results:
        label = STATUS_LABEL[result.status]
        painted_label = _paint(
            f"{label:<{LABEL_WIDTH}}", STATUS_COLOR[result.status], color
        )
        title = _paint(f"{result.title:<{TITLE_WIDTH}}", BOLD, color)
        lines.append(f"  {painted_label}  {title}  {result.summary}")
        if verbose:
            for detail in result.details:
                for index, part in enumerate(detail.splitlines() or [""]):
                    prefix = "      \u2022 " if index == 0 else "        "
                    lines.append(_paint(prefix + part, DIM, color))

    lines.append("")
    footer = (
        f"Summary: {summarize_counts(report.results)}  "
        f"({report.duration_ms / 1000.0:.2f}s)"
    )
    lines.append(_paint(footer, DIM, color))
    return "\n".join(lines) + "\n"


def format_json(report: Report) -> str:
    """Machine-readable report, stable enough to commit in fixtures."""
    payload = {
        "schema_version": 1,
        "version": report.version,
        "hostname": report.hostname,
        "generated_at": report.generated_at.isoformat(),
        "config_path": report.config_path,
        "status": report.status.value,
        "exit_code": report.exit_code,
        "duration_ms": round(report.duration_ms, 3),
        "counts": report.counts(),
        "checks": [
            {
                "name": result.name,
                "title": result.title,
                "status": result.status.value,
                "summary": result.summary,
                "details": list(result.details),
                "metrics": [
                    {
                        "name": metric.name,
                        "value": metric.value,
                        "labels": dict(metric.labels),
                        "help": metric.help,
                    }
                    for metric in result.metrics
                ],
            }
            for result in report.results
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def format_prometheus(report: Report) -> str:
    """Prometheus text exposition format for node_exporter textfiles."""
    families: dict[str, tuple[str, list[str]]] = {}
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    def add(
        name: str, value: float, labels: dict[str, str] | None, help_text: str
    ) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        if key in seen:
            return
        seen.add(key)
        if name not in families:
            families[name] = (help_text, [])
        families[name][1].append(f"{name}{_labels(labels)} {_number(value)}")

    add(
        "labcheck_info",
        1,
        {"version": report.version, "hostname": report.hostname},
        "labcheck build information",
    )
    add(
        "labcheck_overall_status",
        PROMETHEUS_VALUE[report.status],
        None,
        "Overall status (0 ok, 1 warning, 2 critical, 3 error, 4 skipped)",
    )
    add(
        "labcheck_duration_seconds",
        round(report.duration_ms / 1000.0, 3),
        None,
        "Duration of the most recent check run",
    )
    add(
        "labcheck_last_run_timestamp_seconds",
        report.generated_at.timestamp(),
        None,
        "Unix timestamp of the most recent check run",
    )

    for result in report.results:
        add(
            "labcheck_check_status",
            PROMETHEUS_VALUE[result.status],
            {"check": result.name},
            "Per-check status (0 ok, 1 warning, 2 critical, 3 error, 4 skipped)",
        )
        for metric in result.metrics:
            _add_metric(add, metric)

    output: list[str] = []
    for name, (help_text, samples) in families.items():
        output.append(f"# HELP {name} {_escape_help(help_text)}")
        output.append(f"# TYPE {name} gauge")
        output.extend(samples)
    return "\n".join(output) + "\n"


def _add_metric(add, metric: Metric) -> None:
    add(
        "labcheck_" + metric.name,
        metric.value,
        dict(metric.labels),
        metric.help or metric.name,
    )


def _timestamp(report: Report) -> str:
    moment = report.generated_at
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def _paint(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{code}{text}{RESET}"


def _labels(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    body = ",".join(
        f'{key}="{_escape_label(str(value))}"' for key, value in sorted(labels.items())
    )
    return "{" + body + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _escape_help(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _number(value: float) -> str:
    value = float(value)
    if math.isnan(value):
        return "NaN"
    if value == float("inf"):
        return "+Inf"
    if value == float("-inf"):
        return "-Inf"
    if value.is_integer():
        return str(int(value))
    return f"{value:.10g}"
