from __future__ import annotations

import socket
import ssl
import threading
import unittest
from unittest import mock

from labcheck.checks import certificates
from labcheck.config import CertificatesConfig, CertificateTarget, Config
from tests.helpers import FIXED_NOW, FIXTURES, LabcheckTestCase

CERT = FIXTURES / "test-cert.pem"
KEY = FIXTURES / "test-key.pem"


def decoded_certificate(not_after: str | None = None) -> dict:
    decoded = ssl._ssl._test_decode_cert(str(CERT))
    if not_after is not None:
        decoded = dict(decoded)
        decoded["notAfter"] = not_after
    return decoded


class CertificatesCheckTest(LabcheckTestCase):
    def config(self, *targets: CertificateTarget) -> Config:
        return Config(certificates=CertificatesConfig(targets=list(targets)))

    def target(
        self,
        host: str = "example.com",
        port: int = 443,
        warn_days: float = 14,
        crit_days: float = 7,
    ) -> CertificateTarget:
        return CertificateTarget(
            host=host, port=port, warn_days=warn_days, crit_days=crit_days
        )

    def run_check(self, config: Config, decoded: dict | None = None, error=None):
        patcher = mock.patch(
            "labcheck.checks.certificates._fetch",
            return_value=decoded if decoded is not None else decoded_certificate(),
            side_effect=error,
        )
        with patcher:
            return certificates.run(self.context(config=config))

    def test_no_targets_is_skipped(self) -> None:
        result = certificates.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("no certificate targets", result.summary)

    def test_valid_certificate(self) -> None:
        result = self.run_check(
            self.config(self.target()),
            decoded_certificate("Jul  1 12:00:00 2026 GMT"),
        )
        self.assertEqual(result.status.value, "ok")
        self.assertIn("1 certificate valid", result.summary)
        self.assertIn("nearest 30d (example.com:443)", result.summary)
        metric = result.metrics[0]
        self.assertEqual(metric.name, "certificate_days_remaining")
        self.assertEqual(metric.labels, {"host": "example.com", "port": "443"})
        self.assertAlmostEqual(metric.value, 30.0, places=1)

    def test_warning_threshold_is_inclusive(self) -> None:
        result = self.run_check(
            self.config(self.target(warn_days=14, crit_days=7)),
            decoded_certificate("Jun 15 12:00:00 2026 GMT"),
        )
        self.assertEqual(result.status.value, "warn")
        self.assertIn("example.com:443 14d left", result.summary)
        self.assertIn("warning threshold 14", "\n".join(result.details))

    def test_critical_threshold_is_inclusive(self) -> None:
        result = self.run_check(
            self.config(self.target(warn_days=14, crit_days=7)),
            decoded_certificate("Jun  8 12:00:00 2026 GMT"),
        )
        self.assertEqual(result.status.value, "crit")
        self.assertIn("example.com:443 7d left", result.summary)
        self.assertIn("critical threshold 7", "\n".join(result.details))

    def test_expired_certificate(self) -> None:
        result = self.run_check(
            self.config(self.target()),
            decoded_certificate("May 20 12:00:00 2026 GMT"),
        )
        self.assertEqual(result.status.value, "crit")
        self.assertIn("example.com:443 expired", result.summary)
        self.assertIn("expired 12 day(s) ago", "\n".join(result.details))

    def test_recently_expired_certificate_reports_at_least_one_day(self) -> None:
        result = self.run_check(
            self.config(self.target()),
            decoded_certificate("Jun  1 00:00:00 2026 GMT"),
        )
        self.assertEqual(result.status.value, "crit")
        self.assertIn("expired 1 day(s) ago", "\n".join(result.details))

    def test_custom_thresholds(self) -> None:
        config = self.config(self.target(warn_days=30, crit_days=20))
        warn = self.run_check(config, decoded_certificate("Jun 26 12:00:00 2026 GMT"))
        self.assertEqual(warn.status.value, "warn")
        crit = self.run_check(config, decoded_certificate("Jun 21 12:00:00 2026 GMT"))
        self.assertEqual(crit.status.value, "crit")

    def test_fetch_error_is_an_error(self) -> None:
        result = self.run_check(
            self.config(self.target()), error=OSError("connection refused")
        )
        self.assertEqual(result.status.value, "error")
        self.assertIn("example.com:443 unreadable", result.summary)
        self.assertIn("connection refused", "\n".join(result.details))

    def test_multiple_targets(self) -> None:
        result = self.run_check(
            self.config(self.target(), self.target(host="other.example", port=8443)),
            decoded_certificate("Jul  1 12:00:00 2026 GMT"),
        )
        self.assertEqual(result.status.value, "ok")
        self.assertIn("2 certificates valid", result.summary)

    def test_details_include_subject_and_issuer(self) -> None:
        result = self.run_check(self.config(self.target()))
        details = "\n".join(result.details)
        self.assertIn("labcheck-test", details)
        self.assertIn("issued by", details)

    def test_expiry_without_not_after_field(self) -> None:
        with self.assertRaises(TypeError):
            certificates._expiry({"subject": ()})

    def test_common_name_handles_missing_fields(self) -> None:
        self.assertEqual(certificates._common_name({}, "subject"), "")
        self.assertEqual(certificates._common_name({"subject": "bad"}, "subject"), "")

    def test_fetch_against_local_tls_server(self) -> None:
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(str(CERT), str(KEY))

        listener = socket.socket()
        listener.settimeout(5)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        errors: list[Exception] = []

        def serve() -> None:
            try:
                connection, _ = listener.accept()
                with (
                    connection,
                    server_context.wrap_socket(connection, server_side=True),
                ):
                    pass
            except Exception as exc:  # noqa: BLE001  # pragma: no cover - failure path
                errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            target = CertificateTarget(host="127.0.0.1", port=port)
            decoded = certificates._fetch(target, 5.0)
        finally:
            listener.close()
            thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertGreater(certificates._expiry(decoded), FIXED_NOW.timestamp())
        self.assertEqual(certificates._common_name(decoded, "subject"), "labcheck-test")


if __name__ == "__main__":
    unittest.main()
