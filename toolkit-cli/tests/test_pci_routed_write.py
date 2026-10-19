"""Independent literal-wire and fault tests for one-shot routed WRITE."""
import dataclasses
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_routed_write as module
from cbus_toolkit import pci_routed_write_journal as journal_module
from cbus_toolkit.pci import AcknowledgeCAL, IdentifyCAL, PCIRejected, ProtocolError, WriteCAL
from cbus_toolkit.pci_routing import RoutedCALCommand
from cbus_toolkit.pci_routed_recall import RoutedReplyPath
from cbus_toolkit.pci_routed_write import RoutedWriteClient
from tests.test_pci_routed_recall import Peer, SocketFixture
from tests.test_pci_routed_recall import literal_command as recall_literal_command
from tests.test_pci_routed_recall import literal_frame as recall_literal_frame


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


J_BRIDGES = (20, 21)
J_PATH = RoutedReplyPath(20, 16, (21, 4))
J_COMMAND = RoutedCALCommand(4, WriteCAL(7, b"\x55\xaa\xbb"), bridges=J_BRIDGES)
J_WRITE = literal_command(data=b"\x55\xaa\xbb", bridges=J_BRIDGES)
J_ACK = literal_ack(outer=20, route=(21, 4))
J_RECALL = recall_literal_command(unit=4, parameter=7, count=2, bridges=J_BRIDGES)


def j_reply(data):
    return recall_literal_frame(outer=20, destination=16, route=(21, 4), parameter=7, data=data)


class _Crash(BaseException):
    """Stand-in for process death: nothing after it may be recorded."""


class RoutedWriteJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "attempt.json"

    def write(self, fixtures, *, path=None, **options):
        with patch.object(module.socket, "socket", side_effect=list(fixtures)), \
             patch.object(module.socket, "getaddrinfo", side_effect=AssertionError("No resolver")):
            return module.journaled_write(
                J_COMMAND, expected=J_PATH, expected_ack_tag=0x55, journal=path or self.path,
                host="127.0.0.1", port=10001, **options)

    def recover(self, chunks, **options):
        fixture = SocketFixture(chunks)
        with patch.object(module.socket, "socket", side_effect=[fixture]), \
             patch.object(module.RoutedWriteClient, "exchange",
                          side_effect=AssertionError("Recovery must never WRITE")):
            report = module.recover_write(self.path, host="127.0.0.1", port=10001, **options)
        self.assertEqual(fixture.sent, [J_RECALL])
        return report, fixture

    def document(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_baseline_journal_then_single_write_resolves_acknowledged(self):
        recall, write = SocketFixture([b"g." + j_reply(b"\x11\x22")]), SocketFixture([b"g." + J_ACK])
        receipt, attempt = self.write([recall, write])
        self.assertEqual(receipt.acknowledgement.raw, J_ACK)
        self.assertEqual((recall.sent, write.sent), ([J_RECALL], [J_WRITE]))
        document = self.document()
        self.assertEqual(document, attempt.document)
        self.assertEqual(document["phase"], "acknowledged")
        self.assertTrue(document["complete"] and document["resolved"])
        self.assertTrue(document["send_may_have_occurred"] and document["read_only_recovery_only"])
        plan = document["plan"]
        self.assertEqual(plan["recovery_read"], {"parameter": 7, "count": 2,
                                                 "expected_hex": "AABB", "baseline_hex": "1122"})
        self.assertEqual((plan["pci_generation"], plan["pci_generation_source"]), (None, "unavailable"))
        self.assertEqual(document["attempt_id"], journal_module.attempt_id(plan))
        self.assertEqual(plan["topology_sha256"], journal_module.topology_sha256(
            mode="raw", bridges=J_BRIDGES, expected=J_PATH.as_dict(), project_sha256=None,
            route_plan=None))
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual([entry["phase"] for entry in document["history"]], ["planned", "acknowledged"])

    def test_journal_records_planned_before_the_send(self):
        seen = []

        class Watching(SocketFixture):
            def sendall(inner, data):
                seen.append(json.loads(self.path.read_text(encoding="utf-8"))["phase"])
                super().sendall(data)

        self.write([SocketFixture([b"g." + j_reply(b"\x11\x22")]), Watching([b"g." + J_ACK])])
        self.assertEqual(seen, ["planned"])

    def test_journal_exclusivity_refuses_before_any_io(self):
        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaises(journal_module.RoutedWriteJournalError):
            self.write([])
        self.path.unlink()
        # An unresolved journal for the same endpoint/route/unit blocks a new path.
        crash = self.crash_before_send()
        other = Path(self.directory.name) / "second.json"
        with self.assertRaises(journal_module.RoutedWriteJournalError) as caught:
            self.write([], path=other)
        self.assertIn("unresolved", str(caught.exception))
        self.assertFalse(other.exists())
        # A different unit is a different target and is not blocked.
        command = RoutedCALCommand(5, WriteCAL(7, b"\x55\xaa\xbb"), bridges=J_BRIDGES)
        with patch.object(module.socket, "socket", side_effect=[SocketFixture([])]), \
             self.assertRaises(module.RoutedWriteRefused):
            module.journaled_write(command, expected=RoutedReplyPath(20, 16, (21, 5)),
                                   expected_ack_tag=0x55, journal=other, host="127.0.0.1")
        self.assertFalse(other.exists())
        self.assertEqual(crash["phase"], "planned")

    def test_concurrent_creation_between_baseline_and_journal_sends_nothing(self):
        recall = SocketFixture([b"g." + j_reply(b"\x11\x22")])

        def racing():
            if not self.path.exists():
                self.path.write_text("{}", encoding="utf-8")

        with self.assertRaises(journal_module.RoutedWriteJournalError):
            self.write([recall], handoff_check=racing)
        self.assertEqual(recall.sent, [J_RECALL])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{}")

    def crash_before_send(self):
        recall = SocketFixture([b"g." + j_reply(b"\x11\x22")])

        def crashing_factory(*args, **kwargs):
            client = module.RoutedWriteClient(*args, **kwargs)
            if crashing_factory.calls:
                client.exchange = lambda *a, **k: (_ for _ in ()).throw(_Crash())
            crashing_factory.calls += 1
            return client

        crashing_factory.calls = 0
        with patch.object(journal_module.RoutedWriteJournal, "advance", side_effect=_Crash()), \
             self.assertRaises(_Crash):
            self.write([recall], write_client_factory=crashing_factory)
        return self.document()

    def test_crash_before_send_leaves_planned_journal_and_recovery_classifies(self):
        document = self.crash_before_send()
        self.assertEqual(document["phase"], "planned")
        self.assertFalse(document["complete"] or document["resolved"])
        report, _ = self.recover([b"g." + j_reply(b"\x11\x22")])
        self.assertEqual(report["classification"], "unchanged")
        self.assertTrue(report["resolved"])
        self.assertEqual(report["journal_phase"], "planned")
        self.assertFalse(report["writes_attempted"] or report["write_resubmitted"])
        self.assertFalse(report["attempt_replay_authorized"])
        self.assertEqual(self.document()["resolution"]["outcome"], "unchanged")

    def test_lost_reply_is_uncertain_then_recovery_classifies_without_writing(self):
        cases = ((b"\xaa\xbb", "expected", True), (b"\x11\x22", "unchanged", True),
                 (b"\xaa\x22", "mixed", False), (b"\x00\x00", "mixed", False))
        for index, (fresh, classification, resolved) in enumerate(cases):
            with self.subTest(classification=classification, fresh=fresh):
                # A mixed result stays unresolved and would block the next
                # same-target WRITE in its directory, so each case owns one.
                case = Path(self.directory.name) / f"case-{index}"
                case.mkdir()
                self.path = case / "lost.json"
                write = SocketFixture([b"g."])
                with self.assertRaises(ConnectionError):
                    self.write([SocketFixture([b"g." + j_reply(b"\x11\x22")]), write])
                self.assertEqual(write.sent, [J_WRITE])
                document = self.document()
                self.assertEqual(document["phase"], "uncertain")
                self.assertTrue(document["send"]["send_attempted"])
                self.assertFalse(document["resolved"])
                report, _ = self.recover([b"g." + j_reply(fresh)])
                self.assertEqual(report["classification"], classification)
                self.assertTrue(report["conclusive"])
                self.assertEqual(report["resolved"], resolved)
                self.assertEqual(report["fresh_hex"], fresh.hex().upper())
                self.assertEqual(self.document()["resolved"], resolved)
                self.assertEqual(len(self.document()["recoveries"]), 1)

    def test_unreadable_recovery_leaves_journal_unresolved(self):
        with self.assertRaises(ConnectionError):
            self.write([SocketFixture([b"g." + j_reply(b"\x11\x22")]), SocketFixture([b"g."])])
        report, _ = self.recover([b"g."])
        self.assertEqual((report["classification"], report["conclusive"], report["resolved"]),
                         ("unreadable", False, False))
        self.assertEqual(report["errors"][0]["phase"], "recall")
        self.assertEqual(self.document()["phase"], "uncertain")

    def test_generation_change_refuses_before_send_or_is_uncertain_after(self):
        def probe(values):
            values = iter(values)
            return lambda: next(values)

        # Changed across the baseline read: no journal, no WRITE connection.
        recall = SocketFixture([b"g." + j_reply(b"\x11\x22")])
        with self.assertRaises(module.RoutedWriteRefused):
            self.write([recall], generation_probe=probe([7, 8]))
        self.assertFalse(self.path.exists())
        # Changed at the handoff: connected, refused before any byte, journal not-sent.
        write = SocketFixture([b"g." + J_ACK])
        with self.assertRaises(module.RoutedWriteRefused):
            self.write([SocketFixture([b"g." + j_reply(b"\x11\x22")]), write],
                       generation_probe=probe([7, 7, 8]))
        self.assertEqual(write.sent, [])
        document = self.document()
        self.assertEqual((document["phase"], document["resolved"]), ("not-sent", True))
        self.assertEqual(document["plan"]["pci_generation"], 7)
        self.assertEqual(document["plan"]["pci_generation_source"], "caller-probe")
        self.assertFalse(document["send"]["send_attempted"])
        # Changed after the send: the exact ACK is not accepted; outcome uncertain.
        self.path = Path(self.directory.name) / "after.json"
        write = SocketFixture([b"g." + J_ACK])
        with self.assertRaises(module.RoutedWriteUncertain):
            self.write([SocketFixture([b"g." + j_reply(b"\x11\x22")]), write],
                       generation_probe=probe([7, 7, 7, 9]))
        self.assertEqual(write.sent, [J_WRITE])
        document = self.document()
        self.assertEqual((document["phase"], document["resolved"]), ("uncertain", False))
        self.assertTrue(document["send"]["generation_changed_after_send"])
        report, _ = self.recover([b"g." + j_reply(b"\xaa\xbb")], generation_probe=lambda: 9)
        self.assertEqual((report["classification"], report["pci_generation_changed"]), ("expected", True))

    def test_topology_change_at_handoff_refuses_before_send(self):
        calls = []

        def check():
            calls.append(None)
            if len(calls) == 2:
                raise ValueError("project changed")

        write = SocketFixture([b"g." + J_ACK])
        with self.assertRaises(module.RoutedWriteRefused):
            self.write([SocketFixture([b"g." + j_reply(b"\x11\x22")]), write], handoff_check=check)
        self.assertEqual(write.sent, [])
        self.assertEqual(self.document()["phase"], "not-sent")

    def test_recover_never_writes_and_refuses_bad_inputs_before_io(self):
        with self.assertRaises(ConnectionError):
            self.write([SocketFixture([b"g." + j_reply(b"\x11\x22")]), SocketFixture([b"g."])])
        with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")):
            with self.assertRaises(ValueError):
                module.recover_write(self.path, host="127.0.0.2", port=10001)
            with self.assertRaises(ValueError):
                module.recover_write(self.path, host="127.0.0.1", port=10001,
                                     route_check=lambda plan: (_ for _ in ()).throw(ValueError("stale")))
            tampered = self.document()
            tampered["plan"]["data_hex"] = "55AACC"
            tampered_path = Path(self.directory.name) / "tampered.json"
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(journal_module.RoutedWriteJournalError):
                module.recover_write(tampered_path, host="127.0.0.1", port=10001)
        with patch.object(module, "RoutedWriteClient", side_effect=AssertionError("No WRITE client")):
            report, fixture = self.recover([b"g." + j_reply(b"\xaa\xbb")])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["automatic_retries"], 0)
        self.assertFalse(report["nonvolatile_persistence_verified"])
        self.assertEqual(len(fixture.sent), 1)

    def test_journal_mode_requires_a_recallable_tagged_payload(self):
        with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")):
            for data, tag in ((b"", 0x55), (b"\x55", 0x55), (b"\xaa\xbb", 0x55)):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    module.journaled_write(RoutedCALCommand(4, WriteCAL(7, data), bridges=J_BRIDGES),
                                           expected=J_PATH, expected_ack_tag=tag,
                                           journal=self.path, host="127.0.0.1")
        self.assertFalse(self.path.exists())


class RoutedWriteJournalIntegrityTests(unittest.TestCase):
    """Tampered, oversize and nonregular journals refuse before any I/O.

    Ported from the 2026-10-19 Mac mini WIP snapshot onto
    ``pci_routed_write_journal.RoutedWriteJournal``.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "attempt.json"
        with patch.object(module.socket, "socket",
                          side_effect=[SocketFixture([b"g." + j_reply(b"\x11\x22")]),
                                       SocketFixture([b"g." + J_ACK])]):
            module.journaled_write(J_COMMAND, expected=J_PATH, expected_ack_tag=0x55,
                                   journal=self.path, host="127.0.0.1", port=10001)
        self.raw = self.path.read_bytes()

    def refused(self, path):
        with patch.object(module.socket, "socket", side_effect=AssertionError("No socket")):
            with self.assertRaises(journal_module.RoutedWriteJournalError):
                journal_module.RoutedWriteJournal.open(path)
            with self.assertRaises((journal_module.RoutedWriteJournalError, ValueError)):
                module.recover_write(path, host="127.0.0.1", port=10001)

    def test_tampered_plan_and_safety_flags_refuse(self):
        for mutate in (lambda d: d["plan"].__setitem__("parameter", 8),
                       lambda d: d.__setitem__("read_only_recovery_only", False),
                       lambda d: d.__setitem__("send_may_have_occurred", False),
                       lambda d: d.__setitem__("unexpected", 1)):
            document = json.loads(self.raw)
            mutate(document)
            self.path.write_bytes((json.dumps(document) + "\n").encode())
            self.refused(self.path)
        self.path.write_bytes(self.raw)
        self.assertEqual(journal_module.RoutedWriteJournal.open(self.path).document["phase"],
                         "acknowledged")

    def test_oversize_missing_and_nonregular_journals_refuse(self):
        with open(self.path, "wb") as stream:
            stream.truncate(journal_module.MAX_ROUTED_WRITE_JOURNAL_BYTES + 1)
        self.refused(self.path)
        self.refused(Path(self.directory.name) / "missing.json")
        if hasattr(os, "mkfifo"):
            fifo = Path(self.directory.name) / "fifo.json"
            os.mkfifo(fifo)
            self.refused(fifo)
        self.path.write_bytes(self.raw)
        link = Path(self.directory.name) / "link.json"
        try:
            link.symlink_to(self.path)
        except OSError:
            return
        self.refused(link)


if __name__ == "__main__":
    unittest.main()
