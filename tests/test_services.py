from __future__ import annotations

import unittest

from labcheck.checks import services
from labcheck.config import Config, SystemdConfig
from tests.helpers import FakeRunner, LabcheckTestCase, response

FAILED_OUTPUT = """\
foo.service loaded failed failed Foo daemon
bar.service loaded failed failed Bar daemon
"""


class ServicesCheckTest(LabcheckTestCase):
    def runner(self, **responses) -> FakeRunner:
        return FakeRunner(available=["systemctl"], responses=responses)

    def systemctl_failed(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        return response(stdout=stdout, returncode=returncode, stderr=stderr)

    def test_missing_systemctl_is_skipped(self) -> None:
        result = services.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("not available", result.summary)

    def test_no_failed_units(self) -> None:
        runner = self.runner(**{"systemctl --failed": self.systemctl_failed()})
        result = services.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(result.summary, "no failed units")
        self.assertEqual(
            runner.calls,
            [
                (
                    "systemctl",
                    "--failed",
                    "--no-legend",
                    "--plain",
                    "--no-pager",
                )
            ],
        )

    def test_failed_units_are_critical(self) -> None:
        runner = self.runner(
            **{"systemctl --failed": self.systemctl_failed(FAILED_OUTPUT)}
        )
        result = services.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("2 failed units", result.summary)
        self.assertIn("foo.service: failed (Foo daemon)", result.details)
        self.assertIn("bar.service", result.summary)

    def test_failed_units_can_be_allowed(self) -> None:
        runner = self.runner(
            **{"systemctl --failed": self.systemctl_failed(FAILED_OUTPUT)}
        )
        config = Config(systemd=SystemdConfig(allow_failed=["foo.*"]))
        result = services.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("1 failed unit: bar.service", result.summary)
        self.assertIn("foo.service: failed, allowed", "\n".join(result.details))

    def test_all_failed_units_allowed(self) -> None:
        runner = self.runner(
            **{"systemctl --failed": self.systemctl_failed(FAILED_OUTPUT)}
        )
        config = Config(systemd=SystemdConfig(allow_failed=["*"]))
        result = services.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(result.summary, "no failed units")

    def test_required_services_active(self) -> None:
        runner = self.runner(
            **{
                "systemctl --failed": self.systemctl_failed(),
                "systemctl is-active ssh.service": response("active\n"),
                "systemctl is-active smbd.service": response("active\n"),
            }
        )
        config = Config(
            systemd=SystemdConfig(required_services=["ssh.service", "smbd.service"])
        )
        result = services.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "ok")
        self.assertIn("2 required services active", result.summary)
        states = {
            metric.labels["service"]: metric.value
            for metric in result.metrics
            if metric.name == "service_active"
        }
        self.assertEqual(states, {"ssh.service": 1, "smbd.service": 1})

    def test_required_service_inactive_is_critical(self) -> None:
        runner = self.runner(
            **{
                "systemctl --failed": self.systemctl_failed(),
                "systemctl is-active ssh.service": response("inactive\n", 3),
            }
        )
        config = Config(systemd=SystemdConfig(required_services=["ssh.service"]))
        result = services.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn(
            "required service not running: ssh.service (inactive)", result.summary
        )

    def test_required_service_activating_is_not_active(self) -> None:
        runner = self.runner(
            **{
                "systemctl --failed": self.systemctl_failed(),
                "systemctl is-active app.service": response("activating\n", 3),
            }
        )
        config = Config(systemd=SystemdConfig(required_services=["app.service"]))
        result = services.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("app.service (activating)", result.summary)

    def test_failed_units_and_missing_required_are_both_reported(self) -> None:
        runner = self.runner(
            **{
                "systemctl --failed": self.systemctl_failed(FAILED_OUTPUT),
                "systemctl is-active ssh.service": response("inactive\n", 3),
            }
        )
        config = Config(systemd=SystemdConfig(required_services=["ssh.service"]))
        result = services.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("foo.service", result.summary)
        self.assertNotIn("required service", result.summary)
        self.assertTrue(any("ssh.service: inactive" in line for line in result.details))

    def test_systemd_not_reachable_is_skipped(self) -> None:
        runner = self.runner(
            **{
                "systemctl --failed": self.systemctl_failed(
                    returncode=1,
                    stderr="System has not been booted with systemd as init system",
                )
            }
        )
        result = services.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "skip")
        self.assertIn("not reachable", result.summary)

    def test_other_systemctl_failure_is_an_error(self) -> None:
        runner = self.runner(
            **{
                "systemctl --failed": self.systemctl_failed(
                    returncode=1, stderr="some unexpected failure"
                )
            }
        )
        result = services.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "error")
        self.assertIn("systemctl --failed failed", result.summary)

    def test_header_line_is_ignored(self) -> None:
        runner = self.runner(
            **{
                "systemctl --failed": self.systemctl_failed(
                    "UNIT LOAD ACTIVE SUB DESCRIPTION\nfoo.service loaded failed failed Foo\n"
                )
            }
        )
        result = services.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("1 failed unit: foo.service", result.summary)


if __name__ == "__main__":
    unittest.main()
