"""Independent literal protected-address packets and persistent fixture state."""
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.simulator import PCISimulator, synthetic_units


def fixture(**kwargs):
    units = synthetic_units()
    units[0].parameters[0x20] = b"\x04"
    return PCISimulator(units, profile="synthetic", readdress_challenges={4: 0x5A}, **kwargs)


def exchange(conn, command, expected):
    conn.sendall(command)
    result = bytearray()
    while len(result) < len(expected):
        block = conn.recv(len(expected) - len(result))
        if not block: break
        result.extend(block)
    return bytes(result)


class SimulatorAddressingTests(unittest.TestCase):
    def test_literal_unlock_special_store_recall_and_single_use(self):
        sim = fixture()
        with sim.running() as address, socket.create_connection(address, timeout=2) as conn:
            self.assertEqual(exchange(conn, b"\\4604001120g\r", b"g.8604100082205A6A\r\n"), b"g.8604100082205A6A\r\n")
            self.assertEqual(exchange(conn, b"A3204E065Ah\r", b"h.8606100032204EC4\r\n"), b"h.8606100032204EC4\r\n")
            self.assertEqual(exchange(conn, b"\\4606001A2001i\r", b"i.86061000822006BC\r\n"), b"i.86061000822006BC\r\n")
            self.assertEqual(exchange(conn, b"A3204E045Aj\r", b"j.860610003B204EBB\r\n"), b"j.860610003B204EBB\r\n")
        self.assertNotIn(4, sim.units)
        self.assertEqual(sim.units[6].attributes[4], bytes.fromhex("38FFFFFFFF18B10616A20005"))
        self.assertEqual(sim.readdress_challenges, {6: 0x5A})

    def test_invalid_missing_unlock_occupied_destination_and_malformed_store_do_not_move(self):
        for command in (b"\\460400A3204E065Bg\r", b"\\460400A3204E055Ag\r", b"\\460400A3204E105Ag\r",
                        b"\\460400A3204E005Ag\r", b"\\460400A3204EFF5Ag\r"):
            with self.subTest(command=command):
                sim = fixture(); before = sim.snapshot()
                with sim.running() as address, socket.create_connection(address, timeout=2) as conn:
                    exchange(conn, b"\\4604001120h\r", b"h.8604100082205A6A\r\n")
                    self.assertEqual(exchange(conn, command, b"g.860410003B204EBD\r\n"), b"g.860410003B204EBD\r\n")
                self.assertEqual(sim.snapshot(), before)
        sim = fixture()
        with sim.running() as address, socket.create_connection(address, timeout=2) as conn:
            self.assertEqual(exchange(conn, b"\\460400A3204E065Ag\r", b"g.860410003B204EBD\r\n"), b"g.860410003B204EBD\r\n")
            for command in (b"\\460400A3204E06h\r", b"\\460400A4204E065Ah\r", b"\\4604001121h\r"):
                self.assertEqual(exchange(conn, command, b"h#"), b"h#")
        self.assertIn(4, sim.units)

    def test_declared_memory_status_maps_survive_move_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            sim = fixture(state_path=path, legacy_memory={4: {0x20: 4, 0x21: 56, 0x22: 255}},
                          legacy_writable={4: {0x21}}, status_blocks={4: {1: b"chosen"}},
                          physical_memory={4: {100: 77}})
            sim._physical_pointers[4] = 100
            with sim.running() as address, socket.create_connection(address, timeout=2) as conn:
                exchange(conn, b"\\4604001120g\r", b"g.8604100082205A6A\r\n")
                self.assertEqual(exchange(conn, b"A3204E065Ah\r", b"h.8606100032204EC4\r\n"), b"h.8606100032204EC4\r\n")
            self.assertEqual(sim._physical_pointers, {6: 100})
            self.assertEqual(sim.legacy_memory[6], {0x20: 6, 0x21: 56, 0x22: 255})
            self.assertEqual(sim.legacy_writable, {6: {0x21}})
            self.assertEqual(sim.status_blocks, {6: {1: b"chosen"}})
            self.assertEqual(sim.physical_memory, {6: {100: 77}})
            restarted = PCISimulator(profile="synthetic", state_path=path)
            self.assertEqual(restarted.snapshot(), sim.snapshot())
            self.assertEqual(restarted._pending_readdress, {})
            with restarted.running() as address, socket.create_connection(address, timeout=2) as conn:
                self.assertEqual(exchange(conn, b"\\4606001A2001g\r", b"g.86061000822006BC\r\n"), b"g.86061000822006BC\r\n")
                self.assertEqual(exchange(conn, b"\\4604002101h\r", b"h#"), b"h#")

    def test_persistence_failure_rolls_back_every_map_before_ack(self):
        sim = fixture(legacy_memory={4: {0x20: 4, 0x21: 56}}, legacy_writable={4: {0x21}},
                      status_blocks={4: {1: b"chosen"}}, physical_memory={4: {100: 77}})
        before = sim.snapshot(); sim._physical_pointers[4] = 100
        with sim.running() as address, socket.create_connection(address, timeout=2) as conn:
            exchange(conn, b"\\4604001120g\r", b"g.8604100082205A6A\r\n")
            with patch.object(sim, "_persist", side_effect=OSError("disk full")):
                self.assertEqual(exchange(conn, b"A3204E065Ah\r", b"h#"), b"h#")
        self.assertEqual(sim.snapshot(), before)
        self.assertEqual(sim._physical_pointers, {4: 100})

    def test_opt_in_and_fixture_identity_address_protection_guards(self):
        for challenges in ({16: 0}, {5: 0}, {0: 0}, {255: 0}, {4: 256}, {4: True}):
            with self.subTest(challenges=challenges), self.assertRaises(ValueError):
                PCISimulator(profile="synthetic", readdress_challenges=challenges)
        with self.assertRaises(ValueError): PCISimulator(profile="synthetic", readdress_challenges={4: 1})
        with self.assertRaises(ValueError): fixture(legacy_memory={4: {32: 4}}, legacy_writable={4: {32}})
        sim = PCISimulator(profile="synthetic")
        with sim.running() as address, socket.create_connection(address, timeout=2) as conn:
            self.assertEqual(exchange(conn, b"\\4604001120g\r", b"g#"), b"g#")


if __name__ == "__main__": unittest.main()
