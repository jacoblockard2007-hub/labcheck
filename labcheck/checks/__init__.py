"""The built-in checks and how they are selected.

Each check module exposes ``NAME``, ``TITLE``, ``DESCRIPTION`` and a
``run(context) -> CheckResult`` function.  Checks must never raise for expected
conditions (missing tools, unreadable files); they report ``ERROR`` instead.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ..config import Config
from ..context import Context
from ..model import CheckResult
from . import (
    backups,
    certificates,
    clock,
    containers,
    raid,
    services,
    smart,
    storage,
    system,
)

CheckFunc = Callable[[Context], CheckResult]


@dataclass(frozen=True)
class CheckSpec:
    """Registry entry describing one check."""

    name: str
    title: str
    description: str
    config_key: str
    func: CheckFunc


CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec(system.NAME, system.TITLE, system.DESCRIPTION, "system", system.run),
    CheckSpec(storage.NAME, storage.TITLE, storage.DESCRIPTION, "storage", storage.run),
    CheckSpec(
        services.NAME, services.TITLE, services.DESCRIPTION, "systemd", services.run
    ),
    CheckSpec(
        containers.NAME,
        containers.TITLE,
        containers.DESCRIPTION,
        "docker",
        containers.run,
    ),
    CheckSpec(raid.NAME, raid.TITLE, raid.DESCRIPTION, "raid", raid.run),
    CheckSpec(smart.NAME, smart.TITLE, smart.DESCRIPTION, "smart", smart.run),
    CheckSpec(backups.NAME, backups.TITLE, backups.DESCRIPTION, "backups", backups.run),
    CheckSpec(
        certificates.NAME,
        certificates.TITLE,
        certificates.DESCRIPTION,
        "certificates",
        certificates.run,
    ),
    CheckSpec(clock.NAME, clock.TITLE, clock.DESCRIPTION, "clock", clock.run),
)

BY_NAME = {spec.name: spec for spec in CHECKS}


def names() -> list[str]:
    return [spec.name for spec in CHECKS]


def is_enabled(spec: CheckSpec, config: Config) -> bool:
    section = getattr(config, spec.config_key)
    return bool(getattr(section, "enabled", True))


def select(
    config: Config,
    only: Sequence[str] | None = None,
    skip: Sequence[str] | None = None,
) -> list[CheckSpec]:
    """Pick checks based on config and ``--only`` / ``--skip``.

    ``--only`` may select checks that are disabled in the config; that is how a
    user runs a one-off check.  Unknown names raise :class:`KeyError`.
    """
    if only:
        unknown = [name for name in only if name not in BY_NAME]
        if unknown:
            raise KeyError(", ".join(sorted(unknown)))
        selected = [spec for spec in CHECKS if spec.name in set(only)]
    else:
        selected = [spec for spec in CHECKS if is_enabled(spec, config)]

    if skip:
        unknown = [name for name in skip if name not in BY_NAME]
        if unknown:
            raise KeyError(", ".join(sorted(unknown)))
        skipped = set(skip)
        selected = [spec for spec in selected if spec.name not in skipped]
    return selected


def split_names(values: Iterable[str]) -> list[str]:
    """Flatten repeated comma-separated CLI options into a list of names."""
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part not in result:
                result.append(part)
    return result
