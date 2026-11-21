from __future__ import annotations

import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from labcheck.config import (
    Config,
    ConfigError,
    config_from_toml,
    default_config_candidates,
    find_config,
    load_config,
)


def parse(text: str, base_dir: Path | None = None):
    return config_from_toml(tomllib.loads(text), base_dir=base_dir)


class DefaultsTest(unittest.TestCase):
    def test_everything_enabled_except_smart(self) -> None:
        config = Config()
        for name in (
            "system",
            "storage",
            "systemd",
            "docker",
            "raid",
            "backups",
            "certificates",
            "clock",
        ):
            self.assertTrue(getattr(config, name).enabled, name)
        self.assertFalse(config.smart.enabled)
        self.assertEqual(config.smart.devices, [])
        self.assertEqual(config.backups.targets, [])
        self.assertFalse(config.backups.kopia.enabled)
        self.assertEqual(config.certificates.targets, [])
        self.assertEqual(config.warnings, [])

    def test_threshold_defaults(self) -> None:
        config = Config()
        self.assertEqual(config.storage.warn_disk_percent, 80.0)
        self.assertEqual(config.storage.crit_disk_percent, 90.0)
        self.assertEqual(config.system.crit_load_per_core, 3.0)
        self.assertTrue(config.system.check_swap)


class FullConfigTest(unittest.TestCase):
    def test_parses_every_section(self) -> None:
        config = parse(
            """
            [system]
            enabled = false
            warn_load_per_core = 2.0
            crit_load_per_core = 4.5
            warn_memory_percent = 70
            crit_memory_percent = 90
            warn_swap_percent = 25
            crit_swap_percent = 60
            warn_temperature_c = 65
            crit_temperature_c = 80
            check_swap = false

            [storage]
            enabled = true
            warn_disk_percent = 75
            crit_disk_percent = 85
            warn_inode_percent = 80
            crit_inode_percent = 90
            ignore_mounts = ["/boot", "/snap/*"]
            only_mounts = ["/", "/srv"]
            ignore_filesystems = ["nfs", "cifs"]

            [systemd]
            required_services = ["ssh.service", "smbd.service"]
            allow_failed = ["apt-daily*.service"]

            [docker]
            require_running = ["traefik", "nextcloud"]
            ignore = ["watchtower"]

            [raid]
            enabled = false

            [smart]
            enabled = true
            devices = ["/dev/sda", "/dev/nvme0"]

            [[backups.targets]]
            path = "backups/db.sql"
            max_age_hours = 12

            [[backups.targets]]
            name = "photos"
            path = "/srv/photos"
            max_age_hours = 168

            [certificates]
            timeout_seconds = 2.5

            [[certificates.targets]]
            host = "example.com"
            warn_days = 30
            crit_days = 10

            [[certificates.targets]]
            host = "internal.lan"
            port = 8443

            [clock]
            enabled = false
            """
        )

        self.assertFalse(config.system.enabled)
        self.assertEqual(config.system.crit_load_per_core, 4.5)
        self.assertFalse(config.system.check_swap)
        self.assertEqual(config.storage.ignore_mounts, ["/boot", "/snap/*"])
        self.assertEqual(config.storage.only_mounts, ["/", "/srv"])
        self.assertEqual(config.storage.ignore_filesystems, ["nfs", "cifs"])
        self.assertEqual(
            config.systemd.required_services, ["ssh.service", "smbd.service"]
        )
        self.assertEqual(config.systemd.allow_failed, ["apt-daily*.service"])
        self.assertEqual(config.docker.require_running, ["traefik", "nextcloud"])
        self.assertEqual(config.docker.ignore, ["watchtower"])
        self.assertFalse(config.raid.enabled)
        self.assertTrue(config.smart.enabled)
        self.assertEqual(config.smart.devices, ["/dev/sda", "/dev/nvme0"])

        self.assertEqual(len(config.backups.targets), 2)
        self.assertEqual(config.backups.targets[0].name, "db.sql")
        self.assertEqual(config.backups.targets[0].max_age_hours, 12)
        self.assertEqual(config.backups.targets[1].name, "photos")
        self.assertEqual(config.backups.targets[1].path, "/srv/photos")

        self.assertEqual(config.certificates.timeout_seconds, 2.5)
        self.assertEqual(config.certificates.targets[0].host, "example.com")
        self.assertEqual(config.certificates.targets[0].port, 443)
        self.assertEqual(config.certificates.targets[0].warn_days, 30)
        self.assertEqual(config.certificates.targets[0].crit_days, 10)
        self.assertEqual(config.certificates.targets[1].port, 8443)
        self.assertFalse(config.clock.enabled)
        self.assertEqual(config.warnings, [])

    def test_relative_backup_paths_resolve_against_config_directory(self) -> None:
        base = Path("/etc/labcheck")
        config = config_from_toml(
            {"backups": {"targets": [{"path": "dumps/db.sql"}]}}, base_dir=base
        )
        self.assertEqual(config.backups.targets[0].path, str(base / "dumps" / "db.sql"))

    def test_absolute_backup_paths_are_kept(self) -> None:
        config = config_from_toml(
            {"backups": {"targets": [{"path": "/srv/backup"}]}}, base_dir=Path("/etc")
        )
        self.assertEqual(config.backups.targets[0].path, "/srv/backup")

    def test_unknown_keys_are_warnings_not_errors(self) -> None:
        config = parse(
            """
            unknown_top = 1

            [system]
            warn_lod_per_core = 2

            [[backups.targets]]
            path = "/srv/b"
            max_age = 5

            """
        )
        joined = "\n".join(config.warnings)
        self.assertIn("unknown_top", joined)
        self.assertIn("warn_lod_per_core", joined)
        self.assertIn("max_age", joined)


class BackupSnapshotConfigTest(unittest.TestCase):
    def test_legacy_snapshot_section_is_not_supported(self) -> None:
        config = parse(
            """
            [backups.snapshot]
            enabled = true
            """
        )

        self.assertEqual(config.backups.snapshots, [])
        self.assertTrue(any("snapshot" in warning for warning in config.warnings))

    def test_snapshot_check_mount_defaults_to_true(self) -> None:
        config = parse(
            """
            [[backups.snapshots]]
            name = "Media"
            mountpoint = "/backup"
            snapshots_dir = "/backup/snapshots"
            latest_link = "/backup/snapshots/latest"
            """
        )

        self.assertTrue(config.backups.snapshots[0].check_mount)

    def test_snapshot_check_mount_can_be_disabled(self) -> None:
        config = parse(
            """
            [[backups.snapshots]]
            name = "Media"
            mountpoint = "/backup"
            snapshots_dir = "/backup/snapshots"
            latest_link = "/backup/snapshots/latest"
            check_mount = false
            """
        )

        self.assertFalse(config.backups.snapshots[0].check_mount)


class ValidationTest(unittest.TestCase):
    def assert_invalid(self, raw: object, fragment: str) -> None:
        with self.assertRaises(ConfigError) as caught:
            config_from_toml(raw)  # type: ignore[arg-type]
        self.assertIn(fragment, str(caught.exception))

    def test_top_level_must_be_a_table(self) -> None:
        self.assert_invalid([], "top-level")

    def test_section_must_be_a_table(self) -> None:
        self.assert_invalid({"system": []}, "system must be a table")

    def test_boolean_must_be_boolean(self) -> None:
        self.assert_invalid({"system": {"enabled": "yes"}}, "must be true or false")

    def test_number_rejects_boolean(self) -> None:
        self.assert_invalid(
            {"system": {"warn_load_per_core": True}}, "must be a number"
        )

    def test_number_must_be_finite(self) -> None:
        self.assert_invalid(
            {"storage": {"warn_disk_percent": float("inf")}}, "must be finite"
        )

    def test_string_list_types(self) -> None:
        self.assert_invalid(
            {"storage": {"ignore_mounts": "/boot"}}, "must be a list of strings"
        )
        self.assert_invalid(
            {"systemd": {"required_services": [1]}}, "must be a list of strings"
        )

    def test_target_tables(self) -> None:
        self.assert_invalid({"backups": {"targets": "x"}}, "must be an array of tables")
        self.assert_invalid({"backups": {"targets": [1]}}, "must be an array of tables")
        self.assert_invalid(
            {"certificates": {"targets": [{"host": "x", "port": 443.5}]}},
            "must be an integer",
        )

    def test_backup_target_requires_path(self) -> None:
        self.assert_invalid(
            {"backups": {"targets": [{"name": "db"}]}}, "path is required"
        )

    def test_backup_max_age_must_be_positive(self) -> None:
        self.assert_invalid(
            {"backups": {"targets": [{"path": "/b", "max_age_hours": 0}]}},
            "greater than zero",
        )

    def test_snapshot_max_age_must_be_positive(self) -> None:
        for max_age in (0, -1):
            with self.subTest(max_age=max_age):
                self.assert_invalid(
                    {
                        "backups": {
                            "snapshots": [
                                {
                                    "mountpoint": "/backup",
                                    "snapshots_dir": "/backup/snapshots",
                                    "latest_link": "/backup/snapshots/latest",
                                    "max_age_hours": max_age,
                                }
                            ]
                        }
                    },
                    "greater than zero",
                )

    def test_snapshot_unit_names_cannot_be_empty(self) -> None:
        for key in ("timer_unit", "service_unit"):
            with self.subTest(key=key):
                self.assert_invalid(
                    {
                        "backups": {
                            "snapshots": [
                                {
                                    "mountpoint": "/backup",
                                    "snapshots_dir": "/backup/snapshots",
                                    "latest_link": "/backup/snapshots/latest",
                                    key: "",
                                }
                            ]
                        }
                    },
                    "cannot be empty",
                )

    def test_certificate_target_requires_host(self) -> None:
        self.assert_invalid(
            {"certificates": {"targets": [{"port": 443}]}}, "host is required"
        )

    def test_certificate_port_range(self) -> None:
        for port in (0, 65536):
            with self.subTest(port=port):
                self.assert_invalid(
                    {"certificates": {"targets": [{"host": "x", "port": port}]}},
                    "between 1 and 65535",
                )

    def test_certificate_days_cannot_be_negative(self) -> None:
        self.assert_invalid(
            {"certificates": {"targets": [{"host": "x", "warn_days": -1}]}},
            "cannot be negative",
        )

    def test_certificate_timeout_must_be_positive(self) -> None:
        self.assert_invalid(
            {"certificates": {"timeout_seconds": 0}}, "greater than zero"
        )


class LoadConfigTest(unittest.TestCase):
    def test_missing_explicit_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nope.toml"
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
            self.assertIn("not found", str(caught.exception))

    def test_loads_file_and_reports_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                "[storage]\nwarn_disk_percent = 50\n[[backups.targets]]\npath = 'x'\n",
                encoding="utf-8",
            )
            config, loaded = load_config(path)
            self.assertEqual(loaded, path)
            self.assertEqual(config.storage.warn_disk_percent, 50.0)
            self.assertEqual(config.backups.targets[0].path, str(Path(directory) / "x"))

    def test_parse_errors_include_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.toml"
            path.write_text("[system\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
            self.assertIn(str(path), str(caught.exception))

    def test_explicit_path_beats_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            explicit = Path(directory) / "explicit.toml"
            explicit.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"LABCHECK_CONFIG": "/nope.toml"}):
                self.assertEqual(find_config(explicit), explicit)

    def test_environment_variable_is_first_candidate(self) -> None:
        with mock.patch.dict(os.environ, {"LABCHECK_CONFIG": "~/my.toml"}):
            candidates = default_config_candidates()
        self.assertEqual(candidates[0], Path("~/my.toml").expanduser())

    def test_find_config_without_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.toml"
            with mock.patch(
                "labcheck.config.default_config_candidates", return_value=[missing]
            ):
                self.assertIsNone(find_config())

    def test_default_candidates_include_xdg_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labcheck" / "config.toml"
            path.parent.mkdir()
            path.write_text("", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    "LABCHECK_CONFIG": "",
                    "XDG_CONFIG_HOME": directory,
                    "HOME": directory,
                },
            ):
                candidates = default_config_candidates()
            self.assertIn(path, candidates)
            with mock.patch(
                "labcheck.config.default_config_candidates", return_value=[path]
            ):
                self.assertEqual(find_config(), path)


class GeneralizedBackupConfigTest(unittest.TestCase):
    def test_multiple_named_snapshot_monitors(self) -> None:
        config = parse(
            """
            [[backups.snapshots]]
            name = "Media"
            mountpoint = "/mnt/backup"
            snapshots_dir = "/mnt/backup/Media/Weekly"
            latest_link = "/mnt/backup/Media/Weekly/current"
            name_prefix = "Media_"
            timestamp_format = "%Y-%m-%d_%H:%M:%S"
            max_age_hours = 192
            timer_unit = "media.timer"
            service_unit = "media.service"

            [[backups.snapshots]]
            name = "AppData"
            mountpoint = "/mnt/backup"
            snapshots_dir = "/mnt/backup/AppData/Weekly"
            latest_link = "/mnt/backup/AppData/Weekly/current"
            name_prefix = "AppData_"
            timestamp_format = "%Y-%m-%d_%H:%M:%S"
            max_age_hours = 192
            """
        )
        self.assertEqual(
            [item.name for item in config.backups.snapshots], ["Media", "AppData"]
        )
        self.assertEqual(
            config.backups.snapshots[0].timestamp_format, "%Y-%m-%d_%H:%M:%S"
        )
        self.assertEqual(config.backups.snapshots[0].timer_unit, "media.timer")
        self.assertIsNone(config.backups.snapshots[1].timer_unit)

    def test_duplicate_snapshot_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "names must be unique"):
            parse(
                """
                [[backups.snapshots]]
                name = "same"
                mountpoint = "/backup"
                snapshots_dir = "/backup/a"
                latest_link = "/backup/a/latest"
                [[backups.snapshots]]
                name = "same"
                mountpoint = "/backup"
                snapshots_dir = "/backup/b"
                latest_link = "/backup/b/latest"
                """
            )

    def test_snapshot_requires_timer_and_service_as_a_pair(self) -> None:
        with self.assertRaisesRegex(ConfigError, "both timer_unit and service_unit"):
            parse(
                """
                [[backups.snapshots]]
                mountpoint = "/backup"
                snapshots_dir = "/backup/snapshots"
                latest_link = "/backup/snapshots/latest"
                timer_unit = "backup.timer"
                """
            )

    def test_generic_target_accepts_optional_systemd_units(self) -> None:
        config = parse(
            """
            [[backups.targets]]
            name = "Jellyfin"
            path = "/srv/backups/*.zip"
            max_age_hours = 36
            timer_unit = "jellyfin-backup.timer"
            service_unit = "jellyfin-backup.service"
            """
        )
        target = config.backups.targets[0]
        self.assertEqual(target.timer_unit, "jellyfin-backup.timer")
        self.assertEqual(target.service_unit, "jellyfin-backup.service")

    def test_generic_target_requires_both_systemd_units(self) -> None:
        with self.assertRaisesRegex(ConfigError, "both timer_unit and service_unit"):
            parse(
                """
                [[backups.targets]]
                path = "/srv/backups/*.zip"
                timer_unit = "backup.timer"
                """
            )

    def test_snapshot_timestamp_format_must_include_a_calendar_date(self) -> None:
        with self.assertRaisesRegex(ConfigError, "timestamp_format is invalid"):
            parse(
                """
                [[backups.snapshots]]
                mountpoint = "/backup"
                snapshots_dir = "/backup/snapshots"
                latest_link = "/backup/snapshots/latest"
                timestamp_format = "%H:%M:%S"
                """
            )

    def test_snapshot_timestamp_format_rejects_timezone_abbreviations(self) -> None:
        with self.assertRaisesRegex(ConfigError, r"cannot use %Z; use %z"):
            parse(
                """
                [[backups.snapshots]]
                mountpoint = "/backup"
                snapshots_dir = "/backup/snapshots"
                latest_link = "/backup/snapshots/latest"
                timestamp_format = "%Y-%m-%d_%H:%M:%S_%Z"
                """
            )

    def test_snapshot_timestamp_format_accepts_numeric_timezone_offsets(self) -> None:
        config = parse(
            """
            [[backups.snapshots]]
            mountpoint = "/backup"
            snapshots_dir = "/backup/snapshots"
            latest_link = "/backup/snapshots/latest"
            timestamp_format = "%Y-%m-%d_%H:%M:%S_%z"
            """
        )
        self.assertEqual(
            config.backups.snapshots[0].timestamp_format,
            "%Y-%m-%d_%H:%M:%S_%z",
        )


class KopiaBackupConfigTest(unittest.TestCase):
    def test_kopia_monitor_defaults_to_disabled_with_seven_sources(self) -> None:
        config = parse("[backups.kopia]\nenabled = false\n")
        kopia = config.backups.kopia
        self.assertFalse(kopia.enabled)
        self.assertEqual(kopia.config_file, "/etc/kopia/mail-b2.config")
        self.assertEqual(kopia.host, "mail")
        self.assertEqual(kopia.user, "root")
        self.assertEqual(len(kopia.source_paths), 7)
        self.assertIn("/var/backups/mail-server", kopia.source_paths)
        self.assertEqual(kopia.max_age_hours, 30)

    def test_kopia_paths_and_units_are_parsed(self) -> None:
        config = parse(
            """
            [backups.kopia]
            enabled = true
            config_file = "/etc/kopia/production.config"
            host = "mail"
            user = "root"
            source_paths = ["/etc", "/var/vmail"]
            max_age_hours = 36
            timer_unit = "mail-kopia-backup.timer"
            service_unit = "mail-kopia-backup.service"
            """
        )
        kopia = config.backups.kopia
        self.assertTrue(kopia.enabled)
        self.assertEqual(kopia.source_paths, ("/etc", "/var/vmail"))
        self.assertEqual(kopia.timer_unit, "mail-kopia-backup.timer")
        self.assertEqual(kopia.service_unit, "mail-kopia-backup.service")

    def test_kopia_source_paths_must_be_absolute_and_unique(self) -> None:
        for paths in (["etc"], ["/etc", "/etc"]):
            with self.subTest(paths=paths), self.assertRaises(ConfigError):
                config_from_toml({"backups": {"kopia": {"source_paths": paths}}})

    def test_kopia_timer_and_service_must_be_paired(self) -> None:
        with self.assertRaisesRegex(ConfigError, "both timer_unit and service_unit"):
            config_from_toml({"backups": {"kopia": {"timer_unit": "mail.timer"}}})

    def test_kopia_max_age_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ConfigError, "greater than zero"):
            config_from_toml({"backups": {"kopia": {"max_age_hours": 0}}})


if __name__ == "__main__":
    unittest.main()
