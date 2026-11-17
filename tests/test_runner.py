from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from labcheck.runner import CommandResult, Runner


class CommandResultTest(unittest.TestCase):
    def test_ok_and_message(self) -> None:
        self.assertTrue(CommandResult(("x",), 0).ok)
        result = CommandResult(("x",), 1, stdout="", stderr="\n  boom  \nsecond")
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "boom")

    def test_message_falls_back_to_stdout(self) -> None:
        self.assertEqual(
            CommandResult(("x",), 1, stdout="from stdout").message, "from stdout"
        )
        self.assertEqual(CommandResult(("x",), 1).message, "no output")


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = Runner()

    def test_which_finds_python(self) -> None:
        self.assertIsNotNone(self.runner.which("python3"))

    def test_which_missing(self) -> None:
        self.assertIsNone(self.runner.which("labcheck-not-a-real-command"))

    def test_which_falls_back_to_sbin_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "labcheck-fake-daemon"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with (
                mock.patch("labcheck.runner.shutil.which", return_value=None),
                mock.patch("labcheck.runner.FALLBACK_DIRECTORIES", (directory,)),
            ):
                self.assertEqual(
                    self.runner.which("labcheck-fake-daemon"), str(executable)
                )

    def test_which_fallback_requires_an_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "not-executable"
            tool.write_text("", encoding="utf-8")
            with (
                mock.patch("labcheck.runner.shutil.which", return_value=None),
                mock.patch("labcheck.runner.FALLBACK_DIRECTORIES", (directory,)),
            ):
                self.assertIsNone(self.runner.which("not-executable"))

    def test_runs_without_shell_expansion(self) -> None:
        result = self.runner.run(["python3", "-c", "print('hello')"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")
        self.assertTrue(result.found)

    def test_nonzero_exit(self) -> None:
        result = self.runner.run(["python3", "-c", "raise SystemExit(7)"])
        self.assertEqual(result.returncode, 7)
        self.assertFalse(result.ok)

    def test_missing_command_is_reported_not_raised(self) -> None:
        result = self.runner.run(["labcheck-not-a-real-command"])
        self.assertEqual(result.returncode, 127)
        self.assertFalse(result.found)

    def test_timeout(self) -> None:
        result = self.runner.run(
            ["python3", "-c", "import time; time.sleep(2)"], timeout=0.05
        )
        self.assertEqual(result.returncode, 124)
        self.assertTrue(result.timed_out)


if __name__ == "__main__":
    unittest.main()
