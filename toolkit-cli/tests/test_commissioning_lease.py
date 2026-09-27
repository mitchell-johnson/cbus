"""Cross-process selected-serial lease, independent of C-Bus hardware."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.commissioning_lease import EndpointLease
from cbus_toolkit import commissioning_lease


HOST = "127.0.0.1"
PORT = 49437


def child_attempt(host: str, port: int, *, env=None) -> subprocess.CompletedProcess[str]:
    code = (
        "from cbus_toolkit.commissioning_lease import EndpointLease, EndpointLeaseBusy\n"
        "try:\n"
        "    with EndpointLease(__import__('sys').argv[1], int(__import__('sys').argv[2])):\n"
        "        print('acquired')\n"
        "except EndpointLeaseBusy:\n"
        "    print('busy')\n"
        "    raise SystemExit(17)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code, host, str(port)],
        capture_output=True, text=True, timeout=10, env=env,
    )


class EndpointLeaseTests(unittest.TestCase):
    def test_same_lease_cannot_be_reentered(self):
        lease = EndpointLease(HOST, PORT)
        with lease:
            with self.assertRaisesRegex(RuntimeError, "already held"):
                with lease:
                    pass
            blocked = child_attempt(HOST, PORT)
            self.assertEqual((blocked.returncode, blocked.stdout.strip()), (17, "busy"), blocked.stderr)

    def test_second_process_is_refused_and_can_acquire_after_release(self):
        with EndpointLease(HOST, PORT):
            blocked = child_attempt(HOST, PORT)
            self.assertEqual((blocked.returncode, blocked.stdout.strip()), (17, "busy"), blocked.stderr)
            other = child_attempt(HOST, PORT + 1)
            self.assertEqual((other.returncode, other.stdout.strip()), (0, "acquired"), other.stderr)
        available = child_attempt(HOST, PORT)
        self.assertEqual((available.returncode, available.stdout.strip()), (0, "acquired"), available.stderr)

    def test_abrupt_process_exit_releases_lease(self):
        code = (
            "import os, sys\n"
            "from cbus_toolkit.commissioning_lease import EndpointLease\n"
            "with EndpointLease(sys.argv[1], int(sys.argv[2])):\n"
            "    print('held', flush=True)\n"
            "    os._exit(0)\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", code, HOST, str(PORT)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual((child.returncode, child.stdout.strip()), (0, "held"), child.stderr)
        with EndpointLease(HOST, PORT):
            pass

    @unittest.skipIf(os.name != "posix", "Fixed /tmp lease namespace is POSIX-specific")
    def test_changed_tmpdir_cannot_bypass_host_endpoint_lease(self):
        with tempfile.TemporaryDirectory() as other_temp:
            env = dict(os.environ, TMPDIR=other_temp, TMP=other_temp, TEMP=other_temp)
            with EndpointLease(HOST, PORT):
                blocked = child_attempt(HOST, PORT, env=env)
                self.assertEqual((blocked.returncode, blocked.stdout.strip()), (17, "busy"), blocked.stderr)

    @unittest.skipIf(os.name == "nt", "No-follow filesystem check is POSIX-specific")
    def test_symlinked_lease_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(commissioning_lease, "_directory", return_value=root):
                lease = EndpointLease(HOST, PORT)
                target = root / "target"
                target.write_bytes(b"unchanged")
                lease.path.symlink_to(target)
                with self.assertRaises(OSError):
                    with lease:
                        pass
                self.assertEqual(target.read_bytes(), b"unchanged")


if __name__ == "__main__":
    unittest.main()
