"""Freshness of configured backup files and snapshot backups."""

from __future__ import annotations

import glob
import os
import re
from datetime import datetime
from pathlib import Path

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import human_duration

NAME = "backups"
TITLE = "Backups"
DESCRIPTION = "Freshness of backup files or directories"


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.backups
    snapshot_configs = list(cfg.snapshots)
    if cfg.snapshot is not None:
        snapshot_configs.insert(0, cfg.snapshot)
    snapshot_configs = [item for item in snapshot_configs if item.enabled]

    if not cfg.targets and not snapshot_configs:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="no backup targets configured",
            details=["add [[backups.targets]] or [[backups.snapshots]] entries"],
        )

    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = []
    summaries: list[str] = []

    if cfg.targets:
        target_result = _check_targets(ctx, cfg.targets)
        status = worse(status, target_result.status)
        details.extend(target_result.details)
        metrics.extend(target_result.metrics)
        summaries.append(target_result.summary)

    for snapshot_cfg in snapshot_configs:
        snapshot_result = _check_snapshot(ctx, snapshot_cfg)
        status = worse(status, snapshot_result.status)
        details.extend(snapshot_result.details)
        metrics.extend(snapshot_result.metrics)
        summaries.append(f"{snapshot_cfg.name}: {snapshot_result.summary}")

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary="; ".join(summaries),
        details=details,
        metrics=metrics,
    )


def _check_targets(ctx: Context, targets: list) -> CheckResult:
    """Check the original generic backup targets without changing their behavior."""
    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = []
    problems: list[str] = []
    now = ctx.now.timestamp()
    fresh = 0

    for target in targets:
        if target.timer_unit and target.service_unit:
            unit_status, unit_details, unit_metrics, unit_findings = _check_units(
                ctx, target.timer_unit, target.service_unit, target.name
            )
            status = worse(status, unit_status)
            details.extend(unit_details)
            metrics.extend(unit_metrics)
            problems.extend(unit_findings)

        matches = [path for path in glob.glob(target.path) if os.path.exists(path)]
        if not matches:
            status = worse(status, Status.CRIT)
            problems.append(f"{target.name} missing")
            details.append(f"{target.name}: no file matches {target.path}")
            metrics.append(
                Metric(
                    "backup_present",
                    0,
                    {"target": target.name},
                    "Backup target exists",
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
                    "backup_present",
                    1,
                    {"target": target.name},
                    "Backup target exists",
                )
            )
            continue

        age_seconds = max(0.0, now - newest)
        age_hours = age_seconds / 3600.0
        latest = newest_path(matches, newest)
        metrics.append(
            Metric(
                "backup_present",
                1,
                {"target": target.name},
                "Backup target exists",
            )
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
            summary += f"; {fresh}/{len(targets)} fresh"
    else:
        summary = f"{len(targets)} target" + ("" if len(targets) == 1 else "s")
        summary += " fresh"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _check_snapshot(ctx: Context, cfg) -> CheckResult:
    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = []
    findings: list[str] = []

    mountinfo = ctx.read_proc("self/mountinfo")
    if mountinfo is None:
        status = worse(status, Status.ERROR)
        findings.append("mount information unavailable")
        details.append("cannot read /proc/self/mountinfo")
    elif not _mount_is_present(mountinfo, cfg.mountpoint):
        status = worse(status, Status.CRIT)
        findings.append("backup mount missing")
        details.append(f"{cfg.mountpoint}: not present in mount information")
    else:
        details.append(f"{cfg.mountpoint}: mounted")

    snapshots_dir = _rooted(ctx, cfg.snapshots_dir)
    latest_link = _rooted(ctx, cfg.latest_link)
    snapshots_real: Path | None = None

    try:
        if snapshots_dir.is_dir():
            snapshots_real = snapshots_dir.resolve(strict=True)
            mountpoint_real = _rooted(ctx, cfg.mountpoint).resolve(strict=True)

            if not snapshots_real.is_relative_to(mountpoint_real):
                status = worse(status, Status.CRIT)
                findings.append("snapshot directory outside backup mount")
                details.append(
                    f"snapshot directory resolves outside {mountpoint_real}: "
                    f"{snapshots_real}"
                )
                snapshots_real = None
        else:
            status = worse(status, Status.CRIT)
            findings.append("snapshot directory missing")
            details.append(f"snapshot directory missing: {snapshots_dir}")
    except (OSError, RuntimeError) as exc:
        status = worse(status, Status.ERROR)
        findings.append("snapshot directory inaccessible")
        details.append(f"cannot inspect backup paths: {exc}")

    if snapshots_real is not None:
        latest_status = _check_latest(
            ctx,
            cfg,
            latest_link,
            snapshots_real,
            details,
            metrics,
            findings,
        )
        status = worse(status, latest_status)

        try:
            incomplete = sorted(
                path.name
                for path in snapshots_real.iterdir()
                if path.name.startswith(".incomplete_") and path.is_dir()
            )
            metrics.append(
                Metric(
                    "backup_incomplete_snapshots",
                    len(incomplete),
                    {"snapshot": cfg.name},
                    "Abandoned incomplete backup snapshots",
                )
            )
            if incomplete:
                status = worse(status, Status.WARN)
                findings.append(f"{len(incomplete)} incomplete snapshot(s)")
                details.append(
                    "incomplete snapshot directories found: " + ", ".join(incomplete)
                )
            else:
                details.append("no incomplete snapshot directories")
        except OSError as exc:
            status = worse(status, Status.ERROR)
            findings.append("cannot inspect incomplete snapshots")
            details.append(f"cannot list {snapshots_real}: {exc}")

    if cfg.timer_unit and cfg.service_unit:
        systemd_status, systemd_details, systemd_metrics, systemd_findings = (
            _check_units(ctx, cfg.timer_unit, cfg.service_unit, cfg.name)
        )
        status = worse(status, systemd_status)
        details.extend(systemd_details)
        metrics.extend(systemd_metrics)
        findings.extend(systemd_findings)

    summary = ", ".join(findings) if findings else "snapshot backup healthy"
    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _check_latest(
    ctx: Context,
    cfg,
    latest_link: Path,
    snapshots_real: Path,
    details: list[str],
    metrics: list[Metric],
    findings: list[str],
) -> Status:
    if not latest_link.is_symlink():
        findings.append("latest snapshot link missing or invalid")
        details.append(f"latest snapshot is not a symlink: {latest_link}")
        metrics.append(Metric("backup_snapshot_present", 0, {"snapshot": cfg.name}))
        return Status.CRIT

    try:
        latest_real = latest_link.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        findings.append("latest snapshot link is broken")
        details.append(f"cannot resolve {latest_link}: {exc}")
        metrics.append(Metric("backup_snapshot_present", 0, {"snapshot": cfg.name}))
        return Status.CRIT

    if not latest_real.is_relative_to(snapshots_real):
        findings.append("latest snapshot link escapes snapshot directory")
        details.append(
            f"latest snapshot resolves outside {snapshots_real}: {latest_real}"
        )
        metrics.append(Metric("backup_snapshot_present", 0, {"snapshot": cfg.name}))
        return Status.CRIT

    if not latest_real.is_dir():
        findings.append("latest snapshot is not a directory")
        details.append(f"latest snapshot target is not a directory: {latest_real}")
        metrics.append(Metric("backup_snapshot_present", 0, {"snapshot": cfg.name}))
        return Status.CRIT

    if not latest_real.name.startswith(cfg.name_prefix):
        findings.append("latest snapshot has invalid name")
        details.append(
            f"latest snapshot {latest_real.name!r} does not start with "
            f"configured prefix {cfg.name_prefix!r}"
        )
        metrics.append(Metric("backup_snapshot_present", 0, {"snapshot": cfg.name}))
        return Status.CRIT

    timestamp_text = latest_real.name[len(cfg.name_prefix) :]
    try:
        snapshot_time = datetime.strptime(timestamp_text, cfg.timestamp_format)
        # strptime accepts some non-zero-padded values; round-tripping enforces
        # the exact configured directory-name representation.
        if snapshot_time.strftime(cfg.timestamp_format) != timestamp_text:
            raise ValueError("timestamp does not match format exactly")
        if snapshot_time.tzinfo is None:
            # Backup scripts commonly embed the host's local wall-clock time
            # in directory names. Interpret naive timestamps in the host's
            # local timezone (including the offset applicable on that date),
            # rather than copying ctx.now.tzinfo, which may be UTC.
            snapshot_time = snapshot_time.astimezone()
    except (ValueError, TypeError, OverflowError):
        if cfg.timestamp_format == "%Y-%m-%d" and not cfg.name_prefix:
            findings.append("latest snapshot has invalid date name")
            details.append(
                f"latest snapshot directory is not YYYY-MM-DD: {latest_real.name}"
            )
        else:
            findings.append("latest snapshot has invalid timestamp")
            details.append(
                f"latest snapshot {latest_real.name!r} does not contain a valid "
                f"timestamp matching {cfg.timestamp_format!r}"
            )
        metrics.append(Metric("backup_snapshot_present", 0, {"snapshot": cfg.name}))
        return Status.CRIT
    age_seconds = max(0.0, (ctx.now - snapshot_time).total_seconds())
    age_hours = age_seconds / 3600.0

    metrics.append(Metric("backup_snapshot_present", 1, {"snapshot": cfg.name}))
    metrics.append(
        Metric("backup_snapshot_age_hours", round(age_hours, 2), {"snapshot": cfg.name})
    )
    details.append(
        f"{cfg.name} latest snapshot {latest_real.name}: "
        f"{human_duration(age_seconds)} old "
        f"(limit {cfg.max_age_hours:g}h)"
    )

    if age_hours > cfg.max_age_hours:
        findings.append("latest snapshot stale")
        return Status.CRIT

    return Status.OK


def _check_units(ctx: Context, timer_unit: str, service_unit: str, label: str):
    details: list[str] = []
    metrics: list[Metric] = []
    findings: list[str] = []
    status = Status.OK

    if ctx.runner.which("systemctl") is None:
        return (
            Status.ERROR,
            ["systemctl was not found; backup timer and service cannot be verified"],
            metrics,
            ["systemd verification unavailable"],
        )

    enabled = ctx.runner.run(
        ["systemctl", "is-enabled", timer_unit],
        timeout=10,
    )
    if _command_unavailable(enabled):
        return (
            Status.ERROR,
            [f"cannot query timer enabled state: {enabled.message}"],
            metrics,
            ["systemd verification unavailable"],
        )

    enabled_state = (
        enabled.stdout.strip().splitlines()[0] if enabled.stdout.strip() else "unknown"
    )
    is_enabled = enabled.returncode == 0 and enabled_state == "enabled"
    metrics.append(Metric("backup_timer_enabled", int(is_enabled), {"target": label}))
    details.append(f"{timer_unit}: enabled state {enabled_state}")
    if not is_enabled:
        status = worse(status, Status.CRIT)
        findings.append(f"{label}: backup timer not enabled")

    active = ctx.runner.run(
        ["systemctl", "is-active", timer_unit],
        timeout=10,
    )
    if _command_unavailable(active):
        return (
            Status.ERROR,
            details + [f"cannot query timer active state: {active.message}"],
            metrics,
            findings + ["systemd verification unavailable"],
        )

    active_state = (
        active.stdout.strip().splitlines()[0] if active.stdout.strip() else "unknown"
    )
    is_active = active.returncode == 0 and active_state == "active"
    metrics.append(Metric("backup_timer_active", int(is_active), {"target": label}))
    details.append(f"{timer_unit}: active state {active_state}")
    if not is_active:
        status = worse(status, Status.CRIT)
        findings.append(f"{label}: backup timer not active")

    service = ctx.runner.run(
        [
            "systemctl",
            "show",
            service_unit,
            "--property=Result",
            "--property=ExecMainStatus",
            "--property=ExecMainStartTimestamp",
            "--no-pager",
        ],
        timeout=10,
    )
    if _command_unavailable(service):
        return (
            Status.ERROR,
            details + [f"cannot inspect backup service: {service.message}"],
            metrics,
            findings + ["backup service status unavailable"],
        )
    if service.returncode != 0:
        return (
            Status.ERROR,
            details + [f"systemctl show failed: {service.message}"],
            metrics,
            findings + ["backup service status unavailable"],
        )

    properties: dict[str, str] = {}
    for line in service.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            properties[key] = value.strip()

    result = properties.get("Result", "")
    exit_status = properties.get("ExecMainStatus", "")
    started = properties.get("ExecMainStartTimestamp", "")
    has_started = bool(started) and started.strip().lower() != "n/a"
    successful = result == "success" and exit_status == "0" and has_started

    metrics.append(Metric("backup_service_success", int(successful), {"target": label}))
    details.append(
        f"{service_unit}: result={result or 'unknown'}, "
        f"exit_status={exit_status or 'unknown'}, "
        f"last_start={started or 'unknown'}"
    )
    if not successful:
        status = worse(status, Status.CRIT)
        findings.append(f"{label}: last backup service run unsuccessful or unavailable")

    return status, details, metrics, findings


def _command_unavailable(result) -> bool:
    if not result.found or result.timed_out:
        return True

    lowered = result.stderr.lower()
    return any(
        marker in lowered
        for marker in (
            "not been booted with systemd",
            "failed to connect to bus",
            "system has not been booted",
            "connection refused",
        )
    )


def _mount_is_present(mountinfo: str, mountpoint: str) -> bool:
    expected = os.path.normpath(mountpoint)

    for line in mountinfo.splitlines():
        fields = line.split(" - ", 1)[0].split()
        if len(fields) < 5:
            continue

        decoded = re.sub(
            r"\\([0-7]{3})",
            lambda match: chr(int(match.group(1), 8)),
            fields[4],
        )
        if os.path.normpath(decoded) == expected:
            return True

    return False


def _rooted(ctx: Context, configured_path: str) -> Path:
    path = Path(configured_path)

    if ctx.root != Path("/") and path.is_absolute():
        return ctx.root / path.relative_to("/")

    if ctx.root != Path("/") and not path.is_absolute():
        return ctx.root / path

    return path


def newest_path(paths: list[str], mtime: float) -> str:
    """Return the path whose mtime is ``mtime`` (first match wins)."""
    for path in paths:
        try:
            if os.path.getmtime(path) == mtime:
                return path
        except OSError:
            continue

    return paths[0]
