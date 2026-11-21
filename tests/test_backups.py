from __future__ import annotations

import json
import os
import time as time_module
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from labcheck.checks import backups
from labcheck.config import (
    BackupsConfig,
    BackupSnapshotConfig,
    BackupTarget,
    Config,
)
from tests.helpers import FIXED_NOW, FakeRunner, LabcheckTestCase


class BackupsCheckTest(LabcheckTestCase):
    def config(self, *targets: BackupTarget) -> Config:
        return Config(backups=BackupsConfig(targets=list(targets)))

    def prepare_snapshot_fixture(self) -> tuple[Config, FakeRunner]:
        backup_root = self.temp / "backup"
        snapshots = backup_root / "snapshots"
        snapshots.mkdir(parents=True)

        completed = snapshots / "2026-06-01"
        completed.mkdir()

        latest = snapshots / "latest"
        latest.symlink_to("2026-06-01")

        self.write_proc(
            "self/mountinfo",
            "36 25 8:33 / /backup rw,relatime - ext4 /dev/test-backup rw\n",
        )

        runner = FakeRunner(
            available={"systemctl"},
            responses={
                "systemctl is-enabled snapshot-backup.timer": (0, "enabled\n", ""),
                "systemctl is-active snapshot-backup.timer": (0, "active\n", ""),
                (
                    "systemctl show snapshot-backup.service "
                    "--property=Result --property=ExecMainStatus "
                    "--property=ExecMainStartTimestamp --no-pager"
                ): (
                    0,
                    (
                        "Result=success\n"
                        "ExecMainStatus=0\n"
                        "ExecMainStartTimestamp=Mon 2026-06-01 01:00:00 UTC\n"
                    ),
                    "",
                ),
            },
        )

        snapshot = BackupSnapshotConfig(
            timer_unit="snapshot-backup.timer",
            service_unit="snapshot-backup.service",
        )
        config = Config(backups=BackupsConfig(snapshots=[snapshot]))
        return config, runner

    def make_target(
        self, name: str = "db", *, age_hours: float | None = 2, max_age: float = 24
    ) -> tuple[BackupTarget, Path]:
        path = self.temp / f"{name}.sql"
        if age_hours is not None:
            path.write_text("backup", encoding="utf-8")
            stamp = FIXED_NOW.timestamp() - age_hours * 3600
            os.utime(path, (stamp, stamp))
        return (
            BackupTarget(name=name, path=str(path), max_age_hours=max_age),
            path,
        )

    def test_no_targets_is_skipped(self) -> None:
        result = backups.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("no backup targets", result.summary)

    def test_healthy_snapshot_monitoring(self) -> None:
        config, runner = self.prepare_snapshot_fixture()

        result = backups.run(self.context(config=config, runner=runner))

        self.assertEqual(result.status.value, "ok")
        self.assertEqual(len(runner.calls), 3)
        systemd_metrics = [
            metric
            for metric in result.metrics
            if metric.name
            in {
                "backup_timer_enabled",
                "backup_timer_active",
                "backup_service_success",
            }
        ]
        self.assertEqual(len(systemd_metrics), 3)
        self.assertTrue(
            all(metric.labels == {"snapshot": "Snapshot"} for metric in systemd_metrics)
        )
        self.assertTrue(all(call[0] == "systemctl" for call in runner.calls))

        details = "\n".join(result.details)
        self.assertIn("2026-06-01", details)

    def test_snapshot_timer_static_and_indirect_states_are_accepted(self) -> None:
        config, runner = self.prepare_snapshot_fixture()

        for enabled_state in ("static", "indirect"):
            with self.subTest(enabled_state=enabled_state):
                runner.responses["systemctl is-enabled snapshot-backup.timer"] = (
                    0,
                    f"{enabled_state}\n",
                    "",
                )

                result = backups.run(self.context(config=config, runner=runner))

                self.assertEqual(result.status.value, "ok")
                enabled_metric = next(
                    metric
                    for metric in result.metrics
                    if metric.name == "backup_timer_enabled"
                )
                self.assertEqual(enabled_metric.value, 1)

    def test_snapshot_directory_outside_mount_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()

        backup_root = self.temp / "backup"
        snapshots = backup_root / "snapshots"

        (snapshots / "latest").unlink()
        (snapshots / "2026-06-01").rmdir()
        snapshots.rmdir()

        outside = self.temp / "outside" / "snapshots"
        outside.mkdir(parents=True)
        snapshots.symlink_to(outside, target_is_directory=True)

        result = backups.run(self.context(config=config, runner=runner))

        self.assertEqual(result.status.value, "crit")
        self.assertIn("snapshot directory outside backup mount", result.summary)

    def test_snapshot_mount_missing_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        self.write_proc(
            "self/mountinfo",
            "36 25 8:33 / /other rw,relatime - ext4 /dev/test-backup rw\n",
        )
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("backup mount missing", result.summary)

        presence = [
            metric
            for metric in result.metrics
            if metric.name == "backup_snapshot_present"
        ]
        self.assertEqual(len(presence), 1)
        self.assertEqual(presence[0].value, 0)

    def test_snapshot_mountinfo_unavailable_is_error(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        (self.proc / "self" / "mountinfo").unlink()
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "error")
        self.assertIn("mount information unavailable", result.summary)

        presence = [
            metric
            for metric in result.metrics
            if metric.name == "backup_snapshot_present"
        ]
        self.assertEqual(len(presence), 1)
        self.assertEqual(presence[0].value, 0)

    def test_snapshot_directory_missing_emits_absent_metric(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        snapshots = self.temp / "backup" / "snapshots"
        (snapshots / "latest").unlink()
        (snapshots / "2026-06-01").rmdir()
        snapshots.rmdir()

        result = backups.run(self.context(config=config, runner=runner))

        self.assertEqual(result.status.value, "crit")
        self.assertIn("snapshot directory missing", result.summary)
        presence = [
            metric
            for metric in result.metrics
            if metric.name == "backup_snapshot_present"
        ]
        self.assertEqual(len(presence), 1)
        self.assertEqual(presence[0].value, 0)

    def test_snapshot_latest_missing_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        (self.temp / "backup" / "snapshots" / "latest").unlink()
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("latest snapshot link missing", result.summary)

    def test_snapshot_latest_outside_directory_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        latest = self.temp / "backup" / "snapshots" / "latest"
        outside = self.temp / "outside" / "2026-06-01"
        outside.mkdir(parents=True)
        latest.unlink()
        latest.symlink_to(outside)
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("escapes snapshot directory", result.summary)

    def test_snapshot_non_padded_date_name_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        snapshots = self.temp / "backup" / "snapshots"
        invalid = snapshots / "2026-6-1"
        invalid.mkdir()
        latest = snapshots / "latest"
        latest.unlink()
        latest.symlink_to(invalid.name)

        result = backups.run(self.context(config=config, runner=runner))

        self.assertEqual(result.status.value, "crit")
        self.assertIn("latest snapshot has invalid date name", result.summary)

    def test_snapshot_stale_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        snapshots = self.temp / "backup" / "snapshots"
        stale = snapshots / "2026-05-20"
        stale.mkdir()
        latest = snapshots / "latest"
        latest.unlink()
        latest.symlink_to(stale.name)
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("latest snapshot stale", result.summary)

    def test_snapshot_timer_disabled_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        runner.responses["systemctl is-enabled snapshot-backup.timer"] = (
            1,
            "disabled\n",
            "",
        )
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("backup timer not enabled", result.summary)

    def test_snapshot_timer_inactive_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        runner.responses["systemctl is-active snapshot-backup.timer"] = (
            3,
            "inactive\n",
            "",
        )
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("backup timer not active", result.summary)

    def test_nonexistent_configured_timer_is_critical_not_error(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        runner.responses["systemctl is-enabled snapshot-backup.timer"] = (
            1,
            "",
            (
                "Failed to get unit file state for snapshot-backup.timer: "
                "No such file or directory"
            ),
        )

        result = backups.run(self.context(config=config, runner=runner))

        self.assertEqual(result.status.value, "crit")
        self.assertIn("backup timer not enabled", result.summary)

    def test_snapshot_service_failure_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        show_command = (
            "systemctl show snapshot-backup.service "
            "--property=Result --property=ExecMainStatus "
            "--property=ExecMainStartTimestamp --no-pager"
        )
        runner.responses[show_command] = (
            0,
            (
                "Result=exit-code\n"
                "ExecMainStatus=1\n"
                "ExecMainStartTimestamp=Mon 2026-06-01 01:00:00 UTC\n"
            ),
            "",
        )
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("last backup service run unsuccessful", result.summary)

    def test_snapshot_service_never_run_is_critical(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        show_command = (
            "systemctl show snapshot-backup.service "
            "--property=Result --property=ExecMainStatus "
            "--property=ExecMainStartTimestamp --no-pager"
        )
        runner.responses[show_command] = (
            0,
            ("Result=success\nExecMainStatus=0\nExecMainStartTimestamp=n/a\n"),
            "",
        )
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("last backup service run unsuccessful", result.summary)

    def test_snapshot_systemd_unavailable_is_error(self) -> None:
        config, _ = self.prepare_snapshot_fixture()
        runner = FakeRunner()
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "error")
        self.assertIn("systemd verification unavailable", result.summary)

    def test_incomplete_snapshot_directory_is_warning(self) -> None:
        config, runner = self.prepare_snapshot_fixture()
        incomplete = self.temp / "backup" / "snapshots" / ".incomplete_2026-06-01"
        incomplete.mkdir()
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "warn")
        self.assertIn("1 incomplete snapshot", result.summary)
        self.assertTrue(incomplete.is_dir())

    def test_fresh_backup(self) -> None:
        target, _ = self.make_target(age_hours=2)
        result = backups.run(self.context(config=self.config(target)))
        self.assertEqual(result.status.value, "ok")
        self.assertIn("1 target fresh", result.summary)
        metrics = {metric.name: metric for metric in result.metrics}
        self.assertEqual(metrics["backup_present"].value, 1)
        self.assertAlmostEqual(metrics["backup_age_hours"].value, 2.0, places=2)

    def test_stale_backup_is_critical(self) -> None:
        target, _ = self.make_target(age_hours=30, max_age=24)
        result = backups.run(self.context(config=self.config(target)))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("db stale", result.summary)
        details = "\n".join(result.details)
        self.assertIn("1d 6h old", details)
        self.assertIn("limit 24h", details)

    def test_missing_backup_is_critical(self) -> None:
        target, _ = self.make_target(age_hours=None)
        result = backups.run(self.context(config=self.config(target)))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("db missing", result.summary)
        present = next(
            metric for metric in result.metrics if metric.name == "backup_present"
        )
        self.assertEqual(present.value, 0)

    def test_glob_uses_newest_file(self) -> None:
        directory = self.temp / "dumps"
        directory.mkdir()
        older = directory / "dump-1.sql"
        newer = directory / "dump-2.sql"
        older.write_text("old", encoding="utf-8")
        newer.write_text("new", encoding="utf-8")
        now = FIXED_NOW.timestamp()
        os.utime(older, (now - 30 * 3600, now - 30 * 3600))
        os.utime(newer, (now - 1800, now - 1800))
        target = BackupTarget(
            name="dumps", path=str(directory / "dump-*.sql"), max_age_hours=24
        )
        result = backups.run(self.context(config=self.config(target)))
        self.assertEqual(result.status.value, "ok")
        self.assertIn("dump-2.sql", "\n".join(result.details))

    def test_future_timestamp_is_treated_as_fresh(self) -> None:
        target, _ = self.make_target(age_hours=-5)
        result = backups.run(self.context(config=self.config(target)))
        self.assertEqual(result.status.value, "ok")
        age = next(
            metric for metric in result.metrics if metric.name == "backup_age_hours"
        )
        self.assertEqual(age.value, 0)

    def test_mixed_targets(self) -> None:
        fresh, _ = self.make_target("fresh", age_hours=1)
        stale, _ = self.make_target("stale", age_hours=48)
        result = backups.run(self.context(config=self.config(fresh, stale)))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("stale stale", result.summary)
        self.assertIn("1/2 fresh", result.summary)

    def test_directory_target(self) -> None:
        directory = self.temp / "snapshots"
        directory.mkdir()
        (directory / "file").write_text("x", encoding="utf-8")
        target = BackupTarget(name="snapshots", path=str(directory), max_age_hours=1)
        result = backups.run(self.context(config=self.config(target)))
        self.assertEqual(result.status.value, "ok")


class GeneralizedSnapshotCheckTest(LabcheckTestCase):
    def _snapshot(self, name: str, *, timestamp_format: str = "%Y-%m-%d_%H:%M:%S"):
        root = self.temp / "backup"
        snapshots = root / "snapshots"
        snapshots.mkdir(parents=True)
        snapshot_dir = snapshots / name
        snapshot_dir.mkdir()
        latest = snapshots / "latest"
        latest.symlink_to(name)
        self.write_proc(
            "self/mountinfo",
            "36 25 8:33 / /backup rw,relatime - ext4 /dev/test-backup rw\n",
        )
        from labcheck.config import BackupSnapshotConfig

        return BackupSnapshotConfig(
            mountpoint="/backup",
            snapshots_dir="/backup/snapshots",
            latest_link="/backup/snapshots/latest",
            max_age_hours=192,
            timer_unit=None,
            service_unit=None,
            name="Media",
            name_prefix="Media_",
            timestamp_format=timestamp_format,
        )

    def test_snapshot_mount_check_can_be_disabled(self) -> None:
        cfg = self._snapshot("Media_2026-06-01_02:00:15")

        cfg = replace(cfg, check_mount=False)
        (self.proc / "self" / "mountinfo").unlink()

        result = backups.run(
            self.context(config=Config(backups=BackupsConfig(snapshots=[cfg])))
        )

        self.assertEqual(result.status.value, "ok")
        presence = [
            metric
            for metric in result.metrics
            if metric.name == "backup_snapshot_present"
        ]
        self.assertEqual(len(presence), 1)
        self.assertEqual(presence[0].value, 1)

    def test_timestamped_snapshot_uses_name_not_directory_mtime(self) -> None:
        # Pin UTC so this test remains deterministic on hosts in other timezones.
        try:
            with patch.dict(os.environ, {"TZ": "UTC"}):
                time_module.tzset()
                cfg = self._snapshot("Media_2026-06-01_02:00:15")
                result = backups.run(
                    self.context(config=Config(backups=BackupsConfig(snapshots=[cfg])))
                )
                self.assertEqual(result.status.value, "ok")
                age = next(
                    m.value
                    for m in result.metrics
                    if m.name == "backup_snapshot_age_hours"
                )
                self.assertAlmostEqual(age, 10.0, places=2)
        finally:
            time_module.tzset()

    def test_naive_snapshot_timestamp_uses_host_local_timezone(self) -> None:
        try:
            with patch.dict(os.environ, {"TZ": "America/New_York"}):
                time_module.tzset()
                cfg = self._snapshot("Media_2026-06-01_11:00:00")
                # 16:00 UTC is noon in New York on this date; the snapshot is 11:00 EDT.
                now = FIXED_NOW.replace(hour=16)
                result = backups.run(
                    self.context(
                        config=Config(backups=BackupsConfig(snapshots=[cfg])),
                        now=now,
                    )
                )
                age = next(
                    m.value
                    for m in result.metrics
                    if m.name == "backup_snapshot_age_hours"
                )
                self.assertAlmostEqual(age, 1.0, places=2)
        finally:
            time_module.tzset()

    def test_impossible_timestamp_is_critical(self) -> None:
        cfg = self._snapshot("Media_2026-02-30_02:00:15")
        result = backups.run(
            self.context(config=Config(backups=BackupsConfig(snapshots=[cfg])))
        )
        self.assertEqual(result.status.value, "crit")
        self.assertIn("invalid timestamp", result.summary)

    def test_multiple_snapshot_monitors_are_both_checked(self) -> None:
        first = self._snapshot("Media_2026-06-01_02:00:15")
        second_root = self.temp / "backup2"
        second_dir = second_root / "snapshots"
        second_dir.mkdir(parents=True)
        (second_dir / "AppData_2026-06-01_02:30:13").mkdir()
        (second_dir / "latest").symlink_to("AppData_2026-06-01_02:30:13")
        second = type(first)(
            mountpoint="/backup2",
            snapshots_dir="/backup2/snapshots",
            latest_link="/backup2/snapshots/latest",
            max_age_hours=192,
            timer_unit=None,
            service_unit=None,
            name="AppData",
            name_prefix="AppData_",
            timestamp_format="%Y-%m-%d_%H:%M:%S",
        )
        self.write_proc(
            "self/mountinfo",
            "36 25 8:33 / /backup rw - ext4 /dev/a rw\n"
            "37 25 8:34 / /backup2 rw - ext4 /dev/b rw\n",
        )
        result = backups.run(
            self.context(
                config=Config(backups=BackupsConfig(snapshots=[first, second]))
            )
        )
        self.assertEqual(result.status.value, "ok")
        labels = {
            m.labels.get("snapshot")
            for m in result.metrics
            if m.name == "backup_snapshot_present"
        }
        self.assertEqual(labels, {"Media", "AppData"})

    def test_generic_target_checks_optional_systemd_units(self) -> None:
        target, _ = self._make_target()
        target = BackupTarget(
            name=target.name,
            path=target.path,
            max_age_hours=24,
            timer_unit="sample.timer",
            service_unit="sample.service",
        )
        runner = FakeRunner(
            available={"systemctl"},
            responses={
                "systemctl is-enabled sample.timer": (0, "enabled\n", ""),
                "systemctl is-active sample.timer": (0, "active\n", ""),
                "systemctl show sample.service": (
                    0,
                    (
                        "Result=success\nExecMainStatus=0\n"
                        "ExecMainStartTimestamp=Mon 2026-06-01 01:00:00 UTC\n"
                    ),
                    "",
                ),
            },
        )
        result = backups.run(
            self.context(
                config=Config(backups=BackupsConfig(targets=[target])),
                runner=runner,
            )
        )
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(len(runner.calls), 3)
        systemd_metrics = [
            metric
            for metric in result.metrics
            if metric.name
            in {
                "backup_timer_enabled",
                "backup_timer_active",
                "backup_service_success",
            }
        ]
        self.assertEqual(len(systemd_metrics), 3)
        self.assertTrue(
            all(metric.labels == {"target": "archive"} for metric in systemd_metrics)
        )

    def _make_target(self):
        path = self.temp / "archive.zip"
        path.write_text("backup", encoding="utf-8")
        return BackupTarget(name="archive", path=str(path)), path

    def test_numeric_timezone_offset_is_respected(self) -> None:
        cfg = self._snapshot(
            "Media_2026-06-01_02:00:00_+0000",
            timestamp_format="%Y-%m-%d_%H:%M:%S_%z",
        )
        result = backups.run(
            self.context(config=Config(backups=BackupsConfig(snapshots=[cfg])))
        )
        age = next(
            metric.value
            for metric in result.metrics
            if metric.name == "backup_snapshot_age_hours"
        )
        self.assertAlmostEqual(age, 10.0, places=2)

    def test_colon_timezone_offset_is_respected(self) -> None:
        cfg = self._snapshot(
            "Media_2026-06-01_02:00:00_+00:00",
            timestamp_format="%Y-%m-%d_%H:%M:%S_%z",
        )
        result = backups.run(
            self.context(config=Config(backups=BackupsConfig(snapshots=[cfg])))
        )
        self.assertEqual(result.status.value, "ok")

    def test_z_timezone_offset_is_respected(self) -> None:
        cfg = self._snapshot(
            "Media_2026-06-01_02:00:00_Z",
            timestamp_format="%Y-%m-%d_%H:%M:%S_%z",
        )
        result = backups.run(
            self.context(config=Config(backups=BackupsConfig(snapshots=[cfg])))
        )
        self.assertEqual(result.status.value, "ok")

    def test_fractional_seconds_accept_one_to_six_digits(self) -> None:
        timestamp_format = "%Y-%m-%d_%H:%M:%S.%f"
        cfg = self._snapshot(
            "Media_2026-06-01_02:00:00.1",
            timestamp_format=timestamp_format,
        )
        snapshots = self.temp / "backup" / "snapshots"
        latest = snapshots / "latest"

        for fraction in ("1", "123", "123456"):
            with self.subTest(fraction=fraction):
                name = f"Media_2026-06-01_02:00:00.{fraction}"
                snapshot_dir = snapshots / name
                snapshot_dir.mkdir(exist_ok=True)
                latest.unlink()
                latest.symlink_to(name)

                result = backups.run(
                    self.context(config=Config(backups=BackupsConfig(snapshots=[cfg])))
                )
                self.assertEqual(result.status.value, "ok")


class KopiaBackupCheckTest(LabcheckTestCase):
    SOURCES = (
        "/etc",
        "/home",
        "/var/mail",
        "/var/vmail",
        "/srv",
        "/usr/local",
        "/var/backups/mail-server",
    )

    def setup_kopia(self, *, records=None, repository=(0, "{}\n", "")):
        from labcheck.config import BackupKopiaConfig

        config_path = self.temp / "etc" / "kopia" / "mail-b2.config"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("fixture only", encoding="utf-8")
        cfg = BackupKopiaConfig(
            enabled=True,
            config_file="/etc/kopia/mail-b2.config",
            source_paths=self.SOURCES,
        )
        config = Config(backups=BackupsConfig(kopia=cfg))
        if records is None:
            records = [
                {
                    "id": f"snapshot-{index}",
                    "source": {"host": "mail", "userName": "root", "path": path},
                    "startTime": "2026-06-01T10:59:00Z",
                    "endTime": "2026-06-01T11:00:00Z",
                    "stats": {"errorCount": 0, "ignoredErrorCount": 0},
                    "rootEntry": {"summ": {"numFailed": 0}},
                }
                for index, path in enumerate(self.SOURCES)
            ]

        def response(argv):
            if "repository" in argv:
                return repository
            return (0, json.dumps(records), "")

        runner = FakeRunner(available={"kopia"})
        runner.responses["/usr/bin/kopia --config-file"] = response
        return config, runner

    def test_healthy_repository_and_all_seven_sources(self) -> None:
        config, runner = self.setup_kopia()
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(
            result.status.value, "ok",
            msg=f"summary={result.summary!r}; details={result.details!r}",
        )
        self.assertIn("7/7 sources fresh", result.summary)
        self.assertEqual(len(runner.calls), 2)
        present = [
            metric
            for metric in result.metrics
            if metric.name == "backup_kopia_source_present" and metric.value == 1
        ]
        self.assertEqual(len(present), 7)
        self.assertTrue(
            any("Kopia repository: accessible" in line for line in result.details)
        )

    def test_missing_source_is_critical(self) -> None:
        config, runner = self.setup_kopia(records=[])
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(
            result.status.value, "crit",
            msg=f"summary={result.summary!r}; details={result.details!r}",
        )
        self.assertIn("/var/backups/mail-server missing", result.summary)

    def test_stale_source_and_snapshot_errors_are_critical(self) -> None:
        config, runner = self.setup_kopia()
        records = [
            {
                "id": "old-snapshot",
                "source": {
                    "host": "mail",
                    "userName": "root",
                    "path": "/var/vmail",
                },
                "endTime": "2026-05-30T11:00:00Z",
                "stats": {"errorCount": 1, "ignoredErrorCount": 0},
                "rootEntry": {"summ": {"numFailed": 0}},
            }
        ]

        def response(argv):
            if "repository" in argv:
                return (0, "{}\n", "")
            return (0, json.dumps(records), "")

        runner.responses["/usr/bin/kopia --config-file"] = response
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(
            result.status.value, "crit",
            msg=f"summary={result.summary!r}; details={result.details!r}",
        )
        self.assertIn("/var/vmail stale", result.summary)
        self.assertIn("/var/vmail snapshot errors", result.summary)

    def test_repository_failure_does_not_expose_command_output(self) -> None:
        config, runner = self.setup_kopia(
            repository=(1, "", "secret-looking diagnostic")
        )
        result = backups.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertNotIn("secret-looking", " ".join(result.details))


if __name__ == "__main__":
    unittest.main()
