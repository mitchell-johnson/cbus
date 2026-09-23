"""Opt-in native TLS acceptance; no existing oracle or credentials are reused."""
import importlib.util
import os
from pathlib import Path
import unittest

_path = Path(__file__).resolve().parents[1] / "research/verify_tls.py"
_spec = importlib.util.spec_from_file_location("cbus_verify_native_tls", _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


@unittest.skipUnless(os.environ.get("CBUS_NATIVE_TLS_TEST") == "1",
                     "Set CBUS_NATIVE_TLS_TEST=1 to create a disposable native TLS oracle")
class NativeTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = _module.verify(output=os.environ.get("CBUS_NATIVE_TLS_REPORT"))

    def test_exact_native_verified_tls_and_cli_project_lifecycle(self):
        self.assertTrue(self.report["passed"])
        self.assertIn("v3.4.0 (build 2001)", self.report["greeting"])
        self.assertIn(self.report["tls_version"], ("TLSv1.2", "TLSv1.3"))
        self.assertEqual(self.report["native_noop"], "200 OK.")
        self.assertEqual(self.report["verification_defaults"], {"check_hostname": True, "verify_mode": "CERT_REQUIRED"})
        cases = {row["case"]: row for row in self.report["cases"]}
        for name in ("verified_mutual_tls_noop", "verified_mutual_tls_project_lifecycle", "verified_connection_after_rejections"):
            self.assertTrue(cases[name]["passed"])
            self.assertEqual(cases[name]["exit_status"], 0)
        self.assertEqual(self.report["cleanup_errors"], [])

    def test_native_server_rejects_missing_untrusted_and_expired_client_certificates(self):
        cases = {row["case"]: row for row in self.report["cases"]}
        for name in ("missing_client_certificate", "untrusted_client_certificate", "expired_client_certificate"):
            with self.subTest(case=name):
                self.assertEqual(cases[name]["exit_status"], 1)
                self.assertEqual(cases[name]["stdout"], "")
                self.assertEqual(cases[name]["tls_failure"]["type"], "SSLError")
                self.assertIsNotNone(cases[name]["tls_failure"]["reason"])

    def test_client_rejects_untrusted_server_and_hostname_mismatch(self):
        cases = {row["case"]: row for row in self.report["cases"]}
        for name in ("untrusted_server_certificate", "server_hostname_mismatch"):
            with self.subTest(case=name):
                self.assertEqual(cases[name]["exit_status"], 1)
                self.assertEqual(cases[name]["tls_failure"]["type"], "SSLCertVerificationError")
                self.assertIsNotNone(cases[name]["tls_failure"]["verify_code"])


if __name__ == "__main__":
    unittest.main()
