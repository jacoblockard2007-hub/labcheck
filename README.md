# labcheck

[![tests](https://github.com/jacoblockard2007-hub/labcheck/actions/workflows/tests.yml/badge.svg)](https://github.com/jacoblockard2007-hub/labcheck/actions/workflows/tests.yml)
[![latest release](https://img.shields.io/github/v/release/jacoblockard2007-hub/labcheck?sort=semver)](https://github.com/jacoblockard2007-hub/labcheck/releases)
[![license](https://img.shields.io/github/license/jacoblockard2007-hub/labcheck)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![platforms](https://img.shields.io/badge/platforms-Debian%2013%20%7C%20Ubuntu%2026.04%20%7C%20Fedora%2045-blue)](#tested-platforms)
[![dependencies](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen)](pyproject.toml)

A dependency-free health auditor for Linux homelabs.

`labcheck` runs a set of read-only checks, prints one concise report, and exits
with a nagios-style status code so cron, systemd and monitoring systems can act
on the result. It needs nothing but Python 3.11+ and the tools already present
on a typical homelab host.

<img src="https://raw.githubusercontent.com/jacoblockard2007-hub/labcheck/main/docs/demo.png" alt="Terminal running labcheck -v on a Debian host" width="880">

<sub>Real output from `labcheck --verbose`. Docker, RAID, backups and
certificates report `SKIP` until the service or targets exist.</sub>

## Quick start

```bash
pipx install https://github.com/jacoblockard2007-hub/labcheck/releases/download/v0.1.0/labcheck-0.1.0-py3-none-any.whl
labcheck -v
```

Linux, Python 3.11+, no runtime dependencies. The wheel comes from the
[latest release](https://github.com/jacoblockard2007-hub/labcheck/releases/latest);
there is no PyPI listing yet. If `pipx` is missing, install it with
`sudo apt install pipx` or `sudo dnf install pipx`.

## Why another monitoring tool?

Because a homelab often has no monitoring stack yet, and a full agent is
overkill for "is everything still fine?". `labcheck` is meant to be:

- **Useful in one command.** No server, database, daemon or config file is
  required to get a first answer.
- **Dependency-free.** Runtime code is pure Python standard library.
- **Read-only.** It inspects `/proc`, `/sys`, Docker and systemd; it never
  changes the system.
- **Cron-friendly.** Exit code `0/1/2/3`, optional atomic report files, and a
  Prometheus mode for node_exporter's textfile collector.
- **Honest about gaps.** A check that cannot run reports `SKIP`, not `OK`.

## What it checks

| Check | What it inspects | Skipped when |
| --- | --- | --- |
| `system` | Load per CPU core, memory, swap, hottest thermal sensor, uptime | `/proc` metrics are unreadable (reported as an error) |
| `storage` | Space and inode usage of mounted local filesystems | every mount is filtered out |
| `services` | Failed systemd units and configured required services | `systemctl` is missing or systemd is not reachable |
| `docker` | Container states, unhealthy containers, required containers | Docker is not installed |
| `raid` | Linux md software RAID arrays from `/proc/mdstat` | no arrays are present |
| `smart` | SMART overall health via `smartctl` (opt-in) | no devices configured or `smartctl` missing |
| `backups` | Freshness of configured backup files and named snapshot directories; optional read-only Kopia repository and per-source snapshot checks, with optional systemd schedule checks | no targets, snapshots or enabled Kopia monitor configured |
| `certificates` | TLS certificate expiry for remote endpoints | no targets configured |
| `clock` | NTP synchronisation via `timedatectl` | `timedatectl` or systemd is unavailable |

## Installation

Requirements:

- Linux
- Python 3.11 or newer
- Optional: `systemctl` (systemd), `docker`, `smartctl` (smartmontools),
  `timedatectl` (systemd)

### Tested platforms

| Distribution | Python | Verified |
| --- | --- | --- |
| Debian 13 (trixie), x86_64 | 3.13 | Full report |
| Ubuntu 26.04.1 LTS, x86_64 | 3.14 | Full report |
| Fedora Linux 45, x86_64 | 3.15 | Full report |

Checks that need a service or configured target report `SKIP` until it exists,
so a clean host shows `SKIP` for Docker, RAID, backups and certificates. Report
your distribution in an issue if something behaves unexpectedly.

### From a GitHub release

Each release ships a wheel, an sdist and `SHA256SUMS`. The quick start above
installs the current wheel by URL. To pin a different version, download the
asset from the [releases page](https://github.com/jacoblockard2007-hub/labcheck/releases)
and install the file:

```bash
pipx install ~/Downloads/labcheck-X.Y.Z-py3-none-any.whl
```

Verify a download against the attached checksums:

```bash
sha256sum -c SHA256SUMS
```

### With pipx from git

```bash
pipx install git+https://github.com/jacoblockard2007-hub/labcheck.git
```

### From a checkout

```bash
python3 -m pip install .
labcheck --version
```

### Without installing

Or run it straight from a checkout without installing anything:

```bash
python3 -m labcheck --version
```

`pipx install .` works too if you prefer isolated applications. There are no
runtime dependencies to download.

## Usage

```bash
labcheck                         # the whole report
labcheck --verbose               # add per-check details
labcheck --only storage,system   # run a subset (comma-separated)
labcheck --skip docker           # remove checks from the configured set
labcheck --list-checks           # show checks and whether config enables them
labcheck --json                  # machine-readable report
labcheck --prometheus            # Prometheus text exposition format
labcheck --output report.txt     # write atomically to a file
labcheck --config ./labcheck.toml
```

`--only` can also run a check that is disabled in the configuration, which is
handy for a one-off SMART test:

```bash
labcheck --only smart --verbose
```

### Example report

```text
$ labcheck
labcheck 0.1.0  ·  atlas  ·  2026-06-01 12:00:00 UTC

  OK    System        load 0.42 (8 cores), memory 38%, swap 2%, up 27d 4h
  WARN  Storage       /srv at 84% used (+1 more), 5 mounts
  OK    Services      no failed units
  CRIT  Containers    1 unhealthy: nextcloud
  OK    RAID          2 arrays healthy (md0, md1)
  SKIP  SMART         no devices configured
  OK    Backups       2 targets fresh
  WARN  Certificates  cloud.example.com:443 9d left
  OK    Clock         NTP synchronized

Summary: 1 critical, 2 warnings, 5 ok, 1 skipped  (0.31s)
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | OK, or every check was skipped |
| `1` | At least one warning |
| `2` | At least one critical finding |
| `3` | A check could not run, or labcheck itself failed (bad config, bad arguments, unwritable output) |

Skipped checks never change the exit code. Warnings and critical findings are
folded into the single overall status.

### Colour

ANSI colours are enabled only when stdout is a terminal. `--no-color` disables
them, as does setting the `NO_COLOR` environment variable.

## Configuration

All settings are optional. Explicit config path first, otherwise:

1. `$LABCHECK_CONFIG`
2. `/etc/labcheck.toml`
3. `$XDG_CONFIG_HOME/labcheck/config.toml` (usually
   `~/.config/labcheck/config.toml`)

A complete annotated file is included as
[`labcheck.example.toml`](labcheck.example.toml). Minimal example:

```toml
[storage]
warn_disk_percent = 75
ignore_mounts = ["/snap/*"]

[systemd]
required_services = ["ssh.service", "smbd.service"]

[backups]
[[backups.targets]]
name = "database"
path = "/srv/backups/database-*.sql.gz"
max_age_hours = 26

# Snapshot directories are monitored using the timestamp in the directory
# name, not directory mtime (which can change with hard-link snapshots).
[[backups.snapshots]]
name = "ProjectData"
mountpoint = "/mnt/backup"
snapshots_dir = "/mnt/backup/ProjectData/Weekly"
latest_link = "/mnt/backup/ProjectData/Weekly/latest"
name_prefix = "ProjectData_"
timestamp_format = "%Y-%m-%d_%H:%M:%S"
max_age_hours = 192
timer_unit = "project-data-weekly.timer"
service_unit = "project-data-weekly.service"

# Kopia/B2 monitoring is opt-in. The CLI reads its existing protected config;
# do not copy B2 credentials into labcheck configuration.
[backups.kopia]
enabled = true
config_file = "/etc/kopia/mail-b2.config"
host = "mail"
user = "root"
source_paths = ["/etc", "/home", "/var/mail", "/var/vmail", "/srv",
                "/usr/local", "/var/backups/mail-server"]
max_age_hours = 30
timer_unit = "mail-kopia-backup.timer"
service_unit = "mail-kopia-backup.service"

[certificates]
[[certificates.targets]]
host = "cloud.example.com"
warn_days = 30
crit_days = 7
```

Notes:

- Relative backup paths are resolved against the directory containing the
  config file.
- Add more `[[backups.snapshots]]` tables to monitor independent snapshot
  sets. Each requires `mountpoint`, `snapshots_dir` and `latest_link`; `name`
  defaults to the snapshot directory's basename.
- The optional [backups.kopia] monitor invokes Kopia repository status and snapshot inventory commands in JSON mode using the configured CLI config file. It checks each exact (host, user, source path) independently for a completed, fresh snapshot and reports snapshot error counters. It never creates snapshots, runs maintenance, changes retention, or modifies the repository. The monitor is disabled by default. Keep B2 credentials in Kopia's protected config file, not in the Labcheck TOML. source_paths must be absolute and unique; max_age_hours defaults to 30. Optional timer_unit and service_unit must be configured together.
- `name_prefix` is removed before parsing the timestamp with
  `timestamp_format` (a Python `datetime` format). Timestamps without a numeric
  UTC offset are interpreted in the host's local timezone. Use `%z` for an
  explicit numeric offset; `%Z` timezone abbreviations are not supported.
- Snapshot checks require `mountpoint` to be an actual mounted filesystem by
  default (`check_mount = true`). The snapshot directory must resolve inside
  that mount. Set `check_mount = false` only when intentionally monitoring
  snapshots on a directory that is not a separate mount; the snapshot directory
  must still exist. `timer_unit` and `service_unit` are optional, but must be
  configured together. The same optional pair can be used on
  `[[backups.targets]]` to verify a file backup's systemd schedule and last run.
  Systemd timer enabled states `enabled`, `static` and `indirect` are accepted;
  the timer must still be active.
- `ignore_mounts`, `only_mounts`, `systemd.allow_failed`,
  `docker.require_running`, and `docker.ignore` accept shell-style patterns
  (`fnmatch`).
- Unknown keys produce a warning on stderr but are otherwise ignored, so a
  typo in a threshold does not silently take the whole run down.
- SMART is disabled by default.

### Section reference

| Section | Keys and defaults |
| --- | --- |
| `[system]` | `enabled`, `warn_load_per_core = 1.5`, `crit_load_per_core = 3.0`, `warn_memory_percent = 85`, `crit_memory_percent = 95`, `warn_swap_percent = 50`, `crit_swap_percent = 80`, `warn_temperature_c = 75`, `crit_temperature_c = 85`, `check_swap = true` |
| `[storage]` | `enabled`, `warn_disk_percent = 80`, `crit_disk_percent = 90`, `warn_inode_percent = 85`, `crit_inode_percent = 95`, `ignore_mounts = []`, `only_mounts = []`, `ignore_filesystems = []` |
| `[systemd]` | `enabled`, `required_services = []`, `allow_failed = []` |
| `[docker]` | `enabled`, `require_running = []`, `ignore = []` |
| `[raid]` | `enabled` |
| `[smart]` | `enabled = false`, `devices = []` |
| `[backups]` | `enabled`; `[[backups.targets]]` with `name`, `path`, `max_age_hours = 24`, optional paired `timer_unit`/`service_unit`; `[[backups.snapshots]]` with `name`, `enabled`, `check_mount = true`, `mountpoint`, `snapshots_dir`, `latest_link`, `name_prefix`, `timestamp_format`, `max_age_hours`, optional paired `timer_unit`/`service_unit`; `[backups.kopia]` with `enabled = false`, `config_file`, `host`, `user`, `source_paths`, `max_age_hours = 30`, optional paired `timer_unit`/`service_unit` |
| `[certificates]` | `enabled`, `timeout_seconds = 5`, `[[certificates.targets]]` with `host`, `port = 443`, `warn_days = 14`, `crit_days = 7` |
| `[clock]` | `enabled` |

## Cron and node_exporter

A plain cron job that writes a human-readable snapshot:

```cron
*/15 * * * * root /usr/local/bin/labcheck --output /var/lib/labcheck/status.txt
```

The exit code still reflects the result, and `--output` uses a temporary file
plus `os.replace`, so readers never see a half-written report. New files are
created mode `0644` and an existing file keeps its mode, which matters when
node_exporter runs as a different user. Cron often has no sbin directories in
`PATH`; `labcheck` falls back to `/usr/sbin`, `/sbin` and `/usr/local/sbin`
when looking for `smartctl` and friends.

For Prometheus, let `labcheck` write a textfile for node_exporter:

```cron
*/5 * * * * root /usr/local/bin/labcheck --prometheus \
  --output /var/lib/node_exporter/textfile_collector/labcheck.prom
```

node_exporter must be started with `--collector.textfile.directory` pointing at
that directory. The file is replaced atomically and ends in `.prom`. Create the
directory first and make sure node_exporter's user can read the generated file.

If you prefer systemd timers, the same thing looks like this:

```ini
# /etc/systemd/system/labcheck.service
[Unit]
Description=Audit homelab health

[Service]
Type=oneshot
ExecStart=/usr/local/bin/labcheck --prometheus \
  --output /var/lib/node_exporter/textfile_collector/labcheck.prom
```

```ini
# /etc/systemd/system/labcheck.timer
[Unit]
Description=Run labcheck every five minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now labcheck.timer
```

Because the service exits non-zero on warnings, critical findings and errors,
you can attach `OnFailure=` to the service to trigger systemd's own failure
handling.

Example alert rules:

```yaml
groups:
  - name: labcheck
    rules:
      - alert: LabcheckCritical
        expr: labcheck_overall_status == 2
        for: 15m
        annotations:
          summary: "Homelab check is critical on {{ $labels.instance }}"

      - alert: LabcheckCheckFailing
        expr: labcheck_check_status{check!="smart"} >= 2
        for: 15m
        annotations:
          summary: "{{ $labels.check }} is not healthy on {{ $labels.instance }}"
```

### Prometheus metrics

Every check-specific metric is prefixed with `labcheck_`.

| Metric | Labels | Meaning |
| --- | --- | --- |
| `labcheck_info` | `version`, `hostname` | Build information, always `1` |
| `labcheck_overall_status` | | 0 ok, 1 warn, 2 crit, 3 error, 4 skipped |
| `labcheck_check_status` | `check` | Status of one check, same scale |
| `labcheck_duration_seconds` | | Duration of the run |
| `labcheck_last_run_timestamp_seconds` | | Unix timestamp of the run |
| `labcheck_load1`, `labcheck_load5`, `labcheck_load15` | `period` | Load averages |
| `labcheck_memory_used_percent`, `labcheck_memory_total_bytes`, `labcheck_memory_used_bytes` | | Memory |
| `labcheck_swap_used_percent` | | Swap in use |
| `labcheck_uptime_seconds` | | Uptime |
| `labcheck_temperature_celsius` | | Hottest thermal sensor |
| `labcheck_disk_used_percent`, `labcheck_disk_used_bytes`, `labcheck_disk_size_bytes` | `mount`, `fstype` | Filesystem usage |
| `labcheck_inode_used_percent` | `mount`, `fstype` | Inode usage |
| `labcheck_failed_units` | | Number of failed systemd units |
| `labcheck_unit_failed` | `unit` | One series per failed unit |
| `labcheck_service_active` | `service` | Required service is active |
| `labcheck_containers_total`, `labcheck_containers_running`, `labcheck_containers_unhealthy` | | Docker counts |
| `labcheck_md_degraded` | `device` | RAID array is degraded |
| `labcheck_md_resync_percent` | `device` | Rebuild or scrub progress |
| `labcheck_smart_healthy` | `device` | SMART health verdict |
| `labcheck_backup_present`, `labcheck_backup_age_hours` | `target` | Generic file backup presence and freshness |
| `labcheck_backup_snapshot_present`, `labcheck_backup_snapshot_age_hours`, `labcheck_backup_incomplete_snapshots` | `snapshot` | Snapshot presence, age and incomplete snapshot count |
| `labcheck_backup_kopia_repository_accessible`, `labcheck_backup_kopia_source_present`, `labcheck_backup_kopia_source_age_hours`, `labcheck_backup_kopia_source_errors`, `labcheck_backup_kopia_sources_expected` | `source` where applicable | Kopia repository reachability and per-source snapshot presence, age and error counts |
| `labcheck_backup_timer_enabled`, `labcheck_backup_timer_active`, `labcheck_backup_service_success` | `target` (generic targets), `snapshot` (snapshot monitors) | Backup timer enabled state, active state and last service-run success |
| `labcheck_certificate_days_remaining` | `host`, `port` | Days until expiry |
| `labcheck_ntp_synchronized` | | Clock is synchronised |

## How it works

```text
labcheck/
├── labcheck/
│   ├── __main__.py       python -m labcheck
│   ├── cli.py            argument parsing, execution, output
│   ├── config.py         TOML schema and validation
│   ├── context.py        injectable clock, runner and filesystem roots
│   ├── formatters.py     text, JSON and Prometheus renderers
│   ├── model.py          status, metrics, results, report
│   ├── runner.py         subprocess wrapper that never raises
│   ├── util.py           formatting helpers
│   └── checks/           one module per check
└── tests/                stdlib unittest suite
```

Checks receive a `Context` containing the config, a command runner, the current
time and filesystem roots. Tests use fake runners and fixture `/proc` trees, so
the suite needs no Docker daemon, systemd session or real disks. One test spins
up a local TLS server with a checked-in self-signed certificate to exercise the
certificate fetch path.

The code intentionally keeps the runtime surface small:

- no shell invocation and no shell expansion;
- subprocess timeouts on every external command;
- check exceptions become an `ERROR` result instead of aborting the report;
- output files are written atomically;
- non-UTF-8 terminals do not crash the text renderer.

## Development

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q labcheck
python3 -m labcheck --list-checks
```

If you have `make` and Ruff installed, `make check` runs the tests plus lint and
format checks. The runtime must stay standard-library-only. New checks should
get pure parser tests where possible and integration tests driven by fakes.

## Limitations

- Linux only; the tool reads Linux-specific interfaces.
- systemd checks and the clock check are skipped where systemd is not PID 1.
- Docker is supported; Podman is not (yet).
- The backup check verifies age and presence, not restoreability.
- The certificate check deliberately disables chain and hostname verification.
  It answers "when does this endpoint's certificate expire?", which is useful
  with private CAs, but it is not a replacement for `curl`/browser validation.
- Temperature is the hottest readable sensor, which may be a board or NVMe
  sensor rather than the CPU package.
- SMART health depends on the drive and controller; USB bridges often hide it.
- `labcheck` reports problems; it does not send notifications itself.

## Security

`labcheck` is read-only, but some checks need privileged access: `systemctl`
queries the system bus, `smartctl` opens block devices, and talking to the
Docker daemon is equivalent to root on the host. Run it as root when using those
checks, or skip them in an unprivileged cron job. The generated Prometheus file
can reveal hostnames, mount points and service names, so protect the textfile
collector directory accordingly.

The certificate check does not send credentials and does not validate the
certificate chain. See [SECURITY.md](SECURITY.md) for private vulnerability
reporting and the full security scope.

## Contributing and license

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). User-visible changes are recorded in
[CHANGELOG.md](CHANGELOG.md).

MIT. See [LICENSE](LICENSE).
