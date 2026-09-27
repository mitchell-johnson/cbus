"""CLI boundary for strict, one-shot routed WRITE."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import main
from cbus_toolkit import pci_routed_write as core
from cbus_toolkit import pci_routed_write_cli as helper
from cbus_toolkit.project import ProjectError
from tests.test_pci_routed_recall import Peer, SocketFixture


class RoutedWriteCLITests(unittest.TestCase):
    def invoke(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                status = main(arguments)
            except SystemExit as exc:
                status = exc.code
        return status, output.getvalue(), error.getvalue()

    def arguments(self, port=10001, *, prefix=(), extra=(), routed=True):
        path = (["--bridge", "20", "--bridge", "21", "--expected-source", "20",
                 "--expected-route", "21", "--expected-route", "4"] if routed
                else ["--expected-source", "4"])
        return ["--compact", "pci", "--host", "127.0.0.1", "--port", str(port), *prefix,
                "routed-write", "4", "7", "AABB", "--expected-ack-tag", "0x55",
                "--expected-destination", "16", *path, *extra]

    def typed_arguments(self, project, port=10001, *, extra=()):
        return ["--compact", "pci", "--host", "127.0.0.1", "--port", str(port),
                "--local-unit", "16", "routed-write", "4", "7", "AABB",
                "--expected-ack-tag", "0x55", "--project-file", str(project),
                "--source-network", "254", "--target-network", "252", *extra]

    def project(self, directory):
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
            '</Project></Installation>',
            encoding="utf-8",
        )
        return path

    def test_owned_peer_reports_wire_ack_without_persistence_claim(self):
        peer = Peer(b"\\4614121504A307AABBg\r", [b"g.861410021504320755AD\r"])
        try:
            code, stdout, stderr = self.invoke(self.arguments(peer.port))
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["requested"], {
                "unit": 4, "parameter": 7, "data_hex": "AABB",
                "bridges": [20, 21], "addressing": "direct",
            })
            self.assertTrue(result["acknowledgement_received"])
            self.assertFalse(result["physical_delivery_verified"])
            self.assertFalse(result["parameter_commit_verified"])
            self.assertFalse(result["nonvolatile_persistence_verified"])
        finally:
            peer.finish()

    def test_typed_project_target_resolves_exact_route_and_ack_path(self):
        peer = Peer(b"\\46FD12FC04A307AABBg\r", [b"g.86FD1002FC04320755DD\r"])
        try:
            with tempfile.TemporaryDirectory() as directory:
                project = self.project(directory)
                code, stdout, stderr = self.invoke(self.typed_arguments(project, peer.port))
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["requested"]["bridges"], [253, 252])
            self.assertTrue(result["logical_network_resolved"])
            self.assertTrue(result["topology_fresh_at_handoff"])
            self.assertEqual(result["route_plan"]["expected_ack_path"], {
                "outer_source_byte": 253,
                "destination_byte": 16,
                "route_entries": [252, 4],
            })
            self.assertFalse(result["route_plan"]["physical_bridge_acceptance_verified"])
            self.assertFalse(result["nonvolatile_persistence_verified"])
        finally:
            peer.finish()

    def test_typed_project_change_at_handoff_refuses_before_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            stale = ProjectError("project changed at handoff")
            with patch.object(helper, "assert_fresh_project", side_effect=[None, stale]), \
                 patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
                code, stdout, stderr = self.invoke(self.typed_arguments(project))
        self.assertEqual((code, stdout), (1, ""))
        result = json.loads(stderr)
        evidence = result["pci_routed_write_evidence"]
        self.assertEqual(evidence["stage"], "cli_preflight")
        self.assertFalse(evidence["connect_attempted"])
        self.assertFalse(evidence["send_attempted"])
        self.assertTrue(evidence["logical_network_resolved"])
        self.assertFalse(evidence["topology_fresh_at_handoff"])
        self.assertEqual(evidence["route_plan"]["bridges"], [253, 252])

    def test_typed_post_send_fault_is_uncertain_and_route_is_preserved(self):
        peer = Peer(b"\\46FD12FC04A307AABBg\r", [b"g#"])
        try:
            with tempfile.TemporaryDirectory() as directory:
                project = self.project(directory)
                code, stdout, stderr = self.invoke(self.typed_arguments(project, peer.port))
            self.assertEqual((code, stdout), (1, ""))
            evidence = json.loads(stderr)["pci_routed_write_evidence"]
            self.assertTrue(evidence["send_completed"])
            self.assertTrue(evidence["write_outcome_uncertain"])
            self.assertFalse(evidence["resubmitted"])
            self.assertTrue(evidence["logical_network_resolved"])
            self.assertTrue(evidence["topology_fresh_at_handoff"])
            self.assertEqual(evidence["route_plan"]["project_name"], "HOUSE")
        finally:
            peer.finish()

    def test_parser_rejects_bad_hex_or_missing_exact_ack_inputs(self):
        base = self.arguments()
        variants = [base[:base.index("--expected-ack-tag")]]
        for bad in ("0", "GG", "00" * 31):
            args = self.arguments()
            args[args.index("AABB")] = bad
            variants.append(args)
        with patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
            for args in variants:
                code, stdout, _ = self.invoke(args)
                self.assertEqual((code, stdout), (2, ""))

    def test_semantic_failure_has_no_socket_and_error_uses_write_key(self):
        variants = [self.arguments(prefix=("--local-unit", "4")),
                    self.arguments(extra=("--expected-route", "5")),
                    self.arguments(extra=("--max-events", "4097"))]
        host = self.arguments()
        host[host.index("--host") + 1] = "localhost"
        variants.append(host)
        with patch.object(core.socket, "socket", side_effect=AssertionError("No socket")), \
             patch.object(core.socket, "getaddrinfo", side_effect=AssertionError("No resolver")):
            for args in variants:
                code, stdout, stderr = self.invoke(args)
                self.assertEqual((code, stdout), (1, ""))
                evidence = json.loads(stderr)["pci_routed_write_evidence"]
                self.assertFalse(evidence["connect_attempted"])
                self.assertFalse(evidence["send_attempted"])

    def test_post_send_rejection_is_uncertain_and_never_replayed(self):
        peer = Peer(b"\\460400A307AABBg\r", [b"g#"])
        try:
            code, stdout, stderr = self.invoke(self.arguments(peer.port, routed=False))
            self.assertEqual((code, stdout), (1, ""))
            result = json.loads(stderr)
            self.assertEqual(result["type"], "PCIRejected")
            evidence = result["pci_routed_write_evidence"]
            self.assertTrue(evidence["send_completed"])
            self.assertTrue(evidence["write_outcome_uncertain"])
            self.assertFalse(evidence["resubmitted"])
        finally:
            peer.finish()

    def test_interruption_keeps_partial_mutation_evidence(self):
        first = KeyboardInterrupt("owned receive interruption")
        fixture = SocketFixture(fault={"recv": first})
        with patch.object(core.socket, "socket", return_value=fixture):
            code, stdout, stderr = self.invoke(self.arguments(routed=False))
        self.assertEqual((code, stdout), (130, ""))
        evidence = json.loads(stderr)["pci_routed_write_evidence"]
        self.assertEqual(evidence["error"]["type"], "KeyboardInterrupt")
        self.assertTrue(evidence["write_outcome_uncertain"])
        self.assertEqual(len(fixture.sent), 1)


if __name__ == "__main__":
    unittest.main()
