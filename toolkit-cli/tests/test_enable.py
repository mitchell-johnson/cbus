import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit.enable import NativeEnable, encode_enable_set, parse_enable_event
from cbus_toolkit.simulator_enable import EnablePacketError, EnableState


class EnableTests(unittest.TestCase):
    def test_native_event_literal_and_malformed_values(self):
        line = "#e# 20260914-102313.996 702 //EN0F6EAE/254/203/1 3496d660-9254-103f-aa50-c222a1decd35 [enable] set value=127 sourceUnit=16 sessionId=cmd1317 commandId=57"
        event = parse_enable_event(line)
        self.assertEqual((event.value, event.source_unit, event.session_id, event.command_id), (127, 16, "cmd1317", "57"))
        self.assertIsNone(parse_enable_event(line.replace("set value=127 sourceUnit=16", "loaded application")))
        for mutated in (line.replace("value=127", "value=256"), line.replace("sourceUnit=16", "sourceUnit=256"), line + " commandId=58", line + "\n"):
            with self.assertRaises(ValueError):
                parse_enable_event(mutated)

    def test_literal_vendor_wire_and_numeric_validation(self):
        self.assertEqual(encode_enable_set(1, "50%"), bytes.fromhex("02017f"))
        self.assertEqual(encode_enable_set(255, "$ff"), bytes.fromhex("02ffff"))
        for variable, value in ((True, 0), (256, 0), (1, "Named"), (1, "101%"), (1, -1)):
            with self.assertRaises(ValueError):
                encode_enable_set(variable, value)

    def test_native_command_named_level_and_cached_byte_get(self):
        from test_applications import Client, Reply
        client = Client(Reply("300 //HOME/254/203/1: Level=127"))
        control = NativeEnable(client)
        control.set("//HOME/254/203/1", "50%", force=True)
        control.set("//HOME/254/203/1", "Evening")
        self.assertEqual(client.commands[:3], ["ENABLE SET //HOME/254/203/1 127 FORCE", "DBGETXML //HOME/254/203/1", "ENABLE SET //HOME/254/203/1 123"])
        result = control.level("//HOME/254/203/1")
        self.assertEqual(result["levels"], {"//HOME/254/203/1": 127})
        self.assertTrue(result["cached"])
        self.assertFalse(result["device_verified"])
        for value in ("-1", "256", "1.5", "unknown"):
            client.reply = Reply("300 //HOME/254/203/1: Level=" + value)
            with self.assertRaises(ValueError):
                control.level("//HOME/254/203/1")
        before = len(client.commands)
        with self.assertRaises(ValueError):
            control.set("//HOME/254/203/1", 0, force="true")
        with self.assertRaises(ValueError):
            control.remove("//HOME/254/203/1\nNOOP")
        self.assertEqual(len(client.commands), before)

    def test_independent_decoder_atomic_chains_and_strict_persistence(self):
        state = EnableState()
        self.assertEqual(state.receive(bytes.fromhex("02010002ffff02017f")), 3)
        self.assertEqual(state.variables, {1: {"level": 127, "set_count": 2}, 255: {"level": 255, "set_count": 1}})
        snapshot = state.snapshot()
        for payload in (bytes.fromhex("0201010901"), bytes.fromhex("0201"), bytes.fromhex("020101090101"), b"", "020100"):
            with self.assertRaises(EnablePacketError):
                state.receive(payload)
            self.assertEqual(state.snapshot(), snapshot)
        self.assertEqual(EnableState.from_snapshot(json.loads(json.dumps(snapshot))).snapshot(), snapshot)
        for invalid in ({**snapshot, "sequence": 4}, {**snapshot, "variables": snapshot["variables"] * 2}, {**snapshot, "sequence": True}):
            with self.assertRaises(EnablePacketError):
                EnableState.from_snapshot(invalid)

    def test_simulator_socket_header_compression_disk_and_failed_write_rollback(self):
        from cbus_toolkit.simulator import PCISimulator
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            sim = PCISimulator(profile="synthetic", state_path=path)
            with sim.running() as address, socket.create_connection(address, timeout=1) as conn:
                conn.settimeout(1)
                conn.sendall(b"\\05CB0002017Fg\r")
                self.assertEqual(conn.recv(2), b"g.")
                conn.sendall(b"0201FFh\r")
                self.assertEqual(conn.recv(2), b"h.")
                before = sim.snapshot()
                with patch.object(sim, "_persist", side_effect=OSError("disk full")):
                    conn.sendall(b"020100i\r")
                    self.assertEqual(conn.recv(2), b"i#")
                self.assertEqual(sim.snapshot(), before)
            reloaded = PCISimulator(profile="synthetic", state_path=path)
            self.assertEqual(reloaded.enable.snapshot(), sim.enable.snapshot())
            self.assertEqual(reloaded.enable.variables[1], {"level": 255, "set_count": 2})

    def test_cli_reports_queue_and_rejects_native_confirmation(self):
        from test_cgate import peer
        for reply, expected in ((b"[1] 200 OK.\r\n", 0), (b"[1] 600 Please confirm\r\n", 1)):
            with peer([[reply]]) as ((host, port), sent):
                result = subprocess.run([sys.executable, "-m", "cbus_toolkit", "cgate", "--host", host, "--port", str(port), "enable", "set", "//HOME/254/203/1", "50%", "--force"], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                data = json.loads(result.stdout if result.returncode == 0 else result.stderr)
                if expected == 0:
                    self.assertTrue(data["queued"])
                    self.assertFalse(data["device_verified"])
            self.assertEqual(sent, [b"[1] ENABLE SET //HOME/254/203/1 127 FORCE\r\n"])


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native Enable Control acceptance")
class NativeEnableTests(unittest.TestCase):
    def test_native_set_named_level_cache_remove_and_peer_persistence(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.simulator import PCISimulator
        name = "EN" + uuid4().hex[:6].upper()
        network, group = f"//{name}/254", f"//{name}/254/203/1"
        report = {"project": name, "commands": [], "physical_device_verified": False}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            sim = PCISimulator(profile="synthetic", state_path=path)
            with sim.running("0.0.0.0", 0) as (_, port), CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=30) as client:
                class Recorded:
                    def command(self, text):
                        response = client.command(text)
                        report["commands"].append({"command": text, "lines": response.lines,
                                                   "command_id": str(client._sequence)})
                        return response
                control = NativeEnable(Recorded())
                db, projects = NativeDatabase(client), NativeProjects(client)
                projects.operation("new", name)
                try:
                    projects.operation("save", name)
                    db.create_network(name, 254, "Enable", "Cni", f'{os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal")}:{port}')
                    db.add(network, "application", 203, "Enable")
                    db.add(network + "/203", "netvar", 1, "Sensor")
                    db.add(group, "level", 123, "Sensor enabled")
                    projects.operation("save", name)
                    client.command("NET LOAD DB " + name)
                    client.command("EVENT e9s0c0")
                    client.command("NET OPEN " + network)
                    deadline = time.monotonic() + 20
                    while "state=ok" not in client.command("GET " + network + " state").final:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.1)
                    events, event_lines, command_ids = [], [], []
                    for index, value in enumerate((0, 255, "50%", "Sensor enabled", "Sensor enabled"), 1):
                        control.set(group, value, force=isinstance(value, str))
                        command_id = report["commands"][-1]["command_id"]
                        command_ids.append(command_id)
                        deadline = time.monotonic() + 5
                        while sim.enable.sequence < index:
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(0.01)
                        # The receiver mutates before C-Gate processes its PCI
                        # confirmation. A duplicate FORCE issued in that gap can
                        # share the pending native command instead of sending a
                        # second SAL. The correlated702 is downstream of native
                        # queue removal; await it before the next operation.
                        previous_timeout = client.timeout
                        try:
                            while True:
                                remaining = deadline - time.monotonic()
                                self.assertGreater(remaining, 0, "Timed out waiting for the correlated Enable event")
                                client.timeout = min(previous_timeout, remaining)
                                line = client.read_event()
                                event_lines.append(line)
                                event = parse_enable_event(line)
                                if event is not None and event.address == group:
                                    events.append(event)
                                    if event.command_id == command_id and event.source_unit == 16:
                                        break
                        finally:
                            client.timeout = previous_timeout
                    self.assertEqual(sim.enable.variables, {1: {"level": 123, "set_count": 5}})
                    self.assertEqual(control.level(group)["levels"], {group: 123})
                    self.assertEqual(control.state(group)["objects"][group], {"State": "ok"})
                    self.assertEqual(control.groups(network + "/203")["groups"], {network + "/203": [1]})
                    events.extend(event for text in client.events if (event := parse_enable_event(text)) is not None and event.address == group)
                    self.assertEqual([event.value for event in events], [0, 255, 127, 123, 123])
                    self.assertTrue(all(event.source_unit == 16 and event.session_id and event.command_id for event in events))
                    self.assertEqual([event.command_id for event in events], command_ids)
                    self.assertEqual(len({event.session_id for event in events}), 1)
                    self.assertEqual(PCISimulator(profile="synthetic", state_path=path).enable.snapshot(), sim.enable.snapshot())
                    before_remove = sim.enable.snapshot()
                    original_xml = db.get(group, xml=True).lines
                    self.assertEqual(control.remove(group).code, 200)
                    # Exact native build2001 does not remove its in-memory
                    # variable despite the public help's stronger description.
                    self.assertEqual(control.level(group)["levels"], {group: 123})
                    self.assertEqual(control.groups(network + "/203")["groups"], {network + "/203": [1]})
                    self.assertEqual(sim.enable.snapshot(), before_remove)
                    self.assertEqual(db.get(group, xml=True).lines, original_xml)
                    self.assertFalse([record for record in sim.wire_log if "reason" in record])
                    report.update(passed=True, peer_state=sim.enable.snapshot(), wire=list(sim.wire_log),
                                  events=event_lines + list(client.events),
                                  per_operation_deadline_seconds=5, event_command_ids=command_ids)
                finally:
                    for command in ("NET CLOSE " + network, "PROJECT CLOSE " + name, "PROJECT DELETE " + name):
                        if not client.connected:
                            client.connect()
                        client.command(command)
            if os.environ.get("CBUS_ENABLE_REPORT"):
                target = Path(os.environ["CBUS_ENABLE_REPORT"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
