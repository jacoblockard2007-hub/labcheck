"""System load, memory, swap, uptime and temperature."""

from __future__ import annotations

import os

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import human_bytes, human_duration, percent, read_text

NAME = "system"
TITLE = "System"
DESCRIPTION = "Load average, memory and swap pressure, temperature, uptime"


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.system
    metrics: list[Metric] = []
    details: list[str] = []
    summary: list[str] = []
    status = Status.OK
    cores = os.cpu_count() or 1

    load_text = ctx.read_proc("loadavg")
    load1 = None
    if load_text is None:
        status = worse(status, Status.ERROR)
        summary.append("load unreadable")
        details.append("cannot read /proc/loadavg")
    else:
        fields = load_text.split()
        try:
            load1, load5, load15 = (float(value) for value in fields[:3])
        except (ValueError, IndexError):
            status = worse(status, Status.ERROR)
            summary.append("load unreadable")
            details.append(f"unexpected /proc/loadavg content: {load_text.strip()!r}")
        else:
            per_core = load1 / cores
            metrics.append(
                Metric("load1", load1, {"period": "1m"}, "1 minute load average")
            )
            metrics.append(
                Metric("load5", load5, {"period": "5m"}, "5 minute load average")
            )
            metrics.append(
                Metric("load15", load15, {"period": "15m"}, "15 minute load average")
            )
            summary.append(f"load {load1:.2f} ({cores} cores)")
            details.append(f"load averages: {load1:.2f}, {load5:.2f}, {load15:.2f}")
            if per_core >= cfg.crit_load_per_core:
                status = worse(status, Status.CRIT)
                details.append(
                    f"load per core {per_core:.2f} is at or above the critical "
                    f"threshold {cfg.crit_load_per_core:g}"
                )
            elif per_core >= cfg.warn_load_per_core:
                status = worse(status, Status.WARN)
                details.append(
                    f"load per core {per_core:.2f} is at or above the warning "
                    f"threshold {cfg.warn_load_per_core:g}"
                )

    meminfo = _meminfo(ctx)
    if not meminfo or not meminfo.get("MemTotal"):
        status = worse(status, Status.ERROR)
        summary.append("memory unreadable")
        details.append("cannot read /proc/meminfo")
    else:
        total = meminfo["MemTotal"]
        available = meminfo.get("MemAvailable")
        if available is None:
            available = (
                meminfo.get("MemFree", 0.0)
                + meminfo.get("Buffers", 0.0)
                + meminfo.get("Cached", 0.0)
            )
        available = min(total, available)
        used = max(0.0, total - available)
        used_pct = percent(used, total)
        metrics.append(
            Metric(
                "memory_used_percent", round(used_pct, 2), {}, "Memory in use, percent"
            )
        )
        metrics.append(Metric("memory_total_bytes", total, {}, "Total physical memory"))
        metrics.append(Metric("memory_used_bytes", used, {}, "Physical memory in use"))
        summary.append(f"memory {used_pct:.0f}%")
        details.append(
            f"memory: {human_bytes(used)} / {human_bytes(total)} used ({used_pct:.1f}%)"
        )
        if used_pct >= cfg.crit_memory_percent:
            status = worse(status, Status.CRIT)
            details.append(
                f"memory use is at or above the critical threshold "
                f"{cfg.crit_memory_percent:g}%"
            )
        elif used_pct >= cfg.warn_memory_percent:
            status = worse(status, Status.WARN)
            details.append(
                f"memory use is at or above the warning threshold "
                f"{cfg.warn_memory_percent:g}%"
            )

        if cfg.check_swap:
            swap_total = meminfo.get("SwapTotal", 0.0)
            swap_free = meminfo.get("SwapFree", 0.0)
            if swap_total > 0:
                swap_used = max(0.0, swap_total - swap_free)
                swap_pct = percent(swap_used, swap_total)
                metrics.append(
                    Metric(
                        "swap_used_percent",
                        round(swap_pct, 2),
                        {},
                        "Swap in use, percent",
                    )
                )
                summary.append(f"swap {swap_pct:.0f}%")
                details.append(
                    f"swap: {human_bytes(swap_used)} / {human_bytes(swap_total)} "
                    f"used ({swap_pct:.1f}%)"
                )
                if swap_pct >= cfg.crit_swap_percent:
                    status = worse(status, Status.CRIT)
                    details.append(
                        f"swap use is at or above the critical threshold "
                        f"{cfg.crit_swap_percent:g}%"
                    )
                elif swap_pct >= cfg.warn_swap_percent:
                    status = worse(status, Status.WARN)
                    details.append(
                        f"swap use is at or above the warning threshold "
                        f"{cfg.warn_swap_percent:g}%"
                    )

    uptime_text = ctx.read_proc("uptime")
    if uptime_text:
        try:
            uptime = float(uptime_text.split()[0])
        except (ValueError, IndexError):
            pass
        else:
            metrics.append(Metric("uptime_seconds", uptime, {}, "System uptime"))
            summary.append(f"up {human_duration(uptime)}")
            details.append(f"uptime: {human_duration(uptime)}")

    temperature, sensor_count = _temperature(ctx)
    if temperature is not None:
        metrics.append(
            Metric(
                "temperature_celsius",
                round(temperature, 1),
                {},
                "Hottest thermal sensor",
            )
        )
        summary.append(f"temp {temperature:.0f}\u00b0C")
        details.append(
            f"hottest of {sensor_count} thermal sensor(s): {temperature:.1f}\u00b0C"
        )
        if temperature >= cfg.crit_temperature_c:
            status = worse(status, Status.CRIT)
            details.append(
                f"temperature is at or above the critical threshold "
                f"{cfg.crit_temperature_c:g}\u00b0C"
            )
        elif temperature >= cfg.warn_temperature_c:
            status = worse(status, Status.WARN)
            details.append(
                f"temperature is at or above the warning threshold "
                f"{cfg.warn_temperature_c:g}\u00b0C"
            )

    if not summary:
        summary.append("no system metrics available")
    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=", ".join(summary),
        details=details,
        metrics=metrics,
    )


def _meminfo(ctx: Context) -> dict[str, float] | None:
    """Parse /proc/meminfo into a mapping of byte counts."""
    raw = ctx.read_proc("meminfo")
    if raw is None:
        return None
    values: dict[str, float] = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if not fields:
            continue
        try:
            value = float(fields[0]) * 1024.0  # values are in KiB
        except ValueError:
            continue
        values[key.strip()] = value
    return values


def _temperature(ctx: Context) -> tuple[float | None, int]:
    """Return the hottest plausible sensor reading in Celsius."""
    readings: list[float] = []
    for pattern in (
        "class/thermal/thermal_zone*/temp",
        "class/hwmon/hwmon*/temp*_input",
    ):
        for path in sorted(ctx.sys.glob(pattern)):
            text = read_text(path, limit=64)
            if text is None:
                continue
            try:
                value = float(text.strip()) / 1000.0
            except ValueError:
                continue
            if 0.0 < value < 150.0:
                readings.append(value)
    if not readings:
        return None, 0
    return max(readings), len(readings)
