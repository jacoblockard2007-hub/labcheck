from __future__ import annotations

import unittest
from unittest import mock

from labcheck.checks import system
from labcheck.config import Config, SystemConfig
from tests.helpers import LabcheckTestCase

GB = 1024**3


def meminfo(
    total: int = 8 * GB,
    available: int = 6 * GB,
    swap_total: int = 1024 * 1024,  # 1 GiB, expressed in KiB
    swap_free: int = 900 * 1024,  # ~879 MiB
    include_available: bool = True,
) -> str:
    lines = [f"MemTotal: {total // 1024} kB"]
    if include_available:
        lines.append(f"MemAvailable: {available // 1024} kB")
    else:
        lines.extend(
            [
                f"MemFree: {GB // 1024} kB",
                f"Buffers: {GB // 2048} kB",
                f"Cached: {GB // 2048} kB",
            ]
        )
    lines.append(f"SwapTotal: {swap_total} kB")
    lines.append(f"SwapFree: {swap_free} kB")
    return "\n".join(lines) + "\n"


class SystemCheckTest(LabcheckTestCase):
    def run_check(self, config: Config | None = None):
        with mock.patch("labcheck.checks.system.os.cpu_count", return_value=4):
            return system.run(self.context(config=config))

    def test_healthy_system(self) -> None:
        self.write_proc("loadavg", "0.50 0.40 0.30 1/100 1234\n")
        self.write_proc("meminfo", meminfo())
        self.write_proc("uptime", "90000.00 120000.00\n")
        result = self.run_check()
        self.assertEqual(result.status.value, "ok")
        self.assertIn("load 0.50 (4 cores)", result.summary)
        self.assertIn("memory 25%", result.summary)
        self.assertIn("swap 12%", result.summary)
        self.assertIn("up 1d 1h", result.summary)
        names = {metric.name for metric in result.metrics}
        self.assertIn("load1", names)
        self.assertIn("memory_used_percent", names)
        self.assertIn("swap_used_percent", names)
        self.assertIn("uptime_seconds", names)
        self.assertNotIn("temperature_celsius", names)

    def test_memory_warning_and_critical(self) -> None:
        self.write_proc("loadavg", "0.1 0.1 0.1 1/1 1\n")
        self.write_proc("uptime", "10 10\n")
        self.write_proc("meminfo", meminfo(available=int(0.12 * 8 * GB)))
        warn = self.run_check()
        self.assertEqual(warn.status.value, "warn")
        self.write_proc("meminfo", meminfo(available=int(0.03 * 8 * GB)))
        crit = self.run_check()
        self.assertEqual(crit.status.value, "crit")

    def test_load_per_core_warning_and_critical(self) -> None:
        self.write_proc("meminfo", meminfo())
        self.write_proc("uptime", "10 10\n")
        self.write_proc("loadavg", "7.0 1.0 1.0 1/1 1\n")
        self.assertEqual(self.run_check().status.value, "warn")
        self.write_proc("loadavg", "13.0 1.0 1.0 1/1 1\n")
        self.assertEqual(self.run_check().status.value, "crit")

    def test_swap_thresholds(self) -> None:
        self.write_proc("loadavg", "0.1 0.1 0.1 1/1 1\n")
        self.write_proc("uptime", "10 10\n")
        self.write_proc(
            "meminfo",
            meminfo(swap_total=1024 * 1024, swap_free=400 * 1024),
        )
        self.assertEqual(self.run_check().status.value, "warn")
        self.write_proc(
            "meminfo",
            meminfo(swap_total=1024 * 1024, swap_free=50 * 1024),
        )
        self.assertEqual(self.run_check().status.value, "crit")

    def test_check_swap_false_suppresses_swap(self) -> None:
        self.write_proc("loadavg", "0.1 0.1 0.1 1/1 1\n")
        self.write_proc("uptime", "10 10\n")
        self.write_proc("meminfo", meminfo(swap_total=1024 * 1024, swap_free=10 * 1024))
        config = Config(system=SystemConfig(check_swap=False))
        result = self.run_check(config)
        self.assertEqual(result.status.value, "ok")
        self.assertNotIn("swap", result.summary)
        self.assertNotIn(
            "swap_used_percent", {metric.name for metric in result.metrics}
        )

    def test_temperature_uses_hottest_sensor(self) -> None:
        self.write_proc("loadavg", "0.1 0.1 0.1 1/1 1\n")
        self.write_proc("meminfo", meminfo())
        self.write_proc("uptime", "10 10\n")
        self.write_sys("class/thermal/thermal_zone0/temp", "76000\n")
        self.write_sys("class/thermal/thermal_zone1/temp", "40000\n")
        self.write_sys("class/hwmon/hwmon0/temp1_input", "50000\n")
        result = self.run_check()
        self.assertEqual(result.status.value, "warn")
        temperature = next(
            metric for metric in result.metrics if metric.name == "temperature_celsius"
        )
        self.assertEqual(temperature.value, 76.0)
        self.assertIn("temp 76\u00b0C", result.summary)

        self.write_sys("class/hwmon/hwmon0/temp2_input", "86000\n")
        self.assertEqual(self.run_check().status.value, "crit")

    def test_invalid_temperature_values_are_ignored(self) -> None:
        self.write_proc("loadavg", "0.1 0.1 0.1 1/1 1\n")
        self.write_proc("meminfo", meminfo())
        self.write_sys("class/thermal/thermal_zone0/temp", "nonsense\n")
        self.write_sys("class/thermal/thermal_zone1/temp", "0\n")
        result = self.run_check()
        self.assertEqual(result.status.value, "ok")
        self.assertNotIn(
            "temperature_celsius", {metric.name for metric in result.metrics}
        )

    def test_missing_proc_files_is_an_error(self) -> None:
        result = self.run_check()
        self.assertEqual(result.status.value, "error")
        self.assertIn("load unreadable", result.summary)
        self.assertIn("cannot read /proc/loadavg", result.details)

    def test_missing_meminfo_is_an_error(self) -> None:
        self.write_proc("loadavg", "0.1 0.1 0.1 1/1 1\n")
        result = self.run_check()
        self.assertEqual(result.status.value, "error")
        self.assertIn("memory unreadable", result.summary)

    def test_malformed_loadavg_is_an_error(self) -> None:
        self.write_proc("loadavg", "not numbers\n")
        self.write_proc("meminfo", meminfo())
        result = self.run_check()
        self.assertEqual(result.status.value, "error")
        self.assertIn("load unreadable", result.summary)

    def test_memavailable_fallback(self) -> None:
        self.write_proc("loadavg", "0.1 0.1 0.1 1/1 1\n")
        self.write_proc("uptime", "10 10\n")
        self.write_proc("meminfo", meminfo(include_available=False))
        result = self.run_check()
        self.assertEqual(result.status.value, "ok")
        self.assertIn("memory 75%", result.summary)


if __name__ == "__main__":
    unittest.main()
