# Changelog

All notable changes to labcheck are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Test on Python 3.15 and document Fedora Linux 45 compatibility.

## [0.1.0] - 2026-11-16

### Added

- Initial release.
- Checks for system load, memory, swap, temperature and uptime.
- Checks for filesystem space and inode usage.
- Checks for failed systemd units and required services.
- Checks for Docker container state and required containers.
- Checks for Linux md RAID arrays.
- Optional SMART health checks through `smartctl`.
- Backup freshness checks with glob support.
- TLS certificate expiry checks.
- NTP synchronisation checks.
- Human-readable, JSON and Prometheus output modes.
- Atomic report files and nagios-style exit codes.
- TOML configuration with validation and non-fatal unknown-key warnings.
- Test suite covering parsers, checks, formatters, configuration and CLI.
