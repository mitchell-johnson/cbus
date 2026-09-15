"""Literal public/native SAL vectors against an independent timed peer."""
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.lighting_state import LightingPacketError, LightingState, RAMP_SECONDS
from cbus_toolkit.simulator import PCISimulator, synthetic_units
from cbus_toolkit.pci import PCIClient


class Clock:
    value = 0.0
    def __call__(self):
        return self.value


def wire(address, command, count=2):
    with socket.create_connection(address, timeout=1) as conn:
        conn.settimeout(1)
        conn.sendall(command)
        output = bytearray()
        while len(output) < count:
            part = conn.recv(count - len(output))
            if not part:
                break
            output.extend(part)
        return bytes(output)


class LightingStateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = LightingState({(56, 12): 0, (57, 12): 64}, clock=self.clock)

    def test_public_on_off_instant_and_application_isolation(self):
        for payload, expected in ((b"\x79\x0c", 255), (b"\x01\x0c", 0), (b"\x02\x0c\x7f", 127)):
            self.state.receive(56, payload)
            self.assertEqual(self.state.level(56, 12), expected)
            self.assertEqual(self.state.level(57, 12), 64)
        self.assertEqual(self.state.mmi_states(56), {12: 1})
        self.state.receive(56, b"\x01\x0c")
        self.assertEqual(self.state.mmi_states(56), {12: 2})

    def test_all_public_ramp_rates_are_full_scale_durations(self):
        expected = [0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900, 1020]
        self.assertEqual(list(RAMP_SECONDS.values()), expected)
        for opcode, seconds in zip(range(2, 123, 8), expected):
            with self.subTest(opcode=opcode):
                self.clock.value = 0
                state = LightingState({(56, 12): 0}, clock=self.clock)
                state.receive(56, bytes((opcode, 12, 255)))
                self.clock.value = seconds / 2
                self.assertEqual(state.level(56, 12), 127.5 if seconds else 255)
                self.clock.value = seconds
                self.assertEqual(state.level(56, 12), 255)

    def test_partial_ramp_terminate_and_replacement_use_current_level(self):
        self.state.receive(56, bytes.fromhex("0a0cff"))
        self.clock.value = 1
        self.assertEqual(self.state.level(56, 12), 63.75)
        self.state.receive(56, bytes.fromhex("090c"))
        self.clock.value = 100
        self.assertEqual(self.state.level(56, 12), 63.75)
        self.state.receive(56, bytes.fromhex("0a0c00"))
        self.clock.value = 100.5
        self.assertEqual(self.state.level(56, 12), 31.875)
        self.state.receive(56, bytes.fromhex("0a0cff"))
        self.clock.value = 104
        self.assertEqual(self.state.level(56, 12), 255)

    def test_chain_unknown_group_and_malformed_payload_are_atomic(self):
        before = self.state.snapshot()
        for payload in (b"", b"\x79", b"\x79\x0c\x0a", b"\x79\x0c\x79\x0d", b"\x03\x0c", b"\x79\xff"):
            with self.subTest(payload=payload), self.assertRaises(LightingPacketError):
                self.state.receive(56, payload)
            self.assertEqual(self.state.snapshot(), before)
        self.assertEqual(self.state.receive(56, bytes.fromhex("790c020c7f090c")), 3)
        self.assertEqual(self.state.level(56, 12), 127)

    def test_snapshot_pauses_and_resumes_at_sampled_progress(self):
        self.state.receive(56, bytes.fromhex("0a0cff"))
        self.clock.value = 1
        saved = self.state.snapshot()
        self.clock.value = 100
        restored = LightingState.from_snapshot(saved, clock=self.clock)
        self.assertEqual(restored.level(56, 12), 63.75)
        self.clock.value = 101
        self.assertEqual(restored.level(56, 12), 127.5)
        self.clock.value = 103
        self.assertEqual(restored.level(56, 12), 255)
        for changes in ({"remaining": -1}, {"level": float("nan")}, {"target": 256}, {"remaining": 0}, {"group": True}):
            invalid = json.loads(json.dumps(saved))
            invalid["groups"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(LightingPacketError):
                LightingState.from_snapshot(invalid)


class LightingSocketTests(unittest.TestCase):
    def test_legacy_terminal_slots_preserve_unmapped_indices(self):
        units = synthetic_units()
        units[0].attributes[1] = b"KEY4    "
        units[0].attributes[8] = b"\x0a\x0b\x0c"
        sim = PCISimulator(units, profile="synthetic",
                           legacy_memory={4: {0x21: 56, 0x50: 12, 0x52: 24}},
                           lighting_groups={(56, 12): 127, (56, 24): 64})
        with sim.running() as address, PCIClient(*address, local_unit=16) as client:
            self.assertEqual(client.identify(4, 8), b"\x7f\x0b\x40")
        # A missing group slot cannot shift later terminal indices.
        self.assertEqual(units[0].attributes[8], b"\x0a\x0b\x0c")

    def test_literal_compressed_commands_mmi_and_disk_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            sim = PCISimulator(profile="synthetic", state_path=path, fragment_sizes=(1,))
            with sim.running() as address:
                self.assertEqual(wire(address, b"\\053800790Cg\r020C7Fh\r", 4), b"g.h.")
                self.assertEqual(sim.lighting.level(56, 12), 127)
                # Only group12's two-bit pair differs from the independently
                # captured OFF fixture; checksum changes from5C to5D.
                expected = (b"i.D838000000000100008A0008000000000000000000000000005D\r\n"
                            b"D838580000000000000000000000000000000000000000000098\r\n"
                            b"D638B0000000000000000000000000000000000000000042\r\n")
                self.assertEqual(wire(address, b"\\05FF00FA3800i\r", len(expected)), expected)
            loaded = PCISimulator(profile="synthetic", state_path=path)
            self.assertEqual(loaded.lighting.level(56, 12), 127)
            with loaded.running() as address, PCIClient(*address, local_unit=16) as client:
                self.assertEqual(client.identify(4, 8), b"\x7f" + bytes(8))

    def test_timed_ramp_stop_and_persistence_failure_through_tcp(self):
        clock = Clock()
        sim = PCISimulator(profile="synthetic", lighting_clock=clock)
        with sim.running() as address:
            self.assertEqual(wire(address, b"\\0538000A0CFFg\r"), b"g.")
            clock.value = 2
            self.assertEqual(sim.lighting.level(56, 12), 127.5)
            self.assertEqual(wire(address, b"\\053800090Ch\r"), b"h.")
            clock.value = 10
            self.assertEqual(sim.lighting.level(56, 12), 127.5)
            before = sim.snapshot()
            with patch.object(sim, "_persist", side_effect=OSError("disk full")):
                self.assertEqual(wire(address, b"\\053800010Ci\r"), b"i#")
            self.assertEqual(sim.snapshot(), before)
            for request in (b"\\053800790C790Dg\r", b"\\0538000A0Cg\r"):
                self.assertEqual(wire(address, request), b"g#")
            self.assertEqual(sim.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
