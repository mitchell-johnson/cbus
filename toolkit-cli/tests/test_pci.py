"""Literal capture vectors plus an independent scripted TCP peer.

The peer does not use the implementation encoder: agreement between two
copies of the same codec would not establish interoperability.
"""
import contextlib
import socket
import threading
import unittest

from cbus_toolkit.pci import (
    AcknowledgeCAL, Confirmation, Frame, FrameStream, IdentifyCAL, Notification,
    PCIClient, PCIRejected, ProtocolError, RecallCAL, ReplyCAL, WriteCAL,
    decode_cal, decode_cals, decode_frame, encode_cal, encode_command,
)


# Values from the repository capture and its analysis, including unusual routes.
PROGRAMMING_WRITE = b"\\46050900A40041a000o\r"
PROGRAMMING_ACK = b"8605100100320041F1\r\n"
DATA_ACK = b"8605100100320142EF\r\n"
DIRECT_ACK = b"8605100032210012\r\n"
CNI_TYPE = b"890150435F434E49454421\r\n"
UNIT4_REPLY = b"8604990082300328\r\n"


@contextlib.contextmanager
def peer(test, dialogue):
    """Run a finite socket script and propagate every server-side assertion."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    failures = []

    def run():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(2)
                stream = conn.makefile("rb", buffering=0)
                for expected, chunks in dialogue:
                    received = bytearray()
                    while not received.endswith(b"\r"):
                        part = stream.read(1)
                        if not part:
                            break
                        received.extend(part)
                    test.assertEqual(bytes(received), expected)
                    for chunk in chunks:
                        if chunk is None:
                            test.assertEqual(conn.recv(1), b"", "Client must close after timeout")
                        else:
                            conn.sendall(chunk)
        except BaseException as exc:
            failures.append(exc)
        finally:
            listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        thread.join(3)
        test.assertFalse(thread.is_alive(), "Scripted PCI peer failed to finish")
        if failures:
            raise failures[0]


class CALTests(unittest.TestCase):
    def test_literal_cal_vectors(self):
        for obj, literal in [
            (IdentifyCAL(1), "2101"),
            (RecallCAL(0xFA, 44), "1AFA2C"),
            (WriteCAL(0, b"\x41\xA0\0"), "A40041A000"),
            (AcknowledgeCAL(0, 0x41), "320041"),
            (AcknowledgeCAL(1, 0x42), "320142"),
            (ReplyCAL(1, b"PC_CNIED"), "890150435F434E494544"),
        ]:
            with self.subTest(literal=literal):
                self.assertEqual(encode_cal(obj), bytes.fromhex(literal))
                self.assertEqual(decode_cal(bytes.fromhex(literal)), (obj, len(bytes.fromhex(literal))))

    def test_chained_cal_consumes_exact_count(self):
        self.assertEqual(decode_cals(bytes.fromhex("21021A2102320041823003")), (
            IdentifyCAL(2), RecallCAL(0x21, 2), AcknowledgeCAL(0, 0x41), ReplyCAL(0x30, b"\3")))

    def test_every_truncated_fixed_and_counted_cal_rejected(self):
        for literal in ("2101", "1AFA2C", "320041", "A40041A000", "890150435F434E494544"):
            value = bytes.fromhex(literal)
            for i in range(len(value)):
                with self.subTest(literal=literal, length=i), self.assertRaises(ProtocolError):
                    decode_cal(value[:i])
        for literal in ("80", "A0", "1A3000", "0800", "C100"):
            with self.subTest(literal=literal), self.assertRaises(ProtocolError):
                decode_cal(bytes.fromhex(literal))

    def test_no_byte_wrapping_or_payload_clipping(self):
        for bad in (-1, 256, 1.0, True):
            for constructor in (lambda: IdentifyCAL(bad), lambda: RecallCAL(bad, 1),
                                lambda: RecallCAL(0, bad), lambda: WriteCAL(bad, b""),
                                lambda: AcknowledgeCAL(0, bad), lambda: ReplyCAL(bad, b"")):
                with self.assertRaises(ValueError):
                    constructor()
        with self.assertRaises(ValueError):
            RecallCAL(0, 0)
        for cls in (WriteCAL, ReplyCAL):
            self.assertEqual(len(cls(0, bytes(30)).encode()), 32)
            with self.assertRaises(ValueError):
                cls(0, bytes(31))
            with self.assertRaises(TypeError):
                cls(0, 30)


class FrameTests(unittest.TestCase):
    def test_programming_capture_preserves_route_and_mixed_case(self):
        frame = decode_frame(PROGRAMMING_WRITE, from_pci=False)
        self.assertEqual(frame.destination, 5)
        self.assertEqual(frame.route, b"\x09\x00")
        self.assertEqual(frame.confirmation, b"o")
        self.assertEqual(frame.cals, (WriteCAL(0, b"\x41\xA0\0"),))
        self.assertEqual(encode_command(5, frame.cals[0], addressing="programming", confirmation=b"o"),
                         b"\\46050900A40041A000o\r")

    def test_ack_source_is_not_destination_or_route(self):
        for raw, expected in ((PROGRAMMING_ACK, AcknowledgeCAL(0, 0x41)),
                              (DATA_ACK, AcknowledgeCAL(1, 0x42))):
            frame = decode_frame(raw)
            self.assertEqual((frame.source, frame.destination, frame.route), (5, 16, b"\x01\0"))
            self.assertEqual(frame.cals, (expected,))
        self.assertEqual(decode_frame(DIRECT_ACK).cals, (AcknowledgeCAL(0x21, 0),))

    def test_direct_response_and_ambiguous_86_use_explicit_mode(self):
        frame = decode_frame(CNI_TYPE)
        self.assertTrue(frame.bare)
        self.assertIsNone(frame.source)
        self.assertEqual(frame.cals, (ReplyCAL(1, b"PC_CNIED"),))
        frame = decode_frame(UNIT4_REPLY)
        self.assertEqual((frame.source, frame.destination), (4, 153))
        self.assertEqual(frame.cals, (ReplyCAL(0x30, b"\3"),))
        frame = decode_frame(UNIT4_REPLY, bare=True)
        self.assertTrue(frame.bare)
        self.assertEqual(frame.cals, (ReplyCAL(4, bytes.fromhex("9900823003")),))

    def test_invalid_checksum_hex_routing_truncation(self):
        for raw in (b"8605100100320041F0\r\n", b"123\r", b"gggg\r",
                    b"8605100200320041F0\r\n", b"890150435F434E494500\r\n"):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                decode_frame(raw)
        with self.assertRaisesRegex(ProtocolError, "routing"):
            decode_frame(b"\\46051200A40041A000o\r", from_pci=False)

    def test_command_vectors_and_checksum_mode(self):
        self.assertEqual(encode_command(16, IdentifyCAL(1), confirmation=b"g"), b"\\4610002101g\r")
        self.assertEqual(encode_command(4, RecallCAL(0x30, 1), confirmation=b"g", checksum=True),
                         b"\\4604001A30016Bg\r")
        self.assertEqual(encode_command(None, WriteCAL(0, b"\x41\x16\0"), confirmation=b"m"),
                         b"A400411600m\r")
        for options in ({"addressing": "bridge"}, {"confirmation": b"a"}, {"confirmation": b"zz"}):
            with self.assertRaises(ValueError):
                encode_command(5, IdentifyCAL(1), **options)
        with self.assertRaises(ValueError):
            encode_command(None, WriteCAL(0, b""), addressing="programming")

    def test_every_split_and_coalesced_stream_preserves_all_events(self):
        wire = b"\x11g\x13." + PROGRAMMING_ACK + b"h." + DATA_ACK + b"+\r\n!"
        expected = FrameStream().feed(wire)
        self.assertEqual(len(expected), 6)
        self.assertEqual(expected[0], Confirmation(b"g", "."))
        self.assertEqual(expected[-2:], [Notification("+"), Notification("!")])
        for split in range(len(wire) + 1):
            stream = FrameStream()
            self.assertEqual(stream.feed(wire[:split]) + stream.feed(wire[split:]), expected)
            stream.finish()
        stream = FrameStream()
        events = []
        for c in wire:
            events.extend(stream.feed(bytes((c,))))
        self.assertEqual(events, expected)
        stream.finish()

    def test_truncated_oversized_and_invalid_confirmations(self):
        for wire in (b"8", b"86", b"g"):
            stream = FrameStream()
            self.assertEqual(stream.feed(wire), [])
            with self.assertRaisesRegex(ProtocolError, "truncated"):
                stream.finish()
        for wire in (b"123456789", b"123456789\r"):
            with self.assertRaisesRegex(ProtocolError, "maximum"):
                FrameStream(max_buffer=8).feed(wire)
        with self.assertRaises(ProtocolError):
            FrameStream().feed(b"g?")
        self.assertEqual(FrameStream().feed(b"g#h!"), [Confirmation(b"g", "#"), Confirmation(b"h", "!")])

    def test_documented_checksum_and_clock_failures_survive_every_split(self):
        # CBUS-QS issue 2.0 section 4.2 specifies these two literal statuses.
        wire = b"g$h%"
        expected = [Confirmation(b"g", "$"), Confirmation(b"h", "%")]
        for split in range(len(wire) + 1):
            stream = FrameStream()
            self.assertEqual(stream.feed(wire[:split]) + stream.feed(wire[split:]), expected)
            stream.finish()


class ClientTests(unittest.TestCase):
    def test_unit_source_parameter_confirmation_and_trailing_frames(self):
        # First reply has the wrong source; second has the wrong parameter.
        # An unrelated confirmation and later frame must also survive parsing.
        response = (b"z.8605990082300327\r\n8604990082310327\r\n"
                    + UNIT4_REPLY + b"g." + DATA_ACK)
        with peer(self, [(b"\\4604001A3001g\r", [response])]) as port:
            with PCIClient("127.0.0.1", port) as client:
                self.assertEqual(client.recall(4, 0x30, 1), b"\3")
                self.assertEqual(len(client.unsolicited), 4)
                self.assertEqual(client.unsolicited[0], Confirmation(b"z", "."))
                self.assertEqual(client.unsolicited[-1].cals, (AcknowledgeCAL(1, 0x42),))

    def test_programming_write_waits_for_confirmation_and_matching_ack(self):
        response = DATA_ACK + b"\x11g" + b"." + PROGRAMMING_ACK
        with peer(self, [(b"\\46050900A40041A000g\r", [response[:17], response[17:]])]) as port:
            with PCIClient("127.0.0.1", port) as client:
                result = client.write(5, 0, b"\x41\xA0\0", addressing="programming", ack_tag=0x41)
                self.assertEqual(result, AcknowledgeCAL(0, 0x41))
                self.assertEqual(client.unsolicited[0].cals, (AcknowledgeCAL(1, 0x42),))

    def test_two_requests_and_bare_attached_pci(self):
        with peer(self, [(b"@1A2001\r", [b"8220104E\r\n"]),
                         (b"\\4610002101g\r", [CNI_TYPE, b"g."]),
                         (b"\\4610002101h\r", [b"h." + CNI_TYPE])]) as port:
            with PCIClient("127.0.0.1", port) as client:
                self.assertEqual(client.identify(None, 1), b"PC_CNIED")
                self.assertEqual(client.identify(None, 1), b"PC_CNIED")

    def test_local_discovery_ignores_addressed_monitor_traffic(self):
        monitor = b"8604990082200338\r\n"
        with peer(self, [(b"@1A2001\r", [monitor + b"8220104E\r\n"]),
                         (b"\\4610002101g\r", [b"g." + CNI_TYPE])]) as port:
            with PCIClient("127.0.0.1", port) as client:
                self.assertEqual(client.identify(None, 1), b"PC_CNIED")
                self.assertEqual(client.local_unit, 16)
                self.assertEqual(client.unsolicited[0].source, 4)

    def test_invalid_discovery_never_sends_requested_write(self):
        for reply in (b"!", b"832010004D\r\n", b"8604990082200338\r\n"):
            with self.subTest(reply=reply):
                with peer(self, [(b"@1A2001\r", [reply])]) as port:
                    with PCIClient("127.0.0.1", port) as client:
                        with self.assertRaises((ProtocolError, ConnectionError)):
                            client.write(None, 0, b"\x41\0\0")
                        self.assertIsNone(client.socket)
                        self.assertIsNone(client.local_unit)

    def test_known_local_unit_uses_explicit_route_without_discovery(self):
        with peer(self, [(b"\\4610002101g\r", [b"g." + CNI_TYPE])]) as port:
            with PCIClient("127.0.0.1", port, local_unit=16) as client:
                self.assertEqual(client.identify(None, 1), b"PC_CNIED")

    def test_explicit_local_unit_accepts_bare_response(self):
        with peer(self, [(b"\\4610002101g\r", [b"g." + CNI_TYPE])]) as port:
            with PCIClient("127.0.0.1", port, local_unit=16) as client:
                self.assertEqual(client.identify(16, 1), b"PC_CNIED")

    def test_unproven_source_and_confirmation_alone_cannot_prove_success(self):
        for response in (b"g." + CNI_TYPE, b"g.", PROGRAMMING_ACK):
            with self.subTest(response=response):
                with peer(self, [(b"\\4605002101g\r", [response])]) as port:
                    with PCIClient("127.0.0.1", port) as client:
                        with self.assertRaises(ConnectionError):
                            client.identify(5, 1)
                        self.assertIsNone(client.socket)

    def test_ack_tag_mismatch_is_not_success(self):
        with peer(self, [(b"\\46050900A40041A000g\r", [b"g." + PROGRAMMING_ACK])]) as port:
            with PCIClient("127.0.0.1", port) as client:
                with self.assertRaises(ConnectionError):
                    client.write(5, 0, b"\x41\xA0\0", addressing="programming", ack_tag=0x42)

    def test_recall_length_mismatch_does_not_return_partial_data(self):
        with peer(self, [(b"\\4604001A3002g\r", [b"g." + UNIT4_REPLY])]) as port:
            with PCIClient("127.0.0.1", port) as client:
                with self.assertRaisesRegex(ProtocolError, "length mismatch"):
                    client.recall(4, 0x30, 2)
                self.assertIsNone(client.socket)

    def test_timeout_requires_response_and_never_retries_write(self):
        with peer(self, [(b"\\46050900A40041A000g\r", [b"g.", None])]) as port:
            with PCIClient("127.0.0.1", port, timeout=0.03) as client:
                with self.assertRaises(TimeoutError):
                    client.write(5, 0, b"\x41\xA0\0", addressing="programming")
                self.assertIsNone(client.socket)
                with self.assertRaises(RuntimeError):
                    client.write(5, 0, b"\x41\xA0\0", addressing="programming")

    def test_monitor_packet_cannot_masquerade_as_local_reply(self):
        with peer(self, [(b"@1A2001\r", [b"8220104E\r\n"]),
                         (b"\\4610002104g\r", [b"g." + UNIT4_REPLY])]) as port:
            with PCIClient("127.0.0.1", port) as client:
                with self.assertRaises(ConnectionError):
                    client.identify(None, 4)

    def test_peer_rejection_buffer_error_and_bad_checksum_close_client(self):
        for response in (b"g#", b"g!", b"!", b"g.8604990082300329\r\n"):
            with self.subTest(response=response):
                with peer(self, [(b"\\4604001A3001g\r", [response])]) as port:
                    with PCIClient("127.0.0.1", port) as client:
                        with self.assertRaises(ProtocolError):
                            client.recall(4, 0x30, 1)
                        self.assertIsNone(client.socket)

    def test_documented_transmit_failures_close_without_retry(self):
        for status in (b"$", b"%"):
            with self.subTest(status=status):
                with peer(self, [(b"\\4604001A3001g\r", [b"g" + status, None])]) as port:
                    with PCIClient("127.0.0.1", port) as client:
                        with self.assertRaises(PCIRejected) as caught:
                            client.recall(4, 0x30, 1)
                        self.assertTrue(str(caught.exception).endswith(status.decode()))
                        self.assertIsNone(client.socket)

    def test_captured_multical_recall_assembles_exact44_bytes(self):
        chunks = [b"g.860510010091FAFFFFFFFFFFFFFFFFFFFFFFFF381B381941\r\n",
                  b"860510010091FA38213818FFFFFFFFFFFFFFFFFFFFFFFF3C\r\n",
                  b"86051001008DFAFFFFFFFFFFFFFFFFFFFFFFFFE9\r\n"]
        expected = bytes.fromhex("FFFFFFFFFFFFFFFFFFFFFFFF381B381938213818FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF")
        with peer(self, [(b"\\460509001AFA2Cg\r", chunks)]) as port:
            with PCIClient("127.0.0.1", port) as client:
                self.assertEqual(client.recall(5, 0xFA, 44, addressing="programming"), expected)

    def test_multical_recall_rejects_missing_and_excess_data(self):
        first = b"g.860510010091FAFFFFFFFFFFFFFFFFFFFFFFFF381B381941\r\n"
        for count, chunks in ((44, [first]), (1, [first])):
            expected_command = b"\\460509001AFA" + (b"2C" if count == 44 else b"01") + b"g\r"
            with peer(self, [(expected_command, chunks)]) as port:
                with PCIClient("127.0.0.1", port) as client:
                    with self.assertRaisesRegex(ProtocolError, "length mismatch"):
                        client.recall(5, 0xFA, count, addressing="programming")

    def test_checksums_and_recall_counts_are_validated(self):
        with peer(self, [(b"\\4604001A30016Bg\r", [b"g." + UNIT4_REPLY])]) as port:
            with PCIClient("127.0.0.1", port, command_checksum=True) as client:
                self.assertEqual(client.recall(4, 0x30, 1), b"\3")
        client = PCIClient("127.0.0.1")
        with self.assertRaises(ValueError):
            client.recall(4, 0, 256)
        for bad in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                PCIClient("127.0.0.1", timeout=bad)


if __name__ == "__main__":
    unittest.main()
