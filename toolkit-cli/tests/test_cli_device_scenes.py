"""CLI scene-table plans and explicit native programming persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Set native C-Gate and unit specifications for stored scene CLI acceptance")
class DeviceSceneCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_plan_native_preview_entries_binding_persistence_and_clear(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "DC" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        args = ("cgate", "--host", host, "--port", port, "--timeout", "20", "unit",
                "--lock-address", network, "--source", "/db" + network + "/p/20")
        options = ("--scene", 1, "--entry", "0x2a=255", "--entry", "43=64", "--key", 1,
                   "--ramp-seconds", 12, "--action-selector", 7, "--trigger-group", 23)
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "Scene_CLI", "Cni", "127.0.0.1:29999")
                database.create_unit(network, 20, "Neo", "KEYE1", "2.5.00", catalog_number="5031NMML")
                projects.operation("save", project)
                original = self.cli(*args, "show")
                snapshot = Path(folder) / "neo.json"
                self.cli(*args, "export", snapshot)
                self.assertEqual(self.cli("unit-scenes", "inspect", snapshot)["commands_used"], 0)
                plan = self.cli("unit-scenes", "plan", snapshot, *options)
                entries = Path(folder) / "entries.json"
                entries.write_text(json.dumps([{"group": 42, "level": 255}, {"group": 43, "level": 64}]))
                file_plan = self.cli("unit-scenes", "plan", snapshot, "--scene", 1, "--entries", entries,
                                     "--key", 1, "--ramp-rate", 3, "--action-selector", 7, "--trigger-group", 23)
                self.assertEqual(plan, file_plan)
                preview = self.cli(*args, "--dry-run", "device-scene", *options)
                self.assertEqual(preview["changes"], plan["changes"])
                self.assertFalse(preview["saved"])
                self.assertTrue(preview["verified"])
                self.assertEqual(self.cli(*args, "show"), original)
                applied = self.cli(*args, "device-scene", *options)
                self.assertTrue(applied["saved"])
                self.assertFalse(applied["device_verified"])
                self.assertEqual(applied["scenes"]["commands_used"], 2)
                binding = applied["scenes"]["key_bindings"][0]
                self.assertEqual((binding["scene"], binding["ramp_rate"], binding["ramp_seconds"], binding["action_selector"]), (1, 3, 12, 7))
                projects.operation("save", project)
                projects.operation("close", project)
                projects.operation("load", project)
                self.assertEqual(self.cli(*args, "show"), applied["parameters"])
                error = self.cli(*args, "device-scene", "--scene", 3, "--entry", "44=0", status=1)
                self.assertIn("contiguous prefix", error["error"])
                self.assertEqual(self.cli(*args, "show"), applied["parameters"])
                cleared = self.cli(*args, "device-scene", "--scene", 1, "--clear")
                self.assertTrue(cleared["saved"])
                self.assertEqual(cleared["scenes"]["commands_used"], 0)
                self.assertEqual(cleared["scenes"]["key_bindings"], applied["scenes"]["key_bindings"])
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
