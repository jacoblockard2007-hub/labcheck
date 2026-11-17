"""Execution context passed to every check."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config
from .runner import RunnerLike
from .util import read_text


@dataclass
class Context:
    """Config, clock, command runner and filesystem roots for a check run.

    The filesystem roots are parameters rather than hard-coded paths so the
    checks can be exercised against fixtures in tests.
    """

    config: Config
    runner: RunnerLike
    now: datetime
    proc: Path = field(default_factory=lambda: Path("/proc"))
    sys: Path = field(default_factory=lambda: Path("/sys"))
    root: Path = field(default_factory=lambda: Path("/"))

    def read_proc(self, name: str) -> str | None:
        return read_text(self.proc / name)
