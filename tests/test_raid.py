from __future__ import annotations

import unittest

from labcheck.checks import raid
from tests.helpers import LabcheckTestCase

HEALTHY = """\
Personalities : [raid1] [raid5]
md0 : active raid1 sda1[0] sdb1[1]
      976630336 blocks super 1.2 [2/2] [UU]

md1 : active raid5 sdc1[0] sdd1[1] sde1[2]
      1953262592 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/3] [UUU]

unused devices: <none>
"""

DEGRADED = """\
Personalities : [raid1]
md0 : active raid1 sda1[0]
      976630336 blocks super 1.2 [2/1] [U_]

unused devices: <none>
"""

RESYNC = """\
Personalities : [raid1]
md0 : active raid1 sda1[0] sdb1[1]
      976630336 blocks super 1.2 [2/2] [UU]
      [=>...................]  resync =  5.2% (50790400/976630336) finish=120.3min speed=100000K/sec

unused devices: <none>
"""


class RaidCheckTest(LabcheckTestCase):
    def test_missing_mdstat_is_skipped(self) -> None:
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("not available", result.details[0])

    def test_no_arrays_is_skipped(self) -> None:
        self.write_proc("mdstat", "Personalities : [raid1]\nunused devices: <none>\n")
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("no software RAID arrays", result.summary)

    def test_healthy_arrays(self) -> None:
        self.write_proc("mdstat", HEALTHY)
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "ok")
        self.assertIn("2 arrays healthy", result.summary)
        self.assertIn("md0", result.summary)
        self.assertIn("md1", result.summary)
        self.assertTrue(
            any("md0 (raid1), 2/2 disks" in line for line in result.details)
        )
        degraded = {
            metric.labels["device"]: metric.value
            for metric in result.metrics
            if metric.name == "md_degraded"
        }
        self.assertEqual(degraded, {"md0": 0, "md1": 0})

    def test_degraded_array_is_critical(self) -> None:
        self.write_proc("mdstat", DEGRADED)
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "crit")
        self.assertIn("md0 degraded", result.summary)
        self.assertIn("1 of 2 disks active", "\n".join(result.details))
        metric = next(item for item in result.metrics if item.name == "md_degraded")
        self.assertEqual(metric.value, 1)

    def test_resync_is_a_warning(self) -> None:
        self.write_proc("mdstat", RESYNC)
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "warn")
        self.assertIn("md0 resync 5%", result.summary)
        progress = next(
            item for item in result.metrics if item.name == "md_resync_percent"
        )
        self.assertEqual(progress.value, 5.2)

    def test_inactive_array_is_critical(self) -> None:
        self.write_proc(
            "mdstat",
            "Personalities : [raid1]\n"
            "md0 : inactive sdb1[1] sda1[0]\n"
            "      976630336 blocks super 1.2\n",
        )
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "crit")
        self.assertIn("md0 inactive", result.summary)
        self.assertIn("array is inactive", "\n".join(result.details))

    def test_consistency_check_is_not_a_problem(self) -> None:
        self.write_proc(
            "mdstat",
            "md0 : active raid1 sda1[0] sdb1[1]\n"
            "      100 blocks super 1.2 [2/2] [UU]\n"
            "      [====>....]  check = 75.0% (75/100) finish=1.0min\n",
        )
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "ok")
        self.assertIn("consistency check", "\n".join(result.details))

    def test_degraded_and_resyncing_is_critical(self) -> None:
        self.write_proc(
            "mdstat",
            "md0 : active raid1 sda1[0]\n"
            "      100 blocks super 1.2 [2/1] [U_]\n"
            "      [=>....]  recovery =  10.0% (10/100) finish=1.0min\n",
        )
        result = raid.run(self.context())
        self.assertEqual(result.status.value, "crit")
        self.assertIn("md0 degraded", result.summary)
        self.assertIn("recovery at 10.0%", "\n".join(result.details))


if __name__ == "__main__":
    unittest.main()
