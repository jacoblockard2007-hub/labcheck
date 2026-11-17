from __future__ import annotations

import unittest
from datetime import UTC, datetime

from labcheck.model import (
    EXIT_CODE,
    SEVERITY,
    CheckResult,
    Metric,
    Report,
    Status,
    summarize_counts,
    worse,
)


def result(status: Status, name: str = "x") -> CheckResult:
    return CheckResult(name=name, title=name.title(), status=status, summary="summary")


def report(*results: CheckResult) -> Report:
    return Report(
        version="0.1.0",
        hostname="host",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        results=list(results),
        duration_ms=1.0,
    )


class SeverityTest(unittest.TestCase):
    def test_worse(self) -> None:
        self.assertIs(worse(Status.OK, Status.WARN), Status.WARN)
        self.assertIs(worse(Status.CRIT, Status.WARN), Status.CRIT)
        self.assertIs(worse(Status.ERROR, Status.CRIT), Status.ERROR)
        self.assertIs(worse(Status.SKIP, Status.OK), Status.OK)
        self.assertIs(worse(Status.CRIT, Status.CRIT), Status.CRIT)

    def test_skip_has_ok_severity_but_own_exit_code(self) -> None:
        self.assertEqual(SEVERITY[Status.SKIP], SEVERITY[Status.OK])
        self.assertEqual(EXIT_CODE[Status.SKIP], 0)


class ReportTest(unittest.TestCase):
    def test_overall_status_uses_worst_check(self) -> None:
        self.assertIs(
            report(result(Status.OK), result(Status.WARN), result(Status.CRIT)).status,
            Status.CRIT,
        )
        self.assertIs(
            report(result(Status.WARN), result(Status.ERROR)).status, Status.ERROR
        )

    def test_skipped_checks_are_ignored(self) -> None:
        self.assertIs(report(result(Status.SKIP), result(Status.OK)).status, Status.OK)
        self.assertIs(report(result(Status.SKIP)).status, Status.SKIP)
        self.assertIs(report().status, Status.SKIP)

    def test_exit_codes(self) -> None:
        cases = {
            Status.OK: 0,
            Status.SKIP: 0,
            Status.WARN: 1,
            Status.CRIT: 2,
            Status.ERROR: 3,
        }
        for status, code in cases.items():
            with self.subTest(status=status):
                self.assertEqual(report(result(status)).exit_code, code)

    def test_counts(self) -> None:
        counts = report(
            result(Status.OK),
            result(Status.OK),
            result(Status.WARN),
            result(Status.SKIP),
        ).counts()
        self.assertEqual(counts, {"ok": 2, "warn": 1, "crit": 0, "error": 0, "skip": 1})


class SummaryTest(unittest.TestCase):
    def test_summary_order_and_plurals(self) -> None:
        summary = summarize_counts(
            [
                result(Status.ERROR),
                result(Status.CRIT),
                result(Status.CRIT),
                result(Status.WARN),
                result(Status.OK),
                result(Status.SKIP),
            ]
        )
        self.assertEqual(summary, "1 error, 2 critical, 1 warning, 1 ok, 1 skipped")

    def test_singulars(self) -> None:
        self.assertEqual(summarize_counts([result(Status.CRIT)]), "1 critical")
        self.assertEqual(summarize_counts([result(Status.OK)]), "1 ok")

    def test_empty(self) -> None:
        self.assertEqual(summarize_counts([]), "no checks ran")


class MetricTest(unittest.TestCase):
    def test_labels_default_to_independent_dicts(self) -> None:
        first = Metric("a", 1.0)
        second = Metric("b", 2.0)
        self.assertEqual(first.labels, {})
        self.assertIsNot(first.labels, second.labels)


if __name__ == "__main__":
    unittest.main()
