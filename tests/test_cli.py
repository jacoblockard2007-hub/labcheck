from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from labcheck import cli
from labcheck.checks import CheckSpec
from tests.helpers import FakeRunner, response

CLOCK_COMMAND = "timedatectl show -p NTPSynchronized --value"


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="labcheck-cli-")
        self.temp = Path(self._temporary.name)
        # Keep tests independent of any labcheck config on the host.
        default_config = self.temp / "empty.toml"
        default_config.write_text("", encoding="utf-8")
        environment = mock.patch.dict(
            os.environ, {"LABCHECK_CONFIG": str(default_config)}
        )
        environment.start()
        self.addCleanup(environment.stop)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def clock_runner(
        self, stdout: str = "yes\n", returncode: int = 0, stderr: str = ""
    ) -> FakeRunner:
        return FakeRunner(
            available=["timedatectl"],
            responses={CLOCK_COMMAND: response(stdout, returncode, stderr)},
        )

    def invoke(self, argv: list[str], runner: FakeRunner | None = None):
        runner = runner or self.clock_runner()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch("labcheck.cli.Runner", return_value=runner),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def write_config(self, text: str) -> Path:
        path = self.temp / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_list_checks(self) -> None:
        code, stdout, _ = self.invoke(["--list-checks"])
        self.assertEqual(code, 0)
        self.assertIn("labcheck 0.1.0 checks", stdout)
        self.assertIn("system", stdout)
        self.assertIn("smart", stdout)
        self.assertIn("disabled", stdout)

    def test_list_checks_respects_config(self) -> None:
        config = self.write_config(
            "[system]\nenabled = false\n[smart]\nenabled = true\n"
        )
        code, stdout, _ = self.invoke(["--config", str(config), "--list-checks"])
        self.assertEqual(code, 0)
        line = next(line for line in stdout.splitlines() if "system" in line)
        self.assertIn("disabled", line)
        smart_line = next(line for line in stdout.splitlines() if "smart" in line)
        self.assertIn("enabled", smart_line)

    def test_version(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            cli.main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("labcheck 0.1.0", stdout.getvalue())

    def test_unknown_check_exits_three(self) -> None:
        code, _, stderr = self.invoke(["--only", "nope"])
        self.assertEqual(code, 3)
        self.assertIn("unknown check(s): nope", stderr)
        self.assertIn("valid checks", stderr)

    def test_missing_config_exits_three(self) -> None:
        code, _, stderr = self.invoke(["--config", str(self.temp / "missing.toml")])
        self.assertEqual(code, 3)
        self.assertIn("not found", stderr)

    def test_broken_config_exits_three(self) -> None:
        path = self.write_config("[system\n")
        code, _, stderr = self.invoke(["--config", str(path)])
        self.assertEqual(code, 3)
        self.assertIn(str(path), stderr)

    def test_config_warnings_go_to_stderr(self) -> None:
        path = self.write_config("[system]\nwarn_memory_percent = 80\nunknown = 1\n")
        code, _, stderr = self.invoke(
            ["--config", str(path), "--only", "clock", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertIn("unknown key 'unknown'", stderr)

    def test_json_output(self) -> None:
        code, stdout, _ = self.invoke(["--only", "clock", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["checks"][0]["name"], "clock")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["exit_code"], 0)

    def test_prometheus_output(self) -> None:
        code, stdout, _ = self.invoke(["--only", "clock", "--prometheus"])
        self.assertEqual(code, 0)
        self.assertIn("labcheck_overall_status 0", stdout)
        self.assertIn('labcheck_check_status{check="clock"} 0', stdout)

    def test_warning_exit_code(self) -> None:
        code, stdout, _ = self.invoke(
            ["--only", "clock", "--json"], runner=self.clock_runner("no\n")
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["status"], "warn")

    def test_error_exit_code(self) -> None:
        code, stdout, _ = self.invoke(
            ["--only", "clock", "--json"],
            runner=self.clock_runner(returncode=1, stderr="unexpected"),
        )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout)["status"], "error")

    def test_skipped_check_exits_zero(self) -> None:
        code, stdout, _ = self.invoke(["--only", "smart"], runner=FakeRunner())
        self.assertEqual(code, 0)
        self.assertIn("SKIP", stdout)
        self.assertIn("SMART", stdout)

    def test_skip_all_checks_exits_three(self) -> None:
        config = self.write_config(
            "[system]\nenabled=false\n[storage]\nenabled=false\n"
            "[systemd]\nenabled=false\n[docker]\nenabled=false\n"
            "[raid]\nenabled=false\n[backups]\nenabled=false\n"
            "[certificates]\nenabled=false\n"
        )
        code, _, stderr = self.invoke(
            ["--config", str(config), "--skip", "clock", "--only", "clock"]
        )
        self.assertEqual(code, 3)
        self.assertIn("no checks selected", stderr)

    def test_output_file_is_written_atomically(self) -> None:
        target = self.temp / "report.json"
        code, stdout, _ = self.invoke(
            ["--only", "clock", "--json", "--output", str(target)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["checks"][0]["name"], "clock")
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        self.assertEqual(list(self.temp.glob(".report.json.*")), [])

    def test_output_file_preserves_existing_mode(self) -> None:
        target = self.temp / "report.txt"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o600)
        code, _, _ = self.invoke(["--only", "clock", "--output", str(target)])
        self.assertEqual(code, 0)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_output_dash_means_stdout(self) -> None:
        code, stdout, _ = self.invoke(["--only", "clock", "--json", "--output", "-"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["checks"][0]["name"], "clock")

    def test_unwritable_output_exits_three(self) -> None:
        target = self.temp / "missing-directory" / "report.txt"
        code, stdout, stderr = self.invoke(["--only", "clock", "--output", str(target)])
        self.assertEqual(code, 3)
        self.assertEqual(stdout, "")
        self.assertIn("cannot write", stderr)

    def test_json_and_prometheus_are_mutually_exclusive(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as caught,
        ):
            cli.main(["--json", "--prometheus"])
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_no_color_and_no_color_environment(self) -> None:
        class Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        args = Namespace(no_color=False, output=None)
        with mock.patch("labcheck.cli.sys.stdout", Tty()):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertTrue(cli._use_color(args))
            with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
                self.assertFalse(cli._use_color(args))
        args.no_color = True
        self.assertFalse(cli._use_color(args))
        args = Namespace(no_color=False, output=str(self.temp / "report.txt"))
        self.assertFalse(cli._use_color(args))

    def test_crashing_check_becomes_error_result(self) -> None:
        def explode(context):
            raise RuntimeError("boom")

        spec = CheckSpec("crash", "Crash", "test", "clock", explode)
        with (
            mock.patch("labcheck.checks.CHECKS", (spec,)),
            mock.patch("labcheck.checks.BY_NAME", {"crash": spec}),
        ):
            code, stdout, _ = self.invoke(["--only", "crash", "--verbose", "--json"])
        self.assertEqual(code, 3)
        payload = json.loads(stdout)
        check = payload["checks"][0]
        self.assertEqual(check["status"], "error")
        self.assertIn("check crashed: RuntimeError", check["summary"])
        self.assertIn("boom", check["details"][0])
        self.assertIn("Traceback", check["details"][1])


if __name__ == "__main__":
    unittest.main()
