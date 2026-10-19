"""Independent literal-wire and fault tests for one-shot routed WRITE."""
import contextlib
import dataclasses
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbus_toolkit import pci_routed_write as module
from cbus_toolkit.commissioning_route import (
    plan_commissioning_route,
    project_sha256,
)
from cbus_toolkit.pci import AcknowledgeCAL, IdentifyCAL, PCIRejected, ProtocolError, WriteCAL
from cbus_toolkit.pci_routing import RoutedCALCommand
from cbus_toolkit.pci_routed_recall import RoutedReplyPath
from cbus_toolkit.pci_routed_write import (
    RoutedWriteClient,
    RoutedWriteJournalError,
    RoutedWriteUncertain,
    create_routed_write_journal,
    load_routed_write_recovery,
    routed_write_attempt_id,
    routed_write_generation,
    update_routed_write_journal,
)
from cbus_toolkit.project import ProjectDocument
from tests.test_pci_routed_recall import Peer, SocketFixture


DIRECT_ACK = b"86041000320755D8\r"
ROUTED_ACK = b"861410021504320755AD\r"
COMMAND = RoutedCALCommand(4, WriteCAL(7, b"\xaa\xbb"))
PATH = RoutedReplyPath(4, 16)


def literal_command(*, unit=4, parameter=7, data=b"\xaa\xbb", bridges=(), checksum=False):
    addresses = (*bridges, unit)
    raw = bytes((0x46, addresses[0], 9 * len(bridges), *addresses[1:],
                 0xA0 | (len(data) + 1), parameter, *data))
    if checksum:
        raw += bytes((-sum(raw) & 255,))
    return b"\\" + raw.hex().upper().encode() + b"g\r"


def literal_ack(*, outer=4, destination=16, route=(), parameter=7, tag=0x55):
    raw = bytes((0x86, outer, destination, len(route), *route, 0x32, parameter, tag))
    raw += bytes((-sum(raw) & 255,))
    return raw.hex().upper().encode() + b"\r"


class RoutedWriteTests(unittest.TestCase):
    def exchange(self, chunks, *, command=COMMAND, expected=PATH, tag=0x55, options=None):
        fixture = SocketFixture(chunks)
        client = RoutedWriteClient("127.0.0.1", **(options or {}))
        with patch.object(module.socket, "socket", return_value=fixture) as factory, \
             patch.object(module.socket, "getaddrinfo", side_effect=AssertionError("No resolver")):
            result = client.exchange(command, expected=expected, expected_ack_tag=tag)
        self.assertEqual(factory.call_args.args, (socket.AF_INET, socket.SOCK_STREAM))
        self.assertEqual(fixture.sent, [literal_command(
            unit=command.unit, parameter=command.cal.parameter, data=command.cal.data,
            bridges=command.bridges, checksum=client.command_checksum)])
        self.assertEqual([call for call in fixture.calls if call[0] == "close"], [("close",)])
        return result, client, fixture

    def test_exact_ack_both_orders_and_every_stream_split(self):
        for joined in (b"g." + DIRECT_ACK, DIRECT_ACK + b"g."):
            for cut in range(1, len(joined)):
                with self.subTest(order=joined[:2], cut=cut):
                    result, client, _ = self.exchange([joined[:cut], joined[cut:]])
                    self.assertEqual(result.acknowledgement.cal, AcknowledgeCAL(7, 0x55))
                    self.assertTrue(client.last_evidence["complete"])
                    self.assertFalse(result.as_dict()["parameter_commit_verified"])
                    self.assertFalse(result.as_dict()["nonvolatile_persistence_verified"])

    def test_all_parameter_and_ack_tag_bytes_are_exact(self):
        for value in range(256):
            command = RoutedCALCommand(4, WriteCAL(value, bytes((value,))))
            frame = literal_ack(parameter=value, tag=value)
            result, _, _ = self.exchange([frame + b"g."], command=command, tag=value)
            self.assertEqual(result.acknowledgement.cal, AcknowledgeCAL(value, value))

    def test_zero_and_maximum_payloads_and_route_depths(self):
        for depth in range(7):
            bridges = tuple(range(40, 40 + depth))
            route = tuple(range(21, 20 + depth)) + (4,) if depth else ()
            expected = RoutedReplyPath(20 if depth else 4, 0, route)
            for data in (b"", bytes(range(30))):
                command = RoutedCALCommand(4, WriteCAL(7, data), bridges=bridges)
                frame = literal_ack(outer=expected.outer_source_byte, destination=0, route=route)
                fixture = SocketFixture([b"g." + frame])
                client = RoutedWriteClient("127.0.0.1")
                with patch.object(module.socket, "socket", return_value=fixture):
                    result = client.exchange(command, expected=expected, expected_ack_tag=0x55)
                self.assertEqual(result.acknowledgement.route_entries, route)
                self.assertEqual(len(fixture.sent), 1)

    def test_unmatched_path_parameter_tag_and_cal_never_complete(self):
        frames = (
            literal_ack(outer=5),
            literal_ack(destination=99),
            literal_ack(route=(4,)),
            literal_ack(parameter=8),
            literal_ack(tag=0x54),
            b"860410008107DE\r",  # checksum-valid zero-byte REPLY, not ACK
        )
        result, _, _ = self.exchange([b"h#" + b"".join(frames) + b"g." + DIRECT_ACK])
        self.assertEqual([event.matched for event in result.events], [False] * 7 + [True, True])
        for frame in frames:
            client = RoutedWriteClient("127.0.0.1")
            fixture = SocketFixture([b"g." + frame])
            with self.subTest(frame=frame), patch.object(module.socket, "socket", return_value=fixture), \
                 self.assertRaises(ConnectionError):
                client.exchange(COMMAND, expected=PATH, expected_ack_tag=0x55)
            self.assertFalse(client.last_evidence["acknowledgement_received"])
            self.assertTrue(client.last_evidence["write_outcome_uncertain"])

    def test_duplicates_rejection_malformed_and_partial_tail_fail_without_replay(self):
        cases = (
            (b"g." + DIRECT_ACK + DIRECT_ACK, ProtocolError),
            (b"g." + DIRECT_ACK + b"g.", ProtocolError),
            (b"g." + DIRECT_ACK + b"86", ProtocolError),
            (b"g#", PCIRejected),
            (DIRECT_ACK[:-3] + b"00\r", ProtocolError),
            (b"g!", ProtocolError),
        )
        for chunk, error in cases:
            client = RoutedWriteClient("127.0.0.1")
            fixture = SocketFixture([chunk])
            with self.subTest(chunk=chunk), patch.object(module.socket, "socket", return_value=fixture), \
                 self.assertRaises(error):
                client.exchange(COMMAND, expected=PATH, expected_ack_tag=0x55)
            self.assertEqual(len(fixture.sent), 1)
            self.assertFalse(client.last_evidence["resubmitted"])

    def test_preflight_rejects_every_semantic_mismatch_before_socket(self):
        with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")), \
             patch.object(module.socket, "getaddrinfo", side_effect=AssertionError("No resolver")):
            for host in ("localhost", "::1%lo0", "", None):
                with self.assertRaises((ValueError, TypeError)):
                    RoutedWriteClient(host)
            for options in ({"port": 0}, {"timeout": True}, {"timeout": float("nan")},
                            {"max_events": 0}, {"max_received_bytes": 1048577},
                            {"command_checksum": 1}):
                with self.assertRaises(ValueError):
                    RoutedWriteClient("127.0.0.1", **options)
            for tag in (True, -1, 256, 1.0, "1"):
                with self.assertRaises(ValueError):
                    RoutedWriteClient("127.0.0.1").exchange(COMMAND, expected=PATH,
                                                                  expected_ack_tag=tag)
            for command, expected in (
                (RoutedCALCommand(4, IdentifyCAL(1)), PATH),
                (RoutedCALCommand(4, WriteCAL(7, b"x"), addressing="programming"), PATH),
                (COMMAND, RoutedReplyPath(5, 16)),
            ):
                with self.assertRaises(ValueError):
                    RoutedWriteClient("127.0.0.1").exchange(command, expected=expected,
                                                                  expected_ack_tag=0x55)

    def test_preflight_refuses_non_exact_expected_and_route_entry_terminal_before_socket(self):
        # P3.01 routed-WRITE refusal path: a non-exact expected envelope and a
        # declared ACK path whose terminal route entry is not the addressed
        # unit are both refused before any socket exists. Canned fixtures only.
        class ExactSubclass(RoutedReplyPath):
            pass
        non_exact = (
            None,
            {"outer_source_byte": 4, "destination_byte": 16, "route_entries": []},
            (4, 16),
            "RoutedReplyPath(4, 16)",
            ExactSubclass(4, 16),
        )
        terminal_mismatches = (
            RoutedReplyPath(20, 16, (21, 5)),
            RoutedReplyPath(4, 16, (21, 5)),
            RoutedReplyPath(4, 16, (4, 5)),
        )
        with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")), \
             patch.object(module.socket, "getaddrinfo", side_effect=AssertionError("No resolver")):
            for expected in non_exact:
                with self.subTest(expected=repr(expected)):
                    client = RoutedWriteClient("127.0.0.1")
                    with self.assertRaisesRegex(ValueError, "expected must be an exact RoutedReplyPath"):
                        client.exchange(COMMAND, expected=expected, expected_ack_tag=0x55)
                    self.assertFalse(client.last_evidence["connect_attempted"])
                    self.assertFalse(client.last_evidence["send_attempted"])
            for expected in terminal_mismatches:
                with self.subTest(expected=expected.as_dict()):
                    client = RoutedWriteClient("127.0.0.1")
                    with self.assertRaisesRegex(ValueError, "Final declared ACK path byte"):
                        client.exchange(COMMAND, expected=expected, expected_ack_tag=0x55)
                    self.assertFalse(client.last_evidence["connect_attempted"])
                    self.assertFalse(client.last_evidence["send_attempted"])

    def test_send_or_receive_failure_is_uncertain_and_single_use(self):
        for stage in ("send", "recv"):
            original = OSError(stage)
            fixture = SocketFixture(fault={stage: original})
            client = RoutedWriteClient("127.0.0.1")
            with patch.object(module.socket, "socket", return_value=fixture), \
                 self.assertRaises(OSError) as caught:
                client.exchange(COMMAND, expected=PATH, expected_ack_tag=0x55)
            self.assertIs(caught.exception, original)
            self.assertTrue(client.last_evidence["write_outcome_uncertain"])
            self.assertFalse(client.last_evidence["resubmitted"])
        result, client, _ = self.exchange([b"g." + DIRECT_ACK])
        exported = result.as_dict()
        exported["events"].clear()
        self.assertEqual(len(result.events), 2)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.expected_ack_tag = 0
        with patch.object(module.socket, "socket", side_effect=AssertionError("No reconnect")), \
             self.assertRaises(RuntimeError):
            client.exchange(COMMAND, expected=PATH, expected_ack_tag=0x55)
        self.assertFalse(client.last_evidence["connect_attempted"])


class RoutedWritePeerTests(unittest.TestCase):
    def test_owned_ipv4_ipv6_peers_pin_literal_request_and_ack(self):
        for family in (socket.AF_INET, socket.AF_INET6):
            for checksum in (False, True):
                expected_wire = (b"\\4614121504A307AABB6Cg\r" if checksum
                                 else b"\\4614121504A307AABBg\r")
                peer = Peer(expected_wire, [ROUTED_ACK[:7], ROUTED_ACK[7:] + b"g."], family=family)
                try:
                    client = RoutedWriteClient(peer.host, peer.port, timeout=2,
                                               command_checksum=checksum)
                    result = client.exchange(
                        RoutedCALCommand(4, WriteCAL(7, b"\xaa\xbb"), bridges=(20, 21)),
                        expected=RoutedReplyPath(20, 16, (21, 4)),
                        expected_ack_tag=0x55,
                    )
                    self.assertEqual(result.acknowledgement.raw, ROUTED_ACK)
                finally:
                    peer.finish()
                self.assertEqual(bytes(peer.received), expected_wire)


def _line_project(depth):
    # One CNI root (254) with a linear 1..6 bridge chain, matching
    # tests/test_commissioning_route.py line().
    addresses = tuple(range(254, 254 - depth - 1, -1))
    networks = []
    for index, address in enumerate(addresses):
        units = []
        if index + 1 < len(addresses):
            units.append(f"<Unit><Address>{addresses[index + 1]}</Address><UnitType>BRIDGE2N</UnitType></Unit>")
        if index == len(addresses) - 1:
            units.append("<Unit><Address>5</Address><UnitType>KEYGL5</UnitType></Unit>")
        interface = ('<Interface><InterfaceType>CNI</InterfaceType>'
                     '<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>'
                     if index == 0 else
                     f'<Interface><InterfaceType>Bridge</InterfaceType>'
                     f'<InterfaceAddress>{addresses[index - 1]}/p/{address}</InterfaceAddress></Interface>')
        networks.append(
            f"<Network><TagName>N{address}</TagName><Address>{address}</Address>"
            f"{interface}{''.join(units)}</Network>")
    raw = (f"<Installation><Project><TagName>HOUSE</TagName>{''.join(networks)}"
           f"</Project></Installation>").encode()
    return raw, ProjectDocument.from_bytes(raw)


class RoutedWriteGenerationTests(unittest.TestCase):
    def test_generation_binds_wire_and_topology(self):
        command = RoutedCALCommand(4, WriteCAL(7, b"\xaa\xbb"), bridges=(20, 21))
        expected = RoutedReplyPath(20, 16, (21, 4))
        first = routed_write_generation(command, expected, 0x55)
        self.assertEqual(routed_write_attempt_id(first), routed_write_attempt_id(dict(first)))
        self.assertTrue(routed_write_attempt_id(first).startswith("sha256:"))
        # Any wire or tag edit changes the generation.
        for other in (
            RoutedCALCommand(4, WriteCAL(8, b"\xaa\xbb"), bridges=(20, 21)),
            RoutedCALCommand(4, WriteCAL(7, b"\xaa\xbb"), bridges=(20, 22)),
            RoutedReplyPath(21, 16, (20, 4)),
        ):
            other_command = other if isinstance(other, RoutedCALCommand) else command
            other_expected = other if isinstance(other, RoutedReplyPath) else expected
            self.assertNotEqual(
                routed_write_attempt_id(routed_write_generation(other_command, other_expected, 0x55)),
                routed_write_attempt_id(first))
        self.assertNotEqual(
            routed_write_attempt_id(routed_write_generation(command, expected, 0x54)),
            routed_write_attempt_id(first))
        # A bound route plan must match the wire identity exactly.
        raw, project = _line_project(2)
        digest = project_sha256(raw)
        plan = plan_commissioning_route(
            project, project_digest=digest, source_network=254, target_network=252,
            target_unit=5, local_unit=16, expected_ack_tag=0x55)
        typed = RoutedCALCommand(5, WriteCAL(7, b"\xaa"), bridges=plan.bridges)
        bound = routed_write_generation(
            typed, plan.expected, 0x55, project_sha256=digest, route_plan=plan.as_dict())
        self.assertEqual(bound["project_sha256"], digest)
        self.assertEqual(bound["route_plan"], plan.as_dict())
        with self.assertRaises(ValueError):
            routed_write_generation(
                RoutedCALCommand(5, WriteCAL(7, b"\xaa"), bridges=(253,)),
                plan.expected, 0x55, project_sha256=digest, route_plan=plan.as_dict())
        with self.assertRaises(ValueError):
            routed_write_generation(
                typed, RoutedReplyPath(252, 16, (253, 5)), 0x55,
                project_sha256=digest, route_plan=plan.as_dict())

    def test_generation_rejects_non_exact_inputs_before_any_journal(self):
        command = RoutedCALCommand(4, WriteCAL(7, b"x"))
        expected = RoutedReplyPath(4, 16)
        for bad_command in (None, "command", RoutedCALCommand(4, IdentifyCAL(1))):
            with self.assertRaises(ValueError):
                routed_write_generation(bad_command, expected, 0x55)
        for bad_expected in (None, {"outer_source_byte": 4}, "path"):
            with self.assertRaises(ValueError):
                routed_write_generation(command, bad_expected, 0x55)
        with self.assertRaises(ValueError):
            routed_write_generation(command, RoutedReplyPath(5, 16), 0x55)


class RoutedWriteJournalTests(unittest.TestCase):
    def _generation(self):
        return routed_write_generation(
            RoutedCALCommand(4, WriteCAL(7, b"\xaa\xbb"), bridges=(20, 21)),
            RoutedReplyPath(20, 16, (21, 4)), 0x55)

    def test_exclusive_journal_and_read_only_recovery_without_socket(self):
        generation = self._generation()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")):
                raw = create_routed_write_journal(path, generation)
                self.assertTrue(path.is_file())
                recovered = load_routed_write_recovery(path)
                self.assertEqual(recovered["generation"], generation)
                self.assertEqual(recovered["attempt_id"], routed_write_attempt_id(generation))
                self.assertFalse(recovered["complete"])
                self.assertTrue(recovered["send_may_have_occurred"])
                self.assertTrue(recovered["read_only_recovery_only"])
                self.assertFalse(recovered["resubmitted"])
                # A second exclusive creation refuses without touching the record.
                before = path.read_bytes()
                with self.assertRaises(RoutedWriteUncertain):
                    create_routed_write_journal(path, generation)
                self.assertEqual(path.read_bytes(), before)
                # Completing the attempt is an atomic checked replacement.
                completed = dict(recovered)
                completed.update({"complete": True, "stage": "complete",
                                  "evidence": {"complete": True}})
                updated = update_routed_write_journal(path, raw, completed)
                self.assertEqual(load_routed_write_recovery(path)["stage"], "complete")
                # A stale writer cannot overwrite the completed record.
                with self.assertRaises(RoutedWriteJournalError):
                    update_routed_write_journal(path, raw, completed)

    def test_tampered_oversize_and_nonregular_journals_refuse(self):
        generation = self._generation()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            raw = create_routed_write_journal(path, generation)
            tampered = json.loads(raw.decode())
            tampered["generation"]["parameter"] = 8
            path.write_bytes((json.dumps(tampered) + "\n").encode())
            with self.assertRaises(RoutedWriteJournalError):
                load_routed_write_recovery(path)
            path.write_bytes(raw)
            outside = path.read_bytes()
            path.write_bytes(outside.replace(b'"resubmitted":false', b'"resubmitted":true'))
            with self.assertRaises(RoutedWriteJournalError):
                load_routed_write_recovery(path)
            path.write_bytes(raw)
            with open(path, "wb") as stream:
                stream.truncate(module.MAX_ROUTED_WRITE_JOURNAL_BYTES + 1)
            with self.assertRaises(RoutedWriteJournalError):
                load_routed_write_recovery(path)
            missing = Path(directory) / "missing.json"
            with self.assertRaises(OSError):
                load_routed_write_recovery(missing)
            if hasattr(os, "mkfifo"):
                fifo = Path(directory) / "fifo.json"
                os.mkfifo(fifo)
                with self.assertRaises(RoutedWriteJournalError):
                    load_routed_write_recovery(fifo)
                with self.assertRaises((RoutedWriteJournalError, RoutedWriteUncertain)):
                    create_routed_write_journal(fifo, generation)
            link = Path(directory) / "link.json"
            try:
                link.symlink_to(path)
            except OSError:
                pass
            else:
                with self.assertRaises((OSError, RoutedWriteJournalError)):
                    load_routed_write_recovery(link)

    def test_journaled_failure_marks_uncertain_without_replay(self):
        # A post-send rejection is uncertain; the journal records it and the
        # client still permits only one exchange.
        command = COMMAND
        expected = PATH
        fixture = SocketFixture([b"g#"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            generation = routed_write_generation(command, expected, 0x55)
            raw = create_routed_write_journal(path, generation)
            client = RoutedWriteClient("127.0.0.1")
            with patch.object(module.socket, "socket", return_value=fixture):
                with self.assertRaises(PCIRejected):
                    client.exchange(command, expected=expected, expected_ack_tag=0x55)
            self.assertTrue(client.last_evidence["write_outcome_uncertain"])
            self.assertFalse(client.last_evidence["resubmitted"])
            uncertain = dict(load_routed_write_recovery(path))
            uncertain.update({"complete": False, "stage": "uncertain",
                              "evidence": client.last_evidence})
            update_routed_write_journal(path, raw, uncertain)
            self.assertFalse(load_routed_write_recovery(path)["complete"])
            with patch.object(module.socket, "socket", side_effect=AssertionError("No reconnect")):
                with self.assertRaises(RuntimeError):
                    client.exchange(command, expected=expected, expected_ack_tag=0x55)


class RoutedWriteJournaledPeerTests(unittest.TestCase):
    def _peer_case(self, bridges, family=socket.AF_INET):
        unit = 5
        outer = bridges[0] if bridges else unit
        route = tuple(bridges[1:]) + (unit,) if bridges else ()
        expected = RoutedReplyPath(outer, 16, route)
        path = (outer,) + tuple(bridges[1:]) + (unit,) if bridges else (unit,)
        raw_command = bytes((0x46, path[0], 9 * len(bridges), *path[1:], 0xA0 | 2, 7, 0xAA))
        wire = b"\\" + raw_command.hex().upper().encode() + b"g\r"
        raw_ack = bytes((0x86, outer, 16, len(route), *route, 0x32, 7, 0x55))
        raw_ack += bytes((-sum(raw_ack) & 255,))
        ack = raw_ack.hex().upper().encode() + b"\r"
        return wire, ack, expected

    def test_journaled_peer_covers_one_two_and_six_bridges(self):
        from cbus_toolkit.cli import main as cli_main
        for depth in (1, 2, 6):
            raw, project = _line_project(depth)
            plan = plan_commissioning_route(
                project, project_digest=project_sha256(raw), source_network=254,
                target_network=254 - depth, target_unit=5, local_unit=16,
                expected_ack_tag=0x55)
            bridges = list(plan.bridges)
            # Independent literal wire/ACK derived from the planned bytes.
            unit = 5
            outer = bridges[0]
            route = tuple(bridges[1:]) + (unit,)
            path = tuple(bridges) + (unit,)
            raw_command = bytes((0x46, path[0], 9 * len(bridges), *path[1:], 0xA2, 7, 0xAA))
            wire = b"\\" + raw_command.hex().upper().encode() + b"g\r"
            raw_ack = bytes((0x86, outer, 16, len(route), *route, 0x32, 7, 0x55))
            raw_ack += bytes((-sum(raw_ack) & 255,))
            ack = raw_ack.hex().upper().encode() + b"\r"
            peer = Peer(wire, [b"g." + ack])
            try:
                with tempfile.TemporaryDirectory() as directory:
                    project_path = Path(directory) / "house.xml"
                    project_path.write_bytes(raw)
                    journal = Path(directory) / "attempt.json"
                    output, error = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                        status = cli_main([
                            "--compact", "pci", "--host", "127.0.0.1", "--port", str(peer.port),
                            "--local-unit", "16", "routed-write", str(unit), "7", "AA",
                            "--expected-ack-tag", "0x55", "--project-file", str(project_path),
                            "--source-network", "254", "--target-network", str(254 - depth),
                            "--journal", str(journal)])
                    self.assertEqual((status, error.getvalue()), (0, ""), depth)
                    result = json.loads(output.getvalue())
                    self.assertEqual(result["requested"]["bridges"], bridges, depth)
                    self.assertTrue(result["topology_fresh_at_handoff"], depth)
                    self.assertTrue(result["reply_network_revalidated"], depth)
                    self.assertEqual(result["journal"], str(journal), depth)
                    recovered = load_routed_write_recovery(journal)
                    self.assertTrue(recovered["complete"], depth)
                    self.assertEqual(recovered["generation"]["bridges"], bridges, depth)
                    # Read-only recovery replays no bytes.
                    with patch.object(module.socket, "socket",
                                      side_effect=AssertionError("No socket on recovery")):
                        output2, error2 = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(output2), contextlib.redirect_stderr(error2):
                            recover_status = cli_main([
                                "--compact", "pci", "--host", "127.0.0.1", "--port", str(peer.port),
                                "--local-unit", "16", "routed-write", str(unit), "7", "AA",
                                "--expected-ack-tag", "0x55", "--project-file", str(project_path),
                                "--source-network", "254", "--target-network", str(254 - depth),
                                "--journal", str(journal), "--recover"])
                        self.assertEqual((recover_status, error2.getvalue()), (0, ""), depth)
                        recovery = json.loads(output2.getvalue())
                        self.assertTrue(recovery["recovery_only"], depth)
                        self.assertFalse(recovery["io_performed"], depth)
            finally:
                peer.finish()

    def test_duplicate_journal_refuses_before_socket(self):
        from cbus_toolkit.cli import main as cli_main
        from cbus_toolkit.project import ProjectDocument as _ProjectDocument
        raw, project = _line_project(1)
        digest = project_sha256(raw)
        plan = plan_commissioning_route(
            _ProjectDocument.from_bytes(raw), project_digest=digest, source_network=254,
            target_network=253, target_unit=5, local_unit=16, expected_ack_tag=0x55)
        command = RoutedCALCommand(5, WriteCAL(7, b"\xaa"), bridges=plan.bridges)
        wire = command.encode(confirmation=b"g", checksum=False)
        ack_outer = plan.expected.outer_source_byte
        ack_route = plan.expected.route_entries
        raw_ack = bytes((0x86, ack_outer, 16, len(ack_route), *ack_route, 0x32, 7, 0x55))
        raw_ack += bytes((-sum(raw_ack) & 255,))
        ack = raw_ack.hex().upper().encode() + b"\r"
        peer = Peer(wire, [b"g." + ack])
        try:
            with tempfile.TemporaryDirectory() as directory:
                project_path = Path(directory) / "house.xml"
                project_path.write_bytes(raw)
                journal = Path(directory) / "attempt.json"
                base = ["--compact", "pci", "--host", "127.0.0.1", "--port", str(peer.port),
                        "--local-unit", "16", "routed-write", "5", "7", "AA",
                        "--expected-ack-tag", "0x55", "--project-file", str(project_path),
                        "--source-network", "254", "--target-network", "253",
                        "--journal", str(journal)]
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    self.assertEqual(cli_main(base), 0)
                self.assertEqual(bytes(peer.received), wire)
                received_before = bytes(peer.received)
                with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")):
                    output2, error2 = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(output2), contextlib.redirect_stderr(error2):
                        self.assertEqual(cli_main(base), 1)
                    payload = json.loads(error2.getvalue())
                    self.assertEqual(payload["type"], "RoutedWriteUncertain")
                    self.assertFalse(payload["pci_routed_write_evidence"]["send_attempted"])
                self.assertEqual(bytes(peer.received), received_before)
        finally:
            peer.finish()

    def test_raw_journaled_exchange_and_recovery_without_topology(self):
        from cbus_toolkit.cli import main as cli_main
        peer = Peer(b"\\460400A307AABBg\r", [b"g.86041000320755D8\r"])
        try:
            with tempfile.TemporaryDirectory() as directory:
                journal = Path(directory) / "attempt.json"
                base = ["--compact", "pci", "--host", "127.0.0.1", "--port", str(peer.port),
                        "routed-write", "4", "7", "AABB", "--expected-ack-tag", "0x55",
                        "--expected-destination", "16", "--expected-source", "4",
                        "--journal", str(journal)]
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    self.assertEqual(cli_main(base), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["requested"]["bridges"], [])
                self.assertEqual(result["journal"], str(journal))
                self.assertEqual(load_routed_write_recovery(journal)["generation"]["project_sha256"], None)
                with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")):
                    output2, error2 = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(output2), contextlib.redirect_stderr(error2):
                        self.assertEqual(cli_main(base + ["--recover"]), 0)
                    recovery = json.loads(output2.getvalue())
                    self.assertTrue(recovery["recovery_only"])
                    self.assertFalse(recovery["io_performed"])
        finally:
            peer.finish()


if __name__ == "__main__":
    unittest.main()
