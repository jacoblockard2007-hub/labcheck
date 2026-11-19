"""Configuration loading and validation.

The file format is TOML (Python 3.11+ ships ``tomllib``).  Every setting is
optional; labcheck runs with sensible defaults when no file is present.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a configuration file cannot be read or parsed."""


@dataclass
class SystemConfig:
    enabled: bool = True
    warn_load_per_core: float = 1.5
    crit_load_per_core: float = 3.0
    warn_memory_percent: float = 85.0
    crit_memory_percent: float = 95.0
    warn_swap_percent: float = 50.0
    crit_swap_percent: float = 80.0
    warn_temperature_c: float = 75.0
    crit_temperature_c: float = 85.0
    check_swap: bool = True


@dataclass
class StorageConfig:
    enabled: bool = True
    warn_disk_percent: float = 80.0
    crit_disk_percent: float = 90.0
    warn_inode_percent: float = 85.0
    crit_inode_percent: float = 95.0
    ignore_mounts: list[str] = field(default_factory=list)
    only_mounts: list[str] = field(default_factory=list)
    ignore_filesystems: list[str] = field(default_factory=list)


@dataclass
class SystemdConfig:
    enabled: bool = True
    required_services: list[str] = field(default_factory=list)
    allow_failed: list[str] = field(default_factory=list)


@dataclass
class DockerConfig:
    enabled: bool = True
    require_running: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)


@dataclass
class RaidConfig:
    enabled: bool = True


@dataclass
class SmartConfig:
    enabled: bool = False
    devices: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BackupTarget:
    name: str
    path: str
    max_age_hours: float = 24.0
    timer_unit: str | None = None
    service_unit: str | None = None


@dataclass(frozen=True)
class BackupSnapshotConfig:
    enabled: bool = True
    mountpoint: str = "/backup"
    snapshots_dir: str = "/backup/snapshots"
    latest_link: str = "/backup/snapshots/latest"
    max_age_hours: float = 192.0
    timer_unit: str | None = None
    service_unit: str | None = None
    name: str = "Snapshot"
    name_prefix: str = ""
    timestamp_format: str = "%Y-%m-%d"


@dataclass
class BackupsConfig:
    enabled: bool = True
    targets: list[BackupTarget] = field(default_factory=list)
    snapshot: BackupSnapshotConfig | None = None
    snapshots: list[BackupSnapshotConfig] = field(default_factory=list)


@dataclass(frozen=True)
class CertificateTarget:
    host: str
    port: int = 443
    warn_days: float = 14.0
    crit_days: float = 7.0


@dataclass
class CertificatesConfig:
    enabled: bool = True
    timeout_seconds: float = 5.0
    targets: list[CertificateTarget] = field(default_factory=list)


@dataclass
class ClockConfig:
    enabled: bool = True


@dataclass
class Config:
    system: SystemConfig = field(default_factory=SystemConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    systemd: SystemdConfig = field(default_factory=SystemdConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    raid: RaidConfig = field(default_factory=RaidConfig)
    smart: SmartConfig = field(default_factory=SmartConfig)
    backups: BackupsConfig = field(default_factory=BackupsConfig)
    certificates: CertificatesConfig = field(default_factory=CertificatesConfig)
    clock: ClockConfig = field(default_factory=ClockConfig)
    warnings: list[str] = field(default_factory=list)


TOP_LEVEL_KEYS = {
    "system",
    "storage",
    "systemd",
    "docker",
    "raid",
    "smart",
    "backups",
    "certificates",
    "clock",
}


def default_config_candidates() -> list[Path]:
    """Likely config locations, in priority order."""
    env = os.environ.get("LABCHECK_CONFIG")
    if env:
        return [Path(env).expanduser()]

    candidates: list[Path] = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "labcheck" / "config.toml")
    elif os.uname().sysname == "Darwin":
        candidates.append(
            Path.home() / "Library" / "Application Support" / "labcheck" / "config.toml"
        )
    else:
        candidates.append(Path("/etc/labcheck.toml"))

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    candidates.append(base / "labcheck" / "config.toml")
    return candidates


def find_config(explicit: str | Path | None = None) -> Path | None:
    """Resolve which config file to use, without reading it."""
    if explicit is not None:
        return Path(explicit).expanduser()
    for candidate in default_config_candidates():
        if candidate.is_file():
            return candidate
    return None


def load_config(
    explicit: str | Path | None = None,
) -> tuple[Config, Path | None]:
    """Load configuration from ``explicit`` or the default locations."""
    path = find_config(explicit)
    if path is None:
        return Config(), None
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None

    return config_from_toml(raw, base_dir=path.parent), path


def config_from_toml(raw: Mapping[str, Any], base_dir: Path | None = None) -> Config:
    """Build a :class:`Config` from already-parsed TOML data."""
    if not isinstance(raw, Mapping):
        raise ConfigError("top-level TOML value must be a table")

    warnings: list[str] = []
    _unknown_keys(raw, TOP_LEVEL_KEYS, "", warnings)

    system_raw = _table(raw, "system", "", warnings)
    system = SystemConfig(
        enabled=_bool(system_raw, "enabled", True, "system"),
        warn_load_per_core=_number(system_raw, "warn_load_per_core", 1.5, "system"),
        crit_load_per_core=_number(system_raw, "crit_load_per_core", 3.0, "system"),
        warn_memory_percent=_number(system_raw, "warn_memory_percent", 85.0, "system"),
        crit_memory_percent=_number(system_raw, "crit_memory_percent", 95.0, "system"),
        warn_swap_percent=_number(system_raw, "warn_swap_percent", 50.0, "system"),
        crit_swap_percent=_number(system_raw, "crit_swap_percent", 80.0, "system"),
        warn_temperature_c=_number(system_raw, "warn_temperature_c", 75.0, "system"),
        crit_temperature_c=_number(system_raw, "crit_temperature_c", 85.0, "system"),
        check_swap=_bool(system_raw, "check_swap", True, "system"),
    )

    storage_raw = _table(raw, "storage", "", warnings)
    storage = StorageConfig(
        enabled=_bool(storage_raw, "enabled", True, "storage"),
        warn_disk_percent=_number(storage_raw, "warn_disk_percent", 80.0, "storage"),
        crit_disk_percent=_number(storage_raw, "crit_disk_percent", 90.0, "storage"),
        warn_inode_percent=_number(storage_raw, "warn_inode_percent", 85.0, "storage"),
        crit_inode_percent=_number(storage_raw, "crit_inode_percent", 95.0, "storage"),
        ignore_mounts=_string_list(storage_raw, "ignore_mounts", [], "storage"),
        only_mounts=_string_list(storage_raw, "only_mounts", [], "storage"),
        ignore_filesystems=_string_list(
            storage_raw, "ignore_filesystems", [], "storage"
        ),
    )

    systemd_raw = _table(raw, "systemd", "", warnings)
    systemd = SystemdConfig(
        enabled=_bool(systemd_raw, "enabled", True, "systemd"),
        required_services=_string_list(systemd_raw, "required_services", [], "systemd"),
        allow_failed=_string_list(systemd_raw, "allow_failed", [], "systemd"),
    )

    docker_raw = _table(raw, "docker", "", warnings)
    docker = DockerConfig(
        enabled=_bool(docker_raw, "enabled", True, "docker"),
        require_running=_string_list(docker_raw, "require_running", [], "docker"),
        ignore=_string_list(docker_raw, "ignore", [], "docker"),
    )

    raid_raw = _table(raw, "raid", "", warnings)
    raid = RaidConfig(enabled=_bool(raid_raw, "enabled", True, "raid"))

    smart_raw = _table(raw, "smart", "", warnings)
    smart = SmartConfig(
        enabled=_bool(smart_raw, "enabled", False, "smart"),
        devices=_string_list(smart_raw, "devices", [], "smart"),
    )

    backups_raw = _table(raw, "backups", "", warnings)
    backup_targets: list[BackupTarget] = []
    for index, item in enumerate(
        _table_list(backups_raw, "targets", "backups", warnings)
    ):
        where = f"backups.targets[{index}]"
        if not isinstance(item, Mapping):
            raise ConfigError(f"{where} must be a table")
        _unknown_keys(
            item,
            {"name", "path", "max_age_hours", "timer_unit", "service_unit"},
            where,
            warnings,
        )
        raw_path = _string(item, "path", "", where)
        if not raw_path:
            raise ConfigError(f"{where}.path is required")
        target_path = _resolve_path(raw_path, base_dir)
        name = _string(item, "name", Path(target_path).name, where)
        max_age = _number(item, "max_age_hours", 24.0, where)
        if max_age <= 0:
            raise ConfigError(f"{where}.max_age_hours must be greater than zero")
        timer_unit = _optional_unit(item, "timer_unit", where)
        service_unit = _optional_unit(item, "service_unit", where)
        if (timer_unit is None) != (service_unit is None):
            raise ConfigError(f"{where} must specify both timer_unit and service_unit")
        backup_targets.append(
            BackupTarget(
                name=name, path=target_path, max_age_hours=max_age,
                timer_unit=timer_unit, service_unit=service_unit,
            )
        )

    snapshot_config = None
    if "snapshot" in backups_raw:
        snapshot_raw = _table(backups_raw, "snapshot", "backups", warnings)
        where = "backups.snapshot"
        _unknown_keys(
            snapshot_raw,
            {
                "enabled", "mountpoint", "snapshots_dir", "latest_link",
                "max_age_hours", "timer_unit", "service_unit",
            },
            where,
            warnings,
        )

        mountpoint = _resolve_path(
            _string(snapshot_raw, "mountpoint", "/backup", where), base_dir
        )
        snapshots_dir = _resolve_path(
            _string(snapshot_raw, "snapshots_dir", "/backup/snapshots", where),
            base_dir,
        )
        latest_link = _resolve_path(
            _string(snapshot_raw, "latest_link", "/backup/snapshots/latest", where),
            base_dir,
        )

        for key, value in (
            ("mountpoint", mountpoint),
            ("snapshots_dir", snapshots_dir),
            ("latest_link", latest_link),
        ):
            if not Path(value).is_absolute():
                raise ConfigError(f"{where}.{key} must resolve to an absolute path")

        max_age = _number(snapshot_raw, "max_age_hours", 192.0, where)
        if max_age <= 0:
            raise ConfigError(f"{where}.max_age_hours must be greater than zero")

        timer_value = _string(snapshot_raw, "timer_unit", "", where)
        service_value = _string(snapshot_raw, "service_unit", "", where)
        if "timer_unit" in snapshot_raw and not timer_value:
            raise ConfigError(f"{where}.timer_unit cannot be empty")
        if "service_unit" in snapshot_raw and not service_value:
            raise ConfigError(f"{where}.service_unit cannot be empty")
        timer_unit = timer_value or None
        service_unit = service_value or None
        if (timer_unit is None) != (service_unit is None):
            raise ConfigError(f"{where} must specify both timer_unit and service_unit")

        snapshot_config = BackupSnapshotConfig(
            enabled=_bool(snapshot_raw, "enabled", True, where),
            mountpoint=mountpoint,
            snapshots_dir=snapshots_dir,
            latest_link=latest_link,
            max_age_hours=max_age,
            timer_unit=timer_unit,
            service_unit=service_unit,
        )

    snapshot_configs: list[BackupSnapshotConfig] = []
    for index, item in enumerate(
        _table_list(backups_raw, "snapshots", "backups", warnings)
    ):
        where = f"backups.snapshots[{index}]"
        _unknown_keys(item, {
            "name", "enabled", "mountpoint", "snapshots_dir", "latest_link",
            "max_age_hours", "timer_unit", "service_unit", "name_prefix",
            "timestamp_format",
        }, where, warnings)
        raw_mount = _string(item, "mountpoint", "", where)
        raw_snapshots = _string(item, "snapshots_dir", "", where)
        raw_latest = _string(item, "latest_link", "", where)
        if not raw_mount or not raw_snapshots or not raw_latest:
            raise ConfigError(
                f"{where} requires mountpoint, snapshots_dir, and latest_link"
            )
        mountpoint = _resolve_path(raw_mount, base_dir)
        snapshots_dir = _resolve_path(raw_snapshots, base_dir)
        latest_link = _resolve_path(raw_latest, base_dir)
        for key, value in (
            ("mountpoint", mountpoint),
            ("snapshots_dir", snapshots_dir),
            ("latest_link", latest_link),
        ):
            if not Path(value).is_absolute():
                raise ConfigError(f"{where}.{key} must resolve to an absolute path")
        max_age = _number(item, "max_age_hours", 192.0, where)
        if max_age <= 0:
            raise ConfigError(f"{where}.max_age_hours must be greater than zero")
        name = _string(item, "name", Path(snapshots_dir).name, where)
        prefix = _string(item, "name_prefix", "", where)
        timestamp_format = _string(item, "timestamp_format", "%Y-%m-%d", where)
        if not name or not timestamp_format:
            raise ConfigError(f"{where}.name and timestamp_format cannot be empty")
        if _has_strftime_directive(timestamp_format, "Z"):
            raise ConfigError(
                f"{where}.timestamp_format cannot use %Z; use %z for a numeric "
                "UTC offset"
            )
        try:
            # Numeric offsets are deterministic. Abbreviations (%Z) are not:
            # strptime may accept one without attaching timezone information.
            reference = datetime(
                2001, 2, 3, 4, 5, 6,
                tzinfo=timezone.utc
                if _has_strftime_directive(timestamp_format, "z")
                else None,
            )
            probe = reference.strftime(timestamp_format)
            parsed_probe = datetime.strptime(probe, timestamp_format)
            if parsed_probe.date() != reference.date():
                raise ValueError("timestamp format must include year, month, and day")
            if (
                _has_strftime_directive(timestamp_format, "z")
                and parsed_probe.utcoffset() is None
            ):
                raise ValueError("numeric UTC offset did not produce an aware timestamp")
        except (ValueError, TypeError):
            raise ConfigError(f"{where}.timestamp_format is invalid") from None
        timer_unit = _optional_unit(item, "timer_unit", where)
        service_unit = _optional_unit(item, "service_unit", where)
        if (timer_unit is None) != (service_unit is None):
            raise ConfigError(f"{where} must specify both timer_unit and service_unit")
        snapshot_configs.append(BackupSnapshotConfig(
            enabled=_bool(item, "enabled", True, where),
            mountpoint=mountpoint, snapshots_dir=snapshots_dir,
            latest_link=latest_link, max_age_hours=max_age,
            timer_unit=timer_unit, service_unit=service_unit, name=name,
            name_prefix=prefix, timestamp_format=timestamp_format,
        ))
    snapshot_names = [item.name for item in snapshot_configs]
    if snapshot_config is not None:
        snapshot_names.append(snapshot_config.name)
    if len(snapshot_names) != len(set(snapshot_names)):
        raise ConfigError("backup snapshot monitor names must be unique")

    backups = BackupsConfig(
        enabled=_bool(backups_raw, "enabled", True, "backups"),
        targets=backup_targets,
        snapshot=snapshot_config,
        snapshots=snapshot_configs,
    )

    certificates_raw = _table(raw, "certificates", "", warnings)
    cert_targets: list[CertificateTarget] = []
    for index, item in enumerate(
        _table_list(certificates_raw, "targets", "certificates", warnings)
    ):
        where = f"certificates.targets[{index}]"
        if not isinstance(item, Mapping):
            raise ConfigError(f"{where} must be a table")
        _unknown_keys(item, {"host", "port", "warn_days", "crit_days"}, where, warnings)
        host = _string(item, "host", "", where)
        if not host:
            raise ConfigError(f"{where}.host is required")
        port = _integer(item, "port", 443, where)
        if not 1 <= port <= 65535:
            raise ConfigError(f"{where}.port must be between 1 and 65535")
        warn_days = _number(item, "warn_days", 14.0, where)
        crit_days = _number(item, "crit_days", 7.0, where)
        if warn_days < 0 or crit_days < 0:
            raise ConfigError(f"{where} thresholds cannot be negative")
        cert_targets.append(
            CertificateTarget(
                host=host,
                port=port,
                warn_days=warn_days,
                crit_days=crit_days,
            )
        )
    certificates = CertificatesConfig(
        enabled=_bool(certificates_raw, "enabled", True, "certificates"),
        timeout_seconds=_number(
            certificates_raw, "timeout_seconds", 5.0, "certificates"
        ),
        targets=cert_targets,
    )
    if certificates.timeout_seconds <= 0:
        raise ConfigError("certificates.timeout_seconds must be greater than zero")

    clock_raw = _table(raw, "clock", "", warnings)
    clock = ClockConfig(enabled=_bool(clock_raw, "enabled", True, "clock"))

    return Config(
        system=system,
        storage=storage,
        systemd=systemd,
        docker=docker,
        raid=raid,
        smart=smart,
        backups=backups,
        certificates=certificates,
        clock=clock,
        warnings=warnings,
    )


# -- primitive parsing -------------------------------------------------


def _has_strftime_directive(format_string: str, directive: str) -> bool:
    """Return whether *format_string* contains an unescaped directive."""
    index = 0
    while index < len(format_string):
        if format_string[index] != "%":
            index += 1
            continue
        if index + 1 < len(format_string) and format_string[index + 1] == "%":
            index += 2
            continue
        if index + 1 < len(format_string) and format_string[index + 1] == directive:
            return True
        index += 2
    return False


def _where(where: str, key: str) -> str:
    return f"{where}.{key}" if where else key


def _table(
    table: Mapping[str, Any],
    key: str,
    where: str,
    warnings: list[str],
) -> Mapping[str, Any]:
    value = table.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{_where(where, key)} must be a table")
    if isinstance(value, Mapping) and key:
        allowed = _SECTION_KEYS.get(key)
        if allowed:
            _unknown_keys(value, allowed, key, warnings)
    return value


_SECTION_KEYS = {
    "system": {
        "enabled",
        "warn_load_per_core",
        "crit_load_per_core",
        "warn_memory_percent",
        "crit_memory_percent",
        "warn_swap_percent",
        "crit_swap_percent",
        "warn_temperature_c",
        "crit_temperature_c",
        "check_swap",
    },
    "storage": {
        "enabled",
        "warn_disk_percent",
        "crit_disk_percent",
        "warn_inode_percent",
        "crit_inode_percent",
        "ignore_mounts",
        "only_mounts",
        "ignore_filesystems",
    },
    "systemd": {"enabled", "required_services", "allow_failed"},
    "docker": {"enabled", "require_running", "ignore"},
    "raid": {"enabled"},
    "smart": {"enabled", "devices"},
    "backups": {"enabled", "targets", "snapshot", "snapshots"},
    "certificates": {"enabled", "timeout_seconds", "targets"},
    "clock": {"enabled"},
}


def _unknown_keys(
    table: Mapping[str, Any],
    allowed: set[str],
    where: str,
    warnings: list[str],
) -> None:
    for key in table:
        if key not in allowed:
            location = f"in [{where}]" if where else "at the top level"
            warnings.append(f"unknown key {key!r} {location}")


def _number(
    table: Mapping[str, Any],
    key: str,
    default: float,
    where: str,
) -> float:
    if key not in table:
        return float(default)
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{_where(where, key)} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"{_where(where, key)} must be finite")
    return number


def _integer(
    table: Mapping[str, Any],
    key: str,
    default: int,
    where: str,
) -> int:
    if key not in table:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{_where(where, key)} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{_where(where, key)} must be an integer")
    return int(value)


def _bool(
    table: Mapping[str, Any],
    key: str,
    default: bool,
    where: str,
) -> bool:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{_where(where, key)} must be true or false")
    return value


def _string(
    table: Mapping[str, Any],
    key: str,
    default: str,
    where: str,
) -> str:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, str):
        raise ConfigError(f"{_where(where, key)} must be a string")
    return value.strip()


def _optional_unit(table: Mapping[str, Any], key: str, where: str) -> str | None:
    if key not in table:
        return None
    value = _string(table, key, "", where)
    if not value:
        raise ConfigError(f"{_where(where, key)} cannot be empty")
    return value


def _string_list(
    table: Mapping[str, Any],
    key: str,
    default: list[str],
    where: str,
) -> list[str]:
    if key not in table:
        return list(default)
    value = table[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{_where(where, key)} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _table_list(
    table: Mapping[str, Any],
    key: str,
    where: str,
    warnings: list[str],
) -> list[Any]:
    if key not in table:
        return []
    value = table[key]
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise ConfigError(
            f"{_where(where, key)} must be an array of tables ([[{where}.{key}]])"
        )
    return list(value)


def _resolve_path(value: str, base_dir: Path | None) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return str(path)
