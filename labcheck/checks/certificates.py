"""TLS certificate expiry for configured endpoints."""

from __future__ import annotations

import math
import os
import socket
import ssl
import tempfile
from datetime import UTC, datetime
from typing import Any

from ..config import CertificateTarget
from ..context import Context
from ..model import CheckResult, Metric, Status, worse

NAME = "certificates"
TITLE = "Certificates"
DESCRIPTION = "TLS certificate expiry for remote endpoints"


def run(ctx: Context) -> CheckResult:
    cfg = ctx.config.certificates
    if not cfg.targets:
        return CheckResult(
            name=NAME,
            title=TITLE,
            status=Status.SKIP,
            summary="no certificate targets configured",
            details=["add [[certificates.targets]] entries to check TLS certificates"],
        )

    status = Status.OK
    details: list[str] = []
    metrics: list[Metric] = []
    problems: list[str] = []
    valid = 0
    nearest: tuple[float, str] | None = None

    for target in cfg.targets:
        label = f"{target.host}:{target.port}"
        try:
            decoded = _fetch(target, cfg.timeout_seconds)
            expiry = _expiry(decoded)
        except (OSError, ssl.SSLError, ValueError, TypeError, KeyError) as exc:
            status = worse(status, Status.ERROR)
            problems.append(f"{label} unreadable")
            details.append(f"{label}: {exc}")
            continue

        days = (expiry - ctx.now.timestamp()) / 86400.0
        expires = datetime.fromtimestamp(expiry, tz=UTC).strftime("%Y-%m-%d")
        metrics.append(
            Metric(
                "certificate_days_remaining",
                round(days, 2),
                {"host": target.host, "port": str(target.port)},
                "Days until the certificate expires",
            )
        )
        if nearest is None or days < nearest[0]:
            nearest = (days, label)

        issuer = _common_name(decoded, "issuer")
        subject = _common_name(decoded, "subject")
        suffix = f" [{subject} issued by {issuer}]" if subject and issuer else ""

        if days < 0:
            status = worse(status, Status.CRIT)
            problems.append(f"{label} expired")
            expired_days = max(1, math.ceil(abs(days)))
            details.append(
                f"{label}: expired {expired_days} day(s) ago on {expires}{suffix}"
            )
        elif days <= target.crit_days:
            status = worse(status, Status.CRIT)
            problems.append(f"{label} {int(days)}d left")
            details.append(
                f"{label}: expires {expires} in {int(days)} day(s), "
                f"critical threshold {target.crit_days:g}{suffix}"
            )
        elif days <= target.warn_days:
            status = worse(status, Status.WARN)
            problems.append(f"{label} {int(days)}d left")
            details.append(
                f"{label}: expires {expires} in {int(days)} day(s), "
                f"warning threshold {target.warn_days:g}{suffix}"
            )
        else:
            valid += 1
            details.append(f"{label}: expires {expires} in {int(days)} day(s){suffix}")

    if problems:
        summary = ", ".join(problems)
        if valid:
            summary += f"; {valid}/{len(cfg.targets)} valid"
    elif nearest is not None:
        summary = f"{valid} certificate" + ("" if valid == 1 else "s") + " valid"
        summary += f", nearest {int(nearest[0])}d ({nearest[1]})"
    else:
        summary = "no certificates checked"

    return CheckResult(
        name=NAME,
        title=TITLE,
        status=status,
        summary=summary,
        details=details,
        metrics=metrics,
    )


def _fetch(target: CertificateTarget, timeout: float) -> dict[str, Any]:
    """Connect, retrieve the peer certificate and decode its fields."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with (
        socket.create_connection((target.host, target.port), timeout=timeout) as raw,
        context.wrap_socket(raw, server_hostname=target.host) as tls,
    ):
        der = tls.getpeercert(binary_form=True)
    if not der:
        raise ValueError("server did not present a certificate")

    decoder = getattr(getattr(ssl, "_ssl", None), "_test_decode_cert", None)
    if decoder is None:
        raise ValueError("this Python build cannot decode certificates")

    pem = ssl.DER_cert_to_PEM_cert(der)
    descriptor, path = tempfile.mkstemp(suffix=".pem", prefix="labcheck-")
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(pem)
        return decoder(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _expiry(decoded: dict[str, Any]) -> float:
    not_after = decoded.get("notAfter")
    if not isinstance(not_after, str):
        raise TypeError("certificate has no notAfter field")
    return float(ssl.cert_time_to_seconds(not_after))


def _common_name(decoded: dict[str, Any], key: str) -> str:
    try:
        for relative_name in decoded.get(key, ()):
            for name, value in relative_name:
                if name == "commonName":
                    return str(value)
    except (TypeError, ValueError):
        pass
    return ""
