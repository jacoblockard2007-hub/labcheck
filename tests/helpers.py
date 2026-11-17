"""Shared fixtures for the labcheck test suite."""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from labcheck.config import Config
from labcheck.context import Context
from labcheck.runner import CommandResult

FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"


class FakeRunner:
    """In-memory command runner.

    ``responses`` maps either an exact command line or a command prefix to a
    ``(returncode, stdout, stderr)`` tuple, a :class:`CommandResult`, or a
    callable receiving the argv tuple.
    """

    def __init__(
        self,
        available: Iterable[str] = (),
        responses: Mapping[str, Any] | None = None,
    ) -> None:
        self.available = set(available)
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, ...]] = []

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.available else None

    def run(self, args: Iterable[str], timeout: float = 5.0) -> CommandResult:
        argv = tuple(str(arg) for arg in args)
        self.calls.append(argv)
        key = " ".join(argv)
        response = self.responses.get(key)
        if response is None:
            for prefix, candidate in self.responses.items():
                if key.startswith(prefix):
                    response = candidate
                    break
        if response is None:
            return CommandResult(argv, 127, found=False, stderr="command not found")
        if callable(response):
            response = response(argv)
        if isinstance(response, CommandResult):
            return CommandResult(
                argv,
                response.returncode,
                response.stdout,
                response.stderr,
                response.found,
                response.timed_out,
            )
        returncode, stdout, stderr = response
        return CommandResult(argv, returncode, stdout, stderr)


class LabcheckTestCase(unittest.TestCase):
    """Base class that builds isolated /proc and /sys trees."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="labcheck-test-")
        self.temp = Path(self._temporary.name)
        self.proc = self.temp / "proc"
        self.sys = self.temp / "sys"
        self.proc.mkdir()
        self.sys.mkdir()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def write_proc(self, name: str, content: str) -> Path:
        path = self.proc / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_sys(self, name: str, content: str) -> Path:
        path = self.sys / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def context(
        self,
        config: Config | None = None,
        runner: FakeRunner | None = None,
        now: datetime | None = None,
    ) -> Context:
        return Context(
            config=config or Config(),
            runner=runner or FakeRunner(),
            now=now or FIXED_NOW,
            proc=self.proc,
            sys=self.sys,
            root=self.temp,
        )


def statvfs(
    *,
    total: int = 100 * 1024**3,
    free: int = 70 * 1024**3,
    available: int | None = None,
    files: int = 1_000_000,
    files_free: int = 900_000,
    files_available: int | None = None,
) -> SimpleNamespace:
    """Build an object shaped like ``os.statvfs`` output."""
    available = free if available is None else available
    files_available = files_free if files_available is None else files_available
    return SimpleNamespace(
        f_bsize=4096,
        f_frsize=4096,
        f_blocks=total // 4096,
        f_bfree=free // 4096,
        f_bavail=available // 4096,
        f_files=files,
        f_ffree=files_free,
        f_favail=files_available,
    )


def response(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> tuple[int, str, str]:
    return (returncode, stdout, stderr)
