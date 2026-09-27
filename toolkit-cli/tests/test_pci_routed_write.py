"""Independent literal-wire and fault tests for one-shot routed WRITE."""
import dataclasses
import socket
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_routed_write as module
from cbus_toolkit.pci import AcknowledgeCAL, IdentifyCAL, PCIRejected, ProtocolError, WriteCAL
from cbus_toolkit.pci_routing import RoutedCALCommand
from cbus_toolkit.pci_routed_recall import RoutedReplyPath
from cbus_toolkit.pci_routed_write import RoutedWriteClient
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


if __name__ == "__main__":
    unittest.main()
