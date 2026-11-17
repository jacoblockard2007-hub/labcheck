from __future__ import annotations

import os
import unittest
from pathlib import Path

from labcheck.checks import backups
from labcheck.config import BackupsConfig, BackupTarget, Config
from tests.helpers import FIXED_NOW, LabcheckTestCase


class BackupsCheckTest(LabcheckTestCase):
    def config(self, *targets: BackupTarget) -> Config:
        return Config(backups=BackupsConfig(targets=list(targets)))

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


if __name__ == "__main__":
    unittest.main()
