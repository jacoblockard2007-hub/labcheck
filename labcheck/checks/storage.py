"""Disk and inode usage for mounted filesystems."""

from __future__ import annotations

import fnmatch
import os

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import human_bytes, percent, read_text

NAME = "storage"
TITLE = "Storage"
DESCRIPTION = "Disk and inode usage of local filesystems"

#: Filesystems that do not represent usable storage.  tmpfs is included
#: because it lives in RAM; ignoring it avoids noisy duplicate readings.
PSEUDO_FILESYSTEMS = {
    "autofs",
    "binfmt_misc",
    "bpf",
    "cgroup",
    "cgroup2",
    "configfs",
    "debugfs",
    "devpts",
    "devtmpfs",
    "efivarfs",
    "fusectl",
    "hugetlbfs",
    "mqueue",
    "nsfs",
    "proc",
    "pstore",
    "ramfs",
    "rpc_pipefs",
    "securityfs",
    "squashfs",
    "sysfs",
    "tmpfs",
    "tracefs",
}


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.storage
    raw = read_text(ctx.proc / "mounts")
    if raw is None:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.ERROR,
            summary="cannot read /proc/mounts",
            details=["labcheck needs /proc/mounts to discover filesystems"],
        )

    ignored_fs = set(PSEUDO_FILESYSTEMS) | {
        entry.lower() for entry in cfg.ignore_filesystems
    }
    mountpoints: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mountpoint, fstype = _unescape(fields[1]), fields[2]
        if mountpoint in seen:
            continue
        if fstype.lower() in ignored_fs:
            continue
        if cfg.only_mounts and not _matches_any(mountpoint, cfg.only_mounts):
            continue
        if _matches_any(mountpoint, cfg.ignore_mounts):
            continue
        seen.add(mountpoint)
        mountpoints.append((mountpoint, fstype))

    if not mountpoints:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="no filesystems to check",
            details=["all mounts were filtered out by the configuration"],
        )

    status = Status.OK
    metrics: list[Metric] = []
    details: list[str] = []
    problems: list[tuple[float, str]] = []
    usable = 0
    uninspectable = 0

    for mountpoint, fstype in mountpoints:
        try:
            stats = os.statvfs(mountpoint)
        except PermissionError:
            # Common for per-user FUSE portal mounts; not a storage problem.
            details.append(f"{mountpoint}: skipped (permission denied)")
            continue
        except OSError as exc:
            status = worse(status, Status.WARN)
            uninspectable += 1
            details.append(f"{mountpoint}: cannot inspect ({exc.strerror or exc})")
            continue
        if stats.f_blocks <= 0:
            continue
        usable += 1

        total = stats.f_blocks * stats.f_frsize
        free = stats.f_bfree * stats.f_frsize
        available = stats.f_bavail * stats.f_frsize
        used = max(0, total - free)
        used_pct = percent(used, used + available)

        inode_used_pct = None
        if stats.f_files > 0:
            inode_used = stats.f_files - stats.f_ffree
            inode_used_pct = percent(inode_used, inode_used + stats.f_favail)

        metrics.append(
            Metric(
                "disk_used_percent",
                round(used_pct, 2),
                {"mount": mountpoint, "fstype": fstype},
                "Filesystem space used, percent",
            )
        )
        metrics.append(
            Metric(
                "disk_used_bytes",
                float(used),
                {"mount": mountpoint, "fstype": fstype},
                "Filesystem space used, bytes",
            )
        )
        metrics.append(
            Metric(
                "disk_size_bytes",
                float(total),
                {"mount": mountpoint, "fstype": fstype},
                "Filesystem size, bytes",
            )
        )
        if inode_used_pct is not None:
            metrics.append(
                Metric(
                    "inode_used_percent",
                    round(inode_used_pct, 2),
                    {"mount": mountpoint, "fstype": fstype},
                    "Filesystem inodes used, percent",
                )
            )

        description = (
            f"{mountpoint}: {used_pct:.1f}% of {human_bytes(total)} used "
            f"({human_bytes(available)} free)"
        )
        if inode_used_pct is not None:
            description += f", inodes {inode_used_pct:.0f}%"
        details.append(description)

        if used_pct >= cfg.crit_disk_percent:
            status = worse(status, Status.CRIT)
            problems.append((used_pct, f"{mountpoint} at {used_pct:.0f}%"))
        elif used_pct >= cfg.warn_disk_percent:
            status = worse(status, Status.WARN)
            problems.append((used_pct, f"{mountpoint} at {used_pct:.0f}%"))

        if inode_used_pct is not None:
            if inode_used_pct >= cfg.crit_inode_percent:
                status = worse(status, Status.CRIT)
                problems.append(
                    (inode_used_pct, f"{mountpoint} inodes at {inode_used_pct:.0f}%")
                )
            elif inode_used_pct >= cfg.warn_inode_percent:
                status = worse(status, Status.WARN)
                problems.append(
                    (inode_used_pct, f"{mountpoint} inodes at {inode_used_pct:.0f}%")
                )

    if usable == 0:
        if status is Status.OK:
            status = Status.ERROR
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=status,
            summary="no filesystem could be inspected",
            details=details,
            metrics=metrics,
        )

    problems.sort(key=lambda item: item[0], reverse=True)
    if problems:
        summary = problems[0][1]
        if len(problems) > 1:
            summary += f" (+{len(problems) - 1} more)"
        summary += f", {usable} mounts"
    else:
        representative = next(
            (mount for mount in mountpoints if mount[0] == "/"), mountpoints[0]
        )
        summary = _usage_summary(representative[0], metrics)
        summary += f", {usable} mount" + ("" if usable == 1 else "s")
    if uninspectable:
        summary += f"; {uninspectable} uninspectable"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _usage_summary(mountpoint: str, metrics: list[Metric]) -> str:
    """Describe space usage of one mount for the all-healthy summary."""
    for metric in metrics:
        if (
            metric.name == "disk_used_percent"
            and metric.labels.get("mount") == mountpoint
        ):
            return f"{mountpoint} {metric.value:.0f}% used"
    return "filesystems healthy"


def _unescape(value: str) -> str:
    """Decode the octal escapes used by /proc/mounts."""
    for encoded, decoded in (
        ("\\040", " "),
        ("\\011", "\t"),
        ("\\012", "\n"),
        ("\\134", "\\"),
    ):
        value = value.replace(encoded, decoded)
    return value


def _matches_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)
