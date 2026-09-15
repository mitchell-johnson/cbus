from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.simulator_applications import ApplicationPacketError, TriggerState


class SimulatorApplicationTests(unittest.TestCase):
    def test_literal_native_capture_events_and_kill_preserve_selector(self):
        state = TriggerState()
        self.assertEqual(state.receive(bytes.fromhex('02017b')), 1)
        self.assertEqual(state.groups[1], {'selector': 123, 'indicator_active': True, 'event_count': 1, 'kill_count': 0})
        state.receive(bytes.fromhex('0901'))
        self.assertEqual(state.groups[1], {'selector': 123, 'indicator_active': False, 'event_count': 1, 'kill_count': 1})
        state.receive(bytes.fromhex('02017f'))
        self.assertEqual(state.groups[1]['selector'], 127)

    def test_repeated_event_is_not_deduplicated_and_chains_are_atomic(self):
        state = TriggerState()
        self.assertEqual(state.receive(bytes.fromhex('020109020109')), 2)
        self.assertEqual(state.groups[1]['event_count'], 2)
        before = state.snapshot()
        for payload in ('02010202', '020102ff01', '', '01', '0201'):
            with self.subTest(payload=payload), self.assertRaises(ApplicationPacketError):
                state.receive(bytes.fromhex(payload))
            self.assertEqual(state.snapshot(), before)

    def test_native_receiver_min_max_and_kill_without_prior_selector(self):
        state = TriggerState()
        state.receive(bytes.fromhex('090301017902'))
        self.assertIsNone(state.groups[3]['selector'])
        self.assertFalse(state.groups[3]['indicator_active'])
        self.assertEqual(state.groups[1]['selector'], 0)
        self.assertEqual(state.groups[2]['selector'], 255)

    def test_bounded_history_persistence_and_snapshot_validation(self):
        state = TriggerState()
        for _ in range(300):
            state.receive(bytes.fromhex('02017b'))
        self.assertEqual(len(state.events), 256)
        self.assertEqual(state.events[0]['sequence'], 45)
        self.assertEqual(TriggerState.from_snapshot(state.snapshot()).snapshot(), state.snapshot())
        for change in ('count', 'sequence', 'selector', 'duplicate'):
            snapshot = state.snapshot()
            if change == 'count':
                snapshot['groups'][0]['event_count'] = 299
            elif change == 'sequence':
                snapshot['events'][-1]['sequence'] = 1
            elif change == 'selector':
                snapshot['groups'][0]['selector'] = 256
            else:
                snapshot['groups'].append(dict(snapshot['groups'][0]))
            with self.subTest(change=change), self.assertRaises(ApplicationPacketError):
                TriggerState.from_snapshot(snapshot)

    def test_literal_socket_frames_compression_atomic_rejection_and_disk_reload(self):
        from cbus_toolkit.simulator import PCISimulator
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            simulator = PCISimulator(profile='synthetic', state_path=path)
            with simulator.running() as address, socket.create_connection(address, timeout=2) as connection:
                for packet, reply in ((b'\\05CA0002017Bq\r', b'q.'), (b'0901r\r', b'r.'), (b'02017Fs\r', b's.')):
                    connection.sendall(packet)
                    self.assertEqual(connection.recv(2), reply)
                self.assertEqual(simulator.triggers.groups[1], {'selector': 127, 'indicator_active': True, 'event_count': 2, 'kill_count': 1})
                before = simulator.triggers.snapshot()
                connection.sendall(b'02010902t\r')
                self.assertEqual(connection.recv(2), b't#')
                self.assertEqual(simulator.triggers.snapshot(), before)
            reloaded = PCISimulator(profile='synthetic', state_path=path)
            self.assertEqual(reloaded.triggers.snapshot(), before)

    def test_trigger_persistence_failure_rolls_back_whole_chain(self):
        from cbus_toolkit.simulator import PCISimulator
        simulator = PCISimulator(profile='synthetic')
        before = simulator.triggers.snapshot()
        with simulator.running() as address, socket.create_connection(address, timeout=2) as connection:
            with patch.object(simulator, '_persist', side_effect=OSError('disk full')):
                connection.sendall(b'\\05CA0002017B0901q\r')
                self.assertEqual(connection.recv(2), b'q#')
            self.assertEqual(simulator.triggers.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
