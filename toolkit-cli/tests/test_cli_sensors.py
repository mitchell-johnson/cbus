"""Sensor CLI preview, offline planning, persistence and identity boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from tests.test_sensors import native_backend


class SensorCLITests(unittest.TestCase):
    host = port = None

    @classmethod
    def setUpClass(cls):
        cls.service = None
        if native_backend() == "local" and os.environ.get("CBUS_UNITSPEC_DIR"):
            from research.local_cgate import LocalCGate
            cls.service = LocalCGate(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
            cls.addClassCleanup(cls.service.close)
            # PP LOCK needs the owned loopback interface at Clipsal access.
            (cls.service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
            cls.service.start()
            cls.host, cls.port = "127.0.0.1", cls.service.port
        elif native_backend() == "host":
            cls.host = os.environ["CBUS_CGATE_TEST_HOST"]
            cls.port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))

    def cli(self, *args, status=0, env=None):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_snapshot_identity_gate_runs_before_loading_schema(self):
        env = {name: value for name, value in os.environ.items() if name != "CBUS_UNITSPEC_DIR"}
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "snapshot.json"
            for identity, message in ((("SENPILL", "2.4.00", "5753PEIRL"), "outside 2.0.01..2.3.9"),
                                      (("SENPILL", "2.3.10", "5753PEIRL"), "no Toolkit ST7 registration"),
                                      (("SENPIRIA", "2.3.00", "5751L"), "PIR sensor class"),
                                      (("SENPILL", "2.1.00", "SLC5753PEIRL"), "--spec-dir")):
                with self.subTest(identity=identity):
                    file.write_text(json.dumps({"format": "cbus-cli-parameters-v1", "unit_type": identity[0],
                        "firmware": identity[1], "catalog_number": identity[2], "parameters": {}}))
                    before = file.read_bytes()
                    error = self.cli("sensors", "plan", file, "--key", "3", "--event", "night", status=1, env=env)
                    self.assertIn(message, error["error"])
                    self.assertEqual(file.read_bytes(), before)

    @unittest.skipUnless(native_backend() and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Select native C-Gate and unit specifications for sensor CLI acceptance")
    def test_native_preview_matches_offline_plan_and_persists_with_unrelated_values(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "SO" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        args = ("cgate", "--host", self.host, "--port", self.port, "--timeout", "20", "unit", "--lock-address", network)
        options = ("--key", "3", "--event", "night", "--group", "31", "--timer-seconds", "513",
                   "--expiry", "ramp_off", "--target-lux", "550", "--margin-percent", "10",
                   "--enable-group", "23", "--enabled-when", "off", "--disable-potentiometer-override")
        profiles = {230: ("2.3.00", "5753PEIRL"), 232: ("2.1.00", "SLC5753PEIRL")}
        with tempfile.TemporaryDirectory() as folder, CGateClient(self.host, self.port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "Sensor_CLI", "Cni", "127.0.0.1:29999")
                for address, (firmware, catalog) in profiles.items():
                    database.create_unit(network, address, "Sensor_" + str(address), "SENPILL", firmware,
                                         catalog_number=catalog)
                database.create_unit(network, 231, "Wrong_Profile", "KEY4", "1.2.67")
                database.create_unit(network, 233, "Layout_Identical_PIR", "SENPIRIA", "2.3.00", catalog_number="5751L")
                projects.operation("save", project)
                applied = {}
                for address, (firmware, catalog) in profiles.items():
                    with self.subTest(firmware=firmware, catalog=catalog):
                        prefix = (*args, "--source", "/db" + network + "/p/" + str(address))
                        original = self.cli(*prefix, "show")
                        snapshot = Path(folder) / f"sensor-{address}.json"
                        self.cli(*prefix, "export", snapshot)
                        plan = self.cli("sensors", "plan", snapshot, *options)
                        self.assertEqual((plan["firmware"], plan["catalog_number"]), (firmware, catalog))
                        preview = self.cli(*prefix, "--dry-run", "sensor-occupancy", *options)
                        self.assertEqual(plan["changes"], preview["changes"])
                        self.assertTrue(preview["verified"])
                        self.assertFalse(preview["saved"])
                        self.assertFalse(preview["device_verified"])
                        self.assertEqual(self.cli(*prefix, "show"), original)
                        applied[address] = self.cli(*prefix, "sensor-occupancy", *options)
                        self.assertTrue(applied[address]["saved"])
                        self.assertEqual(applied[address]["parameters"], preview["parameters"])
                        self.assertEqual(applied[address]["parameters"]["SceneTable"], original["SceneTable"])
                projects.operation("save", project)
                projects.operation("close", project)
                projects.operation("load", project)
                for address, result in applied.items():
                    prefix = (*args, "--source", "/db" + network + "/p/" + str(address))
                    self.assertEqual(self.cli(*prefix, "show"), result["parameters"])
                for address, message in ((231, "Only SENPILL"), (233, "PIR sensor class")):
                    wrong = (*args, "--source", "/db" + network + "/p/" + str(address))
                    before = self.cli(*wrong, "show")
                    error = self.cli(*wrong, "sensor-occupancy", *options, status=1)
                    self.assertIn("Native session must", error["error"])
                    self.assertIn(message, error["error"])
                    self.assertEqual(self.cli(*wrong, "show"), before)
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
