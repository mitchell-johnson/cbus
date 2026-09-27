"""Project-resolved RECALL/IDENTIFY use the same independent route as WRITE."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from cbus_toolkit.cli import main
from cbus_toolkit import pci_routed_read_topology as topology
from cbus_toolkit import pci_routed_recall as recall_core
from cbus_toolkit import pci_routed_identify as identify_core
from cbus_toolkit.project import ProjectError
from tests.test_pci_routed_recall import Peer


RECALL_COMMAND = b"\\46FD12FC041A1E01g\r"
IDENTIFY_COMMAND = b"\\46FD12FC042101g\r"
RECALL_REPLY = b"86FD1002FC04821E00CB\r"
IDENTIFY_REPLY = b"86FD1002FC048201A543\r"


def project_file(directory: str) -> Path:
    path = Path(directory) / "house.xml"
    path.write_text(
        '<Installation><Project><TagName>HOUSE</TagName>'
        '<Network><TagName>Local</TagName><Address>254</Address>'
        '<Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>owned</InterfaceAddress></Interface>'
        '<Unit><Address>253</Address><UnitType>BRIDGE2N</UnitType></Unit></Network>'
        '<Network><TagName>Middle</TagName><Address>253</Address>'
        '<Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>254/p/253</InterfaceAddress></Interface>'
        '<Unit><Address>252</Address><UnitType>BRIDGE2N</UnitType></Unit></Network>'
        '<Network><TagName>Remote</TagName><Address>252</Address>'
        '<Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>253/p/252</InterfaceAddress></Interface>'
        '<Unit><Address>4</Address><UnitType>KEYGL5</UnitType></Unit></Network>'
        '</Project></Installation>', encoding="utf-8")
    return path


class TypedRoutedReadCLITests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                status = main(arguments)
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def arguments(kind, path, port=10001, *, extra=()):
        selector = ["routed-recall", "4", "30", "1"] if kind == "recall" else [
            "routed-identify", "4", "1", "--expected-count", "1"]
        return ["--compact", "pci", "--host", "127.0.0.1", "--port", str(port),
                "--local-unit", "16", *selector, "--project-file", str(path),
                "--project-name", "HOUSE", "--source-network", "254",
                "--target-network", "252", *extra]

    def test_both_typed_reads_use_literal_two_bridge_wires_and_reply_paths(self):
        for kind, command, reply, expected in (
            ("recall", RECALL_COMMAND, RECALL_REPLY, "00"),
            ("identify", IDENTIFY_COMMAND, IDENTIFY_REPLY, "A5"),
        ):
            peer = Peer(command, [reply + b"g."])
            try:
                with tempfile.TemporaryDirectory() as directory:
                    path = project_file(directory)
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    code, stdout, stderr = self.invoke(self.arguments(
                        kind, path, peer.port, extra=("--project-sha256", digest)))
                self.assertEqual((code, stderr), (0, ""))
                result = json.loads(stdout)
                self.assertEqual(result["sent_hex"], command.hex().upper())
                self.assertEqual(result["data_hex"], expected)
                self.assertEqual(result["requested"]["bridges"], [253, 252])
                self.assertEqual(result["route_plan"]["project_sha256"], digest)
                self.assertEqual(result["route_plan"]["expected_reply_path"], {
                    "outer_source_byte": 253, "destination_byte": 16,
                    "route_entries": [252, 4],
                })
                self.assertNotIn("expected_ack_tag", result["route_plan"])
                self.assertTrue(result["logical_network_resolved"])
                self.assertTrue(result["topology_fresh_at_handoff"])
                self.assertFalse(result["physical_delivery_verified"])
                self.assertFalse(result["device_origin_verified"])
            finally:
                peer.finish()

    def test_foreign_reply_does_not_complete_typed_read(self):
        # A valid neighbouring Reply Network envelope has a different route.
        foreign = b"86FD1002FB04821E00CC\r"
        peer = Peer(RECALL_COMMAND, [b"g." + foreign])
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = project_file(directory)
                arguments = self.arguments("recall", path, peer.port)
                arguments[arguments.index("routed-recall"):arguments.index("routed-recall")] = [
                    "--timeout", "1"]
                code, stdout, stderr = self.invoke(arguments)
            self.assertEqual((code, stdout), (1, ""))
            evidence = json.loads(stderr)["pci_routed_recall_evidence"]
            self.assertTrue(evidence["send_completed"])
            self.assertTrue(evidence["logical_network_resolved"])
            self.assertTrue(evidence["topology_fresh_at_handoff"])
            self.assertEqual(evidence["route_plan"]["expected_reply_path"]["route_entries"], [252, 4])
            self.assertFalse(evidence["response_received"])
            self.assertFalse(evidence["resubmitted"])
        finally:
            peer.finish()

    def test_identify_accepts_the_exact_cbz_snapshot(self):
        peer = Peer(IDENTIFY_COMMAND, [b"g." + IDENTIFY_REPLY])
        try:
            with tempfile.TemporaryDirectory() as directory:
                xml = project_file(directory)
                archive = Path(directory) / "house.cbz"
                with ZipFile(archive, "w", ZIP_DEFLATED) as output:
                    output.writestr("project.xml", xml.read_bytes())
                    output.writestr("retained.bin", b"opaque")
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                code, stdout, stderr = self.invoke(self.arguments(
                    "identify", archive, peer.port, extra=("--project-sha256", digest)))
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["route_plan"]["project_format"], "legacy-cbz")
            self.assertEqual(result["route_plan"]["project_sha256"], digest)
            self.assertEqual(result["sent_hex"], IDENTIFY_COMMAND.hex().upper())
        finally:
            peer.finish()

    def test_changed_project_at_handoff_refuses_both_reads_before_socket(self):
        for kind, core in (("recall", recall_core), ("identify", identify_core)):
            with tempfile.TemporaryDirectory() as directory:
                path = project_file(directory)
                with patch.object(topology, "assert_fresh_project",
                                  side_effect=[None, ProjectError("stale at handoff")]), \
                     patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
                    code, stdout, stderr = self.invoke(self.arguments(kind, path))
            self.assertEqual((code, stdout), (1, ""))
            evidence = json.loads(stderr)[f"pci_routed_{kind}_evidence"]
            self.assertFalse(evidence["connect_attempted"])
            self.assertFalse(evidence["send_attempted"])
            self.assertTrue(evidence["logical_network_resolved"])
            self.assertFalse(evidence["topology_fresh_at_handoff"])
            self.assertEqual(evidence["route_plan"]["bridges"], [253, 252])

    def test_changed_project_during_planning_keeps_route_evidence_without_io(self):
        with tempfile.TemporaryDirectory() as directory:
            path = project_file(directory)
            with patch.object(topology, "assert_fresh_project",
                              side_effect=ProjectError("stale during planning")), \
                 patch.object(recall_core.socket, "socket", side_effect=AssertionError("No socket")):
                code, stdout, stderr = self.invoke(self.arguments("recall", path))
        self.assertEqual((code, stdout), (1, ""))
        evidence = json.loads(stderr)["pci_routed_recall_evidence"]
        self.assertFalse(evidence["connect_attempted"])
        self.assertFalse(evidence["send_attempted"])
        self.assertTrue(evidence["logical_network_resolved"])
        self.assertFalse(evidence["topology_fresh_at_handoff"])
        self.assertEqual(evidence["route_plan"]["bridges"], [253, 252])

    def test_bad_hash_missing_target_and_mixed_modes_fail_before_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = project_file(directory)
            for kind, core in (("recall", recall_core), ("identify", identify_core)):
                bad_hash = self.arguments(kind, path, extra=("--project-sha256", "0" * 64))
                missing = self.arguments(kind, path)
                missing[missing.index("4")] = "5"
                mixed = self.arguments(kind, path, extra=("--bridge", "253"))
                with patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
                    for arguments in (bad_hash, missing, mixed):
                        code, stdout, stderr = self.invoke(arguments)
                        self.assertEqual((code, stdout), (1, ""))
                        evidence = json.loads(stderr)[f"pci_routed_{kind}_evidence"]
                        self.assertFalse(evidence["connect_attempted"])
                        self.assertFalse(evidence["send_attempted"])


if __name__ == "__main__":
    unittest.main()
