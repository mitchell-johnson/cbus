"""Sensor CLI preview, offline planning, persistence and identity boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class SensorCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_snapshot_rejects_other_firmware_before_loading_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "snapshot.json"
            file.write_text(json.dumps({"format": "cbus-cli-parameters-v1", "unit_type": "SENPILL",
                "firmware": "2.2.00", "catalog_number": "5753PEIRL", "parameters": {}}))
            before = file.read_bytes()
            error = self.cli("sensors", "plan", file, "--key", "3", "--event", "night", status=1)
            self.assertIn("identity differs", error["error"])
            self.assertEqual(file.read_bytes(), before)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Set native C-Gate and unit specifications for sensor CLI acceptance")
    def test_native_preview_matches_offline_plan_and_persists_with_unrelated_values(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "SO" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        args = ("cgate", "--host", host, "--port", port, "--timeout", "20", "unit", "--lock-address", network)
        prefix = (*args, "--source", "/db" + network + "/p/230")
        options = ("--key", "3", "--event", "night", "--group", "31", "--timer-seconds", "513",
                   "--expiry", "ramp_off", "--target-lux", "550", "--margin-percent", "10",
                   "--enable-group", "23", "--enabled-when", "off", "--disable-potentiometer-override")
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "Sensor_CLI", "Cni", "127.0.0.1:29999")
                database.create_unit(network, 230, "Sensor", "SENPILL", "2.3.00", catalog_number="5753PEIRL")
                database.create_unit(network, 231, "Wrong_Profile", "KEY4", "1.2.67")
                projects.operation("save", project)
                original = self.cli(*prefix, "show")
                snapshot = Path(folder) / "sensor.json"
                self.cli(*prefix, "export", snapshot)
                plan = self.cli("sensors", "plan", snapshot, *options)
                preview = self.cli(*prefix, "--dry-run", "sensor-occupancy", *options)
                self.assertEqual(plan["changes"], preview["changes"])
                self.assertTrue(preview["verified"])
                self.assertFalse(preview["saved"])
                self.assertFalse(preview["device_verified"])
                self.assertEqual(self.cli(*prefix, "show"), original)
                applied = self.cli(*prefix, "sensor-occupancy", *options)
                self.assertTrue(applied["saved"])
                self.assertEqual(applied["parameters"], preview["parameters"])
                self.assertEqual(applied["parameters"]["SceneTable"], original["SceneTable"])
                projects.operation("save", project)
                projects.operation("close", project)
                projects.operation("load", project)
                self.assertEqual(self.cli(*prefix, "show"), applied["parameters"])
                wrong = (*args, "--source", "/db" + network + "/p/231")
                before = self.cli(*wrong, "show")
                error = self.cli(*wrong, "sensor-occupancy", *options, status=1)
                self.assertIn("Native session must", error["error"])
                self.assertEqual(self.cli(*wrong, "show"), before)
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
