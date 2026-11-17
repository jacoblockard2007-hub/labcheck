from __future__ import annotations

import unittest

from labcheck.checks import BY_NAME, CHECKS, is_enabled, names, select, split_names
from labcheck.config import Config, SmartConfig


class RegistryTest(unittest.TestCase):
    def test_order_and_names(self) -> None:
        self.assertEqual(
            names(),
            [
                "system",
                "storage",
                "services",
                "docker",
                "raid",
                "smart",
                "backups",
                "certificates",
                "clock",
            ],
        )
        self.assertEqual(set(BY_NAME), set(names()))

    def test_every_spec_has_metadata(self) -> None:
        for spec in CHECKS:
            with self.subTest(spec=spec.name):
                self.assertTrue(spec.title)
                self.assertTrue(spec.description)
                self.assertTrue(callable(spec.func))
                self.assertTrue(hasattr(Config(), spec.config_key))

    def test_default_selection_respects_disabled_checks(self) -> None:
        selected = select(Config())
        self.assertNotIn("smart", [spec.name for spec in selected])
        self.assertEqual(len(selected), len(CHECKS) - 1)

    def test_enabled_smart_is_selected(self) -> None:
        config = Config(smart=SmartConfig(enabled=True))
        self.assertIn("smart", [spec.name for spec in select(config)])
        self.assertTrue(is_enabled(BY_NAME["smart"], config))

    def test_only_can_force_disabled_check(self) -> None:
        selected = select(Config(), only=["smart"])
        self.assertEqual([spec.name for spec in selected], ["smart"])

    def test_only_preserves_registry_order(self) -> None:
        selected = select(Config(), only=["clock", "system"])
        self.assertEqual([spec.name for spec in selected], ["system", "clock"])

    def test_skip(self) -> None:
        selected = select(Config(), skip=["system", "storage"])
        self.assertNotIn("system", [spec.name for spec in selected])
        self.assertNotIn("storage", [spec.name for spec in selected])

    def test_unknown_names_raise(self) -> None:
        with self.assertRaises(KeyError) as caught:
            select(Config(), only=["nope"])
        self.assertIn("nope", caught.exception.args[0])
        with self.assertRaises(KeyError):
            select(Config(), skip=["nope"])

    def test_split_names(self) -> None:
        self.assertEqual(
            split_names(["system, storage", "clock", "system"]),
            ["system", "storage", "clock"],
        )
        self.assertEqual(split_names([" , "]), [])


if __name__ == "__main__":
    unittest.main()
