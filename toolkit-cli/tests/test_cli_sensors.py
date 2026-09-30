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

    def test_pir_and_light_level_offline_gates_and_key_grammar(self):
        from cbus_toolkit.sensor_dialog_cli import _key
        self.assertEqual(_key("1:block=1,group=41,timer_seconds=0x12c,expiry=ramp_off"),
                         (1, {"block": 1, "group": 41, "timer_seconds": 300, "expiry": "ramp_off"}))
        for bad in ("1", "1:", "1:color=2", "1:group=1,group=2", "1:expiry=later", "x:group=1", "1:group=x"):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                _key(bad)
        env = {name: value for name, value in os.environ.items() if name != "CBUS_UNITSPEC_DIR"}
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "snapshot.json"
            for action, identity, message in (
                    ("light-level-plan", ("SENLL", "1.2.68", "5031PE"), "TSENLL"),
                    ("light-level-plan", ("SENLLA", "2.4.00", "5754PE"), "TSENLLA"),
                    ("light-level-plan", ("SENLL", "2.3.00", "5031PE"), "--spec-dir"),
                    ("pir-plan", ("SENPIRIB", "2.3.10", "5753L"), "unregistered"),
                    ("pir-plan", ("SENLL", "2.3.00", "5031PE"), "Only SENPIROA"),
                    ("pir-plan", ("SENPIRIA", "2.4.00", "5751L"), "--spec-dir")):
                with self.subTest(action=action, identity=identity):
                    file.write_text(json.dumps({"format": "cbus-cli-parameters-v1", "unit_type": identity[0],
                        "firmware": identity[1], "catalog_number": identity[2], "parameters": {}}))
                    before = file.read_bytes()
                    error = self.cli("sensors", action, file, status=1, env=env)
                    self.assertIn(message, error["error"])
                    self.assertEqual(file.read_bytes(), before)
            file.write_text("{}")
            self.assertIn("--spec", self.cli("sensors", "pir-plan", file, "--key", "1:group=3", status=1, env=env)["error"])

    @unittest.skipUnless(native_backend() and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Select native C-Gate and unit specifications for PIR/SENLL CLI acceptance")
    def test_native_pir_and_light_level_preview_matches_offline_plan_and_persists(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "SD" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        args = ("cgate", "--host", self.host, "--port", self.port, "--timeout", "20", "unit", "--lock-address", network)
        cases = {
            210: ("SENLL", "2.3.00", "SLC5031PE", "sensor-light-level", "light-level-plan",
                  ("--level-group", "40", "--on-off-group", "41", "--broadcast-group", "42", "--enable-group", "43",
                   "--indicator", "on-off", "--target-lux", "500", "--margin-percent", "59")),
            211: ("SENPIRIA", "2.4.00", "5751L", "sensor-pir", "pir-plan",
                  ("--key", "1:block=1,group=41,timer_seconds=300,expiry=ramp_off", "--key", "4:group=44",
                   "--restore-functions", "--separate-darkness", "--enable-group", "23", "--enabled-when", "off",
                   "--power-up", "enabled")),
        }
        with tempfile.TemporaryDirectory() as folder, CGateClient(self.host, self.port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "Sensor_Dialog_CLI", "Cni", "127.0.0.1:29999")
                for address, (unit_type, firmware, catalog, *_rest) in cases.items():
                    database.create_unit(network, address, "Sensor_" + str(address), unit_type, firmware,
                                         catalog_number=catalog)
                database.create_unit(network, 212, "Wrong_Profile", "SENPILL", "2.3.00", catalog_number="5753PEIRL")
                projects.operation("save", project)
                applied = {}
                for address, (unit_type, firmware, catalog, action, plan_action, options) in cases.items():
                    with self.subTest(unit_type=unit_type):
                        prefix = (*args, "--source", "/db" + network + "/p/" + str(address))
                        original = self.cli(*prefix, "show")
                        snapshot = Path(folder) / f"sensor-{address}.json"
                        self.cli(*prefix, "export", snapshot)
                        plan = self.cli("sensors", plan_action, snapshot, *options)
                        self.assertEqual((plan["unit_type"], plan["firmware"], plan["catalog_number"]),
                                         (unit_type, firmware, catalog))
                        preview = self.cli(*prefix, "--dry-run", action, *options)
                        self.assertEqual(plan["changes"], preview["changes"])
                        self.assertTrue(preview["verified"])
                        self.assertFalse(preview["saved"] or preview["device_verified"])
                        self.assertEqual(self.cli(*prefix, "show"), original)
                        applied[address] = self.cli(*prefix, action, *options)
                        self.assertTrue(applied[address]["saved"])
                        self.assertEqual(applied[address]["parameters"], preview["parameters"])
                        if unit_type == "SENLL":  # Marked non-programmable by the SENLL agent.
                            for name in ("JPCommand", "BlockAllocation", "SceneKeySelector"):
                                self.assertEqual(applied[address]["parameters"][name], original[name])
                self.assertEqual(int(applied[210]["parameters"]["PECMarginLux"], 0), 29)
                self.assertEqual(applied[210]["dialog"]["indicator"], "on_off")
                projects.operation("save", project)
                projects.operation("close", project)
                projects.operation("load", project)
                for address, result in applied.items():
                    prefix = (*args, "--source", "/db" + network + "/p/" + str(address))
                    self.assertEqual(self.cli(*prefix, "show"), result["parameters"])
                wrong = (*args, "--source", "/db" + network + "/p/212")
                before = self.cli(*wrong, "show")
                for action, message in (("sensor-light-level", "Only SENLL"), ("sensor-pir", "multisensor")):
                    error = self.cli(*wrong, action, status=1)
                    self.assertIn("Native session must", error["error"])
                    self.assertIn(message, error["error"])
                self.assertEqual(self.cli(*wrong, "show"), before)
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
