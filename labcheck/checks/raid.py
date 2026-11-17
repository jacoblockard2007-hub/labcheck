"""Linux software RAID (md) array health."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import human_bytes

NAME = "raid"
TITLE = "RAID"
DESCRIPTION = "Linux md software RAID array state"

_DEVICE_RE = re.compile(r"^(md\w+)\s*:\s*(.*)$")
_DISKS_RE = re.compile(r"\[(\d+)/(\d+)\]\s*\[([U_]+)\]")
_ACTIVITY_RE = re.compile(r"\b(recovery|resync|reshape|check)\b.*?=\s*([\d.]+)%")
_BLOCKS_RE = re.compile(r"^\s*(\d+)\s+blocks\b")


@dataclass
class Array:
    name: str
    state: str = ""
    raid_level: str = ""
    total_disks: int | None = None
    active_disks: int | None = None
    slots: str = ""
    activity: str | None = None
    progress: float | None = None
    blocks: int | None = None

    @property
    def degraded(self) -> bool:
        if "degraded" in self.state.lower():
            return True
        if "_" in self.slots:
            return True
        if self.total_disks is not None and self.active_disks is not None:
            return self.active_disks < self.total_disks
        return False

    @property
    def inactive(self) -> bool:
        return "inactive" in self.state.lower()


def run(ctx: Context) -> CheckResult:
    raw = ctx.read_proc("mdstat")
    if raw is None:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="no software RAID detected",
            details=["/proc/mdstat is not available"],
        )

    arrays = _parse(raw)
    if not arrays:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="no software RAID arrays",
            details=["/proc/mdstat contains no md devices"],
        )

    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = []
    problems: list[str] = []

    for array in arrays:
        label = array.name
        if array.raid_level:
            label += f" ({array.raid_level})"
        if array.total_disks is not None:
            label += f", {array.active_disks}/{array.total_disks} disks"
        if array.blocks:
            label += f", {human_bytes(array.blocks * 1024)}"
        details.append(label)

        degraded = array.degraded or array.inactive
        metrics.append(
            Metric(
                "md_degraded",
                1 if degraded else 0,
                {"device": array.name},
                "Software RAID array is degraded",
            )
        )
        if array.progress is not None:
            metrics.append(
                Metric(
                    "md_resync_percent",
                    round(array.progress, 2),
                    {"device": array.name},
                    "RAID rebuild or scrub progress",
                )
            )

        if array.inactive:
            status = worse(status, Status.CRIT)
            problems.append(f"{array.name} inactive")
            details.append(f"{array.name}: array is inactive")
        elif array.degraded:
            status = worse(status, Status.CRIT)
            problems.append(f"{array.name} degraded")
            details.append(
                f"{array.name}: degraded - {array.active_disks or '?'} of "
                f"{array.total_disks or '?'} disks active"
            )

        if (
            array.activity in {"recovery", "resync", "reshape"}
            and array.progress is not None
        ):
            status = worse(status, Status.WARN)
            details.append(
                f"{array.name}: {array.activity} at {array.progress:.1f}%"
                + ("" if array.degraded else " (array remains available)")
            )
        elif array.activity == "check":
            if array.progress is not None:
                details.append(
                    f"{array.name}: consistency check at {array.progress:.1f}%"
                )
            else:
                details.append(f"{array.name}: consistency check running")

    rebuilding = [
        array for array in arrays if array.activity in {"recovery", "resync", "reshape"}
    ]
    if problems:
        summary = "; ".join(problems)
        healthy = len(arrays) - len(problems)
        if healthy:
            summary += f"; {healthy} healthy"
        if rebuilding and rebuilding[0].progress is not None:
            summary += (
                f"; {rebuilding[0].name} {rebuilding[0].activity} "
                f"{rebuilding[0].progress:.0f}%"
            )
    else:
        if rebuilding:
            array = rebuilding[0]
            summary = (
                f"{array.name} {array.activity} {array.progress:.0f}%"
                if array.progress is not None
                else f"{array.name} {array.activity}"
            )
        else:
            summary = (
                f"{len(arrays)} array" + ("" if len(arrays) == 1 else "s") + " healthy"
            )
            summary += " (" + ", ".join(array.name for array in arrays) + ")"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _parse(raw: str) -> list[Array]:
    arrays: list[Array] = []
    current: Array | None = None

    for line in raw.splitlines():
        if not line.strip() or line.startswith("Personalities"):
            continue
        match = _DEVICE_RE.match(line)
        if match:
            state = match.group(2)
            fields = state.split()
            raid_level = (
                fields[1] if len(fields) > 1 and fields[1].startswith("raid") else ""
            )
            current = Array(name=match.group(1), state=state, raid_level=raid_level)
            arrays.append(current)
            _apply_counts(current, line)
            continue
        if current is None:
            continue
        _apply_counts(current, line)
        activity = _ACTIVITY_RE.search(line)
        if activity:
            current.activity = activity.group(1)
            current.progress = float(activity.group(2))
        blocks = _BLOCKS_RE.match(line)
        if blocks:
            current.blocks = int(blocks.group(1))
        status = re.search(r"\[(\d+)/(\d+)\]", line)
        if status and current.total_disks is None:
            current.total_disks = int(status.group(1))
            current.active_disks = int(status.group(2))
    return arrays


def _apply_counts(array: Array, line: str) -> None:
    match = _DISKS_RE.search(line)
    if match:
        array.total_disks = int(match.group(1))
        array.active_disks = int(match.group(2))
        array.slots = match.group(3)
    else:
        state = line.split(":", 1)[-1]
        flags = re.search(r"\[([U_]+)\]", state)
        if flags:
            array.slots = flags.group(1)
