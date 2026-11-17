from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from labcheck.util import human_bytes, human_duration, percent, read_text, truncate


class HumanBytesTest(unittest.TestCase):
    def test_units(self) -> None:
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(512), "512 B")
        self.assertEqual(human_bytes(1024), "1.0 KiB")
        self.assertEqual(human_bytes(1536), "1.5 KiB")
        self.assertEqual(human_bytes(5 * 1024**3), "5.0 GiB")
        self.assertEqual(human_bytes(2 * 1024**4), "2.0 TiB")

    def test_negative_and_large(self) -> None:
        self.assertEqual(human_bytes(-1024), "-1.0 KiB")
        self.assertTrue(human_bytes(1024**6).endswith("PiB"))


class HumanDurationTest(unittest.TestCase):
    def test_formats(self) -> None:
        self.assertEqual(human_duration(0), "0s")
        self.assertEqual(human_duration(42), "42s")
        self.assertEqual(human_duration(90), "1m 30s")
        self.assertEqual(human_duration(600), "10m")
        self.assertEqual(human_duration(3600), "1h")
        self.assertEqual(human_duration(3900), "1h 05m")
        self.assertEqual(human_duration(86400), "1d")
        self.assertEqual(human_duration(90000), "1d 1h")
        self.assertEqual(human_duration(-10), "0s")


class PercentTest(unittest.TestCase):
    def test_percent(self) -> None:
        self.assertEqual(percent(50, 100), 50.0)
        self.assertEqual(percent(1, 0), 0.0)
        self.assertEqual(percent(0, 0), 0.0)


class ReadTextTest(unittest.TestCase):
    def test_reads_and_handles_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.txt"
            path.write_text("hello", encoding="utf-8")
            self.assertEqual(read_text(path), "hello")
            self.assertIsNone(read_text(Path(directory) / "missing"))
            self.assertEqual(read_text(path, limit=2), "he")


class TruncateTest(unittest.TestCase):
    def test_collapses_whitespace(self) -> None:
        self.assertEqual(truncate("  a \n b  ", 10), "a b")

    def test_shortens_with_ellipsis(self) -> None:
        result = truncate("abcdefghij", 5)
        self.assertEqual(len(result), 5)
        self.assertTrue(result.endswith("\u2026"))
        self.assertEqual(truncate("abc", 5), "abc")


if __name__ == "__main__":
    unittest.main()
