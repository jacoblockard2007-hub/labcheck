from __future__ import annotations

import unittest

from labcheck.checks import clock
from tests.helpers import FakeRunner, LabcheckTestCase, response

COMMAND = "timedatectl show -p NTPSynchronized --value"


class ClockCheckTest(LabcheckTestCase):
    def runner(
        self, stdout: str = "yes\n", returncode: int = 0, stderr: str = ""
    ) -> FakeRunner:
        return FakeRunner(
            available=["timedatectl"],
            responses={COMMAND: response(stdout, returncode, stderr)},
        )

    def test_missing_timedatectl_is_skipped(self) -> None:
        result = clock.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("timedatectl not available", result.summary)

    def test_synchronized(self) -> None:
        result = clock.run(self.context(runner=self.runner("yes\n")))
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(result.summary, "NTP synchronized")
        self.assertEqual(result.metrics[0].value, 1)

    def test_not_synchronized_is_a_warning(self) -> None:
        result = clock.run(self.context(runner=self.runner("no\n")))
        self.assertEqual(result.status.value, "warn")
        self.assertIn("not synchronized", result.summary)
        self.assertEqual(result.metrics[0].value, 0)

    def test_systemd_unreachable_is_skipped(self) -> None:
        result = clock.run(
            self.context(
                runner=self.runner(
                    returncode=1,
                    stderr="Failed to connect to bus: No such file or directory",
                )
            )
        )
        self.assertEqual(result.status.value, "skip")
        self.assertIn("not reachable", result.summary)

    def test_other_failure_is_an_error(self) -> None:
        result = clock.run(
            self.context(runner=self.runner(returncode=1, stderr="unexpected"))
        )
        self.assertEqual(result.status.value, "error")
        self.assertIn("timedatectl failed", result.summary)

    def test_unexpected_output_is_an_error(self) -> None:
        result = clock.run(self.context(runner=self.runner("maybe\n")))
        self.assertEqual(result.status.value, "error")
        self.assertIn("unexpected", result.summary)


if __name__ == "__main__":
    unittest.main()
