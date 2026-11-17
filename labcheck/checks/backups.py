"""Freshness of configured backup files."""

from __future__ import annotations

import glob
import os

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import human_duration

NAME = "backups"
TITLE = "Backups"
DESCRIPTION = "Freshness of backup files or directories"


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.backups
    if not cfg.targets:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="no backup targets configured",
            details=["add [[backups.targets]] entries to check backup freshness"],
        )

    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = []
    problems: list[str] = []
    now = ctx.now.timestamp()
    fresh = 0

    for target in cfg.targets:
        matches = [path for path in glob.glob(target.path) if os.path.exists(path)]
        if not matches:
            status = worse(status, Status.CRIT)
            problems.append(f"{target.name} missing")
            details.append(f"{target.name}: no file matches {target.path}")
            metrics.append(
                Metric(
                    "backup_present", 0, {"target": target.name}, "Backup target exists"
                )
            )
            continue

        try:
            newest = max(os.path.getmtime(path) for path in matches)
        except OSError as exc:
            status = worse(status, Status.ERROR)
            details.append(f"{target.name}: cannot stat {target.path} ({exc})")
            metrics.append(
                Metric(
                    "backup_present", 1, {"target": target.name}, "Backup target exists"
                )
            )
            continue

        age_seconds = max(0.0, now - newest)
        age_hours = age_seconds / 3600.0
        latest = newest_path(matches, newest)
        metrics.append(
            Metric("backup_present", 1, {"target": target.name}, "Backup target exists")
        )
        metrics.append(
            Metric(
                "backup_age_hours",
                round(age_hours, 2),
                {"target": target.name},
                "Age of the newest backup",
            )
        )

        if age_hours > target.max_age_hours:
            status = worse(status, Status.CRIT)
            problems.append(f"{target.name} stale")
            details.append(
                f"{target.name}: newest backup is {human_duration(age_seconds)} old "
                f"(limit {target.max_age_hours:g}h) at {latest}"
            )
        else:
            fresh += 1
            details.append(
                f"{target.name}: {human_duration(age_seconds)} old "
                f"(limit {target.max_age_hours:g}h) at {latest}"
            )

    if problems:
        summary = ", ".join(problems)
        if fresh:
            summary += f"; {fresh}/{len(cfg.targets)} fresh"
    else:
        summary = f"{len(cfg.targets)} target" + ("" if len(cfg.targets) == 1 else "s")
        summary += " fresh"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def newest_path(paths: list[str], mtime: float) -> str:
    """Return the path whose mtime is ``mtime`` (first match wins)."""
    for path in paths:
        try:
            if os.path.getmtime(path) == mtime:
                return path
        except OSError:
            continue
    return paths[0]
