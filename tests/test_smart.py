from __future__ import annotations

import json
import unittest

from labcheck.checks import smart
from labcheck.config import Config, SmartConfig
from tests.helpers import FakeRunner, LabcheckTestCase, response


class SmartCheckTest(LabcheckTestCase):
    def runner(self, responses=None) -> FakeRunner:
        return FakeRunner(available=["smartctl"], responses=responses or {})

    def config(self, *devices: str) -> Config:
        return Config(smart=SmartConfig(enabled=True, devices=list(devices)))

    def test_no_devices_configured_is_skipped(self) -> None:
        result = smart.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("no devices configured", result.summary)

    def test_missing_smartctl_is_skipped(self) -> None:
        result = smart.run(self.context(config=self.config("/dev/sda")))
        self.assertEqual(result.status.value, "skip")
        self.assertIn("smartctl not installed", result.summary)

    def test_passing_device(self) -> None:
        output = json.dumps(
            {"smart_status": {"passed": True}, "model_name": "Samsung SSD"}
        )
        runner = self.runner({"smartctl -H -j /dev/sda": response(output)})
        result = smart.run(self.context(config=self.config("/dev/sda"), runner=runner))
        self.assertEqual(result.status.value, "ok")
        self.assertIn("1 device passed", result.summary)
        self.assertIn("Samsung SSD", result.details[0])
        self.assertEqual(result.metrics[0].value, 1)

    def test_failing_device(self) -> None:
        output = json.dumps({"smart_status": {"passed": False}})
        runner = self.runner({"smartctl -H -j /dev/sda": response(output)})
        result = smart.run(self.context(config=self.config("/dev/sda"), runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("FAILING: /dev/sda", result.summary)
        self.assertIn("/dev/sda: FAILED", result.details[0])
        self.assertEqual(result.metrics[0].value, 0)

    def test_multiple_devices(self) -> None:
        responses = {
            "smartctl -H -j /dev/sda": response(
                json.dumps({"smart_status": {"passed": True}})
            ),
            "smartctl -H -j /dev/sdb": response(
                json.dumps({"smart_status": {"passed": True}})
            ),
        }
        result = smart.run(
            self.context(
                config=self.config("/dev/sda", "/dev/sdb"),
                runner=self.runner(responses),
            )
        )
        self.assertEqual(result.status.value, "ok")
        self.assertIn("2 devices passed", result.summary)
        self.assertIn("(/dev/sda, /dev/sdb)", result.summary)

    def test_device_open_failure_is_an_error(self) -> None:
        runner = self.runner(
            {
                "smartctl -H -j /dev/sda": response(
                    returncode=2, stderr="Smartctl open device failed"
                )
            }
        )
        result = smart.run(self.context(config=self.config("/dev/sda"), runner=runner))
        self.assertEqual(result.status.value, "error")
        self.assertIn("health unknown", result.summary)
        self.assertIn("cannot open device", result.details[0])

    def test_no_health_verdict_is_a_warning(self) -> None:
        runner = self.runner({"smartctl -H -j /dev/sda": response("")})
        result = smart.run(self.context(config=self.config("/dev/sda"), runner=runner))
        self.assertEqual(result.status.value, "warn")
        self.assertIn("health not reported", result.details[0])

    def test_json_message_is_used_for_unknown_health(self) -> None:
        output = json.dumps(
            {
                "smartctl": {
                    "messages": [{"string": "Unsupported USB bridge"}],
                }
            }
        )
        runner = self.runner({"smartctl -H -j /dev/sda": response(output, 4)})
        result = smart.run(self.context(config=self.config("/dev/sda"), runner=runner))
        self.assertEqual(result.status.value, "warn")
        self.assertIn("Unsupported USB bridge", result.details[0])

    def test_passed_verdict_wins_over_nonzero_return_code(self) -> None:
        output = json.dumps({"smart_status": {"passed": True}})
        runner = self.runner({"smartctl -H -j /dev/sda": response(output, 8)})
        result = smart.run(self.context(config=self.config("/dev/sda"), runner=runner))
        self.assertEqual(result.status.value, "ok")

    def test_duplicate_devices_are_checked_once(self) -> None:
        output = json.dumps({"smart_status": {"passed": True}})
        runner = self.runner({"smartctl -H -j /dev/sda": response(output)})
        result = smart.run(
            self.context(config=self.config("/dev/sda", "/dev/sda"), runner=runner)
        )
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("1 device passed", result.summary)


if __name__ == "__main__":
    unittest.main()
