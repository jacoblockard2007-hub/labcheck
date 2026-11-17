from __future__ import annotations

import errno
import unittest
from unittest import mock

from labcheck.checks import storage
from labcheck.config import Config, StorageConfig
from tests.helpers import LabcheckTestCase, statvfs

MOUNTS = """\
/dev/sda1 / ext4 rw,relatime 0 0
proc /proc proc rw,nosuid 0 0
tmpfs /run tmpfs rw,nosuid 0 0
/dev/sdb1 /srv/data ext4 rw,relatime 0 0
/dev/sdc1 /mnt/my\\040disk ext4 rw,relatime 0 0
"""


class StorageCheckTest(LabcheckTestCase):
    def run_check(
        self,
        config: Config | None = None,
        sizes: dict[str, object] | None = None,
        errors: dict[str, OSError] | None = None,
    ):
        sizes = sizes or {}
        errors = errors or {}
        default = statvfs()

        def fake(path: str):
            if path in errors:
                raise errors[path]
            return sizes.get(path, default)

        with mock.patch("labcheck.checks.storage.os.statvfs", side_effect=fake):
            return storage.run(self.context(config=config))

    def test_mounts_file_required(self) -> None:
        result = storage.run(self.context())
        self.assertEqual(result.status.value, "error")
        self.assertIn("/proc/mounts", result.summary)

    def test_healthy_filesystems(self) -> None:
        self.write_proc("mounts", MOUNTS)
        result = self.run_check()
        self.assertEqual(result.status.value, "ok")
        self.assertIn("/ 30% used", result.summary)
        self.assertIn("3 mounts", result.summary)
        mountpoints = {
            metric.labels["mount"]
            for metric in result.metrics
            if metric.name == "disk_used_percent"
        }
        self.assertEqual(mountpoints, {"/", "/srv/data", "/mnt/my disk"})
        self.assertIn("/mnt/my disk: 30.0%", "\n".join(result.details))

    def test_disk_warning_and_critical(self) -> None:
        self.write_proc("mounts", MOUNTS)
        warning = self.run_check(
            sizes={"/": statvfs(free=15 * 1024**3, available=15 * 1024**3)}
        )
        self.assertEqual(warning.status.value, "warn")
        self.assertIn("/ at 85%", warning.summary)

        critical = self.run_check(
            sizes={"/": statvfs(free=5 * 1024**3, available=5 * 1024**3)}
        )
        self.assertEqual(critical.status.value, "crit")
        self.assertIn("/ at 95%", critical.summary)

    def test_inode_warning_and_critical(self) -> None:
        self.write_proc("mounts", "/dev/sda1 / ext4 rw 0 0\n")
        warning = self.run_check(
            sizes={
                "/": statvfs(
                    files=1_000_000, files_free=100_000, files_available=100_000
                )
            }
        )
        self.assertEqual(warning.status.value, "warn")
        self.assertIn("inodes at 90%", warning.summary)

        critical = self.run_check(
            sizes={
                "/": statvfs(files=1_000_000, files_free=50_000, files_available=50_000)
            }
        )
        self.assertEqual(critical.status.value, "crit")
        self.assertIn("inodes at 95%", critical.summary)

    def test_ignore_mounts(self) -> None:
        self.write_proc("mounts", MOUNTS)
        config = Config(storage=StorageConfig(ignore_mounts=["/srv/*", "/mnt/*"]))
        result = self.run_check(config)
        self.assertEqual(len(result.metrics), 4)  # four space metrics for /
        self.assertIn("1 mount", result.summary)

    def test_only_mounts(self) -> None:
        self.write_proc("mounts", MOUNTS)
        config = Config(storage=StorageConfig(only_mounts=["/srv/*"]))
        result = self.run_check(config)
        mounts = {
            metric.labels["mount"]
            for metric in result.metrics
            if metric.name == "disk_used_percent"
        }
        self.assertEqual(mounts, {"/srv/data"})

    def test_ignore_filesystems(self) -> None:
        self.write_proc(
            "mounts",
            "/dev/sda1 / ext4 rw 0 0\nnas:/data /nas nfs4 rw 0 0\n",
        )
        config = Config(storage=StorageConfig(ignore_filesystems=["nfs4"]))
        result = self.run_check(config)
        mounts = {
            metric.labels["mount"]
            for metric in result.metrics
            if metric.name == "disk_used_percent"
        }
        self.assertEqual(mounts, {"/"})

    def test_statvfs_permission_error_is_skipped(self) -> None:
        self.write_proc("mounts", MOUNTS)
        result = self.run_check(
            errors={"/srv/data": PermissionError(errno.EACCES, "Permission denied")}
        )
        self.assertEqual(result.status.value, "ok")
        self.assertIn("skipped (permission denied)", "\n".join(result.details))
        self.assertIn("2 mounts", result.summary)

    def test_other_statvfs_errors_are_warnings(self) -> None:
        self.write_proc("mounts", MOUNTS)
        result = self.run_check(errors={"/srv/data": OSError(errno.EIO, "I/O error")})
        self.assertEqual(result.status.value, "warn")
        self.assertIn("1 uninspectable", result.summary)
        self.assertIn(
            "/srv/data: cannot inspect (I/O error)", "\n".join(result.details)
        )

    def test_all_mounts_filtered_is_skipped(self) -> None:
        self.write_proc("mounts", MOUNTS)
        config = Config(storage=StorageConfig(ignore_mounts=["*"]))
        result = self.run_check(config)
        self.assertEqual(result.status.value, "skip")
        self.assertIn("no filesystems", result.summary)

    def test_pseudo_filesystems_only_is_skipped(self) -> None:
        self.write_proc("mounts", "proc /proc proc rw 0 0\ntmpfs /run tmpfs rw 0 0\n")
        result = self.run_check()
        self.assertEqual(result.status.value, "skip")

    def test_zero_block_filesystem_is_not_inspectable(self) -> None:
        self.write_proc("mounts", "/dev/sda1 / ext4 rw 0 0\n")
        result = self.run_check(sizes={"/": statvfs(total=0, free=0)})
        self.assertEqual(result.status.value, "error")
        self.assertIn("no filesystem could be inspected", result.summary)

    def test_metrics_carry_filesystem_labels(self) -> None:
        self.write_proc("mounts", "/dev/sda1 / ext4 rw 0 0\n")
        result = self.run_check()
        metric = next(
            item for item in result.metrics if item.name == "disk_used_percent"
        )
        self.assertEqual(metric.labels, {"mount": "/", "fstype": "ext4"})
        self.assertTrue(metric.help)


if __name__ == "__main__":
    unittest.main()
