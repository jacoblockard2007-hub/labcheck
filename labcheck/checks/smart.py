"""SMART health of configured disks."""

from __future__ import annotations

import json
from typing import Any

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import truncate

NAME = "smart"
TITLE = "SMART"
DESCRIPTION = "Disk SMART health (disabled by default)"


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.smart
    devices = _unique(cfg.devices)
    if not devices:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="no devices configured",
            details=["add devices to [smart].devices to enable disk health checks"],
        )
    if ctx.runner.which("smartctl") is None:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="smartctl not installed",
            details=["install smartmontools to check disk health"],
        )

    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = []
    failing: list[str] = []
    unknown: list[str] = []

    for device in devices:
        result = ctx.runner.run(["smartctl", "-H", "-j", device], timeout=20)
        report = _load(result.stdout)
        passed: Any = None
        if isinstance(report, dict):
            passed = (report.get("smart_status") or {}).get("passed")
        model = ""
        if isinstance(report, dict):
            model = str(report.get("model_name") or "")

        if passed is True:
            metrics.append(
                Metric("smart_healthy", 1, {"device": device}, "SMART overall health")
            )
            details.append(f"{device}: passed" + (f" ({model})" if model else ""))
            continue

        if passed is False:
            status = worse(status, Status.CRIT)
            failing.append(device)
            metrics.append(
                Metric("smart_healthy", 0, {"device": device}, "SMART overall health")
            )
            details.append(f"{device}: FAILED" + (f" ({model})" if model else ""))
            continue

        # No usable health verdict: distinguish "device absent" from
        # "smartctl installed but this disk cannot report health".
        message = truncate(_smart_message(report) or result.message, 200)
        if result.returncode & 2 or "unable to detect device type" in message.lower():
            status = worse(status, Status.ERROR)
            details.append(f"{device}: cannot open device ({message})")
        else:
            status = worse(status, Status.WARN)
            details.append(f"{device}: health not reported by device ({message})")
        unknown.append(device)

    if failing:
        summary = "FAILING: " + ", ".join(failing)
    elif unknown:
        summary = "health unknown: " + ", ".join(unknown)
    else:
        summary = f"{len(devices)} device" + ("" if len(devices) == 1 else "s")
        summary += " passed"
        if len(devices) > 1:
            summary += " (" + ", ".join(devices) + ")"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _load(output: str) -> Any:
    try:
        return json.loads(output)
    except ValueError:
        return None


def _smart_message(report: Any) -> str:
    """Return the first human-readable smartctl JSON message, if any."""
    if not isinstance(report, dict):
        return ""
    messages = (report.get("smartctl") or {}).get("messages") or []
    for message in messages:
        if isinstance(message, dict):
            text = message.get("string")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
