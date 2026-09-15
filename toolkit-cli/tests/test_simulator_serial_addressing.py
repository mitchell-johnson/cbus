"""Source-correlated broadcast literals and explicit unprogrammed-slot state."""
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.simulator import PCISimulator, synthetic_units
from tests.test_simulator_addressing import exchange


def commissioning_fixture(*, address=255, empty_addresses=(6,), **kwargs):
    units = synthetic_units(); units[0].address = address; units[0].parameters[32] = bytes([address])
    return PCISimulator(units, profile="synthetic", readdress_challenges={address: 0x5A},
                        readdress_empty_addresses=empty_addresses, **kwargs)


class SimulatorSerialAddressingTests(unittest.TestCase):
    def test_literal_serial_broadcast_persisted_move_and_opaque_reply_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            sim = commissioning_fixture(address=4, state_path=state, serial_readdress_reply_tails={"101136.1558": b"\0\0"})
            with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as conn:
                expected = b"g.86061000870018B106160000F8\r\n"
                self.assertEqual(exchange(conn, b"\\05FF000F0018B106160615g\r", expected), expected)
                self.assertEqual(exchange(conn, b"\\4604001120h\r", b"h."), b"h.")
            self.assertEqual(sim.units[6].parameters[32], b"\x06")
            self.assertEqual(sim.readdress_empty_addresses, {4})
            loaded = PCISimulator(profile="synthetic", state_path=state)
            self.assertEqual(loaded.snapshot(), sim.snapshot())
            self.assertEqual(loaded.serial_readdress_reply_tails, {"101136.1558": b"\0\0"})
            self.assertNotIn(4, loaded.units)

    def test_unknown_serial_is_no_cal_and_invalid_or_occupied_requests_do_not_mutate(self):
        sim = commissioning_fixture(address=4, serial_readdress_reply_tails={"101136.1558": b"\0\0"})
        before = sim.snapshot()
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as conn:
            self.assertEqual(exchange(conn, b"\\05FF000F000000000106F9g\r", b"g."), b"g.")
            for command in (b"\\05FF000F0018B106160614h\r", b"\\05FF000F0018B106160516h\r",
                            b"\\05FF000F0018B106160417h\r", b"\\05FF000F0018B10616061500h\r"):
                with self.subTest(command=command): self.assertEqual(exchange(conn, command, b"h#"), b"h#")
        self.assertEqual(sim.snapshot(), before)

    def test_broadcast_failure_keeps_disk_and_memory_before_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            sim = commissioning_fixture(address=4, state_path=path, serial_readdress_reply_tails={"101136.1558": b"\0\0"})
            before = sim.snapshot(); disk = path.read_bytes()
            with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as conn:
                with patch.object(sim, "_persist", side_effect=OSError("disk full")):
                    self.assertEqual(exchange(conn, b"\\05FF000F0018B106160615g\r", b"g#"), b"g#")
            self.assertEqual(sim.snapshot(), before); self.assertEqual(path.read_bytes(), disk)

    def test_explicit_empty_slot_and_unprogrammed_address_unlock(self):
        sim = commissioning_fixture()
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as conn:
            self.assertEqual(exchange(conn, b"\\4606001120g\r", b"g."), b"g.")
            expected = b"h.86FF100082205A6F\r\n"
            self.assertEqual(exchange(conn, b"\\46FF001120h\r", expected), expected)
            self.assertEqual(exchange(conn, b"A3204E065Ai\r", b"i.8606100032204EC4\r\n"), b"i.8606100032204EC4\r\n")
        self.assertEqual(sim.readdress_empty_addresses, {255})

    def test_serial_broadcast_and_empty_slots_require_explicit_valid_fixture_state(self):
        for values in ({"bad": b"\0\0"}, {"0.0": b"\0\0"}, {"101136.1558": b"\0"}, {"101183.1666": b"\0\0"}):
            with self.subTest(values=values), self.assertRaises(ValueError): commissioning_fixture(serial_readdress_reply_tails=values)
        for values in ([True], [4], [0], [256], [6, 6]):
            with self.subTest(values=values), self.assertRaises(ValueError): PCISimulator(profile="synthetic", readdress_empty_addresses=values)
        sim = commissioning_fixture()
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as conn:
            self.assertEqual(exchange(conn, b"\\05FF000F0018B106160615g\r", b"g#"), b"g#")


if __name__ == "__main__": unittest.main()
