"""Independent literal PCI clock/burden vectors and persistence boundaries."""
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from cbus_toolkit.pci import PCIClient
from cbus_toolkit.simulator import PCISimulator

_spec = importlib.util.spec_from_file_location('clock_fixture', Path(__file__).resolve().parents[1] / 'research/clock_fixture.py')
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


class SimulatorClockTests(unittest.TestCase):
    def test_response_delay_precedes_complete_literal_reply_without_retries(self):
        sim = _fixture.clock_simulator()
        self.assertEqual(sim.response_delay, 0.01)
        sim.response_delay = 0.05
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as peer:
            start = time.monotonic()
            peer.sendall(b'\\4610002110g\r')
            self.assertEqual(peer.recv(100), b'g.8510030000FF69\r\n')
            self.assertGreaterEqual(time.monotonic() - start, 0.05)
        self.assertEqual([row['hex'] for row in sim.wire_log if row['direction'] == 'rx'],
                         [b'\\4610002110g\r'.hex()])
        self.assertEqual(PCISimulator().response_delay, 0)
        for invalid in (True, -1, float('nan'), float('inf'), 61, '0.01'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                PCISimulator(response_delay=invalid)

    def test_native_literal_clock_enable_reply_and_dynamic_summary(self):
        sim = _fixture.clock_simulator()
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as peer:
            peer.settimeout(2)
            for command, expected in (
                (b'\\4611001A3E0Cw\r', b'w.861110008D3E00FFFF0007A5A5A5A5A5A5A506\r\n'),
                (b'A33E0001x\r', b'x.86111000323E00E9\r\n'),
                (b'2110y\r', b'y.861110008510020000FFC3\r\n'),
                (b'A33E0000z\r', b'z.86111000323E00E9\r\n'),
                (b'2110g\r', b'g.861110008510000000FFC5\r\n'),
            ):
                peer.sendall(command)
                actual = bytearray()
                while len(actual) < len(expected):
                    received = peer.recv(len(expected) - len(actual))
                    self.assertTrue(received)
                    actual.extend(received)
                self.assertEqual(bytes(actual), expected)
        self.assertFalse([row for row in sim.wire_log if row.get('reason')])

    def test_burden_and_enabled_bits_persist_with_readonly_neighbors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            sim = _fixture.clock_simulator(state_path=path)
            with sim.running() as endpoint, PCIClient(*endpoint, local_unit=16) as client:
                # Literal tagged STORE sets clock and burden, preserving the
                # explicitly chosen surrounding schema and padding bytes.
                before = client.recall(17, 0x3e, 12)
                client.write(17, 0x3e, b'\x00\x41', ack_tag=0)
                self.assertEqual(client.identify(17, 16), bytes.fromhex('820000ff'))
                self.assertEqual(client.recall(17, 0x3e, 12), b'\x41' + before[1:])
                client.write(16, 0x3e, b'\x00\x40', ack_tag=0)
                self.assertEqual(client.identify(None, 16), bytes.fromhex('800000ff'))
            loaded = PCISimulator(profile='synthetic', state_path=path)
            self.assertEqual(loaded.clock_generator, 16)
            self.assertEqual(loaded.pci_settings_units, {16, 17})
            with loaded.running() as endpoint, PCIClient(*endpoint, local_unit=16) as client:
                self.assertEqual(client.recall(17, 0x3e, 1), b'\x41')
                self.assertEqual(client.identify(17, 16), bytes.fromhex('820000ff'))
                self.assertEqual(client.identify(16, 16), bytes.fromhex('800000ff'))

    def test_persistence_failure_rejects_store_and_keeps_status(self):
        sim = _fixture.clock_simulator()
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as peer:
            peer.settimeout(2)
            with patch.object(sim, '_persist', side_effect=OSError('injected disk failure')):
                peer.sendall(b'\\461100A33E0041g\r')
                self.assertEqual(peer.recv(2), b'g#')
            self.assertEqual(sim.legacy_memory[17][0x3e], 0)
            peer.sendall(b'2110h\r')
            self.assertEqual(peer.recv(100), b'h.861110008510000000FFC5\r\n')

    def test_unknown_and_protected_bytes_never_write(self):
        sim = _fixture.clock_simulator()
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as peer:
            peer.settimeout(2)
            for request in (b'\\461100A33F0001g\r', b'A33D0001g\r', b'1A4902g\r'):
                peer.sendall(request)
                self.assertEqual(peer.recv(2), b'g#')
        self.assertEqual(sim.legacy_memory[17][0x3e], 0)

    def test_settings_require_explicit_synthetic_layout(self):
        for options in ({'pci_settings_units': [16]}, {'profile': 'synthetic', 'pci_settings_units': [16]},
                        {'profile': 'synthetic', 'clock_generator': 16}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                PCISimulator(**options)
        raw = PCISimulator()
        self.assertEqual(raw.units[16].attributes[16], bytes.fromhex('030000ff'))
        self.assertEqual(raw.pci_settings_units, set())

    def test_old_snapshot_load_preserves_enable_without_enabling_clock_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            sim = PCISimulator(profile='synthetic')
            sim.enable.receive(bytes.fromhex('02017f'))
            old = sim.snapshot()
            del old['pci_settings_units']
            del old['clock_generator']
            path.write_text(json.dumps(old))
            loaded = PCISimulator(profile='synthetic', state_path=path)
            self.assertEqual(loaded.enable.snapshot(), sim.enable.snapshot())
            self.assertEqual(loaded.pci_settings_units, set())
            self.assertIsNone(loaded.clock_generator)
            self.assertEqual(loaded.units[16].attributes[16], bytes.fromhex('030000ff'))

    def test_enable_and_clock_settings_share_snapshot_without_losing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            sim = _fixture.clock_simulator(state_path=path)
            with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as peer:
                peer.settimeout(2)
                peer.sendall(b'\\05CB0002017Fg\r')
                self.assertEqual(peer.recv(2), b'g.')
            with sim.running() as endpoint, PCIClient(*endpoint, local_unit=16) as peer:
                peer.write(17, 0x3e, b'\x00\x41', ack_tag=0)
            loaded = PCISimulator(profile='synthetic', state_path=path)
            self.assertEqual(loaded.enable.snapshot(), sim.enable.snapshot())
            self.assertEqual(loaded.enable.variables[1]['level'], 127)
            self.assertEqual(loaded.legacy_memory[17][0x3e], 65)
            self.assertEqual(loaded.pci_settings_units, {16, 17})


if __name__ == '__main__':
    unittest.main()
