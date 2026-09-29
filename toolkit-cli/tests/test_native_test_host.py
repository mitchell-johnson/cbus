"""The owned native test host never adopts an externally supplied endpoint."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pytest

from tests import conftest


class OwnedTestHostTests(unittest.TestCase):
    def test_local_backend_refuses_an_external_test_host(self):
        for name in conftest.HOST_VARIABLES:
            with self.subTest(name=name), patch.dict(os.environ, {
                    "CBUS_NATIVE_SERVICE_BACKEND": "local", name: "192.0.2.1"}):
                with self.assertRaisesRegex(pytest.UsageError, "owns the C-Gate test host"):
                    conftest.pytest_configure(None)
        with patch.dict(os.environ, {"CBUS_NATIVE_SERVICE_BACKEND": "docker",
                                     "CBUS_CGATE_TEST_HOST": "127.0.0.1"}):
            conftest.pytest_configure(None)

    def test_service_starts_only_for_host_modules_under_explicit_local_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            host = root / "test_host.py"
            host.write_text("import os\nHOST = os.environ.get('CBUS_CGATE_TEST_HOST')\n")
            offline = root / "test_offline.py"
            offline.write_text("def test_offline(): pass\n")
            helper = root / "helper.py"
            helper.write_text("CBUS_CGATE_TEST_HOST = None\n")
            self.assertTrue(conftest._needs_test_host(host))
            self.assertFalse(conftest._needs_test_host(offline))
            self.assertFalse(conftest._needs_test_host(helper))
            with patch.object(conftest, "_start_owned_service") as start:
                with patch.dict(os.environ, {"CBUS_NATIVE_SERVICE_BACKEND": "docker",
                                             "CBUS_LOCAL_CGATE_VENDOR": folder, "CBUS_CGATE_JAVA": "java"}):
                    conftest.pytest_collect_file(host, None)
                with patch.dict(os.environ, {"CBUS_NATIVE_SERVICE_BACKEND": "local",
                                             "CBUS_LOCAL_CGATE_VENDOR": "", "CBUS_CGATE_JAVA": ""}):
                    conftest.pytest_collect_file(host, None)
                with patch.dict(os.environ, {"CBUS_NATIVE_SERVICE_BACKEND": "local",
                                             "CBUS_LOCAL_CGATE_VENDOR": folder, "CBUS_CGATE_JAVA": "java"}):
                    conftest.pytest_collect_file(offline, None)
                    start.assert_not_called()
                    conftest.pytest_collect_file(host, None)
                start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
