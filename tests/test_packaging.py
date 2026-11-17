from __future__ import annotations

import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from labcheck import __version__
from labcheck.checks import CHECKS, is_enabled
from labcheck.config import config_from_toml

ROOT = Path(__file__).resolve().parent.parent


class PackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        with open(ROOT / "pyproject.toml", "rb") as handle:
            self.project = tomllib.load(handle)["project"]

    def test_name_and_version_match_package(self) -> None:
        self.assertEqual(self.project["name"], "labcheck")
        self.assertEqual(self.project["version"], __version__)

    def test_no_runtime_dependencies(self) -> None:
        self.assertEqual(self.project["dependencies"], [])

    def test_console_script(self) -> None:
        self.assertEqual(self.project["scripts"]["labcheck"], "labcheck.cli:main")

    def test_python_requirement(self) -> None:
        self.assertEqual(self.project["requires-python"], ">=3.11")


class ModuleEntryPointTest(unittest.TestCase):
    def test_python_dash_m_invocation(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "labcheck", "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("labcheck 0.1.0", result.stdout)


class ExampleConfigTest(unittest.TestCase):
    def test_example_config_is_valid(self) -> None:
        with open(ROOT / "labcheck.example.toml", "rb") as handle:
            raw = tomllib.load(handle)
        config = config_from_toml(raw, base_dir=ROOT)
        self.assertEqual(config.warnings, [])
        self.assertEqual(len(config.backups.targets), 2)
        self.assertEqual(len(config.certificates.targets), 2)
        self.assertFalse(config.smart.enabled)

    def test_example_config_enables_every_default_check(self) -> None:
        with open(ROOT / "labcheck.example.toml", "rb") as handle:
            raw = tomllib.load(handle)
        config = config_from_toml(raw, base_dir=ROOT)
        for spec in CHECKS:
            if spec.name == "smart":
                self.assertFalse(is_enabled(spec, config))
            else:
                self.assertTrue(is_enabled(spec, config), spec.name)


if __name__ == "__main__":
    unittest.main()
