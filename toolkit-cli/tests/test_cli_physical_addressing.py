"""Physical-address CLI against only its own explicit simulator fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set native C-Gate for isolated physical-address CLI acceptance")
class PhysicalAddressCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_preview_saved_plan_single_write_and_explicit_recovery_observation(self):
        self._lifecycle(commission=False)

    def test_serial_commission_preview_plan_single_native_write_and_observation(self):
        self._lifecycle(commission=True)

    def _lifecycle(self, *, commission):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text
        from cbus_toolkit.addressing import _network_canonical
        from test_simulator_addressing import fixture
        from test_simulator_serial_addressing import commissioning_fixture
        project = "PC" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        args = ("cgate", "--host", host, "--port", port, "--timeout", "60", "address")
        old = 255 if commission else 4
        move = ("serial-commission" if commission else "physical-readdress", network + "/p/" + str(old),
                6, "--serial", "101136.1558")
        verify = "serial-verify" if commission else "physical-verify"
        with tempfile.TemporaryDirectory() as folder:
            sim = (commissioning_fixture if commission else fixture)(state_path=Path(folder) / "state.json", response_delay=0.01)
            with sim.running("0.0.0.0", 0) as (_, sim_port), CGateClient(host, port, timeout=60) as client:
                projects, database, lifecycle = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
                projects.operation("new", project)
                try:
                    database.create_network(project, 254, "Physical_CLI", "Cni",
                        os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(sim_port))
                    database.create_unit(network, 6, "Target", "KEYE1", "2.5.00", catalog_number="5031NMML")
                    database.set(network + "/p/6/SerialNumber", "101136.1558")
                    projects.operation("save", project)
                    lifecycle.open(network)
                    self.assertTrue(lifecycle.wait_ready(network, timeout=25)["ready"])
                    original_xml = xml_text(database.get(network, xml=True))
                    original_state = sim.snapshot()
                    rejected = self.cli(*args, *move, "--dry-run", status=1)
                    self.assertIn("Retries=0", rejected["error"])
                    self.assertEqual(sim.snapshot(), original_state)
                    client.command("SET " + network + " Retries 0")
                    preview_file = Path(folder) / "preview.json"
                    preview = self.cli(*args, *move, "--dry-run", "--plan-output", preview_file)
                    self.assertFalse(preview["moved"])
                    self.assertEqual(json.loads(preview_file.read_text()), preview)
                    self.assertEqual(sim.snapshot(), original_state)
                    observed = self.cli(*args, verify, preview_file)
                    self.assertEqual(observed["outcome"], "confirmed_not_moved")
                    plan_file = Path(folder) / "move.json"
                    start = len(sim.wire_log)
                    result = self.cli(*args, *move, "--plan-output", plan_file)
                    self.assertEqual(result["outcome"], "confirmed_moved")
                    self.assertTrue(result["moved"])
                    if commission:
                        self.assertEqual(result["command"], "SET " + network + "/p/255 Address 6")
                        self.assertEqual(result["method"], "database_serial_match_then_scalar_address")
                    self.assertTrue(result["verification"]["source_absent"])
                    self.assertTrue(result["verification"]["serial_confirmed"])
                    self.assertEqual(json.loads(plan_file.read_text()), result["plan"])
                    requests = [bytes.fromhex(row["hex"]) for row in sim.wire_log[start:] if row["direction"] == "rx"]
                    self.assertEqual(sum(b"A3204E06" in request.upper() for request in requests), 1)
                    saved_plan = plan_file.read_bytes()
                    error = self.cli(*args, *move, "--plan-output", plan_file, status=1)
                    self.assertIn("already exists", error["error"])
                    self.assertEqual(plan_file.read_bytes(), saved_plan)
                    result_file = Path(folder) / "result.json"
                    result_file.write_text(json.dumps(result))
                    recovered = self.cli(*args, verify, result_file)
                    self.assertEqual(recovered["outcome"], "confirmed_moved")
                    self.assertTrue(recovered["database_unchanged"])
                    self.assertTrue(recovered["other_identities_unchanged"])
                    self.assertEqual(_network_canonical(xml_text(database.get(network, xml=True))), _network_canonical(original_xml))
                    self.assertNotIn(old, sim.units)
                    self.assertIn(6, sim.units)
                    self.assertFalse([row for row in sim.wire_log if row.get("reason")])
                finally:
                    lifecycle.close(network)
                    projects.operation("close", project)
                    projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
