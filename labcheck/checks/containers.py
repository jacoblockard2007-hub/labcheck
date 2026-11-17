"""Docker container state."""

from __future__ import annotations

import fnmatch
import json
from typing import Any

from ..context import Context
from ..model import CheckResult, Metric, Status, worse
from ..util import truncate

NAME = "docker"
TITLE = "Containers"
DESCRIPTION = "Docker container state and required containers"

UNHEALTHY_STATES = {"restarting", "dead"}
STOPPED_STATES = {"created", "exited", "paused", "removing"}


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.docker
    if ctx.runner.which("docker") is None:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="docker not installed",
            details=["the docker CLI was not found on PATH"],
        )

    result = ctx.runner.run(
        ["docker", "ps", "-a", "--format", "{{json .}}"], timeout=15
    )
    if result.returncode != 0:
        message = truncate(result.message, 200)
        if _daemon_down(result.stderr):
            return CheckResult(
                name=NAME,
                title=TITLE,
                status=Status.CRIT,
                summary="docker daemon unreachable",
                details=[message],
            )
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.ERROR,
            summary="docker ps failed",
            details=[message],
        )

    containers = _parse(result.stdout)
    if containers is None:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.ERROR,
            summary="cannot parse docker ps output",
            details=["expected one JSON object per line from docker ps"],
        )

    status = Status.OK
    details: list[str] = []
    unhealthy: list[str] = []
    running = 0
    checked: list[dict[str, Any]] = []

    for container in containers:
        aliases = [
            alias.strip()
            for alias in str(container.get("Names", "")).split(",")
            if alias.strip()
        ]
        name = aliases[0] if aliases else "unknown"
        if any(_matches_any(alias, cfg.ignore) for alias in aliases):
            continue
        checked.append(container)

        state = str(container.get("State", "")).lower()
        description = truncate(str(container.get("Status", state or "unknown")), 80)
        if state == "running":
            running += 1
            if "unhealthy" in description.lower():
                status = worse(status, Status.CRIT)
                unhealthy.append(name)
                details.append(f"{name}: unhealthy ({description})")
            continue
        if state in UNHEALTHY_STATES or "unhealthy" in description.lower():
            status = worse(status, Status.CRIT)
            unhealthy.append(name)
            details.append(f"{name}: {state or 'unhealthy'} ({description})")
        elif state in STOPPED_STATES:
            status = worse(status, Status.WARN)
            details.append(f"{name}: {state} ({description})")
        else:
            status = worse(status, Status.WARN)
            details.append(f"{name}: unexpected state {state!r} ({description})")

    missing_required: list[str] = []
    for pattern in cfg.require_running:
        matched = [
            container
            for container in checked
            if any(
                fnmatch.fnmatchcase(name, pattern)
                for name in str(container.get("Names", "")).split(",")
            )
        ]
        if not matched:
            status = worse(status, Status.CRIT)
            missing_required.append(pattern)
            details.append(f"required container {pattern!r} was not found")
            continue
        for container in matched:
            state = str(container.get("State", "")).lower()
            if (
                state != "running"
                or "unhealthy" in str(container.get("Status", "")).lower()
            ):
                status = worse(status, Status.CRIT)
                name = str(container.get("Names", "")).split(",")[0].strip()
                missing_required.append(pattern)
                details.append(
                    f"required container {name or pattern!r} is not running "
                    f"({state or 'unknown'})"
                )

    total = len(checked)
    stopped = total - running
    metrics = [
        Metric("containers_total", total, {}, "Containers included in the check"),
        Metric("containers_running", running, {}, "Running containers"),
        Metric("containers_unhealthy", len(set(unhealthy)), {}, "Unhealthy containers"),
    ]

    if total == 0:
        summary = "no containers"
    elif unhealthy:
        summary = f"{len(set(unhealthy))} unhealthy: " + ", ".join(
            sorted(set(unhealthy))[:3]
        )
        if stopped and not running:
            summary += f"; {stopped} stopped"
    elif stopped:
        summary = f"{running} running, {stopped} stopped"
    else:
        summary = f"{running} running"
    if missing_required:
        summary += f"; required missing: {', '.join(dict.fromkeys(missing_required))}"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _parse(output: str) -> list[dict[str, Any]] | None:
    containers: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            return None
        if not isinstance(item, dict):
            return None
        containers.append(item)
    return containers


def _daemon_down(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        marker in lowered
        for marker in (
            "cannot connect to the docker daemon",
            "is the docker daemon running",
            "connection refused",
            "error during connect",
        )
    )


def _matches_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)
