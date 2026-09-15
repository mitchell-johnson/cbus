"""Opt-in real C-Gate and CLI acceptance against only an ephemeral simulator."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.cli import main
from cbus_toolkit.simulator import PCISimulator, synthetic_units


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for isolated native lighting acceptance")
class NativeLightingTests(unittest.TestCase):
    def test_new_native_project_scans_restarted_nonzero_peer(self):
        host = os.environ["CBUS_CGATE_TEST_HOST"]
        oracle_port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        project = "LGR" + uuid4().hex[:5].upper()
        network = f"//{project}/254"
        report = {"scope": "Fresh native project scan against restarted persisted nonzero synthetic lighting",
                  "project": project, "passed": False, "commands": [], "cleanup_errors": []}
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                units = synthetic_units()
                # An explicit synthetic second KEYE1 group slot supplies the
                # second saved level through the proven IDENTIFY8 mapping.
                # The native eDLT-only scan does not query nonzero group levels.
                units[0].parameters[0x50] = b"\x0c\x18" + b"\xff" * 10
                initial = PCISimulator(units, profile="synthetic", state_path=path)
                with initial.running() as endpoint, socket.create_connection(endpoint, timeout=2) as peer:
                    peer.settimeout(2)
                    peer.sendall(b"\\053800020C7Fg\r021840h\r")
                    received = bytearray()
                    while len(received) < 4:
                        part = peer.recv(4 - len(received))
                        self.assertTrue(part, "Peer closed before both confirmations")
                        received.extend(part)
                    self.assertEqual(received, b"g.h.")
                sim = PCISimulator(profile="synthetic", state_path=path)
                self.assertEqual(sim.lighting.level(56, 12), 127)
                self.assertEqual(sim.lighting.level(56, 24), 64)
                with sim.running("0.0.0.0", 0) as (_, port), CGateClient(host, oracle_port, timeout=30) as client:
                    created = False
                    def command(text):
                        response = client.command(text)
                        report["commands"].append({"command": text, "lines": list(response.lines)})
                        return response
                    try:
                        command("PROJECT NEW " + project)
                        created = True
                        command("PROJECT USE " + project)
                        command(f"DBSET //{project}/Project/Description cbus-toolkit-isolated-lighting-restart-v1")
                        sim_host = os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal")
                        command(f"DBCREATENET 254 Lighting Cni {sim_host}:{port}")
                        command("PROJECT SAVE " + project)
                        command("NET LOAD DB " + project)
                        command("NET OPEN " + network)
                        deadline = time.monotonic() + 20
                        while not any("state=ok" in line for line in command("GET " + network + " state").lines):
                            self.assertLess(time.monotonic(), deadline, "Fresh nonzero scan did not become healthy")
                            time.sleep(0.1)
                        for group, level in ((12, 127), (24, 64)):
                            response = command(f"GET {network}/56/{group} level")
                            self.assertTrue(any(f"level={level}" in line for line in response.lines), response.lines)
                        self.assertFalse([row for row in sim.wire_log if row.get("reason")])
                        report.update(passed=True, levels={"12": 127, "24": 64}, persisted=True)
                    finally:
                        report["wire"] = list(sim.wire_log)
                        if created:
                            for text in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                                try:
                                    if not client.connected:
                                        client.connect()
                                    command(text)
                                except Exception as error:
                                    report["cleanup_errors"].append({"command": text, "error": str(error)})
                            if report["passed"]:
                                self.assertEqual(report["cleanup_errors"], [])
        finally:
            if os.environ.get("CBUS_LIGHTING_RESTART_REPORT"):
                target = Path(os.environ["CBUS_LIGHTING_RESTART_REPORT"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + "\n")

    def test_native_cli_lighting_changes_independent_peer_and_persists(self):
        host = os.environ["CBUS_CGATE_TEST_HOST"]
        oracle_port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        project = "LGT" + uuid4().hex[:5].upper()
        network = f"//{project}/254"
        group = network + "/56/12"
        report = {"scope": "CLI to real C-Gate to independent synthetic lighting receiver; no physical hardware claim",
                  "project": project, "passed": False, "commands": [], "cli": []}
        try:
            with tempfile.TemporaryDirectory() as directory:
                state_path = Path(directory) / "state.json"
                sim = PCISimulator(profile="synthetic", state_path=state_path)
                with sim.running("0.0.0.0", 0) as (_, port), CGateClient(host, oracle_port, timeout=30) as client:
                    created = False
                    def command(text):
                        response = client.command(text)
                        report["commands"].append({"command": text, "lines": list(response.lines)})
                        return response
                    def cli(*args):
                        output, errors = io.StringIO(), io.StringIO()
                        with redirect_stdout(output), redirect_stderr(errors):
                            status = main(["cgate", "--host", host, "--port", str(oracle_port), "--timeout", "30", *args])
                        report["cli"].append({"arguments": args, "status": status, "output": output.getvalue(), "errors": errors.getvalue()})
                        self.assertEqual(status, 0, errors.getvalue())
                    def eventually(predicate):
                        deadline = time.monotonic() + 5
                        while not predicate() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertTrue(predicate(), sim.lighting.snapshot())
                    try:
                        command("PROJECT NEW " + project)
                        created = True
                        command("PROJECT USE " + project)
                        command(f"DBSET //{project}/Project/Description cbus-toolkit-isolated-lighting-acceptance-v1")
                        sim_host = os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal")
                        command(f"DBCREATENET 254 Lighting Cni {sim_host}:{port}")
                        command(f"DBADDSAFE {network} Application 56 Lighting")
                        command(f"DBADDSAFE {network}/56 Group 12 TestLight")
                        command("PROJECT SAVE " + project)
                        command("NET LOAD DB " + project)
                        command("NET OPEN " + network)
                        deadline = time.monotonic() + 20
                        while not any("state=ok" in line for line in command("GET " + network + " state").lines):
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(0.1)
                        start = len(sim.wire_log)
                        cli("on", group)
                        eventually(lambda: sim.lighting.level(56, 12) == 255)
                        eventually(lambda: any("level=255" in line for line in command("GET " + group + " level").lines))
                        cli("off", group)
                        eventually(lambda: sim.lighting.level(56, 12) == 0)
                        cli("ramp", group, "127")
                        eventually(lambda: sim.lighting.level(56, 12) == 127)
                        cli("off", group)
                        eventually(lambda: sim.lighting.level(56, 12) == 0)
                        cli("ramp", group, "255", "--seconds", "4")
                        time.sleep(1)
                        self.assertGreater(sim.lighting.level(56, 12), 0)
                        self.assertLess(sim.lighting.level(56, 12), 255)
                        cli("stop", group)
                        eventually(lambda: sim.lighting.snapshot()["groups"][0]["remaining"] == 0)
                        stopped = sim.lighting.level(56, 12)
                        self.assertGreater(stopped, 0)
                        self.assertLess(stopped, 255)
                        time.sleep(0.1)
                        self.assertEqual(sim.lighting.level(56, 12), stopped)
                        loaded = PCISimulator(profile="synthetic", state_path=state_path)
                        self.assertEqual(loaded.lighting.level(56, 12), stopped)
                        commands = [bytes.fromhex(row["hex"]) for row in sim.wire_log[start:] if row["direction"] == "rx"]
                        # Native confirmation letters vary; payloads are fixed
                        # independent vectors, not generated by the helper.
                        actual = [raw[:-2].upper().decode() for raw in commands]
                        expected = ["\\053800790C", "010C", "020C7F", "010C", "0A0CFF", "090C"]
                        self.assertEqual(actual, expected)
                        self.assertFalse([row for row in sim.wire_log if row.get("reason")])
                        report.update(passed=True, persisted=True, stopped_level=stopped, lighting=sim.lighting.snapshot())
                    finally:
                        report["wire"] = list(sim.wire_log)
                        if created:
                            cleanup_errors = []
                            for text in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                                try:
                                    if not client.connected:
                                        client.connect()
                                    command(text)
                                except Exception as error:
                                    cleanup_errors.append({"command": text, "error": str(error)})
                            report["cleanup_errors"] = cleanup_errors
                            if report["passed"]:
                                self.assertEqual(cleanup_errors, [])
        finally:
            if os.environ.get("CBUS_LIGHTING_REPORT"):
                target = Path(os.environ["CBUS_LIGHTING_REPORT"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
