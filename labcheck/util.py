"""Small helpers shared by checks and formatters."""

from __future__ import annotations

import os


def human_bytes(value: float) -> str:
    """Format a byte count with binary units."""
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    amount = float(value)
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} B"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} PiB"  # pragma: no cover - unreachable


def human_duration(seconds: float) -> str:
    """Format a duration as ``12d 4h``, ``3h 07m`` or ``42s``."""
    total = int(max(0, seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m {secs:02d}s" if minutes < 10 else f"{minutes}m"
    return f"{secs}s"


def percent(used: float, total: float) -> float:
    """Safe percentage calculation."""
    if total <= 0:
        return 0.0
    return used / total * 100.0


def read_text(path: os.PathLike[str] | str, limit: int = 4_000_000) -> str | None:
    """Read a text file, returning ``None`` instead of raising."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return None


def truncate(text: str, limit: int) -> str:
    """Collapse whitespace and shorten to ``limit`` characters."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)].rstrip() + "…"
