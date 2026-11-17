from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from labcheck.formatters import format_json, format_prometheus, format_text
from labcheck.model import CheckResult, Metric, Report, Status


def report(*results: CheckResult, config_path: str | None = None) -> Report:
    return Report(
        version="0.1.0",
        hostname="homelab",
        generated_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        results=list(results),
        duration_ms=123.456,
        config_path=config_path,
    )


def result(
    name: str = "system",
    status: Status = Status.OK,
    summary: str = "all good",
    *,
    title: str | None = None,
    details: list[str] | None = None,
    metrics: list[Metric] | None = None,
) -> CheckResult:
    return CheckResult(
        name=name,
        title=title or name.title(),
        status=status,
        summary=summary,
        details=details or [],
        metrics=metrics or [],
    )


class TextFormatterTest(unittest.TestCase):
    def test_basic_layout(self) -> None:
        text = format_text(
            report(
                result("system", Status.OK, "load 0.3"),
                result("storage", Status.WARN, "/ at 82%"),
            )
        )
        self.assertIn("labcheck 0.1.0", text)
        self.assertIn("homelab", text)
        self.assertIn("2026-06-01 12:00:00 UTC", text)
        self.assertIn("  OK    System", text)
        self.assertIn("  WARN  Storage", text)
        self.assertIn(" / at 82%", text)
        self.assertIn("Summary: 1 warning, 1 ok  (0.12s)", text)
        self.assertTrue(text.endswith("\n"))

    def test_details_only_when_verbose(self) -> None:
        check = result(details=["memory: 50% used"])
        plain = format_text(report(check))
        verbose = format_text(report(check), verbose=True)
        self.assertNotIn("memory: 50% used", plain)
        self.assertIn("\u2022 memory: 50% used", verbose)

    def test_multiline_details_are_indented(self) -> None:
        check = result(details=["first\nsecond"])
        verbose = format_text(report(check), verbose=True)
        self.assertIn("\u2022 first", verbose)
        self.assertIn("        second", verbose)

    def test_colour(self) -> None:
        check = result(status=Status.CRIT)
        self.assertNotIn("\x1b[", format_text(report(check)))
        colored = format_text(report(check), color=True)
        self.assertIn("\x1b[1;31m", colored)
        self.assertIn("\x1b[0m", colored)

    def test_empty_report(self) -> None:
        text = format_text(report())
        self.assertIn("no checks ran", text)


class JsonFormatterTest(unittest.TestCase):
    def test_structure(self) -> None:
        payload = json.loads(
            format_json(
                report(
                    result(
                        "storage",
                        Status.CRIT,
                        "/ at 95%",
                        details=["/: 95%"],
                        metrics=[
                            Metric(
                                "disk_used_percent",
                                95.0,
                                {"mount": "/", "fstype": "ext4"},
                                "Filesystem space used",
                            )
                        ],
                    ),
                    config_path="/etc/labcheck.toml",
                )
            )
        )
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["version"], "0.1.0")
        self.assertEqual(payload["hostname"], "homelab")
        self.assertEqual(payload["status"], "crit")
        self.assertEqual(payload["exit_code"], 2)
        self.assertEqual(payload["config_path"], "/etc/labcheck.toml")
        self.assertEqual(payload["counts"]["crit"], 1)
        check = payload["checks"][0]
        self.assertEqual(check["name"], "storage")
        self.assertEqual(check["details"], ["/: 95%"])
        metric = check["metrics"][0]
        self.assertEqual(metric["labels"], {"mount": "/", "fstype": "ext4"})
        self.assertEqual(metric["value"], 95.0)
        self.assertEqual(metric["help"], "Filesystem space used")

    def test_unicode_is_preserved(self) -> None:
        payload = json.loads(format_json(report(result(summary="temp 52\u00b0C"))))
        self.assertEqual(payload["checks"][0]["summary"], "temp 52\u00b0C")

    def test_empty_report(self) -> None:
        payload = json.loads(format_json(report()))
        self.assertEqual(payload["status"], "skip")
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["checks"], [])


class PrometheusFormatterTest(unittest.TestCase):
    def test_status_and_check_metrics(self) -> None:
        text = format_prometheus(
            report(
                result(
                    "storage",
                    Status.CRIT,
                    metrics=[
                        Metric(
                            "disk_used_percent",
                            95.0,
                            {"mount": "/", "fstype": "ext4"},
                            "Filesystem space used",
                        )
                    ],
                ),
                result("clock", Status.SKIP),
            )
        )
        self.assertIn("labcheck_overall_status 2", text)
        self.assertIn('labcheck_check_status{check="storage"} 2', text)
        self.assertIn('labcheck_check_status{check="clock"} 4', text)
        self.assertIn('labcheck_info{hostname="homelab",version="0.1.0"} 1', text)
        self.assertIn('labcheck_disk_used_percent{fstype="ext4",mount="/"} 95', text)
        self.assertIn("# HELP labcheck_disk_used_percent Filesystem space used", text)
        self.assertIn("# TYPE labcheck_disk_used_percent gauge", text)
        self.assertIn("labcheck_duration_seconds 0.123", text)
        self.assertIn("labcheck_last_run_timestamp_seconds", text)

    def test_each_metric_family_help_is_emitted_once(self) -> None:
        text = format_prometheus(
            report(
                result(
                    "storage",
                    metrics=[
                        Metric("disk_used_percent", 10, {"mount": "/"}),
                        Metric("disk_used_percent", 20, {"mount": "/srv"}),
                    ],
                )
            )
        )
        self.assertEqual(text.count("# HELP labcheck_disk_used_percent"), 1)
        self.assertEqual(text.count("# TYPE labcheck_disk_used_percent"), 1)
        self.assertIn('labcheck_disk_used_percent{mount="/"} 10', text)
        self.assertIn('labcheck_disk_used_percent{mount="/srv"} 20', text)

    def test_labels_are_escaped(self) -> None:
        text = format_prometheus(
            report(
                result(
                    "storage",
                    metrics=[
                        Metric(
                            "disk_used_percent",
                            50,
                            {"mount": '/mnt/back\\slash"quote\nline'},
                        )
                    ],
                )
            )
        )
        self.assertIn(
            'mount="/mnt/back\\\\slash\\"quote\\nline"',
            text,
        )

    def test_duplicate_series_are_dropped(self) -> None:
        text = format_prometheus(
            report(
                result(
                    "x",
                    metrics=[
                        Metric("duplicate", 1, {"a": "b"}),
                        Metric("duplicate", 2, {"a": "b"}),
                    ],
                )
            )
        )
        self.assertIn('labcheck_duplicate{a="b"} 1', text)
        self.assertNotIn('labcheck_duplicate{a="b"} 2', text)

    def test_special_values(self) -> None:
        text = format_prometheus(
            report(
                result(
                    "x",
                    metrics=[
                        Metric("nan_value", float("nan")),
                        Metric("pos_inf", float("inf")),
                        Metric("neg_inf", float("-inf")),
                        Metric("whole", 3.0),
                        Metric("fraction", 3.25),
                    ],
                )
            )
        )
        self.assertIn("labcheck_nan_value NaN", text)
        self.assertIn("labcheck_pos_inf +Inf", text)
        self.assertIn("labcheck_neg_inf -Inf", text)
        self.assertIn("labcheck_whole 3", text)
        self.assertIn("labcheck_fraction 3.25", text)

    def test_empty_report(self) -> None:
        text = format_prometheus(report())
        self.assertIn("labcheck_overall_status 4", text)
        self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
