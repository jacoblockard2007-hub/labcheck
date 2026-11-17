"""Thin, testable wrapper around external commands."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

#: Cron jobs often have a PATH without the sbin directories.  smartctl and
#: some other tools live there, so look in the conventional locations when the
#: PATH search fails.
FALLBACK_DIRECTORIES = ("/usr/sbin", "/sbin", "/usr/local/sbin")


@dataclass(frozen=True)
class CommandResult:
    """Outcome of running a command."""

    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    found: bool = True
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def message(self) -> str:
        """First useful line of error output."""
        for stream in (self.stderr, self.stdout):
            for line in stream.splitlines():
                if line.strip():
                    return line.strip()
        return "no output"


class RunnerLike(Protocol):
    """What checks need from a command runner (implemented by fakes in tests)."""

    def which(self, name: str) -> str | None: ...

    def run(self, args: Sequence[str], timeout: float = 5.0) -> CommandResult: ...


class Runner:
    """Run commands without shell expansion and without raising."""

    def which(self, name: str) -> str | None:
        found = shutil.which(name)
        if found:
            return found
        for directory in FALLBACK_DIRECTORIES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def run(self, args: Sequence[str], timeout: float = 5.0) -> CommandResult:
        argv = tuple(str(arg) for arg in args)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return CommandResult(argv, 127, found=False, stderr="command not found")
        except subprocess.TimeoutExpired:
            return CommandResult(argv, 124, timed_out=True, stderr="command timed out")
        except OSError as exc:
            return CommandResult(argv, 126, stderr=str(exc))
        return CommandResult(
            argv,
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )
