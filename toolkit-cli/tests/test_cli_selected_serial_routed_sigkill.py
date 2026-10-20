"""Routed-plan SIGKILL recovery: kill mid-routed-apply, resume read-only.

One-hop routed plan through bridge 253 over a request-routed loopback peer
(ephemeral 127.0.0.1 port, no hardware). The peer persists the routed move
before replying, so SIGKILL after the routed address request leaves a durable
marker plus journal. A fresh process must refuse a repeat apply before any
PCI I/O (zero new address bytes) and verify --recovery must resume read-only.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from cbus_toolkit.pci_selected_serial import (
    SelectedSerialCoordinator,
    _inventory_proof,
    route_from_project,
)
from tests.test_commissioning_route import line
from tests.test_pci_selected_serial import LOCAL, LOCAL_REQUEST, OPTIONS, OPTIONS_REQUEST, SETTINGS
from tests.test_pci_selected_serial_routed import (
    A,
    B,
    C,
    ONE,
    AFTER,
    BEFORE,
    identify4,
    mmi,
    receipt,
    routed_co,
    routed_identify_request,
    routed_mmi_request,
)
from tests.test_pci_serials import BARE_PCI


def _manager(endpoint, **options):
    return SelectedSerialCoordinator(*endpoint, **(SETTINGS | options))


class _RoutedLoopbackPeer:
    """Request-routed one-hop peer that persists the routed move before reply.

    Serves MMI/IDENTIFY4 from BEFORE until the routed address request arrives,
    then serves AFTER. Records every wire request. Tolerates an abrupt client
    disconnect (SIGKILL) mid-conversation and stays alive for fresh-process
    recovery on the same endpoint.
    """

    def __init__(self, route):
        self.route = list(route)
        self._lock = threading.Lock()
        self._requests = []
        self._errors = []
        self._moved = False
        self._stop = threading.Event()
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        listener.settimeout(0.5)
        self._listener = listener
        self.endpoint = listener.getsockname()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(5)
        self._listener.close()

    def requests(self):
        with self._lock:
            return list(self._requests)

    def moved(self):
        with self._lock:
            return self._moved

    def _response(self, request):
        route = self.route
        with self._lock:
            moved = self._moved
        if request == routed_co(route, A, 6):
            with self._lock:
                self._moved = True
            # Persist-then-reply: the move survives a kill during the reply
            # window, matching the direct fixture's durable-move behavior.
            return b"g." + receipt(route, 6, A)
        if request == routed_mmi_request(route):
            states = AFTER if moved else BEFORE
            return b"g." + mmi(route, states)
        for address in (6, 16, 255):
            if request == routed_identify_request(route, address):
                if address == 6:
                    return b"g." + identify4(route, 6, A) if moved else b"g."
                if address == 16:
                    return b"g." + identify4(route, 16, C)
                if moved:
                    return b"g." + identify4(route, 255, B)
                return b"g." + identify4(route, 255, A) + identify4(route, 255, B)
        if request == LOCAL_REQUEST:
            return b"g." + BARE_PCI
        if request == OPTIONS_REQUEST:
            return OPTIONS
        return None

    def _serve(self):
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                connection.settimeout(2)
                request = b""
                while not request.endswith(b"\r"):
                    try:
                        chunk = connection.recv(512)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    request += chunk
                if not request.endswith(b"\r"):
                    continue
                with self._lock:
                    self._requests.append(request)
                response = self._response(request)
                if response is None:
                    with self._lock:
                        self._errors.append("unexpected request %r" % (request,))
                    continue
                # Small scheduler headroom; far below the 0.2s test windows.
                time.sleep(0.02)
                try:
                    connection.sendall(response)
                except (BrokenPipeError, ConnectionResetError):
                    continue
                try:
                    while connection.recv(512):
                        pass
                except socket.timeout:
                    pass
                except (BrokenPipeError, ConnectionResetError):
                    pass
            finally:
                try:
                    connection.close()
                except OSError:
                    pass


class RoutedSigkillRecoveryTests(unittest.TestCase):
    def subprocess_cli(self, *args, status=0):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", *[str(item) for item in args]],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(process.returncode, status, process.stdout + process.stderr)
        return json.loads(process.stdout or process.stderr)

    @unittest.skipUnless(os.name == "posix", "SIGKILL crash recovery needs a POSIX process signal")
    def test_sigkill_mid_routed_apply_resumes_without_readdressing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / "plan.json"
            journal = tmp / "journal.json"
            second = tmp / "second.json"
            raw, _ = line(1)
            project = tmp / "project.xml"
            project.write_bytes(raw)
            derived, digest = route_from_project(project, source_network=254, target_network=253)
            self.assertEqual(derived, ONE)
            binding = {"project": project, "source_network": 254, "target_network": 253}
            binding_args = ["--project", str(project), "--source-network", "254", "--target-network", "253"]
            peer = _RoutedLoopbackPeer(ONE).start()
            try:
                endpoint = peer.endpoint
                plan = _manager(endpoint).plan(A, 6, route=derived, project_sha256=digest)
                path.write_text(json.dumps(plan.as_dict()))
                plan_bytes = path.read_bytes()
                expected_co = routed_co(ONE, A, 6)
                self.assertEqual(bytes.fromhex(plan.as_dict()["request_hex"]), expected_co)
                child = subprocess.Popen(
                    [sys.executable, "-m", "cbus_toolkit", "serial-address", "apply",
                     str(path), "--recovery", str(journal), *binding_args],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    deadline = time.monotonic() + 30
                    while True:
                        if child.poll() is not None:
                            raise AssertionError(
                                "Routed apply exited %s before its address request reached the peer"
                                % child.returncode
                            )
                        if any(item == expected_co for item in peer.requests()):
                            break
                        if time.monotonic() >= deadline:
                            raise AssertionError("Routed address request never reached the peer")
                        time.sleep(0.005)
                    os.kill(child.pid, signal.SIGKILL)
                    self.assertEqual(child.wait(timeout=15), -signal.SIGKILL)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                killed_requests = peer.requests()
                self.assertEqual(killed_requests.count(expected_co), 1)
                self.assertTrue(peer.moved())
                record = json.loads(journal.read_text())
                self.assertTrue(record["attempt_recorded"])
                self.assertEqual(record["operation"], "apply")
                self.assertEqual(record["plan"], plan.as_dict())
                endpoint_document = {"host": endpoint[0], "port": endpoint[1]}
                self.assertEqual(
                    _inventory_proof(record["before"], endpoint_document, 16, False, ONE),
                    _inventory_proof(plan.as_dict()["before"], endpoint_document, 16, False, ONE),
                )
                self.assertIsNone(record["after"])
                self.assertEqual(record["route_binding"]["route"], ONE)
                marker = Path(record["attempt_identity"])
                self.assertTrue(marker.is_file())
                self.assertEqual(marker.parent, journal.resolve().parent)
                envelope = json.loads(marker.read_text())
                self.assertEqual(envelope["format"], "cbus-selected-serial-attempt-v1")
                self.assertEqual(envelope["plan"], plan.as_dict())
                self.assertTrue(envelope["send_may_have_occurred"])
                self.assertTrue(envelope["read_only_recovery_only"])
                self.assertEqual(SelectedSerialCoordinator.load_recovery(journal).as_dict(), plan.as_dict())
                self.assertEqual(SelectedSerialCoordinator.load_recovery(marker).as_dict(), plan.as_dict())
                # Fresh journal path: the durable marker refuses before any
                # PCI I/O, so the routed address request is never repeated.
                repeat = self.subprocess_cli(
                    "serial-address", "apply", path, "--recovery", second, *binding_args, status=1
                )
                self.assertIn("read-only recovery only", repeat["error"])
                self.assertFalse(repeat["selected_serial_evidence"]["transport_invoked"])
                self.assertFalse(second.exists())
                self.assertEqual(peer.requests(), killed_requests)
                # Read-only resume from the journal in another new process.
                journal_bytes = journal.read_bytes()
                resumed = self.subprocess_cli("serial-address", "verify", "--recovery", journal, *binding_args)
                self.assertEqual(resumed["outcome"], "observed_expected_change")
                self.assertTrue(resumed["expected_identity_change"])
                self.assertFalse(resumed["send_attempted"])
                self.assertIsNone(resumed["exchange"])
                self.assertTrue(resumed["after_collection_complete"])
                self.assertTrue(resumed["after"]["complete"])
                self.assertEqual(journal.read_bytes(), journal_bytes)
                self.assertEqual(path.read_bytes(), plan_bytes)
                # Zero new address bytes: exactly one routed co across kill,
                # refused repeat and read-only verification.
                wire = peer.requests()
                self.assertEqual(wire.count(expected_co), 1)
                self.assertEqual(
                    wire[len(killed_requests):],
                    [routed_mmi_request(ONE), routed_identify_request(ONE, 6),
                     routed_identify_request(ONE, 16), routed_identify_request(ONE, 255),
                     routed_mmi_request(ONE)],
                )
                for evidence in (record, resumed):
                    self.assertTrue(evidence["exclusive_ownership_required"])
                    self.assertFalse(evidence["atomic_observation"])
                    self.assertFalse(evidence["firmware_persistence_verified"])
                    self.assertFalse(evidence["physical_compatibility_verified"])
                    self.assertEqual(evidence["automatic_retries"], 0)
                    self.assertFalse(evidence["automatic_rollback"])
            finally:
                peer.stop()
                if peer._errors:
                    self.fail("; ".join(peer._errors))


if __name__ == "__main__":
    unittest.main()
