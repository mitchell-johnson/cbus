"""CLI boundary for strict, one-shot routed WRITE."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import main
from cbus_toolkit import pci_routed_write as core
from cbus_toolkit import pci_routed_write_cli as helper
from cbus_toolkit.project import ProjectError
from tests.test_pci_routed_recall import Peer, SocketFixture
from tests.test_pci_routed_recall import literal_command as recall_literal_command
from tests.test_pci_routed_recall import literal_frame as recall_literal_frame


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


RAW_RECALL = recall_literal_command(unit=4, parameter=7, count=2, bridges=(20, 21))
RAW_WRITE = b"\\4614121504A40755AABBg\r"
RAW_ACK = b"861410021504320755AD\r"
TYPED_RECALL = recall_literal_command(unit=4, parameter=7, count=2, bridges=(253, 252))
TYPED_WRITE = b"\\46FD12FC04A40755AABBg\r"


def raw_reply(data):
    return recall_literal_frame(outer=20, destination=16, route=(21, 4), parameter=7, data=data)


def typed_reply(data):
    return recall_literal_frame(outer=253, destination=16, route=(252, 4), parameter=7, data=data)


class SequencePeer:
    """Owned loopback peer serving one exact command per sequential connection."""

    def __init__(self, exchanges):
        self.exchanges = list(exchanges)
        self.received = []
        self.error = None
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.settimeout(3)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            for command, chunks, *disconnect in self.exchanges:
                connection, _ = self.server.accept()
                with connection:
                    connection.settimeout(3)
                    received = bytearray()
                    while not received.endswith(b"\r"):
                        data = connection.recv(256)
                        if not data:
                            raise AssertionError("EOF before intended command")
                        received.extend(data)
                    self.received.append(bytes(received))
                    if bytes(received) != command:
                        raise AssertionError((bytes(received), command))
                    for chunk in chunks:
                        connection.sendall(chunk)
                    if not disconnect and connection.recv(256):
                        raise AssertionError("A second command was sent")
        except BaseException as error:
            self.error = error
        finally:
            self.server.close()

    def finish(self):
        self.thread.join(4)
        if self.thread.is_alive():
            raise AssertionError("Owned peer did not stop")
        if self.error is not None:
            raise self.error


class RoutedWriteJournalCLITests(unittest.TestCase):
    invoke = RoutedWriteCLITests.invoke
    project = RoutedWriteCLITests.project
    typed_arguments = RoutedWriteCLITests.typed_arguments

    def raw(self, port, journal, data="55AABB"):
        return ["--compact", "pci", "--host", "127.0.0.1", "--port", str(port), "routed-write",
                "4", "7", data, "--expected-ack-tag", "0x55", "--bridge", "20", "--bridge", "21",
                "--expected-source", "20", "--expected-destination", "16", "--expected-route", "21",
                "--expected-route", "4", "--journal", str(journal)]

    def recover(self, port, journal, extra=()):
        return ["--compact", "pci", "--host", "127.0.0.1", "--port", str(port), "routed-write",
                "--recover", "--journal", str(journal), *extra]

    def test_journaled_raw_write_then_recover_expected(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "attempt.json"
            peer = SequencePeer([(RAW_RECALL, [b"g." + raw_reply(b"\x11\x22")]),
                                 (RAW_WRITE, [b"g." + RAW_ACK])])
            try:
                code, stdout, stderr = self.invoke(self.raw(peer.port, journal))
            finally:
                peer.finish()
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["journal"]["phase"], "acknowledged")
            self.assertEqual(result["journal"]["baseline_hex"], "1122")
            self.assertFalse(result["journal"]["recovery_required"])
            self.assertEqual(result["journal"]["pci_generation_source"], "unavailable")
            # Recovery must target the journaled endpoint; a different port is refused.
            with patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
                code, stdout, stderr = self.invoke(self.recover(peer.port + 1, journal))
            self.assertEqual((code, stdout), (1, ""))
            self.assertIn("endpoint", json.loads(stderr)["error"])
            recall = SocketFixture([b"g." + raw_reply(b"\xaa\xbb")])
            with patch.object(core.RoutedWriteClient, "exchange", side_effect=AssertionError("No WRITE")), \
                 patch.object(core.socket, "socket", side_effect=[recall]):
                code, stdout, stderr = self.invoke(self.recover(peer.port, journal))
            self.assertEqual((code, stderr), (0, ""))
            report = json.loads(stdout)
            self.assertEqual(report["classification"], "expected")
            self.assertFalse(report["writes_attempted"])
            self.assertEqual(recall.sent, [RAW_RECALL])

    def test_lost_reply_is_uncertain_and_recover_reports_mixed_without_resolving(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "attempt.json"
            peer = SequencePeer([(RAW_RECALL, [b"g." + raw_reply(b"\x11\x22")]),
                                 (RAW_WRITE, [b"g."], "disconnect")])
            try:
                code, stdout, stderr = self.invoke(self.raw(peer.port, journal))
            finally:
                peer.finish()
            self.assertEqual((code, stdout), (1, ""))
            error = json.loads(stderr)
            self.assertEqual(error["pci_routed_write_journal"]["phase"], "uncertain")
            self.assertTrue(error["pci_routed_write_journal"]["recovery_required"])
            self.assertTrue(error["pci_routed_write_evidence"]["write_outcome_uncertain"])
            self.assertTrue(error["pci_routed_write_baseline_evidence"]["complete"])
            # A second WRITE to the same target is refused before any I/O.
            with patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
                code, stdout, stderr = self.invoke(self.raw(peer.port, Path(directory) / "next.json"))
            self.assertEqual((code, stdout), (1, ""))
            self.assertIn("unresolved", json.loads(stderr)["error"])
            recall = SocketFixture([b"g." + raw_reply(b"\xaa\x22")])
            with patch.object(core.socket, "socket", side_effect=[recall]):
                code, stdout, stderr = self.invoke(self.recover(peer.port, journal))
            self.assertEqual((code, stderr), (1, ""))
            self.assertEqual(recall.sent, [RAW_RECALL])
            report = json.loads(stdout)
            self.assertEqual((report["classification"], report["resolved"]), ("mixed", False))

    def test_recover_rejects_write_options_and_needs_journal(self):
        with patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
            for args in (self.recover(10001, "x.json", ("--expected-ack-tag", "1")),
                         ["--compact", "pci", "routed-write", "--recover"],
                         self.recover(10001, "x.json", ("--bridge", "1"))):
                code, stdout, _ = self.invoke(args)
                self.assertEqual((code, stdout), (2, ""))

    def test_typed_journal_binds_project_and_refuses_handoff_change_before_send(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            journal = Path(directory) / "attempt.json"
            args = self.typed_arguments(project, extra=("--journal", str(journal)))
            args[args.index("AABB")] = "55AABB"
            recall = SocketFixture([b"g." + typed_reply(b"\x11\x22")])
            write = SocketFixture([])
            real = helper.assert_fresh_project
            calls = []

            def stale(*values):
                calls.append(values)
                if len(calls) == 3:
                    raise ProjectError("project changed at handoff")
                return real(*values)

            with patch.object(helper, "assert_fresh_project", side_effect=stale), \
                 patch.object(core.socket, "socket", side_effect=[recall, write]):
                code, stdout, stderr = self.invoke(args)
            self.assertEqual((code, stdout), (1, ""))
            self.assertEqual((recall.sent, write.sent), ([TYPED_RECALL], []))
            error = json.loads(stderr)
            self.assertEqual(error["type"], "RoutedWriteRefused")
            self.assertEqual(error["pci_routed_write_journal"]["phase"], "not-sent")
            self.assertFalse(error["pci_routed_write_evidence"]["send_attempted"])
            document = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(document["plan"]["mode"], "typed")
            self.assertEqual(document["plan"]["project_sha256"],
                             hashlib.sha256(project.read_bytes()).hexdigest())

    def test_typed_recover_rechecks_project_route_before_recall(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            journal = Path(directory) / "attempt.json"
            args = self.typed_arguments(project, extra=("--journal", str(journal)))
            args[args.index("AABB")] = "55AABB"
            with patch.object(core.socket, "socket", side_effect=[
                    SocketFixture([b"g." + typed_reply(b"\x11\x22")]), SocketFixture([b"g."])]):
                code, _, stderr = self.invoke(args)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stderr)["pci_routed_write_journal"]["phase"], "uncertain")
            project.write_text(project.read_text(encoding="utf-8").replace("<TagName>Local<", "<TagName>Local2<"),
                               encoding="utf-8")
            with patch.object(core.socket, "socket", side_effect=AssertionError("No socket")):
                code, stdout, stderr = self.invoke(
                    self.recover(10001, journal, ("--project-file", str(project))))
            self.assertEqual((code, stdout), (1, ""))
            self.assertIn("differs from the journaled route plan", json.loads(stderr)["error"])
            project.write_text(project.read_text(encoding="utf-8").replace("<TagName>Local2<", "<TagName>Local<"),
                               encoding="utf-8")
            recall = SocketFixture([b"g." + typed_reply(b"\x11\x22")])
            with patch.object(core.socket, "socket", side_effect=[recall]):
                code, stdout, stderr = self.invoke(
                    self.recover(10001, journal, ("--project-file", str(project))))
            self.assertEqual((code, stderr), (0, ""))
            report = json.loads(stdout)
            self.assertEqual((report["classification"], report["topology_rechecked"]), ("unchanged", True))
            self.assertEqual(recall.sent, [TYPED_RECALL])



def _line_project(directory, depth, unit=5):
    """One CNI root (254) and a linear chain of ``depth`` bridged networks."""
    addresses = tuple(range(254, 254 - depth - 1, -1))
    networks = []
    for index, address in enumerate(addresses):
        units = []
        if index + 1 < len(addresses):
            units.append(f"<Unit><Address>{addresses[index + 1]}</Address><UnitType>BRIDGE2N</UnitType></Unit>")
        if index == len(addresses) - 1:
            units.append(f"<Unit><Address>{unit}</Address><UnitType>KEYGL5</UnitType></Unit>")
        interface = ("<Interface><InterfaceType>CNI</InterfaceType>"
                     "<InterfaceAddress>owned</InterfaceAddress></Interface>"
                     if index == 0 else
                     "<Interface><InterfaceType>Bridge</InterfaceType>"
                     f"<InterfaceAddress>{addresses[index - 1]}/p/{address}</InterfaceAddress></Interface>")
        networks.append(f"<Network><TagName>N{address}</TagName><Address>{address}</Address>"
                        f"{interface}{''.join(units)}</Network>")
    path = Path(directory) / "house.xml"
    path.write_text("<Installation><Project><TagName>HOUSE</TagName>"
                    f"{''.join(networks)}</Project></Installation>", encoding="utf-8")
    return path, addresses[1:]


def _literal_write(unit, parameter, data, bridges):
    addresses = (*bridges, unit)
    raw = bytes((0x46, addresses[0], 9 * len(bridges), *addresses[1:],
                 0xA0 | (len(data) + 1), parameter, *data))
    return b"\\" + raw.hex().upper().encode() + b"g\r"


def _literal_ack(outer, route, parameter, tag):
    raw = bytes((0x86, outer, 16, len(route), *route, 0x32, parameter, tag))
    return (raw + bytes((-sum(raw) & 255,))).hex().upper().encode() + b"\r"


class RoutedWriteJournaledDepthTests(unittest.TestCase):
    """Typed journaled WRITE and read-only recovery at one, two and six bridges.

    Ported from the 2026-10-19 Mac mini WIP snapshot and adapted to the
    baseline-RECALL journal: every literal is derived independently here.
    """
    invoke = RoutedWriteCLITests.invoke

    def test_journaled_peer_covers_one_two_and_six_bridges(self):
        unit = 5
        for depth in (1, 2, 6):
            with self.subTest(depth=depth), tempfile.TemporaryDirectory() as directory:
                project, bridges = _line_project(directory, depth, unit)
                outer, route = bridges[0], (*bridges[1:], unit)
                recall = recall_literal_command(unit=unit, parameter=7, count=2, bridges=bridges)
                reply = lambda data: recall_literal_frame(
                    outer=outer, destination=16, route=route, parameter=7, data=data)
                write = _literal_write(unit, 7, b"\x55\xaa\xbb", bridges)
                peer = SequencePeer([(recall, [b"g." + reply(b"\x11\x22")]),
                                     (write, [b"g." + _literal_ack(outer, route, 7, 0x55)])])
                journal = Path(directory) / "attempt.json"
                arguments = ["--compact", "pci", "--host", "127.0.0.1", "--port", str(peer.port),
                             "--local-unit", "16", "routed-write", str(unit), "7", "55AABB",
                             "--expected-ack-tag", "0x55", "--project-file", str(project),
                             "--source-network", "254", "--target-network", str(254 - depth),
                             "--journal", str(journal)]
                try:
                    code, stdout, stderr = self.invoke(arguments)
                finally:
                    peer.finish()
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(peer.received, [recall, write])
                result = json.loads(stdout)
                self.assertEqual(result["journal"]["phase"], "acknowledged")
                document = json.loads(journal.read_text(encoding="utf-8"))
                self.assertEqual(document["plan"]["bridges"], list(bridges))
                self.assertEqual(document["plan"]["mode"], "typed")
                self.assertTrue(document["complete"])
                # Recovery reads once and never writes.
                fixture = SocketFixture([b"g." + reply(b"\xaa\xbb")])
                with patch.object(core.RoutedWriteClient, "exchange",
                                  side_effect=AssertionError("Recovery must never WRITE")), \
                     patch.object(core.socket, "socket", side_effect=[fixture]):
                    code, stdout, stderr = self.invoke(
                        ["--compact", "pci", "--host", "127.0.0.1", "--port", str(peer.port),
                         "routed-write", "--recover", "--journal", str(journal),
                         "--project-file", str(project)])
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(fixture.sent, [recall])
                report = json.loads(stdout)
                self.assertEqual(report["classification"], "expected")
                self.assertFalse(report["writes_attempted"])


if __name__ == "__main__":
    unittest.main()
